"""Persistent branch exhaustion memory."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.strategy_effect_signature import branch_key_from_config, read_json

BAD_VALUES = {"duplicate_blocked", "metric_no_effect_blocked", "rejected_with_learning", "ignored_duplicate", "ignored_rejected"}
GOOD_VALUES = {"new_champion", "promotion_candidate", "defensive_secondary_candidate", "accepted_for_followup"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def branch_state_path(state_dir: str | Path = "state") -> Path:
    return Path(state_dir) / "branch_exhaustion.json"


def load_branch_state(state_dir: str | Path = "state") -> dict[str, Any]:
    return read_json(branch_state_path(state_dir), {"version": 1, "branches": {}}) or {"version": 1, "branches": {}}


def save_branch_state(state_dir: str | Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_json(branch_state_path(state_dir), state)


def is_branch_exhausted(*, state_dir: str | Path, strategy_config: dict[str, Any], family: str | None = None) -> dict[str, Any]:
    state = load_branch_state(state_dir)
    key = branch_key_from_config(strategy_config, family=family)
    row = (state.get("branches") or {}).get(key)
    if not isinstance(row, dict):
        return {"exhausted": False, "branch": key}
    return {"exhausted": row.get("status") == "exhausted", "branch": key, "reason": row.get("reason"), "evidence": row.get("evidence", [])}


def rebuild_branch_exhaustion(*, state_dir: str | Path = "state", runs_dir: str | Path = "runs", min_bad: int = 3, recent_rows: int = 80) -> dict[str, Any]:
    ledger = read_jsonl(Path(state_dir) / "research_ledger.jsonl")[-recent_rows:]
    branch_events: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in ledger:
        run_id = row.get("run_id")
        if not run_id:
            continue
        manifest = read_json(Path(runs_dir) / str(run_id) / "run_manifest.json", {}) or {}
        family = manifest.get("hypothesis_family") or row.get("family")
        strategy_id = manifest.get("strategy_id")
        config = {}
        if strategy_id:
            for cfg_path in Path("configs").rglob("*.json"):
                maybe = read_json(cfg_path, {}) or {}
                if maybe.get("strategy_id") == strategy_id or maybe.get("hypothesis_id") == manifest.get("hypothesis_id"):
                    config = maybe
                    break

        if config:
            key = branch_key_from_config(config, family=family)
        else:
            changed = manifest.get("changed_parameters") or []
            text = " ".join(str(x) for x in changed)
            if "market_filter" in text:
                axis = "market_filter"
            elif "entry_rule.top_n" in text:
                axis = "rank_topn"
            elif "exit_rule.rank_threshold" in text:
                axis = "rank_exit"
            elif "risk_filters" in text:
                axis = "rank_confirm"
            else:
                axis = "unknown"
            key = f"{family or 'unknown_family'}/unknown_rank/{axis}"

        value = str(row.get("value_delivered") or row.get("champion_action") or row.get("decision") or "")
        branch_events[key].append({"run_id": run_id, "value": value, "hypothesis_id": row.get("hypothesis_id")})

    state = {"version": 1, "updated_at": now_iso(), "branches": {}}
    for key, events in branch_events.items():
        values = Counter(e["value"] for e in events)
        bad = sum(c for v, c in values.items() if v in BAD_VALUES or "duplicate" in v or "rejected" in v)
        good = sum(c for v, c in values.items() if v in GOOD_VALUES or "champion" in v or "candidate" in v)
        status = "exhausted" if bad >= min_bad and good == 0 else "active"
        state["branches"][key] = {
            "status": status,
            "reason": f"recent_bad_events={bad}, recent_good_events={good}",
            "bad_count": bad,
            "good_count": good,
            "evidence": events[-10:],
            "updated_at": now_iso(),
        }
    save_branch_state(state_dir, state)
    return {"path": str(branch_state_path(state_dir)), "branches": len(state["branches"]), "exhausted": sum(1 for b in state["branches"].values() if b.get("status") == "exhausted")}
