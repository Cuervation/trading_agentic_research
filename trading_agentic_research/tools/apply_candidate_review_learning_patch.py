"""Apply candidate-review learning patch in-place.

Run from repo root:
  python .\tools\apply_candidate_review_learning_patch.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_after(path: Path, needle: str, addition: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if addition.strip() in text:
        return
    if needle not in text:
        raise RuntimeError(f"Needle not found in {path}: {needle!r}")
    path.write_text(text.replace(needle, needle + addition, 1), encoding="utf-8")


def patch_select_next() -> None:
    path = ROOT / "scripts" / "select_next_hypothesis.py"
    insert_after(
        path,
        "from scripts.parameter_effect_memory import load_parameter_effect_memory, score_hypothesis_axis\n",
        "from scripts.research.candidate_review_learning import (\n"
        "    candidate_review_priority,\n"
        "    is_candidate_review_hypothesis_blocked,\n"
        ")\n"
        "from scripts.research.consumed_hypotheses import consumed_hypothesis_ids\n",
    )
    replace_once(
        path,
        "prefer_unseen: bool = True,\n) -> dict:",
        "prefer_unseen: bool = True,\n    state_dir: str | Path = \"state\",\n) -> dict:",
    )
    replace_once(
        path,
        "    candidates = []\n    for hypothesis in hypothesis_bank:",
        "    consumed_ids = consumed_hypothesis_ids(state_dir)\n    candidates = []\n    for hypothesis in hypothesis_bank:",
    )
    replace_once(
        path,
        "        if hypothesis_id in rejected_ids:\n            continue\n        if current_parent_hypothesis_id and hypothesis_id == current_parent_hypothesis_id:\n            continue\n",
        "        if hypothesis_id in rejected_ids:\n            continue\n        if hypothesis_id in consumed_ids:\n            continue\n        if current_parent_hypothesis_id and hypothesis_id == current_parent_hypothesis_id:\n            continue\n        if is_candidate_review_hypothesis_blocked(hypothesis, state_dir=state_dir):\n            continue\n",
    )
    replace_once(
        path,
        "                # Prefer hypotheses with empirical basis.\n                -empirical_count,",
        "                # Candidate-under-review local priority: TOPN before trailing/exit.\n                candidate_review_priority(hypothesis),\n                # Prefer hypotheses with empirical basis.\n                -empirical_count,",
    )
    replace_once(
        path,
        "        prefer_unseen=bool(args.prefer_unseen),\n    )",
        "        prefer_unseen=bool(args.prefer_unseen),\n        state_dir=state_dir,\n    )",
    )


def patch_evaluate_candidate() -> None:
    path = ROOT / "scripts" / "evaluate_candidate.py"
    insert_after(
        path,
        "from scripts.research.champion_governance import update_champion_state\n",
        "from scripts.research.candidate_review_learning import (\n"
        "    update_candidate_review_learning_from_run,\n"
        "    write_candidate_review_learning_report,\n"
        ")\n",
    )
    replace_once(
        path,
        "    # Update artifact index after audit so the current run becomes known.\n    index_result = update_artifact_index(run_dir, args.state_dir)\n",
        "    # Update candidate-under-review learning before the next selection.\n"
        "    candidate_review_learning = update_candidate_review_learning_from_run(\n"
        "        run_dir=run_dir,\n"
        "        state_dir=args.state_dir,\n"
        "        audit=audit,\n"
        "    )\n"
        "    write_candidate_review_learning_report(state_dir=args.state_dir, reports_dir=\"reports\")\n\n"
        "    # Update artifact index after audit so the current run becomes known.\n"
        "    index_result = update_artifact_index(run_dir, args.state_dir)\n",
    )
    replace_once(
        path,
        "    if consumed_result.get(\"written\"):\n        print(f\"Consumed hypothesis: {args.hypothesis_id}\")\n    print(\"Baseline promotion: blocked (manual review required)\")\n",
        "    if consumed_result.get(\"written\"):\n        print(f\"Consumed hypothesis: {args.hypothesis_id}\")\n    if candidate_review_learning.get(\"updated\"):\n        print(\n            \"Candidate-review learning: \"\n            f\"axis={candidate_review_learning.get('axis')} \"\n            f\"exhausted={candidate_review_learning.get('exhausted_axes')}\"\n        )\n    print(\"Baseline promotion: blocked (manual review required)\")\n",
    )


def patch_run_autonomous() -> None:
    path = ROOT / "scripts" / "run_research_batch_autonomous.py"
    insert_after(
        path,
        "from scripts.research.candidate_review_refinement_factory import generate_candidate_review_hypotheses\n",
        "from scripts.research.candidate_review_learning import write_candidate_review_learning_report\n",
    )
    replace_once(
        path,
        "p.add_argument(\"--generation-families\", default=\"candidate_under_review_drawdown_refinement,candidate_under_review_exit_refinement,candidate_under_review_regime_refinement,time_series_momentum_refinement,risk_control_refinement,quality_momentum,trend_following,can_slim,paper_time_series_momentum,paper_quality_momentum,paper_regime_filter\")",
        "p.add_argument(\"--generation-families\", default=\"candidate_under_review_topn_refinement,candidate_under_review_drawdown_refinement,candidate_under_review_exit_refinement,candidate_under_review_regime_refinement,time_series_momentum_refinement,risk_control_refinement,quality_momentum,trend_following,can_slim,paper_time_series_momentum,paper_quality_momentum,paper_regime_filter\")",
    )
    insert_after(
        path,
        "    p.add_argument(\"--allow-zero-iterations\", action=\"store_true\")\n",
        "    p.add_argument(\n"
        "        \"--candidate-review-stop-after-consecutive-rejections\",\n"
        "        type=int,\n"
        "        default=5,\n"
        "        help=\"When candidate_under_review is active, allow more failed refinements before stopping so the loop can switch sub-axis.\",\n"
        "    )\n",
    )
    insert_after(
        path,
        "        write_promotion_candidate_review(state_dir=args.state_dir, runs_dir=args.runs_dir, reports_dir=args.reports_dir)\n",
        "        write_candidate_review_learning_report(state_dir=args.state_dir, reports_dir=args.reports_dir)\n",
    )
    replace_once(
        path,
        "    cmd = [\n        sys.executable,",
        "    stop_after_rejections = 2\n    if candidate_review.get(\"status\") == \"active\":\n        stop_after_rejections = max(2, int(args.candidate_review_stop_after_consecutive_rejections))\n\n    cmd = [\n        sys.executable,",
    )
    replace_once(
        path,
        "        \"--max-repeats-per-hypothesis\", str(args.max_repeats_per_hypothesis),\n        \"--parent-strategy-config\", parent_config,\n",
        "        \"--max-repeats-per-hypothesis\", str(args.max_repeats_per_hypothesis),\n        \"--stop-after-consecutive-rejections\", str(stop_after_rejections),\n        \"--parent-strategy-config\", parent_config,\n",
    )
    replace_once(
        path,
        "    write_promotion_candidate_review(state_dir=args.state_dir, runs_dir=args.runs_dir, reports_dir=args.reports_dir)\n    clear_autonomy_blocker(state_dir=args.state_dir, reason=\"batch_completed_with_value\")\n",
        "    write_promotion_candidate_review(state_dir=args.state_dir, runs_dir=args.runs_dir, reports_dir=args.reports_dir)\n    write_candidate_review_learning_report(state_dir=args.state_dir, reports_dir=args.reports_dir)\n    clear_autonomy_blocker(state_dir=args.state_dir, reason=\"batch_completed_with_value\")\n",
    )


def main() -> int:
    patch_select_next()
    patch_evaluate_candidate()
    patch_run_autonomous()
    print("Candidate review learning patch applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
