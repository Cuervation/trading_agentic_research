"""Generate follow-up hypotheses for the active candidate under review.

The official parent is not changed. These hypotheses refine the candidate config
(e.g. EXP_044) to try to keep its CAGR while reducing drawdown.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.autonomous_hypothesis_factory import (
    append_jsonl,
    existing_ids,
    existing_override_sigs,
    read_json,
    read_jsonl,
    real_override_signature,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _candidate_state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "candidate_under_review.json"


def _hypothesis(
    *,
    hypothesis_id: str,
    family: str,
    claim: str,
    mechanism: str,
    candidate_run_id: str,
    candidate_hypothesis_id: str | None,
    official_parent_run_id: str | None,
    overrides: dict[str, Any],
    falsification_rule: str,
) -> dict[str, Any]:
    return {
        "hypothesis_id": hypothesis_id,
        "family": family,
        "axis": family,
        "claim": claim,
        "causal_mechanism": mechanism,
        "bibliography_basis": [
            {"source_id": "candidate_under_review_refinement", "principle_id": "risk_adjusted_followup"}
        ],
        "empirical_basis": [
            {
                "run_id": candidate_run_id,
                "hypothesis_id": candidate_hypothesis_id,
                "reason": "Candidate under review improved CAGR but worsened drawdown; refine it before any parent move.",
            },
            {
                "run_id": official_parent_run_id,
                "reason": "Official parent remains the governance benchmark.",
            },
        ],
        "features_required": ["close", "ticker"],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "falsification_rule": falsification_rule,
        "strategy_overrides": overrides,
    }


def generate_candidate_review_hypotheses(
    *,
    state_dir: str | Path = "state",
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    max_new: int = 8,
) -> dict[str, Any]:
    candidate = read_json(_candidate_state_path(state_dir), {}) or {}
    if candidate.get("status") != "active":
        return {"generated": 0, "reason": "no_active_candidate_under_review", "candidate_status": candidate.get("status")}

    config_path = candidate.get("candidate_config_path")
    cfg = read_json(config_path, {}) if config_path else {}
    if not cfg:
        return {"generated": 0, "reason": "missing_candidate_config", "candidate_config_path": config_path}

    candidate_run_id = str(candidate.get("candidate_run_id"))
    candidate_hypothesis_id = candidate.get("candidate_hypothesis_id")
    official_parent_run_id = candidate.get("official_parent_run_id")
    entry = dict(cfg.get("entry_rule", {}) or {})
    exit_rule = dict(cfg.get("exit_rule", {}) or {})
    base_top_n = _safe_int(entry.get("top_n"), 6)
    base_exit = _safe_int(exit_rule.get("rank_threshold"), 20)

    bank = read_jsonl(hypothesis_bank_path)
    ids = existing_ids(bank)
    sigs = existing_override_sigs(bank)
    rows: list[dict[str, Any]] = []

    def add(row: dict[str, Any]) -> None:
        if len(rows) >= max_new:
            return
        hid = str(row["hypothesis_id"])
        if hid in ids:
            return
        sig = real_override_signature(row.get("strategy_overrides", {}))
        if sig in sigs:
            return
        rows.append(row)
        ids.add(hid)
        sigs.add(sig)

    # If EXP_044 is top_n=6, try 7/8 to reduce concentration and drawdown.
    for top_n in sorted({base_top_n + 1, base_top_n + 2, max(4, base_top_n - 1)}):
        overrides = {
            "strategy_id": f"HYP_REVIEW_{candidate_run_id}_TOPN_{top_n}_V1",
            "strategy_family": "candidate_under_review_drawdown_refinement",
            "entry_rule": {**entry, "top_n": top_n},
        }
        add(_hypothesis(
            hypothesis_id=overrides["strategy_id"],
            family="candidate_under_review_drawdown_refinement",
            claim=f"Refining {candidate_run_id} with top_n={top_n} may reduce concentration-driven drawdown while preserving much of its CAGR gain.",
            mechanism="A slightly wider basket can soften single-name drawdowns while keeping the candidate's ranking logic.",
            candidate_run_id=candidate_run_id,
            candidate_hypothesis_id=candidate_hypothesis_id,
            official_parent_run_id=official_parent_run_id,
            overrides=overrides,
            falsification_rule="Reject if CAGR advantage versus the official parent disappears or drawdown remains materially worse than the candidate.",
        ))

    # Exit rank refinements around the candidate.
    for rank_threshold in sorted({max(8, base_exit - 4), max(8, base_exit - 2), base_exit + 2}):
        overrides = {
            "strategy_id": f"HYP_REVIEW_{candidate_run_id}_EXIT_{rank_threshold}_V1",
            "strategy_family": "candidate_under_review_exit_refinement",
            "exit_rule": {**exit_rule, "rank_threshold": rank_threshold},
        }
        add(_hypothesis(
            hypothesis_id=overrides["strategy_id"],
            family="candidate_under_review_exit_refinement",
            claim=f"Refining {candidate_run_id} with rank_threshold={rank_threshold} may cut deteriorating positions earlier and reduce drawdown.",
            mechanism="Exit sensitivity can reduce prolonged losers after a concentrated momentum entry.",
            candidate_run_id=candidate_run_id,
            candidate_hypothesis_id=candidate_hypothesis_id,
            official_parent_run_id=official_parent_run_id,
            overrides=overrides,
            falsification_rule="Reject if drawdown does not improve or if yearly SPY comparison deteriorates versus the official parent.",
        ))

    # Gentle regime hardening: only uses a field already present in the user's feature store.
    overrides = {
        "strategy_id": f"HYP_REVIEW_{candidate_run_id}_SPY_REGIME_MINUS1_V1",
        "strategy_family": "candidate_under_review_regime_refinement",
        "market_filter": {
            "benchmark": "SPY",
            "condition_any": [
                {"field": "spy_close_vs_sma50_pct", "operator": ">", "value": -1.0, "enabled_if_field_exists": True}
            ],
            "require_positive_trend": False,
        },
    }
    add(_hypothesis(
        hypothesis_id=overrides["strategy_id"],
        family="candidate_under_review_regime_refinement",
        claim=f"Refining {candidate_run_id} with a mild SPY regime floor may reduce drawdown while preserving participation.",
        mechanism="A mild benchmark regime gate can avoid part of broad market stress without over-filtering recoveries.",
        candidate_run_id=candidate_run_id,
        candidate_hypothesis_id=candidate_hypothesis_id,
        official_parent_run_id=official_parent_run_id,
        overrides=overrides,
        falsification_rule="Reject if market filter fallback dominates or if CAGR improvement is lost without drawdown improvement.",
    ))

    append_jsonl(hypothesis_bank_path, rows)
    return {
        "generated": len(rows),
        "reason": "candidate_under_review_hypotheses_generated" if rows else "no_new_candidate_under_review_hypotheses",
        "candidate_run_id": candidate_run_id,
        "hypotheses": [row["hypothesis_id"] for row in rows],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--max-new", type=int, default=8)
    args = p.parse_args()
    print(json.dumps(generate_candidate_review_hypotheses(state_dir=args.state_dir, hypothesis_bank_path=args.hypothesis_bank, max_new=args.max_new), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
