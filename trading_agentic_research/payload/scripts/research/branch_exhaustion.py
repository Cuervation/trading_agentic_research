"""Branch exhaustion memory for autonomous research.

A branch is more granular than a family.  Example:
feature_space_momentum/channel_r2/top_n.  If a branch repeatedly produces
rejections, duplicates or no-effect runs, generation/selection should stop
spending backtests there and move to a different mechanism.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.research.consumed_hypotheses import append_consumed_hypothesis, read_jsonl
from scripts.research.strategy_effect_signature import read_json

BRANCH_FILE = "branch_exhaustion.json"
LEDGER_FILE = "research_ledger.jsonl"

BAD_VALUES = {
    "duplicate_blocked",
    "duplicate_preflight_blocked",
    "metric_no_effect_blocked",
    "branch_exhausted_preflight_blocked",
}
WEAK_VALUES = {"rejected_with_learning"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: Any):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def append_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    return len(rows)


def _deep_get(d: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def _axis_from_hypothesis_id(hypothesis_id: str) -> str:
    hid = str(hypothesis_id or "").upper()
    if "_TOPN_" in hid or "CONCENTRATION" in hid:
        return "top_n"
    if "_EXIT_" in hid:
        return "exit_rank"
    if "TRAIL" in hid or "RISK" in hid:
        return "risk_management"
    if "_MKT_" in hid or "REGIME" in hid or "SPY" in hid:
        return "market_filter"
    if "_CONF_" in hid or "CONFIRM" in hid:
        return "confirmation"
    if "_RANK_" in hid:
        return "ranking"
    return "unknown_axis"


def branch_key_from_payload(
    *,
    hypothesis_id: str | None = None,
    family: str | None = None,
    axis: str | None = None,
    strategy_config: dict[str, Any] | None = None,
) -> str:
    strategy_config = strategy_config or {}
    ranking = strategy_config.get("ranking", {}) if isinstance(strategy_config.get("ranking"), dict) else {}
    ranking_field = str(strategy_config.get("ranking_column") or ranking.get("field") or "unknown_rank")
    real_axis = str(axis or _axis_from_hypothesis_id(str(hypothesis_id or "")))
    fam = str(family or strategy_config.get("strategy_family") or "unknown_family")
    return f"{fam}/{ranking_field}/{real_axis}"


def branch_key_for_hypothesis(hypothesis: dict[str, Any], strategy_config_path: str | Path | None = None) -> str:
    cfg = read_json(strategy_config_path, {}) if strategy_config_path else {}
    return branch_key_from_payload(
        hypothesis_id=str(hypothesis.get("hypothesis_id") or ""),
        family=str(hypothesis.get("family") or cfg.get("strategy_family") or ""),
        axis=hypothesis.get("axis"),
        strategy_config=cfg or {},
    )


def load_branch_exhaustion(state_dir: str | Path = "state") -> dict[str, Any]:
    payload = read_json(Path(state_dir) / BRANCH_FILE, None)
    if not isinstance(payload, dict):
        return {"version": 1, "branches": {}, "updated_at": now_iso()}
    payload.setdefault("version", 1)
    payload.setdefault("branches", {})
    return payload


def save_branch_exhaustion(state_dir: str | Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = now_iso()
    write_json(Path(state_dir) / BRANCH_FILE, payload)


def refresh_branch_exhaustion(
    *,
    state_dir: str | Path = "state",
    lookback: int = 150,
    duplicate_threshold: int = 2,
    bad_score_threshold: int = 5,
    cooldown_days: int = 30,
) -> dict[str, Any]:
    rows = read_jsonl(Path(state_dir) / LEDGER_FILE)[-int(lookback):]
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get("value_delivered") or "")
        hid = str(row.get("hypothesis_id") or "")
        if not hid:
            continue
        family = str(row.get("family") or "")
        branch = row.get("branch_key") or branch_key_from_payload(hypothesis_id=hid, family=family, axis=row.get("axis"), strategy_config={})
        s = stats.setdefault(str(branch), {"branch_key": str(branch), "events": 0, "duplicates": 0, "metric_no_effect": 0, "rejections": 0, "bad_score": 0, "examples": []})
        s["events"] += 1
        if value in BAD_VALUES:
            s["bad_score"] += 2
            if "duplicate" in value:
                s["duplicates"] += 1
            if "metric_no_effect" in value:
                s["metric_no_effect"] += 1
        elif value in WEAK_VALUES:
            s["bad_score"] += 1
            s["rejections"] += 1
        if len(s["examples"]) < 8:
            s["examples"].append({"hypothesis_id": hid, "value_delivered": value, "run_id": row.get("run_id")})

    payload = load_branch_exhaustion(state_dir)
    branches = payload.setdefault("branches", {})
    until = (datetime.now(timezone.utc) + timedelta(days=int(cooldown_days))).isoformat()
    for branch, s in stats.items():
        exhausted = int(s.get("duplicates", 0)) >= duplicate_threshold or int(s.get("bad_score", 0)) >= bad_score_threshold
        existing = branches.get(branch, {}) if isinstance(branches.get(branch), dict) else {}
        if exhausted:
            branches[branch] = {
                **existing,
                **s,
                "status": "exhausted",
                "blocks_generation": True,
                "blocks_selection": True,
                "cooldown_until": until,
                "reason": "branch_repeated_duplicates_or_rejections",
                "updated_at": now_iso(),
            }
        elif branch not in branches:
            branches[branch] = {**s, "status": "watch", "blocks_generation": False, "blocks_selection": False, "updated_at": now_iso()}
    save_branch_exhaustion(state_dir, payload)
    return {"updated": True, "branches": len(branches), "exhausted": [k for k, v in branches.items() if v.get("status") == "exhausted"]}


def is_hypothesis_branch_exhausted(
    *,
    hypothesis: dict[str, Any],
    strategy_config_path: str | Path | None = None,
    state_dir: str | Path = "state",
) -> dict[str, Any]:
    payload = load_branch_exhaustion(state_dir)
    branch = branch_key_for_hypothesis(hypothesis, strategy_config_path)
    row = payload.get("branches", {}).get(branch)
    if not isinstance(row, dict):
        return {"blocked": False, "branch_key": branch, "reason": "branch_not_exhausted"}
    if row.get("status") != "exhausted" or not row.get("blocks_selection", True):
        return {"blocked": False, "branch_key": branch, "reason": "branch_not_blocking", "branch": row}
    until = parse_dt(row.get("cooldown_until"))
    if until is not None and until <= datetime.now(timezone.utc):
        return {"blocked": False, "branch_key": branch, "reason": "branch_cooldown_expired", "branch": row}
    return {"blocked": True, "branch_key": branch, "reason": row.get("reason") or "branch_exhausted", "branch": row}


def mark_branch_blocked_hypothesis(
    *,
    state_dir: str | Path,
    hypothesis_id: str,
    family: str | None,
    branch_check: dict[str, Any],
    source: str = "branch_exhaustion_preflight",
) -> dict[str, Any]:
    pseudo_run_id = f"PRE_RUN_BRANCH_{hypothesis_id}"
    consumed = append_consumed_hypothesis(
        state_dir=state_dir,
        run_id=pseudo_run_id,
        hypothesis_id=hypothesis_id,
        family=family,
        decision="rejected",
        value_delivered="branch_exhausted_preflight_blocked",
        source=source,
    )
    event = {
        "event_id": f"LEDGER_{pseudo_run_id}",
        "created_at": now_iso(),
        "run_id": pseudo_run_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "decision": "rejected",
        "value_delivered": "branch_exhausted_preflight_blocked",
        "branch_key": branch_check.get("branch_key"),
        "learned": f"{hypothesis_id} was blocked before backtest because branch {branch_check.get('branch_key')} is exhausted.",
        "next_action": "generate_different_branch",
        "reason": branch_check.get("reason"),
    }
    append_jsonl(Path(state_dir) / LEDGER_FILE, [event])
    return {"blocked": True, "consumed": consumed, "event": event}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Refresh branch exhaustion memory.")
    p.add_argument("--state-dir", default="state")
    args = p.parse_args()
    print(json.dumps(refresh_branch_exhaustion(state_dir=args.state_dir), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
