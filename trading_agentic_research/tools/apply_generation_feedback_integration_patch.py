"""Apply generation-feedback integration hardening patch.

This patch keeps the autonomous loop from repeatedly generating branches that
produce no eligible work. It also preserves review_exhausted candidates so the
loop can move on instead of reactivating the same exhausted candidate each run.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_once(path: Path, needle: str, replacement: str, *, description: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        print(f"OK already applied: {description}")
        return False
    if needle not in text:
        raise RuntimeError(f"Could not find insertion point for {description} in {path}")
    path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    print(f"PATCHED: {description}")
    return True


def replace_function(path: Path, start_marker: str, end_marker: str, new_text: str, *, description: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new_text in text:
        print(f"OK already applied: {description}")
        return False
    start = text.find(start_marker)
    if start == -1:
        raise RuntimeError(f"Could not find start marker for {description}: {start_marker!r}")
    end = text.find(end_marker, start)
    if end == -1:
        raise RuntimeError(f"Could not find end marker for {description}: {end_marker!r}")
    path.write_text(text[:start] + new_text + text[end:], encoding="utf-8")
    print(f"PATCHED: {description}")
    return True


def patch_wrapper() -> None:
    path = ROOT / "scripts" / "run_research_batch_autonomous.py"

    patch_once(
        path,
        "from scripts.research.sync_strategy_registry import sync_strategy_registry\n",
        "from scripts.research.sync_strategy_registry import sync_strategy_registry\n"
        "from scripts.research.generation_feedback import (\n"
        "    maybe_mark_candidate_review_exhausted,\n"
        "    record_generation_feedback,\n"
        "    write_generation_feedback_report,\n"
        ")\n",
        description="import generation feedback helpers",
    )

    patch_once(
        path,
        "    eligibility_before = _eligibility(args)\n"
        "    print(f\"Hypothesis eligibility preflight: {eligibility_before}\")\n",
        "    eligibility_before = _eligibility(args)\n"
        "    print(f\"Hypothesis eligibility preflight: {eligibility_before}\")\n"
        "\n"
        "    if not args.no_candidate_under_review:\n"
        "        candidate_review_generation = maybe_mark_candidate_review_exhausted(\n"
        "            state_dir=args.state_dir,\n"
        "            hypothesis_bank=args.hypothesis_bank,\n"
        "            generation_result=candidate_review_generation,\n"
        "        )\n"
        "        record_generation_feedback(\n"
        "            state_dir=args.state_dir,\n"
        "            reports_dir=args.reports_dir,\n"
        "            phase=\"candidate_under_review\",\n"
        "            generation_result=candidate_review_generation,\n"
        "            eligibility_before=None,\n"
        "            eligibility_after=eligibility_before,\n"
        "            context={\"candidate_under_review\": candidate_review},\n"
        "        )\n"
        "        if candidate_review_generation.get(\"candidate_review_status\") == \"review_exhausted\":\n"
        "            refreshed_candidate = read_json(Path(args.state_dir) / \"candidate_under_review.json\", candidate_review) or candidate_review\n"
        "            print(\n"
        "                \"Candidate-under-review exhausted: \"\n"
        "                f\"{refreshed_candidate.get('candidate_run_id')} \"\n"
        "                f\"({refreshed_candidate.get('reason')})\"\n"
        "            )\n",
        description="record candidate review generation feedback and exhaustion",
    )

    patch_once(
        path,
        "    eligibility_after_value = _eligibility(args)\n"
        "    print(f\"Eligibility after value fallback: {eligibility_after_value}\")\n",
        "    eligibility_after_value = _eligibility(args)\n"
        "    print(f\"Eligibility after value fallback: {eligibility_after_value}\")\n"
        "    record_generation_feedback(\n"
        "        state_dir=args.state_dir,\n"
        "        reports_dir=args.reports_dir,\n"
        "        phase=\"value_fallback\",\n"
        "        generation_result=generated,\n"
        "        eligibility_before=eligibility_before,\n"
        "        eligibility_after=eligibility_after_value,\n"
        "        context={\"parent_config\": parent_config},\n"
        "    )\n",
        description="record value fallback generation feedback",
    )

    patch_once(
        path,
        "    eligibility_after_literature = _eligibility(args)\n"
        "    print(f\"Eligibility after literature fallback: {eligibility_after_literature}\")\n",
        "    eligibility_after_literature = _eligibility(args)\n"
        "    print(f\"Eligibility after literature fallback: {eligibility_after_literature}\")\n"
        "    record_generation_feedback(\n"
        "        state_dir=args.state_dir,\n"
        "        reports_dir=args.reports_dir,\n"
        "        phase=\"literature_fallback\",\n"
        "        generation_result=literature,\n"
        "        eligibility_before=eligibility_after_value,\n"
        "        eligibility_after=eligibility_after_literature,\n"
        "        context={\"paper_ideas\": args.paper_ideas, \"parent_config\": parent_config},\n"
        "    )\n",
        description="record literature fallback generation feedback",
    )

    patch_once(
        path,
        "    final_eligibility = _eligibility(args)\n"
        "    print(f\"Final hypothesis eligibility preflight: {final_eligibility}\")\n",
        "    final_eligibility = _eligibility(args)\n"
        "    print(f\"Final hypothesis eligibility preflight: {final_eligibility}\")\n"
        "    record_generation_feedback(\n"
        "        state_dir=args.state_dir,\n"
        "        reports_dir=args.reports_dir,\n"
        "        phase=\"final_preflight\",\n"
        "        generation_result={\"generated\": 0, \"reason\": \"final_preflight_snapshot\"},\n"
        "        eligibility_before=eligibility_after_literature,\n"
        "        eligibility_after=final_eligibility,\n"
        "        context={\"paper_searcher\": paper_search, \"candidate_under_review\": candidate_review},\n"
        "    )\n",
        description="record final preflight feedback snapshot",
    )

    patch_once(
        path,
        "    # Keep review reports fresh after the batch.\n"
        "    write_promotion_candidate_review(state_dir=args.state_dir, runs_dir=args.runs_dir, reports_dir=args.reports_dir)\n",
        "    # Keep review reports fresh after the batch.\n"
        "    write_generation_feedback_report(state_dir=args.state_dir, reports_dir=args.reports_dir)\n"
        "    write_promotion_candidate_review(state_dir=args.state_dir, runs_dir=args.runs_dir, reports_dir=args.reports_dir)\n",
        description="write generation feedback report after batch",
    )


def patch_generation_feedback() -> None:
    path = ROOT / "scripts" / "research" / "generation_feedback.py"
    new_function = '''def _generated_count(result: dict[str, Any]) -> int:\n    if not isinstance(result, dict):\n        return 0\n    for key in ("generated", "rows_written", "created", "added"):\n        if key in result:\n            try:\n                return int(result.get(key) or 0)\n            except (TypeError, ValueError):\n                return 0\n    for list_key in ("hypotheses", "ideas", "rows"):\n        value = result.get(list_key)\n        if isinstance(value, list):\n            return len(value)\n    nested = result.get("literature_miner") if isinstance(result.get("literature_miner"), dict) else None\n    if nested is not None:\n        return _generated_count(nested)\n    return 0\n\n\n'''
    replace_function(
        path,
        "def _generated_count(result: dict[str, Any]) -> int:\n",
        "def record_generation_feedback(\n",
        new_function,
        description="make generation feedback count rows_written/lists",
    )


def patch_candidate_under_review() -> None:
    path = ROOT / "scripts" / "research" / "candidate_under_review.py"
    patch_once(
        path,
        "    recovered = recover_candidate_config(\n"
        "        candidate_run_id=candidate_run_id,\n",
        "    existing = read_json(Path(state_dir) / \"candidate_under_review.json\", {}) or {}\n"
        "    if (\n"
        "        existing.get(\"status\") == \"review_exhausted\"\n"
        "        and str(existing.get(\"candidate_run_id\")) == str(candidate_run_id)\n"
        "    ):\n"
        "        existing[\"updated_at\"] = now_iso()\n"
        "        write_json(Path(state_dir) / \"candidate_under_review.json\", existing)\n"
        "        return existing\n"
        "\n"
        "    recovered = recover_candidate_config(\n"
        "        candidate_run_id=candidate_run_id,\n",
        description="preserve review_exhausted state for same candidate",
    )


def main() -> None:
    patch_wrapper()
    patch_generation_feedback()
    patch_candidate_under_review()
    print("\nGeneration feedback integration patch applied.")
    print("Next: run py_compile + pytest, then refresh candidate_under_review and rerun autonomous batch.")


if __name__ == "__main__":
    main()
