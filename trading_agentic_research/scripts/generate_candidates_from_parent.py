"""Generate new hypotheses (with strategy_overrides) from the current parent + bibliography.

This is the primary hypothesis generator used by the batch runner.

Rules (project-wide):
- No random variants.
- Each hypothesis MUST include bibliography_basis and/or empirical_basis.
- Each hypothesis MUST include non-empty strategy_overrides (small patch).
- Do not generate hypotheses for families currently in cooldown.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_hypotheses_from_bibliography import validate_candidate_basis
from scripts.hypothesis_generator import (
    append_jsonl,
    existing_override_signatures,
    generate_hypotheses_from_parent,
)
from scripts.select_next_hypothesis import read_json, read_jsonl


def _parse_families_arg(value: str) -> list[str]:
    parts = [p.strip() for p in (value or "").split(",") if p.strip()]
    return parts or ["cross_sectional_momentum"]


def _load_parent_context(*, state_dir: str | Path, strategy_registry_path: str | Path, evidence_memory_path: str | Path) -> dict:
    state_dir = Path(state_dir)
    current_parent = read_json(state_dir / "current_parent.json")
    parent_run_id = current_parent.get("current_parent_run_id")
    parent_strategy_id = current_parent.get("current_parent_strategy_id")

    evidence = read_json(evidence_memory_path) if Path(evidence_memory_path).exists() else {}
    parent_learning_id = None
    if parent_run_id and isinstance(evidence, dict):
        parent_run_payload = (evidence.get("runs") or {}).get(str(parent_run_id))
        if isinstance(parent_run_payload, dict):
            parent_learning_id = parent_run_payload.get("learning_id")

    registry = read_json(strategy_registry_path)
    parent_config_path = None
    if parent_strategy_id:
        for row in registry.get("strategies", []):
            if row.get("strategy_id") == parent_strategy_id:
                parent_config_path = row.get("config_path")
                break

    return {
        "parent_run_id": str(parent_run_id) if parent_run_id else None,
        "parent_learning_id": str(parent_learning_id) if parent_learning_id else None,
        "parent_strategy_id": str(parent_strategy_id) if parent_strategy_id else None,
        "parent_config_path": str(parent_config_path) if parent_config_path else None,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate new candidate hypotheses from current parent.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--parent-strategy-config", default="configs/baseline_momentum_trend_v1.json")
    p.add_argument("--evidence-memory", default="state/evidence_memory.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--cooldowns", default="state/subspace_cooldowns.json")
    p.add_argument("--family", default="cross_sectional_momentum", help="Single family (legacy).")
    p.add_argument("--families", default="", help="Comma-separated list of families to generate for.")
    p.add_argument("--max-new-per-family", type=int, default=6)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cooldowns = read_json(args.cooldowns) if Path(args.cooldowns).exists() else {"cooldowns": {}}
    cooldown_map = (cooldowns.get("cooldowns") or {}) if isinstance(cooldowns, dict) else {}

    bank = list(read_jsonl(args.hypothesis_bank))
    existing_ids = {str(r.get("hypothesis_id")) for r in bank if r.get("hypothesis_id")}
    existing_sigs = existing_override_signatures(bank)

    parent_ctx = _load_parent_context(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        evidence_memory_path=args.evidence_memory,
    )
    parent_cfg = read_json(args.parent_strategy_config)

    families = _parse_families_arg(args.families) if args.families else _parse_families_arg(args.family)

    # Backward-compatible behavior: when a single explicit family is requested and it is in cooldown,
    # return an explicit reason instead of silently producing no candidates.
    if not args.families and len(families) == 1 and families[0] in cooldown_map:
        print(json.dumps({"generated": 0, "reason": "family_in_cooldown", "family": families[0]}))
        return 0

    all_new: list[dict] = []
    for fam in families:
        if fam in cooldown_map:
            continue
        new_rows = generate_hypotheses_from_parent(
            family=fam,
            parent_strategy_config=parent_cfg,
            parent_run_id=parent_ctx["parent_run_id"],
            parent_learning_id=parent_ctx["parent_learning_id"],
            existing_ids=existing_ids,
            existing_override_sigs=existing_sigs,
            max_new=int(args.max_new_per_family),
        )
        for row in new_rows:
            validate_candidate_basis(row)
        all_new.extend(new_rows)

    if args.dry_run:
        print(json.dumps({"generated": len(all_new), "hypotheses": [h["hypothesis_id"] for h in all_new]}))
        return 0

    if not all_new:
        print(json.dumps({"generated": 0, "reason": "no_new_candidates"}))
        return 0

    append_jsonl(args.hypothesis_bank, all_new)
    print(json.dumps({"generated": len(all_new), "hypotheses": [h["hypothesis_id"] for h in all_new]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
