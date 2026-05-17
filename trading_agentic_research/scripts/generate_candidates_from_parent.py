"""Generate new hypotheses (with strategy_overrides) from the current parent and bibliography.

Rules:
- No random variants.
- Each hypothesis must include bibliography_basis and/or empirical_basis.
- Each hypothesis must include non-empty strategy_overrides (small patch).
- Do not generate hypotheses for families currently in cooldown.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_hypotheses_from_bibliography import validate_candidate_basis
from scripts.select_next_hypothesis import read_json, read_jsonl


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_parent_context(*, state_dir: str | Path, strategy_registry_path: str | Path, evidence_memory_path: str | Path) -> dict:
    state_dir = Path(state_dir)
    current_parent = read_json(state_dir / "current_parent.json")
    if not current_parent.get("current_parent_run_id"):
        raise ValueError("current_parent_run_id is missing; run at least one promoted_candidate first.")

    evidence = read_json(evidence_memory_path)
    parent_run_id = str(current_parent["current_parent_run_id"])
    parent_run_payload = (evidence.get("runs") or {}).get(parent_run_id)
    if not parent_run_payload:
        raise ValueError(f"Parent run_id not found in evidence_memory.json: {parent_run_id}")

    registry = read_json(strategy_registry_path)
    parent_strategy_id = str(current_parent.get("current_parent_strategy_id") or "")
    if not parent_strategy_id:
        raise ValueError("current_parent_strategy_id is missing.")

    parent_config_path = None
    for row in registry.get("strategies", []):
        if row.get("strategy_id") == parent_strategy_id:
            parent_config_path = row.get("config_path")
            break
    if not parent_config_path:
        raise ValueError(f"Parent strategy_id not found in strategy registry: {parent_strategy_id}")

    return {
        "parent_run_id": parent_run_id,
        "parent_learning_id": str(parent_run_payload.get("learning_id")),
        "parent_strategy_id": parent_strategy_id,
        "parent_strategy_family": str(parent_run_payload.get("family") or ""),
        "parent_config_path": str(parent_config_path),
    }


def _existing_hypothesis_ids(hypothesis_bank_path: str | Path) -> set[str]:
    return {str(row.get("hypothesis_id")) for row in read_jsonl(hypothesis_bank_path) if row.get("hypothesis_id")}


def _append_jsonl(path: str | Path, rows: list[dict]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = p.read_text(encoding="utf-8-sig").splitlines() if p.exists() else []
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(existing_lines) + len(rows)


def build_parent_mutation_hypotheses(
    *,
    parent_run_id: str,
    parent_learning_id: str,
    family: str,
    version_suffix: str = "V1",
) -> list[dict]:
    """Return a deterministic list of small, auditable candidate hypotheses."""
    empirical_basis = [
        {
            "run_id": parent_run_id,
            "learning_id": parent_learning_id,
            "reason": "Derived from current parent evidence; test one small change at a time.",
        }
    ]
    bibliography_basis = [
        {"source_id": "academic_momentum_jegadeesh_titman_1993", "principle_id": "academic_momentum_relative_winners"},
        {"source_id": "faber_tactical_asset_allocation", "principle_id": "market_trend_filter"},
    ]

    candidates = [
        {
            "hypothesis_id": f"HYP_MOMENTUM_TOPN_8_{version_suffix}",
            "family": family,
            "claim": "Further concentration (top 8) may increase signal-to-noise and improve CAGR without worsening drawdown materially.",
            "bibliography_basis": bibliography_basis,
            "empirical_basis": empirical_basis,
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "created_at": _now_utc_iso(),
            "strategy_overrides": {
                "strategy_id": f"SP500_MOMENTUM_TOPN_8_{version_suffix}",
                "entry_rule": {"top_n": 8},
            },
        },
        {
            "hypothesis_id": f"HYP_MOMENTUM_TOPN_12_{version_suffix}",
            "family": family,
            "claim": "Slightly less concentration (top 12) may reduce concentration risk while preserving excess return.",
            "bibliography_basis": bibliography_basis,
            "empirical_basis": empirical_basis,
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "created_at": _now_utc_iso(),
            "strategy_overrides": {
                "strategy_id": f"SP500_MOMENTUM_TOPN_12_{version_suffix}",
                "entry_rule": {"top_n": 12},
            },
        },
        {
            "hypothesis_id": f"HYP_MOMENTUM_EXIT_15_{version_suffix}",
            "family": family,
            "claim": "Tighter exit buffer (exit if rank > 15) may reduce drawdown and improve reactivity, at the cost of more turnover.",
            "bibliography_basis": bibliography_basis,
            "empirical_basis": empirical_basis,
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "created_at": _now_utc_iso(),
            "strategy_overrides": {
                "strategy_id": f"SP500_MOMENTUM_EXIT_15_{version_suffix}",
                "exit_rule": {"rank_threshold": 15},
            },
        },
        {
            "hypothesis_id": f"HYP_MOMENTUM_EXIT_25_{version_suffix}",
            "family": family,
            "claim": "Looser exit buffer (exit if rank > 25) may reduce churn while keeping trend exposure.",
            "bibliography_basis": bibliography_basis,
            "empirical_basis": empirical_basis,
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "created_at": _now_utc_iso(),
            "strategy_overrides": {
                "strategy_id": f"SP500_MOMENTUM_EXIT_25_{version_suffix}",
                "exit_rule": {"rank_threshold": 25},
            },
        },
    ]

    for h in candidates:
        validate_candidate_basis(h)
        if not isinstance(h.get("strategy_overrides"), dict) or not h["strategy_overrides"]:
            raise ValueError(f"Candidate missing strategy_overrides: {h.get('hypothesis_id')}")
    return candidates


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate new candidate hypotheses from current parent.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--evidence-memory", default="state/evidence_memory.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--cooldowns", default="state/subspace_cooldowns.json")
    p.add_argument("--family", default="cross_sectional_momentum")
    p.add_argument("--version-suffix", default="V1")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cooldowns = read_json(args.cooldowns) if Path(args.cooldowns).exists() else {"cooldowns": {}}
    if args.family in (cooldowns.get("cooldowns") or {}):
        print(json.dumps({"generated": 0, "reason": "family_in_cooldown", "family": args.family}))
        return 0

    parent_ctx = _load_parent_context(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        evidence_memory_path=args.evidence_memory,
    )

    existing_ids = _existing_hypothesis_ids(args.hypothesis_bank)
    candidates = build_parent_mutation_hypotheses(
        parent_run_id=parent_ctx["parent_run_id"],
        parent_learning_id=parent_ctx["parent_learning_id"],
        family=args.family,
        version_suffix=str(args.version_suffix),
    )
    to_add = [h for h in candidates if h["hypothesis_id"] not in existing_ids]

    if args.dry_run:
        print(json.dumps({"generated": len(to_add), "hypotheses": [h["hypothesis_id"] for h in to_add]}))
        return 0

    _append_jsonl(args.hypothesis_bank, to_add)
    print(json.dumps({"generated": len(to_add), "written_to": str(args.hypothesis_bank)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
