from pathlib import Path

ROOT = Path.cwd()
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def patch_select_next() -> None:
    path = ROOT / "scripts" / "select_next_hypothesis.py"
    text = read(path)
    old = "            check_exact_duplicate=True,\n            block_feature_space_stall=True,\n        )\n"
    new = "            check_exact_duplicate=True,\n            block_feature_space_stall=True,\n            block_family_stall=True,\n        )\n"
    if "block_family_stall=True" not in text:
        if old not in text:
            raise RuntimeError("select_next_hypothesis.py block_family anchor not found")
        text = text.replace(old, new, 1)
    write(path, text)


def patch_autonomous_mode_recovery() -> None:
    path = ROOT / "scripts" / "run_research_batch_autonomous.py"
    text = read(path)
    anchor = """    candidate_review = {"status": "disabled"}
    candidate_review_generation = {"generated": 0, "reason": "disabled"}
"""
    block = """    # MODE_RECOVERY_DIRECT_PATCH_V2
    prior_batch_state = _load_batch_state(args.state_dir)
    prior_stop_reason = str(prior_batch_state.get("stop_reason") or "")
    prior_recommended_mode = str(prior_batch_state.get("recommended_mode") or "")
    if prior_recommended_mode == "literature_or_new_family" or "feature_space_exhausted_needs_literature_mode" in prior_stop_reason:
        print(f"Pre-batch mode recovery: literature_or_new_family reason={prior_stop_reason or prior_recommended_mode}")
        mode_before = _eligibility(args)

        mode_value = generate_value_hypotheses(
            parent_strategy_config_path=parent_config,
            hypothesis_bank_path=args.hypothesis_bank,
            state_dir=args.state_dir,
            max_new=args.max_value_hypotheses,
            reason="mode_recovery_literature_or_new_family",
        )
        mode_after_value = _eligibility(args)
        _record_feedback(
            args=args,
            phase="mode_recovery_value_factory",
            generation_result=mode_value,
            eligibility_before=mode_before,
            eligibility_after=mode_after_value,
            context={"parent_config": parent_config, "prior_stop_reason": prior_stop_reason},
        )

        mode_after_literature = mode_after_value
        if not mode_after_literature.get("eligible") and not args.no_literature_fallback:
            mode_literature = _mine_literature(args, parent_config)
            mode_after_literature = _eligibility(args)
            print(f"Mode-recovery literature fallback: {mode_literature}")
            _record_feedback(
                args=args,
                phase="mode_recovery_literature_miner",
                generation_result=mode_literature,
                eligibility_before=mode_after_value,
                eligibility_after=mode_after_literature,
                context={"parent_config": parent_config, "prior_stop_reason": prior_stop_reason},
            )

        if (
            not mode_after_literature.get("eligible")
            and not args.no_literature_fallback
            and not args.no_paper_searcher_fallback
        ):
            mode_paper_search = generate_paper_ideas(
                output=args.paper_ideas,
                online=bool(args.online_paper_search),
                limit=int(args.max_paper_ideas),
            )
            print(f"Mode-recovery paper-searcher fallback: {mode_paper_search}")
            _record_feedback(
                args=args,
                phase="mode_recovery_paper_searcher",
                generation_result=mode_paper_search,
                eligibility_before=mode_after_literature,
                eligibility_after=mode_after_literature,
                context={"paper_ideas": args.paper_ideas, "online": bool(args.online_paper_search)},
            )
            mode_literature = _mine_literature(args, parent_config)
            mode_after_literature_2 = _eligibility(args)
            print(f"Mode-recovery literature after paper search: {mode_literature}")
            _record_feedback(
                args=args,
                phase="mode_recovery_literature_after_paper_search",
                generation_result=mode_literature,
                eligibility_before=mode_after_literature,
                eligibility_after=mode_after_literature_2,
                context={"parent_config": parent_config, "paper_ideas": args.paper_ideas},
            )

    candidate_review = {"status": "disabled"}
    candidate_review_generation = {"generated": 0, "reason": "disabled"}
"""
    if "MODE_RECOVERY_DIRECT_PATCH_V2" not in text:
        if anchor not in text:
            raise RuntimeError("run_research_batch_autonomous.py mode recovery anchor not found")
        text = text.replace(anchor, block, 1)
    write(path, text)


def main() -> int:
    src = PACKAGE_ROOT / "scripts" / "research" / "effective_hypothesis_filter.py"
    dst = ROOT / "scripts" / "research" / "effective_hypothesis_filter.py"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    patch_select_next()
    patch_autonomous_mode_recovery()
    print("PATCH_OK: selector mode-aware v2 applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
