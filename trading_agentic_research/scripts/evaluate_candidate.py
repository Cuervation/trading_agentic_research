"""Evaluate a completed run folder, write audit.json, and persist learning.

Adds:
- global duplicate detection via state/artifact_hash_index.json
- research_ledger.jsonl event per run
- champion/current-parent governance updates
- consumed_hypotheses.jsonl so exact hypotheses are not run twice
- candidate-review learning updates scoped to the active candidate under review
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.validation import audit_run_folder
from scripts.update_evidence_memory import persist_learning_from_run
from scripts.research.artifact_index import (
    apply_duplicate_to_audit,
    find_duplicate_artifact,
    update_artifact_index,
)
from scripts.research.champion_governance import update_champion_state
from scripts.research.research_ledger import append_run_to_ledger
from scripts.research.consumed_hypotheses import append_consumed_hypothesis
from scripts.research.candidate_review_learning import update_candidate_review_learning_from_run
from scripts.research.semantic_branch_guard import refresh_semantic_branch_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a completed strategy run.")
    parser.add_argument("--run-id", required=True, help="Run id under runs/, e.g. EXP_001 or AUTO_001.")
    parser.add_argument("--runs-dir", default="runs", help="Base runs directory.")
    parser.add_argument("--parent-run-id", default=None)
    parser.add_argument("--min-trades", type=int, default=10)
    parser.add_argument("--hypothesis-id", default="HYP_BASELINE_MOMENTUM_TREND_V1")
    parser.add_argument("--family", default="cross_sectional_momentum")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--allow-parent-update", action="store_true")
    return parser.parse_args()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")

    parent_run_dir = Path(args.runs_dir) / args.parent_run_id if args.parent_run_id else None
    audit = audit_run_folder(run_dir, min_trades=args.min_trades, parent_run_dir=parent_run_dir)

    duplicate_info = find_duplicate_artifact(run_dir, args.state_dir)
    if duplicate_info.get("is_duplicate"):
        audit = apply_duplicate_to_audit(audit, duplicate_info)

    audit_path = run_dir / "audit.json"
    _write_json(audit_path, audit)

    learning_result = persist_learning_from_run(
        run_dir=run_dir,
        state_dir=args.state_dir,
        run_id=args.run_id,
        hypothesis_id=args.hypothesis_id,
        family=args.family,
        audit=audit,
    )

    index_result = update_artifact_index(run_dir, args.state_dir)
    champion_decision = update_champion_state(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
        duplicate_info=duplicate_info,
        allow_parent_move=bool(args.allow_parent_update),
    )
    ledger_event = append_run_to_ledger(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
        duplicate_info=duplicate_info,
        champion_decision=champion_decision,
    )

    consumed_result = append_consumed_hypothesis(
        state_dir=args.state_dir,
        run_id=args.run_id,
        hypothesis_id=args.hypothesis_id,
        family=args.family,
        decision=audit.get("decision"),
        value_delivered=ledger_event.get("value_delivered"),
    )

    candidate_review_learning = update_candidate_review_learning_from_run(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
    )

    # SEMANTIC_BRANCH_REFRESH_DIRECT_PATCH
    semantic_branch_state = refresh_semantic_branch_state(
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
    )

    print(f"Audit completed: {args.run_id}")
    print(f"Decision: {audit['decision']}")
    if duplicate_info.get("is_duplicate"):
        print(f"Global duplicate: {duplicate_info.get('duplicate_of_run_id')}")
    if args.parent_run_id:
        print(f"Parent comparison: {args.parent_run_id}")
        print(f"Can move parent: {audit['can_move_parent']}")
    print(f"Audit file: {audit_path}")
    print(f"Learning event: {learning_result['learning_event']['learning_id']}")
    print(f"Artifact index updated: {index_result.get('index_path')}")
    print(f"Champion action: {champion_decision.get('champion_action')}")
    print(f"Ledger value: {ledger_event.get('value_delivered')}")
    print(f"Consumed hypothesis: {consumed_result.get('reason') or consumed_result.get('hypothesis_id')}")
    print(f"Candidate-review learning: {candidate_review_learning.get('reason') or candidate_review_learning.get('exhausted_axes') or candidate_review_learning.get('updated')}")
    print(f"Semantic branch exhausted: {sum(1 for b in (semantic_branch_state.get('branches') or {}).values() if b.get('status') == 'exhausted')}")
    print("Baseline promotion: blocked (manual review required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
