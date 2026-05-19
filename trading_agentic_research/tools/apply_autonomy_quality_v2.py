from __future__ import annotations
import argparse, re, shutil
from datetime import datetime
from pathlib import Path

PATCHED=[]

def read(p: Path) -> str: return p.read_text(encoding="utf-8-sig")
def write_file(p: Path, s: str): p.write_text(s, encoding="utf-8"); PATCHED.append(str(p))
def backup(p: Path):
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + ".bak_autonomy_quality_v2_" + datetime.now().strftime("%Y%m%d%H%M%S")))

def ensure_contains(text: str, marker: str, insertion: str, after: str) -> str:
    if marker in text: return text
    if after not in text: raise RuntimeError("Anchor not found: " + after[:80])
    return text.replace(after, after + insertion, 1)

def patch_research_loop(root: Path):
    p=root/"scripts/research_loop.py"; backup(p); text=read(p)
    text=ensure_contains(text, "check_pre_run_duplicate",
'''from scripts.research.pre_run_duplicate_guard import (
    check_pre_run_duplicate,
    record_completed_strategy_effect,
    write_blocked_duplicate_run,
)
''', "from scripts.research.candidate_review_learning import candidate_review_scope_reason\n")
    old='''    if changed_parameters and not strategy_config.get("changed_parameters"):
        strategy_config["changed_parameters"] = changed_parameters

    score = preflight_score(inputs, state_dir=args.state_dir)
'''
    new='''    if changed_parameters and not strategy_config.get("changed_parameters"):
        strategy_config["changed_parameters"] = changed_parameters

    duplicate_guard = check_pre_run_duplicate(
        strategy_config_path=inputs.strategy_config_path,
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        strategy_registry_path=args.strategy_registry,
        repo_root=ROOT,
        run_id=inputs.run_id,
        hypothesis_id=inputs.hypothesis_id,
        family=inputs.family,
    )
    if duplicate_guard.get("blocked"):
        event = write_blocked_duplicate_run(
            guard_result=duplicate_guard,
            run_id=inputs.run_id,
            runs_dir=args.runs_dir,
            state_dir=args.state_dir,
            strategy_config_path=inputs.strategy_config_path,
            project_config_path=inputs.project_config_path,
            weekly_file=inputs.weekly_file,
            daily_folder=inputs.daily_folder,
            parent_run_id=inputs.parent_run_id,
            hypothesis_id=inputs.hypothesis_id,
            family=inputs.family,
        )
        update_research_state(args.state_dir, inputs.run_id, "blocked_pre_run_duplicate", str(event))
        print(f"Pre-run duplicate guard blocked {inputs.run_id}: {duplicate_guard.get('reason')} duplicate_of={duplicate_guard.get('duplicate_of_run_id')}")
        return 0

    score = preflight_score(inputs, state_dir=args.state_dir)
'''
    if "Pre-run duplicate guard blocked" not in text:
        if old not in text: raise RuntimeError("research_loop.py guard anchor not found")
        text=text.replace(old,new,1)
    old2='''    update_research_state(args.state_dir, inputs.run_id, "running", "Loop iteration started.")
    try:
        run_commands(commands)
    except Exception as exc:
        update_research_state(args.state_dir, inputs.run_id, "failed", str(exc))
        raise
    update_research_state(args.state_dir, inputs.run_id, "completed", "Loop iteration completed.")
'''
    new2='''    update_research_state(args.state_dir, inputs.run_id, "running", "Loop iteration started.")
    try:
        run_commands(commands)
    except Exception as exc:
        update_research_state(args.state_dir, inputs.run_id, "failed", str(exc))
        raise
    try:
        record_completed_strategy_effect(
            run_id=inputs.run_id,
            strategy_config_path=inputs.strategy_config_path,
            state_dir=args.state_dir,
            runs_dir=args.runs_dir,
        )
    except Exception as exc:
        print(f"Warning: strategy-effect index update failed: {exc}")
    update_research_state(args.state_dir, inputs.run_id, "completed", "Loop iteration completed.")
'''
    if "strategy-effect index update failed" not in text:
        if old2 not in text: raise RuntimeError("research_loop.py record anchor not found")
        text=text.replace(old2,new2,1)
    write_file(p,text)

def patch_execution(root: Path):
    p=root/"backtester/execution.py"; backup(p); text=read(p)
    if "import warnings as py_warnings" not in text:
        text=text.replace("import pandas as pd\n","import pandas as pd\nimport warnings as py_warnings\n",1)
    old='''    warnings: list[str] = []
    signals = build_momentum_trend_signals(weekly_df, strategy_config)
    prices = _prepare_daily_prices(daily_df, benchmark_ticker=benchmark_ticker)
'''
    new='''    warnings: list[str] = []
    with py_warnings.catch_warnings(record=True) as caught_warnings:
        py_warnings.simplefilter("always")
        signals = build_momentum_trend_signals(weekly_df, strategy_config)
    warnings.extend(str(w.message) for w in caught_warnings)
    prices = _prepare_daily_prices(daily_df, benchmark_ticker=benchmark_ticker)
'''
    if "caught_warnings" not in text:
        if old not in text: raise RuntimeError("execution.py warning capture anchor not found")
        text=text.replace(old,new,1)
    write_file(p,text)

def patch_signal_builder(root: Path):
    p=root/"backtester/signal_builder.py"; backup(p); text=read(p)
    pat=r"def _evaluate_market_filter\(snapshot: pd\.DataFrame, strategy_config: dict, benchmark_ticker: str\) -> bool:\n.*?\n\ndef _apply_risk_filters"
    new='''def _evaluate_market_filter(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> bool:
    market_filter_cfg = strategy_config.get("market_filter", {})
    require_positive_trend = bool(market_filter_cfg.get("require_positive_trend", True))
    fallback_if_missing = bool(market_filter_cfg.get("fallback_allow_if_missing_spy_metric", True))
    primary_metric = str(market_filter_cfg.get("spy_metric", "spy_close_vs_sma50_pct") or "spy_close_vs_sma50_pct")
    fallback_metric = str(market_filter_cfg.get("spy_metric_fallback", "close_vs_sma50_pct") or "close_vs_sma50_pct")

    if not require_positive_trend:
        return True

    spy_rows = snapshot[snapshot["ticker"] == benchmark_ticker]
    if spy_rows.empty:
        msg = f"data_quality_warning: Market filter could not find {benchmark_ticker} row on signal date."
        if not fallback_if_missing:
            warnings.warn(msg + " Strict market filter blocks this rebalance.", UserWarning)
            return False
        warnings.warn(msg + " Using configured fallback.", UserWarning)
        return fallback_if_missing

    row = spy_rows.iloc[0]
    value = None
    if primary_metric in spy_rows.columns:
        value = pd.to_numeric(row[primary_metric], errors="coerce")
    else:
        warnings.warn(f"data_quality_warning: Column {primary_metric} not found for SPY market filter.", UserWarning)

    if pd.isna(value) and fallback_metric in spy_rows.columns:
        fallback_value = pd.to_numeric(row[fallback_metric], errors="coerce")
        if pd.notna(fallback_value):
            warnings.warn(
                f"data_quality_warning: {primary_metric} is NaN; using SPY row fallback metric {fallback_metric}.",
                UserWarning,
            )
            value = fallback_value

    if pd.isna(value):
        msg = f"data_quality_critical: SPY market filter metric unavailable ({primary_metric}; fallback={fallback_metric})."
        if not fallback_if_missing:
            warnings.warn(msg + " Strict market filter blocks this rebalance.", UserWarning)
            return False
        warnings.warn(msg + " Using configured fallback.", UserWarning)
        return fallback_if_missing

    return bool(float(value) > 0)


def _apply_risk_filters'''
    if "SPY row fallback metric" not in text:
        text2,n=re.subn(pat,new,text,count=1,flags=re.S)
        if n!=1: raise RuntimeError("signal_builder.py market filter function not patched")
        text=text2
    write_file(p,text)

def patch_validation(root: Path):
    p=root/"backtester/validation.py"; backup(p); text=read(p)
    if '"data_quality_critical",' not in text:
        text=text.replace('    "costs not applied",\n)', '    "costs not applied",\n    "data_quality_critical",\n)\n', 1)
    write_file(p,text)

def patch_run_research_batch(root: Path):
    p=root/"scripts/run_research_batch.py"; backup(p); text=read(p)
    text=ensure_contains(text, "update_branch_exhaustion_after_run",
'''from scripts.research.branch_exhaustion import update_branch_exhaustion_after_run
from scripts.research.autonomy_quality_report import write_autonomy_quality_report
''', "from scripts.research.cooldown_governance import hard_active_cooldown_family_names\n")
    old='''        audit = read_json(audit_path)

        state["completed"] += 1
'''
    new='''        audit = read_json(audit_path)
        try:
            branch_update = update_branch_exhaustion_after_run(
                state_dir=args.state_dir,
                run_id=latest_run,
                hypothesis_id=hypothesis_id,
                family=str(hypothesis.get("family")),
                audit=audit,
            )
            if branch_update.get("status") == "exhausted":
                print(f"Branch exhausted: {branch_update.get('branch_key')} reason={branch_update.get('reason')}")
        except Exception as exc:
            print(f"Warning: branch exhaustion update failed: {exc}")

        state["completed"] += 1
'''
    if "Branch exhausted:" not in text:
        if old not in text: raise RuntimeError("run_research_batch.py audit anchor not found")
        text=text.replace(old,new,1)
    old2='''    print(f"Batch finished. Completed iterations: {state['completed']}")
    return 0
'''
    new2='''    try:
        write_autonomy_quality_report(
            state_dir=args.state_dir,
            reports_dir=args.reports_dir,
            runs_dir=args.runs_dir,
            last_n=30,
        )
    except Exception as exc:
        print(f"Warning: autonomy quality report failed: {exc}")
    print(f"Batch finished. Completed iterations: {state['completed']}")
    return 0
'''
    if "autonomy quality report failed" not in text:
        if old2 not in text: raise RuntimeError("run_research_batch.py final anchor not found")
        text=text.replace(old2,new2,1)
    write_file(p,text)

def patch_feature_space(root: Path):
    p=root/"scripts/research/feature_space_expansion_factory.py"; backup(p); text=read(p)
    text=ensure_contains(text, "branch_key_for_candidate", "from scripts.research.branch_exhaustion import branch_key_for_candidate, is_branch_exhausted\n", "from scripts.research.cooldown_governance import hard_active_cooldown_families\n")
    old='''        effective_family = family or _row_family_for_combo(spec, suffix)
        effective_axis = axis or spec.axis
        if effective_family in cooldowned_families:
'''
    new='''        effective_family = family or _row_family_for_combo(spec, suffix)
        effective_axis = axis or spec.axis
        branch_key = branch_key_for_candidate(family=effective_family, axis=effective_axis, field=spec.field, layer=layer)
        if is_branch_exhausted(state_dir, branch_key):
            skipped.append({
                "field": spec.field,
                "reason": "branch_exhausted",
                "branch_key": branch_key,
                "hypothesis_id": f"HYP_FSPACE_{safe_parent}_{suffix}_V1",
                "layer": layer,
            })
            return
        if effective_family in cooldowned_families:
'''
    if "branch_exhausted" not in text:
        if old not in text: raise RuntimeError("feature_space_expansion_factory.py branch anchor not found")
        text=text.replace(old,new,1)
    write_file(p,text)

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-root", required=True); args=ap.parse_args()
    root=Path(args.repo_root).resolve()
    patch_research_loop(root); patch_execution(root); patch_signal_builder(root); patch_validation(root); patch_run_research_batch(root); patch_feature_space(root)
    print("Autonomy Quality v2 patches applied:")
    for x in PATCHED: print(" -", x)
    return 0
if __name__=="__main__": raise SystemExit(main())
