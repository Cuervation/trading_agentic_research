from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


def write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak_autonomy_quality_v3")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)


def copy_new_files(repo: Path, package: Path) -> None:
    src_root = package / "files"
    for src in src_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        backup(dst)
        shutil.copy2(src, dst)
        print(f"copied {rel}")


def patch_research_loop(repo: Path) -> None:
    path = repo / "scripts" / "research_loop.py"
    backup(path)
    text = read(path)
    import_line = "from scripts.research.candidate_review_learning import candidate_review_scope_reason\n"
    guard_import = "from scripts.research.pre_run_duplicate_guard import check_pre_run_duplicate_guard\n"
    if guard_import not in text:
        text = text.replace(import_line, import_line + guard_import)

    needle = '''    if changed_parameters and not strategy_config.get("changed_parameters"):
        strategy_config["changed_parameters"] = changed_parameters

    score = preflight_score(inputs, state_dir=args.state_dir)
'''
    replacement = '''    if changed_parameters and not strategy_config.get("changed_parameters"):
        strategy_config["changed_parameters"] = changed_parameters

    guard = check_pre_run_duplicate_guard(
        strategy_config_path=inputs.strategy_config_path,
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        hypothesis_id=inputs.hypothesis_id,
        family=inputs.family,
        attempted_run_id=inputs.run_id,
        repo_root=ROOT,
    )
    if guard.get("blocked"):
        update_research_state(args.state_dir, inputs.run_id, "blocked_duplicate_pre_run", str(guard.get("reason")))
        print(f"Pre-run duplicate guard blocked {inputs.run_id}: {guard.get('reason')}")
        return 3

    score = preflight_score(inputs, state_dir=args.state_dir)
'''
    if "check_pre_run_duplicate_guard(" not in text:
        if needle not in text:
            raise RuntimeError("Could not patch research_loop.py: insertion point not found")
        text = text.replace(needle, replacement)
    write(path, text)
    print("patched scripts/research_loop.py")


def patch_run_research_batch(repo: Path) -> None:
    path = repo / "scripts" / "run_research_batch.py"
    backup(path)
    text = read(path)
    needle = '''        code = _run_command(cmd)
        if code != 0:
            state["status"] = "failed"
            state["stop_reason"] = f"research_loop_exit_code:{code}"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: research_loop failed with code {code}")
            break

        latest_run = get_latest_run_id(args.runs_dir)
'''
    replacement = '''        code = _run_command(cmd)
        if code == 3:
            state["completed"] += 1
            state["consecutive_rejections"] += 1
            state.setdefault("history", []).append(
                {
                    "iteration": state["completed"],
                    "run_id": f"{hypothesis_id}:pre_run_blocked",
                    "hypothesis_id": hypothesis_id,
                    "family": str(hypothesis.get("family")),
                    "decision": "pre_run_blocked",
                    "parent_strategy_config": effective_parent_strategy_config,
                }
            )
            _save_batch_state(args.state_dir, state)
            print(f"Continuing: pre-run guard blocked {hypothesis_id}; no backtest was executed.")

            if state["consecutive_rejections"] >= args.stop_after_consecutive_rejections:
                generation_result = run_feature_space_generation(
                    args=args,
                    parent_strategy_config=effective_parent_strategy_config,
                    reason="pre_run_blocks_recovery",
                )
                if (
                    not bool(args.no_continue_after_recovery_generation)
                    and int(state.get("recovery_cycles", 0) or 0) < int(args.max_recovery_cycles)
                    and _generated_count(generation_result) > 0
                ):
                    state["recovery_cycles"] = int(state.get("recovery_cycles", 0) or 0) + 1
                    state["consecutive_rejections"] = 0
                    _save_batch_state(args.state_dir, state)
                    print(
                        "Continuing after pre-run recovery generation:",
                        f"cycle={state['recovery_cycles']}/{args.max_recovery_cycles}",
                        f"generated={_generated_count(generation_result)}",
                    )
                    continue
                state["status"] = "stopped"
                state["stop_reason"] = f"pre_run_blocks:{state['consecutive_rejections']}"
                _save_batch_state(args.state_dir, state)
                print(f"Stopping: {state['stop_reason']}")
                break
            continue

        if code != 0:
            state["status"] = "failed"
            state["stop_reason"] = f"research_loop_exit_code:{code}"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: research_loop failed with code {code}")
            break

        latest_run = get_latest_run_id(args.runs_dir)
'''
    if "code == 3" not in text:
        if needle not in text:
            raise RuntimeError("Could not patch run_research_batch.py: code block not found")
        text = text.replace(needle, replacement)
    write(path, text)
    print("patched scripts/run_research_batch.py")


def patch_signal_builder(repo: Path) -> None:
    path = repo / "backtester" / "signal_builder.py"
    backup(path)
    text = read(path)
    old = '''    if "spy_close_vs_sma50_pct" not in spy_rows.columns:
        warnings.warn(
            "Column spy_close_vs_sma50_pct not found; using market filter fallback.",
            UserWarning,
        )
        return fallback_if_missing

    value = pd.to_numeric(spy_rows.iloc[0]["spy_close_vs_sma50_pct"], errors="coerce")
    if pd.isna(value):
        warnings.warn(
            "spy_close_vs_sma50_pct is NaN; using market filter fallback.",
            UserWarning,
        )
        return fallback_if_missing

    return bool(value > 0)
'''
    new = '''    metric_candidates = ["spy_close_vs_sma50_pct", "close_vs_sma50_pct"]
    value = None
    used_metric = None
    for metric in metric_candidates:
        if metric not in spy_rows.columns:
            continue
        candidate = pd.to_numeric(spy_rows.iloc[0][metric], errors="coerce")
        if not pd.isna(candidate):
            value = float(candidate)
            used_metric = metric
            break

    if value is None:
        warnings.warn(
            "critical: SPY market filter metric missing/NaN; using market filter fallback.",
            UserWarning,
        )
        return fallback_if_missing

    if used_metric != "spy_close_vs_sma50_pct":
        warnings.warn(
            f"SPY market filter used fallback metric {used_metric} because spy_close_vs_sma50_pct was missing/NaN.",
            UserWarning,
        )

    return bool(value > 0)
'''
    if "metric_candidates = [\"spy_close_vs_sma50_pct\", \"close_vs_sma50_pct\"]" not in text:
        if old not in text:
            raise RuntimeError("Could not patch signal_builder.py: SPY block not found")
        text = text.replace(old, new)
    write(path, text)
    print("patched backtester/signal_builder.py")


def patch_feature_space_factory(repo: Path) -> None:
    path = repo / "scripts" / "research" / "feature_space_expansion_factory.py"
    backup(path)
    text = read(path)
    import_line = "from scripts.research.cooldown_governance import hard_active_cooldown_families\n"
    extra = "from scripts.research.branch_exhaustion import is_hypothesis_branch_exhausted, refresh_branch_exhaustion\n"
    if extra not in text:
        text = text.replace(import_line, import_line + extra)
    marker = "    exhausted_axes = exhausted_axes_from_ledger(state_dir)\n    cooldowned_families = active_cooldown_families(state_dir)\n"
    if "branch_exhaustion_state = refresh_branch_exhaustion(state_dir)" not in text:
        text = text.replace(marker, marker + "    branch_exhaustion_state = refresh_branch_exhaustion(state_dir)\n")
    needle = '''        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        if hypothesis_id in ids:
            skipped.append({"field": spec.field, "reason": "id_exists", "hypothesis_id": hypothesis_id, "layer": layer})
            return
'''
    repl = '''        hypothesis_id = f"HYP_FSPACE_{safe_parent}_{suffix}_V1"
        branch_check = is_hypothesis_branch_exhausted(hypothesis_id, state_dir=state_dir)
        if branch_check.get("exhausted"):
            skipped.append({
                "field": spec.field,
                "reason": "branch_exhausted",
                "branch": branch_check.get("branch"),
                "hypothesis_id": hypothesis_id,
                "layer": layer,
            })
            return
        if hypothesis_id in ids:
            skipped.append({"field": spec.field, "reason": "id_exists", "hypothesis_id": hypothesis_id, "layer": layer})
            return
'''
    if '"reason": "branch_exhausted"' not in text:
        if needle not in text:
            raise RuntimeError("Could not patch feature_space_expansion_factory.py: hypothesis block not found")
        text = text.replace(needle, repl)
    write(path, text)
    print("patched scripts/research/feature_space_expansion_factory.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--package-root", default=None)
    args = ap.parse_args()
    repo = Path(args.repo_root).resolve()
    package = Path(args.package_root).resolve() if args.package_root else Path(__file__).resolve().parents[1]
    copy_new_files(repo, package)
    patch_research_loop(repo)
    patch_run_research_batch(repo)
    patch_signal_builder(repo)
    patch_feature_space_factory(repo)
    print("Autonomy Quality v3 applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
