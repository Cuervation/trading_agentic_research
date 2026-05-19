from pathlib import Path
import re

project = Path.cwd()

research_loop = project / "scripts" / "research_loop.py"
signal_builder = project / "backtester" / "signal_builder.py"

if not research_loop.exists():
    raise FileNotFoundError(research_loop)

if not signal_builder.exists():
    raise FileNotFoundError(signal_builder)

# ============================================================
# Patch scripts/research_loop.py
# ============================================================
text = research_loop.read_text(encoding="utf-8-sig")

import_anchor = "from scripts.research.candidate_review_learning import candidate_review_scope_reason\n"
import_line = "from scripts.research.pre_run_duplicate_guard import check_pre_run_duplicate, write_blocked_duplicate_run\n"

if import_line not in text:
    if import_anchor not in text:
        raise RuntimeError("No encontré import_anchor en research_loop.py")
    text = text.replace(import_anchor, import_anchor + import_line)

command_anchor = '    commands = build_commands(inputs, runs_dir=args.runs_dir, reports_dir=args.reports_dir)\n'

guard_block = '''    # AUTONOMY_DIRECT_PATCH_PRE_RUN_DUPLICATE_GUARD
    guard = check_pre_run_duplicate(
        strategy_config_path=inputs.strategy_config_path,
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        strategy_registry_path=args.strategy_registry,
        repo_root=ROOT,
        run_id=inputs.run_id,
        hypothesis_id=inputs.hypothesis_id,
        family=inputs.family,
    )
    if guard.get("blocked"):
        event = write_blocked_duplicate_run(
            guard_result=guard,
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
        update_research_state(
            args.state_dir,
            inputs.run_id,
            "pre_run_duplicate_blocked",
            str(guard.get("reason")),
        )
        print(
            f"Pre-run duplicate guard blocked {inputs.run_id}: "
            f"{guard.get('reason')} duplicate_of={guard.get('duplicate_of_run_id')}"
        )
        print(f"Pre-run duplicate event: {event}")
        return 0

    commands = build_commands(inputs, runs_dir=args.runs_dir, reports_dir=args.reports_dir)
'''

if "AUTONOMY_DIRECT_PATCH_PRE_RUN_DUPLICATE_GUARD" not in text:
    if command_anchor not in text:
        raise RuntimeError("No encontré command_anchor en research_loop.py")
    text = text.replace(command_anchor, guard_block)

research_loop.write_text(text, encoding="utf-8")

# ============================================================
# Patch backtester/signal_builder.py
# ============================================================
text = signal_builder.read_text(encoding="utf-8-sig")

replacement = '''def _evaluate_market_filter(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> bool:
    # AUTONOMY_DIRECT_PATCH_SPY_MARKET_FILTER
    market_filter_cfg = strategy_config.get("market_filter", {})
    require_positive_trend = bool(market_filter_cfg.get("require_positive_trend", True))
    fallback_if_missing = bool(
        market_filter_cfg.get("fallback_allow_if_missing_spy_metric", True)
    )

    if not require_positive_trend:
        return True

    spy_rows = snapshot[snapshot["ticker"] == benchmark_ticker]
    if spy_rows.empty:
        warnings.warn(
            f"critical: SPY market filter could not find {benchmark_ticker} row on signal date; using fallback={fallback_if_missing}.",
            UserWarning,
        )
        return fallback_if_missing

    row = spy_rows.iloc[0]
    metric_candidates = [
        "spy_close_vs_sma50_pct",
        "close_vs_sma50_pct",
        "close_vs_sma52w_pct",
    ]

    for col in metric_candidates:
        if col not in spy_rows.columns:
            continue
        value = pd.to_numeric(row[col], errors="coerce")
        if not pd.isna(value):
            return bool(value > 0)

    warnings.warn(
        f"critical: SPY market filter metrics unavailable/NaN (tried={metric_candidates}); using fallback={fallback_if_missing}.",
        UserWarning,
    )
    return fallback_if_missing


'''

if "AUTONOMY_DIRECT_PATCH_SPY_MARKET_FILTER" not in text:
    pattern = (
        r"def _evaluate_market_filter\(snapshot: pd\.DataFrame, strategy_config: dict, benchmark_ticker: str\) -> bool:\n"
        r".*?\n(?=def _apply_risk_filters)"
    )
    text2, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("No pude reemplazar _evaluate_market_filter en signal_builder.py")
    text = text2

signal_builder.write_text(text, encoding="utf-8")

print("PATCH_OK")
print(research_loop)
print(signal_builder)
