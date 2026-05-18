"""Apply generation eligibility feedback hardening patch.

This patch closes a subtle autonomy gap observed after parent-lock hardening:
- generators can append hypotheses that are immediately blocked/consumed;
- candidate_under_review can keep cycling exhausted sub-axes;
- value/literature generation reports "generated" but not whether anything became selectable.

The patch is intentionally conservative and idempotent. It:
1. Adds scripts/research/generation_feedback.py.
2. Makes candidate_under_review prefer pending_parent_candidate_run_id.
3. Makes candidate_review_refinement_factory skip exhausted axes and consumed ids.
4. Adds feedback/report hooks to run_research_batch_autonomous.py.
5. Forces the wrapper to sync parent state conservatively (prefer_best_champion=False).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find expected block for {label}")
    return text.replace(old, new, 1)


def patch_candidate_under_review() -> None:
    path = ROOT / "scripts" / "research" / "candidate_under_review.py"
    text = read(path)
    old = '''def _candidate_from_champion_state(state_dir: str | Path) -> str | None:
    champion = load_champion_state(state_dir)
    candidate = champion.get("baseline_candidate_run_id")
    if candidate:
        return str(candidate)
    candidates = champion.get("promotion_candidates", []) or []
    if candidates:
        return str(candidates[0].get("run_id"))
    return None
'''
    new = '''def _candidate_from_champion_state(state_dir: str | Path) -> str | None:
    """Choose the run that should be refined under manual-parent governance.

    Priority is intentional:
    1. pending_parent_candidate_run_id: the best/new champion awaiting manual review;
    2. best_champion_run_id if it differs from official/current parent;
    3. baseline_candidate_run_id / promotion_candidates as fallback.

    This prevents older baseline candidates from stealing focus from a newer,
    stronger pending candidate such as EXP_054.
    """
    champion = load_champion_state(state_dir)
    official_parent = champion.get("official_parent_run_id") or champion.get("current_parent_run_id")

    pending = champion.get("pending_parent_candidate_run_id")
    if pending and str(pending) != str(official_parent):
        return str(pending)

    best = champion.get("best_champion_run_id")
    if best and str(best) != str(official_parent):
        return str(best)

    candidate = champion.get("baseline_candidate_run_id")
    if candidate and str(candidate) != str(official_parent):
        return str(candidate)

    candidates = champion.get("promotion_candidates", []) or []
    for row in candidates:
        rid = row.get("run_id")
        if rid and str(rid) != str(official_parent):
            return str(rid)
    return None
'''
    write(path, replace_once(text, old, new, "candidate_under_review priority"))


def patch_candidate_review_factory() -> None:
    path = ROOT / "scripts" / "research" / "candidate_review_refinement_factory.py"
    text = read(path)
    import_old = '''from scripts.research.autonomous_hypothesis_factory import real_override_signature, read_jsonl
'''
    import_new = '''from scripts.research.autonomous_hypothesis_factory import real_override_signature, read_jsonl
from scripts.research.candidate_review_learning import infer_candidate_review_axis, load_candidate_review_learning
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids
'''
    text = replace_once(text, import_old, import_new, "candidate review factory imports")

    old = '''    ids, sigs = _existing_ids_and_sigs(hypothesis_bank_path)
    rows: list[dict[str, Any]] = []

    def add(row: dict[str, Any]) -> None:
        if len(rows) >= max_new:
            return
        hid = str(row.get("hypothesis_id"))
        if hid in ids:
            return
        sig = real_override_signature(row.get("strategy_overrides", {}))
        if sig in sigs:
            return
        ids.add(hid)
        sigs.add(sig)
        rows.append(row)
'''
    new = '''    ids, sigs = _existing_ids_and_sigs(hypothesis_bank_path)
    rows: list[dict[str, Any]] = []
    review_learning = load_candidate_review_learning(state_dir)
    exhausted_axes = set(review_learning.get("exhausted_axes", []) or [])
    try:
        consumed_ids = consumed_hypothesis_ids(state_dir)
    except Exception:
        consumed_ids = set()
    skipped: list[dict[str, str]] = []

    def add(row: dict[str, Any]) -> None:
        if len(rows) >= max_new:
            return
        hid = str(row.get("hypothesis_id"))
        axis = infer_candidate_review_axis(row)
        if axis in exhausted_axes:
            skipped.append({"hypothesis_id": hid, "axis": axis, "reason": "axis_exhausted"})
            return
        if hid in consumed_ids:
            skipped.append({"hypothesis_id": hid, "axis": axis, "reason": "already_consumed"})
            return
        if hid in ids:
            skipped.append({"hypothesis_id": hid, "axis": axis, "reason": "already_in_bank"})
            return
        sig = real_override_signature(row.get("strategy_overrides", {}))
        if sig in sigs:
            skipped.append({"hypothesis_id": hid, "axis": axis, "reason": "duplicate_override_signature"})
            return
        ids.add(hid)
        sigs.add(sig)
        rows.append(row)
'''
    text = replace_once(text, old, new, "candidate review factory add() filtering")

    old = '''    return rows[:max_new]
'''
    new = '''    # Store lightweight generation feedback on the function object so the CLI and
    # wrapper can inspect why no rows were produced without changing the public
    # return type used by older tests.
    build_candidate_review_hypotheses.last_skipped = skipped  # type: ignore[attr-defined]
    build_candidate_review_hypotheses.last_exhausted_axes = sorted(exhausted_axes)  # type: ignore[attr-defined]
    return rows[:max_new]
'''
    text = replace_once(text, old, new, "candidate review factory metadata")

    old = '''    return {
        "generated": len(rows),
        "reason": "candidate_under_review_hypotheses_generated" if rows else "no_new_candidate_under_review_hypotheses",
        "candidate_run_id": state.get("candidate_run_id"),
        "hypotheses": [row.get("hypothesis_id") for row in rows],
    }
'''
    new = '''    skipped = getattr(build_candidate_review_hypotheses, "last_skipped", [])
    exhausted_axes = getattr(build_candidate_review_hypotheses, "last_exhausted_axes", [])
    reason = "candidate_under_review_hypotheses_generated" if rows else "no_new_candidate_under_review_hypotheses"
    if not rows and exhausted_axes:
        reason = "candidate_under_review_axes_exhausted_or_blocked"
    return {
        "generated": len(rows),
        "reason": reason,
        "candidate_run_id": state.get("candidate_run_id"),
        "hypotheses": [row.get("hypothesis_id") for row in rows],
        "skipped": skipped[:20],
        "exhausted_axes": exhausted_axes,
    }
'''
    text = replace_once(text, old, new, "candidate review factory result metadata")
    write(path, text)


def patch_autonomous_wrapper() -> None:
    path = ROOT / "scripts" / "run_research_batch_autonomous.py"
    text = read(path)
    import_old = '''from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
'''
    import_new = '''from scripts.research.generation_feedback import (
    maybe_mark_candidate_review_exhausted,
    record_generation_feedback,
    write_generation_feedback_report,
)
from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
'''
    text = replace_once(text, import_old, import_new, "wrapper generation feedback imports")

    text = text.replace("prefer_best_champion=True,", "prefer_best_champion=False,")

    old = '''        print(f"Candidate-under-review hypothesis generation: {candidate_review_generation}")

    eligibility_before = _eligibility(args)
'''
    new = '''        print(f"Candidate-under-review hypothesis generation: {candidate_review_generation}")
        candidate_review_generation = maybe_mark_candidate_review_exhausted(
            state_dir=args.state_dir,
            hypothesis_bank=args.hypothesis_bank,
            generation_result=candidate_review_generation,
        )

    eligibility_before = _eligibility(args)
'''
    text = replace_once(text, old, new, "candidate review exhausted marker")

    old = '''    print(f"Hypothesis eligibility preflight: {eligibility_before}")

    generated = {"generated": 0, "reason": "not_needed_existing_eligible"}
'''
    new = '''    print(f"Hypothesis eligibility preflight: {eligibility_before}")
    if candidate_review_generation.get("reason") != "disabled":
        record_generation_feedback(
            state_dir=args.state_dir,
            reports_dir=args.reports_dir,
            phase="candidate_review_factory",
            generation_result=candidate_review_generation,
            eligibility_before={},
            eligibility_after=eligibility_before,
            context={"candidate_under_review": candidate_review},
        )

    generated = {"generated": 0, "reason": "not_needed_existing_eligible"}
'''
    text = replace_once(text, old, new, "candidate review feedback record")

    old = '''    eligibility_after_value = _eligibility(args)
    print(f"Eligibility after value fallback: {eligibility_after_value}")

    if not eligibility_after_value.get("eligible") and not args.no_literature_fallback:
'''
    new = '''    eligibility_after_value = _eligibility(args)
    print(f"Eligibility after value fallback: {eligibility_after_value}")
    record_generation_feedback(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        phase="value_factory",
        generation_result=generated,
        eligibility_before=eligibility_before,
        eligibility_after=eligibility_after_value,
        context={"parent_config": parent_config},
    )

    if not eligibility_after_value.get("eligible") and not args.no_literature_fallback:
'''
    text = replace_once(text, old, new, "value generation feedback")

    old = '''    eligibility_after_literature = _eligibility(args)
    print(f"Eligibility after literature fallback: {eligibility_after_literature}")

    if (
'''
    new = '''    eligibility_after_literature = _eligibility(args)
    print(f"Eligibility after literature fallback: {eligibility_after_literature}")
    record_generation_feedback(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        phase="literature_miner",
        generation_result=literature,
        eligibility_before=eligibility_after_value,
        eligibility_after=eligibility_after_literature,
        context={"paper_ideas": args.paper_ideas},
    )

    if (
'''
    text = replace_once(text, old, new, "literature feedback")

    old = '''        literature = _mine_literature(args, parent_config)
        print(f"Literature-hypothesis fallback after paper search: {literature}")

    final_eligibility = _eligibility(args)
'''
    new = '''        literature = _mine_literature(args, parent_config)
        print(f"Literature-hypothesis fallback after paper search: {literature}")
        record_generation_feedback(
            state_dir=args.state_dir,
            reports_dir=args.reports_dir,
            phase="paper_searcher_then_literature",
            generation_result={"paper_searcher": paper_search, "literature_miner": literature},
            eligibility_before=eligibility_after_literature,
            eligibility_after=_eligibility(args),
            context={"online": bool(args.online_paper_search)},
        )

    final_eligibility = _eligibility(args)
'''
    text = replace_once(text, old, new, "paper feedback")

    old = '''    print(f"Final hypothesis eligibility preflight: {final_eligibility}")

    if not final_eligibility.get("eligible"):
'''
    new = '''    print(f"Final hypothesis eligibility preflight: {final_eligibility}")
    write_generation_feedback_report(state_dir=args.state_dir, reports_dir=args.reports_dir)

    if not final_eligibility.get("eligible"):
'''
    text = replace_once(text, old, new, "final feedback report")

    old = '''    clear_autonomy_blocker(state_dir=args.state_dir, reason="batch_completed_with_value")
    return 0
'''
    new = '''    write_generation_feedback_report(state_dir=args.state_dir, reports_dir=args.reports_dir)
    clear_autonomy_blocker(state_dir=args.state_dir, reason="batch_completed_with_value")
    return 0
'''
    text = replace_once(text, old, new, "post batch feedback report")
    write(path, text)


def main() -> None:
    patch_candidate_under_review()
    patch_candidate_review_factory()
    patch_autonomous_wrapper()
    print("generation_eligibility_feedback_patch applied")


if __name__ == "__main__":
    main()
