"""Semantic branch guard for autonomous research.

This module prevents the loop from repeatedly spending full backtests on
near-equivalent feature-space branches.

It is intentionally branch-level, not exact-config-level. Example branches:

- feature_space_composite_exit/channel_slope_pct/rank_exit
- feature_space_composite_concentration/channel_slope_pct/rank_topn

A branch is marked exhausted when recent evidence shows repeated duplicate
results or repeated rejected runs without useful follow-up/champion signals.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEMANTIC_BRANCH_FILE = "semantic_branch_exhaustion.json"

GOOD_VALUES = {
    "new_champion",
    "promotion_candidate",
    "secondary_candidate",
    "defensive_secondary_candidate",
    "accepted_for_followup",
}

BAD_VALUES = {
    "duplicate_blocked",
    "duplicate_preflight_blocked",
    "duplicate_pre_run_blocked",
    "duplicate_strategy_effect_signature",
    "rejected_with_learning",
    "metric_no_effect_blocked",
    "ignored_duplicate",
    "ignored_rejected",
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


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _slug(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value or "unknown").lower()).strip("_")


def infer_field_and_layer(hypothesis_id: str | None) -> tuple[str, str]:
    hid = str(hypothesis_id or "")
    field = "unknown_field"

    m = re.search(r"_RANK_(.+?)(?:_TOPN_|_EXIT_|_CONF_|_MKT_|_V\d|$)", hid)
    if m:
        field = _slug(m.group(1))

    if "_TOPN_" in hid:
        layer = "rank_topn"
    elif "_EXIT_" in hid:
        layer = "rank_exit"
    elif "_CONF_" in hid:
        layer = "rank_confirmation"
    elif "_MKT_" in hid or "_SPY_" in hid:
        layer = "rank_market_filter"
    elif "_RANK_" in hid:
        layer = "pure_ranking"
    else:
        layer = "unknown_layer"

    return field, layer


def semantic_branch_key(*, hypothesis_id: str | None, family: str | None) -> str:
    field, layer = infer_field_and_layer(hypothesis_id)
    fam = _slug(family or "unknown_family")
    return f"{fam}/{field}/{layer}"


def semantic_branch_path(state_dir: str | Path = "state") -> Path:
    return Path(state_dir) / SEMANTIC_BRANCH_FILE


def load_semantic_branch_state(state_dir: str | Path = "state") -> dict[str, Any]:
    payload = read_json(semantic_branch_path(state_dir), None)
    if not isinstance(payload, dict):
        payload = {"version": 1, "branches": {}, "updated_at": now_iso()}
    payload.setdefault("branches", {})
    return payload


def save_semantic_branch_state(state_dir: str | Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_json(semantic_branch_path(state_dir), state)


def _audit_is_duplicate(audit: dict[str, Any]) -> bool:
    flags = set(audit.get("flags") or [])
    return bool(
        audit.get("duplicate_result")
        or audit.get("duplicate_of_run_id")
        or "duplicate_result" in flags
        or "duplicate_artifact" in flags
        or "duplicate_preflight_blocked" in flags
    )


def _ledger_value_for_run(ledger_rows: list[dict[str, Any]], run_id: str) -> str | None:
    for row in reversed(ledger_rows):
        if str(row.get("run_id")) == str(run_id):
            return str(row.get("value_delivered") or row.get("champion_action") or row.get("decision") or "")
    return None


def refresh_semantic_branch_state(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    duplicate_threshold: int = 2,
    bad_threshold: int = 4,
    window: int = 16,
) -> dict[str, Any]:
    """Rebuild branch state from existing runs and ledger.

    Conservative rule:
    - exhausted if duplicate_count >= duplicate_threshold OR bad_count >= bad_threshold
    - only when good_count == 0
    """
    ledger_rows = read_jsonl(Path(state_dir) / "research_ledger.jsonl")
    state = load_semantic_branch_state(state_dir)
    branches: dict[str, Any] = {}

    for run_dir in sorted(Path(runs_dir).glob("*_*")):
        if not run_dir.is_dir():
            continue

        audit = read_json(run_dir / "audit.json", {}) or {}
        manifest = read_json(run_dir / "run_manifest.json", {}) or {}
        if not audit and not manifest:
            continue

        run_id = run_dir.name
        hypothesis_id = str(manifest.get("hypothesis_id") or audit.get("hypothesis_id") or "")
        family = str(manifest.get("hypothesis_family") or manifest.get("family") or audit.get("family") or "")
        if not hypothesis_id:
            continue

        branch = semantic_branch_key(hypothesis_id=hypothesis_id, family=family)
        row = branches.setdefault(
            branch,
            {
                "branch_key": branch,
                "status": "active",
                "events": [],
                "duplicate_count": 0,
                "bad_count": 0,
                "good_count": 0,
                "last_updated_at": now_iso(),
            },
        )

        ledger_value = _ledger_value_for_run(ledger_rows, run_id)
        decision = str(audit.get("decision") or "")
        is_duplicate = _audit_is_duplicate(audit) or bool(ledger_value and "duplicate" in ledger_value)
        is_good = bool(ledger_value in GOOD_VALUES or "candidate" in str(ledger_value) or "champion" in str(ledger_value))
        is_bad = bool(
            is_duplicate
            or decision == "rejected"
            or ledger_value in BAD_VALUES
            or "rejected" in str(ledger_value)
        )

        event = {
            "created_at": now_iso(),
            "run_id": run_id,
            "hypothesis_id": hypothesis_id,
            "family": family,
            "decision": decision,
            "ledger_value": ledger_value,
            "is_duplicate": is_duplicate,
            "is_bad": is_bad,
            "is_good": is_good,
            "duplicate_of_run_id": audit.get("duplicate_of_run_id"),
        }
        row["events"].append(event)

    for branch, row in branches.items():
        events = row.get("events", [])[-window:]
        row["events"] = events
        row["duplicate_count"] = sum(1 for e in events if e.get("is_duplicate"))
        row["bad_count"] = sum(1 for e in events if e.get("is_bad"))
        row["good_count"] = sum(1 for e in events if e.get("is_good"))
        row["last_updated_at"] = now_iso()

        if row["good_count"] > 0:
            row["status"] = "active"
            row["reason"] = "has_good_recent_event"
        elif row["duplicate_count"] >= duplicate_threshold:
            row["status"] = "exhausted"
            row["reason"] = f"duplicate_threshold_reached:{row['duplicate_count']}"
        elif row["bad_count"] >= bad_threshold:
            row["status"] = "exhausted"
            row["reason"] = f"bad_threshold_reached:{row['bad_count']}"
        else:
            row["status"] = "active"
            row["reason"] = "below_threshold"

    previous = load_semantic_branch_state(state_dir)
    previous["branches"] = branches
    save_semantic_branch_state(state_dir, previous)
    return previous


def semantic_branch_status(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    hypothesis_id: str | None,
    family: str | None,
    refresh: bool = True,
) -> dict[str, Any]:
    if refresh:
        refresh_semantic_branch_state(state_dir=state_dir, runs_dir=runs_dir)
    state = load_semantic_branch_state(state_dir)
    branch = semantic_branch_key(hypothesis_id=hypothesis_id, family=family)
    row = (state.get("branches") or {}).get(branch) or {}
    return {
        "branch_key": branch,
        "exhausted": row.get("status") == "exhausted",
        "status": row.get("status", "active"),
        "reason": row.get("reason"),
        "duplicate_count": row.get("duplicate_count", 0),
        "bad_count": row.get("bad_count", 0),
        "good_count": row.get("good_count", 0),
        "events": row.get("events", [])[-5:],
    }


def semantic_branch_preflight(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    hypothesis_id: str | None,
    family: str | None,
) -> dict[str, Any]:
    status = semantic_branch_status(
        state_dir=state_dir,
        runs_dir=runs_dir,
        hypothesis_id=hypothesis_id,
        family=family,
        refresh=True,
    )
    if not status.get("exhausted"):
        return {"blocked": False, **status}

    duplicate_of = None
    for ev in reversed(status.get("events") or []):
        if ev.get("is_duplicate"):
            duplicate_of = ev.get("duplicate_of_run_id") or ev.get("run_id")
            break

    return {
        "blocked": True,
        "reason": f"semantic_branch_exhausted:{status.get('branch_key')}:{status.get('reason')}",
        "duplicate_of_run_id": duplicate_of,
        **status,
    }


def is_semantic_branch_exhausted(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    hypothesis_id: str | None,
    family: str | None,
) -> dict[str, Any]:
    return semantic_branch_status(
        state_dir=state_dir,
        runs_dir=runs_dir,
        hypothesis_id=hypothesis_id,
        family=family,
        refresh=True,
    )


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--hypothesis-id", default=None)
    p.add_argument("--family", default=None)
    args = p.parse_args()

    refresh_semantic_branch_state(state_dir=args.state_dir, runs_dir=args.runs_dir)
    if args.hypothesis_id:
        print(json.dumps(semantic_branch_preflight(
            state_dir=args.state_dir,
            runs_dir=args.runs_dir,
            hypothesis_id=args.hypothesis_id,
            family=args.family,
        ), indent=2, ensure_ascii=False, default=str))
    else:
        state = load_semantic_branch_state(args.state_dir)
        exhausted = {
            k: v
            for k, v in (state.get("branches") or {}).items()
            if v.get("status") == "exhausted"
        }
        print(json.dumps({
            "path": str(semantic_branch_path(args.state_dir)),
            "branch_count": len(state.get("branches") or {}),
            "exhausted_count": len(exhausted),
            "exhausted_sample": list(exhausted)[:20],
        }, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
