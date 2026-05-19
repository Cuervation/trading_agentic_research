"Branch exhaustion memory for autonomous research."
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.strategy_effect_signature import classify_strategy_branch, read_json

BAD_VALUES = {
    "duplicate_blocked", "duplicate_pre_run_blocked", "metric_no_effect_blocked",
    "rejected_with_learning", "branch_exhausted_pre_run",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def branch_state_path(state_dir: str | Path = "state") -> Path:
    return Path(state_dir) / "branch_exhaustion.json"


def branch_from_hypothesis_id(hypothesis_id: str) -> str:
    hid = str(hypothesis_id or "").upper()
    field = "unknown"
    if "_RANK_" in hid:
        tail = hid.split("_RANK_", 1)[1]
        for marker in ["_CONF_", "_MKT_", "_TOPN_", "_EXIT_", "_V"]:
            if marker in tail:
                field = tail.split(marker, 1)[0].lower()
                break
        else:
            field = tail.lower()
    if "MKT" in hid:
        layer = "market_filter"
    elif "CONF" in hid:
        layer = "confirmation"
    elif "TOPN" in hid:
        layer = "topn"
    elif "EXIT" in hid:
        layer = "exit"
    elif "TRAIL" in hid or "RISK" in hid:
        layer = "risk_management"
    else:
        layer = "ranking"
    return f"feature_space:{field}:{layer}"


def branch_for_config(config: dict[str, Any], hypothesis_id: str | None = None) -> str:
    if hypothesis_id:
        return branch_from_hypothesis_id(hypothesis_id)
    return classify_strategy_branch(config or {}, hypothesis_id=hypothesis_id)


def load_branch_state(state_dir: str | Path = "state") -> dict[str, Any]:
    return read_json(branch_state_path(state_dir), {"version": 1, "branches": {}}) or {"version": 1, "branches": {}}


def refresh_branch_exhaustion(
    state_dir: str | Path = "state",
    *,
    duplicate_threshold: int = 2,
    bad_threshold: int = 5,
    lookback: int = 160,
) -> dict[str, Any]:
    state = load_branch_state(state_dir)
    branches = state.setdefault("branches", {})
    rows = read_jsonl(Path(state_dir) / "research_ledger.jsonl")
    rows.extend(read_jsonl(Path(state_dir) / "pre_run_duplicate_blocks.jsonl"))
    recent = rows[-lookback:]

    counts: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    for row in recent:
        value = str(row.get("value_delivered") or row.get("decision") or "")
        hypothesis_id = str(row.get("hypothesis_id") or "")
        if not hypothesis_id:
            continue
        branch = str(row.get("branch") or branch_from_hypothesis_id(hypothesis_id))
        if value in BAD_VALUES or value == "rejected":
            counts[branch]["bad"] += 1
        if "duplicate" in value:
            counts[branch]["duplicate"] += 1
        if row.get("run_id"):
            examples[branch].append(str(row.get("run_id")))

    for branch, counter in counts.items():
        current = branches.setdefault(branch, {})
        current.update({
            "branch": branch,
            "bad_count_recent": int(counter["bad"]),
            "duplicate_count_recent": int(counter["duplicate"]),
            "examples": examples.get(branch, [])[-8:],
            "last_refreshed_at": now_iso(),
        })
        if int(counter["duplicate"]) >= duplicate_threshold or int(counter["bad"]) >= bad_threshold:
            current["status"] = "exhausted"
            current["reason"] = "duplicate_threshold_reached" if int(counter["duplicate"]) >= duplicate_threshold else "bad_threshold_reached"
        else:
            current.setdefault("status", "active")

    write_json(branch_state_path(state_dir), state)
    return state


def is_branch_exhausted(branch: str, state_dir: str | Path = "state") -> dict[str, Any]:
    state = load_branch_state(state_dir)
    info = (state.get("branches") or {}).get(branch) or {}
    return {"branch": branch, "exhausted": info.get("status") == "exhausted", "info": info}


def is_hypothesis_branch_exhausted(hypothesis_id: str, state_dir: str | Path = "state") -> dict[str, Any]:
    return is_branch_exhausted(branch_from_hypothesis_id(hypothesis_id), state_dir=state_dir)


def record_branch_event(
    *,
    state_dir: str | Path = "state",
    run_id: str | None,
    hypothesis_id: str | None,
    branch: str,
    value_delivered: str,
    reason: str,
) -> None:
    path = Path(state_dir) / "pre_run_duplicate_blocks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "created_at": now_iso(),
        "run_id": run_id,
        "hypothesis_id": hypothesis_id,
        "branch": branch,
        "value_delivered": value_delivered,
        "reason": reason,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
