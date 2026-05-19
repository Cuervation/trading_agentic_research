"""Semantic branch guard for autonomous strategy research.

This module blocks candidates that are not exact config duplicates but belong to
branches that repeatedly produced duplicate/rejected outcomes. It is deliberately
conservative: branches with any recent useful candidate are kept active.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILE = "semantic_branch_exhaustion.json"
BLOCK_VALUES = {
    "duplicate_blocked",
    "duplicate_preflight_blocked",
    "duplicate_pre_run_blocked",
    "branch_exhausted_pre_run",
}
BAD_VALUES = BLOCK_VALUES | {
    "rejected_with_learning",
    "ignored_duplicate",
    "ignored_rejected",
    "metric_no_effect_blocked",
}
GOOD_VALUES = {
    "accepted_for_followup",
    "secondary_candidate",
    "defensive_secondary_candidate",
    "promotion_candidate",
    "new_champion",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


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


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "unknown").lower()).strip("_") or "unknown"


def parse_feature_space_hypothesis(hypothesis_id: str | None) -> dict[str, str | None]:
    """Extract feature/layer from ids like HYP_FSPACE_AUTO_002_RANK_CHANNEL_R2_EXIT_24_V1."""
    hid = str(hypothesis_id or "")
    upper = hid.upper()
    field = None
    layer = None

    match = re.search(r"_RANK_(.+?)(?:_TOPN_|_EXIT_|_CONF_|_MKT_|_V\d+|$)", upper)
    if match:
        field = match.group(1).lower()

    if "_EXIT_" in upper:
        layer = "rank_exit"
    elif "_TOPN_" in upper:
        layer = "rank_topn"
    elif "_CONF_" in upper:
        layer = "rank_confirmation"
    elif "_MKT_" in upper or "_SPY_" in upper:
        layer = "rank_market_filter"
    elif "_RANK_" in upper:
        layer = "pure_ranking"
    elif "TOPN" in upper:
        layer = "topn"
    elif "EXIT" in upper:
        layer = "exit"

    return {"field": field, "layer": layer}


def semantic_branch_key(*, hypothesis_id: str | None, family: str | None = None, config: dict[str, Any] | None = None) -> str:
    parsed = parse_feature_space_hypothesis(hypothesis_id)
    field = parsed.get("field")
    layer = parsed.get("layer")

    if config and not field:
        ranking = config.get("ranking") if isinstance(config.get("ranking"), dict) else {}
        field = ranking.get("field") or config.get("ranking_column")
    if config and not layer:
        if isinstance(config.get("exit_rule"), dict) and config["exit_rule"].get("rank_threshold") is not None:
            layer = "rank_exit"
        elif isinstance(config.get("entry_rule"), dict) and config["entry_rule"].get("top_n") is not None:
            layer = "rank_topn"
        elif config.get("market_filter"):
            layer = "rank_market_filter"
        elif config.get("risk_filters"):
            layer = "rank_confirmation"
        elif field:
            layer = "pure_ranking"

    return "/".join([_slug(family), _slug(field), _slug(layer)])


def _audit_value(audit: dict[str, Any], ledger_value: str | None = None) -> str:
    flags = {str(x) for x in (audit.get("flags") or [])}
    if audit.get("duplicate_result") or "duplicate_result" in flags or "duplicate_artifact" in flags:
        return "duplicate_blocked"
    if ledger_value:
        return str(ledger_value)
    if audit.get("decision") == "accepted_for_followup":
        return "accepted_for_followup"
    return str(audit.get("decision") or "unknown")


def _ledger_by_run(state_dir: str | Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(Path(state_dir) / "research_ledger.jsonl"):
        rid = row.get("run_id")
        if rid:
            out[str(rid)] = row
    return out


def refresh_semantic_branch_exhaustion(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    duplicate_threshold: int = 2,
    bad_threshold: int = 4,
    lookback: int = 240,
) -> dict[str, Any]:
    """Rebuild branch memory from runs and ledger.

    Conservative exhaustion rule:
    - duplicate_count >= duplicate_threshold OR bad_count >= bad_threshold;
    - AND good_count == 0.
    This prevents blocking branches that recently produced an accepted/secondary candidate.
    """
    ledger = _ledger_by_run(state_dir)
    events_by_branch: dict[str, list[dict[str, Any]]] = defaultdict(list)

    run_dirs = [p for p in sorted(Path(runs_dir).glob("*_*")) if p.is_dir()]
    for run_dir in run_dirs[-lookback:]:
        manifest = read_json(run_dir / "run_manifest.json", {}) or {}
        audit = read_json(run_dir / "audit.json", {}) or {}
        if not manifest and not audit:
            continue
        run_id = run_dir.name
        ledger_row = ledger.get(run_id, {})
        hypothesis_id = manifest.get("hypothesis_id") or ledger_row.get("hypothesis_id")
        family = manifest.get("hypothesis_family") or ledger_row.get("family")
        branch = semantic_branch_key(hypothesis_id=str(hypothesis_id or ""), family=str(family or ""))
        value = _audit_value(audit, ledger_row.get("value_delivered"))
        event = {
            "run_id": run_id,
            "hypothesis_id": hypothesis_id,
            "family": family,
            "branch": branch,
            "value_delivered": value,
            "decision": audit.get("decision"),
            "duplicate_of_run_id": audit.get("duplicate_of_run_id") or audit.get("duplicate_against"),
        }
        events_by_branch[branch].append(event)

    state = {
        "version": 1,
        "updated_at": now_iso(),
        "policy": {
            "duplicate_threshold": duplicate_threshold,
            "bad_threshold": bad_threshold,
            "lookback": lookback,
            "rule": "exhaust when duplicate>=threshold or bad>=threshold and good==0",
        },
        "branches": {},
    }

    for branch, events in sorted(events_by_branch.items()):
        values = Counter(str(e.get("value_delivered") or "unknown") for e in events)
        duplicate_count = sum(count for value, count in values.items() if "duplicate" in value)
        bad_count = sum(count for value, count in values.items() if value in BAD_VALUES or "rejected" in value or "duplicate" in value)
        good_count = sum(count for value, count in values.items() if value in GOOD_VALUES or "candidate" in value or "champion" in value)
        status = "active"
        reason = None
        if good_count == 0 and duplicate_count >= duplicate_threshold:
            status = "exhausted"
            reason = f"semantic_duplicate_threshold_reached:{duplicate_count}"
        elif good_count == 0 and bad_count >= bad_threshold:
            status = "exhausted"
            reason = f"semantic_bad_threshold_reached:{bad_count}"

        state["branches"][branch] = {
            "branch": branch,
            "status": status,
            "reason": reason,
            "duplicate_count": duplicate_count,
            "bad_count": bad_count,
            "good_count": good_count,
            "values": dict(values),
            "recent_events": events[-12:],
            "updated_at": now_iso(),
        }

    write_json(Path(state_dir) / STATE_FILE, state)
    return state


def semantic_branch_status(
    *,
    hypothesis_id: str | None,
    family: str | None,
    state_dir: str | Path = "state",
) -> dict[str, Any]:
    state = read_json(Path(state_dir) / STATE_FILE, {"branches": {}}) or {"branches": {}}
    branch = semantic_branch_key(hypothesis_id=hypothesis_id, family=family)
    row = (state.get("branches") or {}).get(branch, {})
    return {
        "branch": branch,
        "blocked": row.get("status") == "exhausted",
        "status": row.get("status", "unknown"),
        "reason": row.get("reason"),
        "details": row,
    }


def check_semantic_branch_block(
    *,
    hypothesis_id: str | None,
    family: str | None,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    refresh: bool = True,
) -> dict[str, Any]:
    if refresh:
        refresh_semantic_branch_exhaustion(state_dir=state_dir, runs_dir=runs_dir)
    return semantic_branch_status(hypothesis_id=hypothesis_id, family=family, state_dir=state_dir)


def record_semantic_pre_run_block(
    *,
    state_dir: str | Path,
    run_id: str | None,
    hypothesis_id: str | None,
    family: str | None,
    branch: str,
    reason: str | None,
) -> None:
    append_jsonl(Path(state_dir) / "semantic_branch_pre_run_blocks.jsonl", {
        "created_at": now_iso(),
        "run_id": run_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "branch": branch,
        "reason": reason,
        "value_delivered": "branch_exhausted_pre_run",
    })
