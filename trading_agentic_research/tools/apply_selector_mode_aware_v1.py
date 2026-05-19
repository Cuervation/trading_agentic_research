from pathlib import Path
import sys

ROOT = Path.cwd()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def patch_select_next() -> None:
    path = ROOT / "scripts" / "select_next_hypothesis.py"
    text = read(path)

    import_anchor = "from scripts.research.consumed_hypotheses import consumed_hypothesis_ids\n"
    import_line = "from scripts.research.effective_hypothesis_filter import effective_hypothesis_status\n"
    if import_line not in text:
        if import_anchor not in text:
            raise RuntimeError("select_next_hypothesis.py import anchor not found")
        text = text.replace(import_anchor, import_anchor + import_line)

    old_sig = '''    state_dir: str | Path = "state",
    consumed_ids: set[str] | None = None,
    allow_retry_consumed: bool = False,
) -> dict:
'''
    new_sig = '''    state_dir: str | Path = "state",
    consumed_ids: set[str] | None = None,
    allow_retry_consumed: bool = False,
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    runs_dir: str | Path = "runs",
) -> dict:
'''
    if old_sig in text:
        text = text.replace(old_sig, new_sig, 1)

    anchor = '''        if isinstance(overrides, dict) and overrides and hypothesis_id not in signature_block_ids:
            if real_override_signature(overrides) in blocked_signatures:
                continue

        score = score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns)
'''
    block = '''        if isinstance(overrides, dict) and overrides and hypothesis_id not in signature_block_ids:
            if real_override_signature(overrides) in blocked_signatures:
                continue

        # EFFECTIVE_HYPOTHESIS_FILTER_DIRECT_PATCH
        effective = effective_hypothesis_status(
            hypothesis=hypothesis,
            state_dir=state_dir,
            runs_dir=runs_dir,
            strategy_registry_path=strategy_registry_path,
            repo_root=ROOT,
            check_exact_duplicate=True,
            block_feature_space_stall=True,
        )
        if effective.get("blocked"):
            continue

        score = score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns)
'''
    if "EFFECTIVE_HYPOTHESIS_FILTER_DIRECT_PATCH" not in text:
        if anchor not in text:
            raise RuntimeError("select_next_hypothesis.py effective-filter anchor not found")
        text = text.replace(anchor, block, 1)

    write(path, text)


def patch_hypothesis_eligibility() -> None:
    path = ROOT / "scripts" / "research" / "hypothesis_eligibility.py"
    text = read(path)

    import_anchor = "from scripts.research.consumed_hypotheses import consumed_hypothesis_ids\n"
    import_line = "from scripts.research.effective_hypothesis_filter import summarize_effective_hypotheses\n"
    if import_line not in text:
        if import_anchor not in text:
            raise RuntimeError("hypothesis_eligibility.py import anchor not found")
        text = text.replace(import_anchor, import_anchor + import_line)

    old = '''    except Exception as exc:
        return {
            "eligible": False,
            "reason": str(exc),
            "bank_size": len(bank),
            "rejected_count": len({str(x) for x in rejected_ids if x}),
            "accepted_count": len({str(x) for x in accepted_ids if x}),
            "consumed_count": len(consumed_ids),
            "repeat_blocked_count": len(repeat_blocked),
        }
'''
    new = '''    except Exception as exc:
        # EFFECTIVE_ELIGIBILITY_SUMMARY_DIRECT_PATCH
        effective_summary = summarize_effective_hypotheses(
            hypothesis_bank=bank,
            state_dir=state_path,
            runs_dir="runs",
            strategy_registry_path="configs/strategy_registry.json",
            repo_root=ROOT,
        )
        return {
            "eligible": False,
            "reason": str(exc),
            "bank_size": len(bank),
            "rejected_count": len({str(x) for x in rejected_ids if x}),
            "accepted_count": len({str(x) for x in accepted_ids if x}),
            "consumed_count": len(consumed_ids),
            "repeat_blocked_count": len(repeat_blocked),
            "effective_summary": effective_summary,
            "recommended_mode": effective_summary.get("recommended_mode"),
            "blocked_counts": effective_summary.get("blocked_counts"),
        }
'''
    if "EFFECTIVE_ELIGIBILITY_SUMMARY_DIRECT_PATCH" not in text:
        if old not in text:
            raise RuntimeError("hypothesis_eligibility.py exception anchor not found")
        text = text.replace(old, new, 1)

    write(path, text)


def patch_run_research_batch() -> None:
    path = ROOT / "scripts" / "run_research_batch.py"
    text = read(path)

    old = '''            state["status"] = "stopped"
            state["stop_reason"] = f"consecutive_rejections:{state['consecutive_rejections']}"
            if _generated_count(generation_result) > 0 and selectable_count == 0:
                state["stop_reason"] += ":recovery_generated_but_not_selectable"
            elif int(state.get("recovery_cycles", 0) or 0) >= int(args.max_recovery_cycles):
                state["stop_reason"] += ":max_recovery_cycles_reached"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: {state['stop_reason']}")
            break
'''
    new = '''            state["status"] = "stopped"
            state["stop_reason"] = f"consecutive_rejections:{state['consecutive_rejections']}"
            # FEATURE_SPACE_EXHAUSTED_MODE_DIRECT_PATCH
            generated_n = _generated_count(generation_result)
            if generated_n > 0 and selectable_count == 0:
                state["stop_reason"] += ":recovery_generated_but_not_selectable"
            elif generated_n == 0 and str((generation_result or {}).get("reason")) == "no_new_feature_space_hypotheses":
                state["stop_reason"] += ":feature_space_exhausted_needs_literature_mode"
                state["recommended_mode"] = "literature_or_new_family"
            elif int(state.get("recovery_cycles", 0) or 0) >= int(args.max_recovery_cycles):
                state["stop_reason"] += ":max_recovery_cycles_reached"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: {state['stop_reason']}")
            break
'''
    if "FEATURE_SPACE_EXHAUSTED_MODE_DIRECT_PATCH" not in text:
        if old not in text:
            raise RuntimeError("run_research_batch.py stop-reason anchor not found")
        text = text.replace(old, new, 1)

    write(path, text)


def patch_run_research_batch_autonomous() -> None:
    path = ROOT / "scripts" / "run_research_batch_autonomous.py"
    text = read(path)

    anchor = '''    final_eligibility = _eligibility(args)
    print(f"Final hypothesis eligibility preflight: {final_eligibility}")
    write_generation_feedback_report(state_dir=args.state_dir, reports_dir=args.reports_dir)

'''
    block = '''    final_eligibility = _eligibility(args)
    print(f"Final hypothesis eligibility preflight: {final_eligibility}")
    # AUTONOMOUS_RESEARCH_MODE_DIRECT_PATCH
    if final_eligibility.get("recommended_mode"):
        print(f"Research mode recommendation: {final_eligibility.get('recommended_mode')}")
    write_generation_feedback_report(state_dir=args.state_dir, reports_dir=args.reports_dir)

'''
    if "AUTONOMOUS_RESEARCH_MODE_DIRECT_PATCH" not in text:
        if anchor not in text:
            raise RuntimeError("run_research_batch_autonomous.py final eligibility anchor not found")
        text = text.replace(anchor, block, 1)

    write(path, text)


def main() -> int:
    required = [
        ROOT / "scripts" / "research" / "effective_hypothesis_filter.py",
        ROOT / "scripts" / "select_next_hypothesis.py",
        ROOT / "scripts" / "research" / "hypothesis_eligibility.py",
        ROOT / "scripts" / "run_research_batch.py",
        ROOT / "scripts" / "run_research_batch_autonomous.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print("ERROR missing files:", missing)
        return 1

    patch_select_next()
    patch_hypothesis_eligibility()
    patch_run_research_batch()
    patch_run_research_batch_autonomous()

    print("PATCH_OK: selector is now semantic-aware and mode-aware.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
