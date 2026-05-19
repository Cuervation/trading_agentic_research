from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

MARK_IMPORT = "# AUTONOMY_QUALITY_V4_IMPORTS"
MARK_GUARD = "# AUTONOMY_QUALITY_V4_PRE_RUN_GUARD"
MARK_CODE3 = "# AUTONOMY_QUALITY_V4_CODE3_HANDLE"
MARK_SIGNAL = "# AUTONOMY_QUALITY_V4_SPY_MARKET_FILTER"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


def write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def copy_payload(repo: Path, package_root: Path) -> None:
    payload = package_root / "payload"
    for src in payload.rglob("*"):
        if src.is_file():
            rel = src.relative_to(payload)
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def patch_research_loop(repo: Path) -> None:
    path = repo / "scripts" / "research_loop.py"
    text = read(path)
    if MARK_IMPORT not in text:
        anchor = "from scripts.research.candidate_review_learning import candidate_review_scope_reason\n"
        insert = anchor + f"{MARK_IMPORT}\nfrom scripts.research.pre_run_duplicate_guard import check_pre_run_duplicate_guard\n"
        if anchor not in text:
            raise RuntimeError("research_loop.py import anchor not found")
        text = text.replace(anchor, insert)

    if MARK_GUARD not in text:
        anchor = '''    score = preflight_score(inputs, state_dir=args.state_dir)
    if score.get("decision") == "rejected":
        update_research_state(args.state_dir, inputs.run_id, "blocked", f"Preflight rejected: {score.get('reason')}")
        print(f"Research loop blocked before backtest: {score.get('reason')}")
        return 2

'''
        block = anchor + '''    # AUTONOMY_QUALITY_V4_PRE_RUN_GUARD
    guard = check_pre_run_duplicate_guard(
        run_id=inputs.run_id,
        strategy_config_path=inputs.strategy_config_path,
        state_dir=args.state_dir,
        runs_dir=args.runs_dir,
        hypothesis_id=inputs.hypothesis_id,
        family=inputs.family,
    )
    if guard.get("blocked"):
        reason = str(guard.get("reason") or "pre_run_guard_blocked")
        update_research_state(args.state_dir, inputs.run_id, "pre_run_guard_blocked", reason)
        print(f"Pre-run duplicate guard blocked {inputs.run_id}: {reason}")
        return 3

'''
        if anchor not in text:
            raise RuntimeError("research_loop.py preflight anchor not found")
        text = text.replace(anchor, block)
    write(path, text)


def patch_run_research_batch(repo: Path) -> None:
    path = repo / "scripts" / "run_research_batch.py"
    text = read(path)
    if MARK_CODE3 not in text:
        anchor = '''        code = _run_command(cmd)
        if code != 0:
            state["status"] = "failed"
            state["stop_reason"] = f"research_loop_exit_code:{code}"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: research_loop failed with code {code}")
            break

'''
        block = '''        code = _run_command(cmd)
        if code == 3:
            # AUTONOMY_QUALITY_V4_CODE3_HANDLE
            state["completed"] += 1
            state["consecutive_rejections"] += 1
            state.setdefault("history", []).append(
                {
                    "iteration": state["completed"],
                    "run_id": f"PRE_RUN_GUARD_{state['completed']:03d}",
                    "hypothesis_id": hypothesis_id,
                    "family": str(hypothesis.get("family")),
                    "decision": "pre_run_guard_blocked",
                    "parent_strategy_config": effective_parent_strategy_config,
                }
            )
            _save_batch_state(args.state_dir, state)
            print(f"Continuing: pre-run guard blocked {hypothesis_id}; no backtest was executed.")
            continue
        if code != 0:
            state["status"] = "failed"
            state["stop_reason"] = f"research_loop_exit_code:{code}"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: research_loop failed with code {code}")
            break

'''
        if anchor not in text:
            raise RuntimeError("run_research_batch.py code handling anchor not found")
        text = text.replace(anchor, block)
    write(path, text)


def patch_signal_builder(repo: Path) -> None:
    path = repo / "backtester" / "signal_builder.py"
    text = read(path)
    pattern = re.compile(
        r"def _evaluate_market_filter\(snapshot: pd\.DataFrame, strategy_config: dict, benchmark_ticker: str\) -> bool:\n"
        r".*?\n(?=def _apply_risk_filters)",
        re.S,
    )
    replacement = '''def _evaluate_market_filter(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> bool:
    # AUTONOMY_QUALITY_V4_SPY_MARKET_FILTER
    market_filter_cfg = strategy_config.get("market_filter", {})
    require_positive_trend = bool(market_filter_cfg.get("require_positive_trend", True))
    fallback_if_missing = bool(
        market_filter_cfg.get("fallback_allow_if_missing_spy_metric", True)
    )

    if not require_positive_trend:
        return True

    spy_rows = snapshot[snapshot["ticker"] == benchmark_ticker]
    if spy_rows.empty:
        msg = f"critical: SPY market filter could not find {benchmark_ticker} row on signal date; using fallback={fallback_if_missing}."
        warnings.warn(msg, UserWarning)
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

    msg = (
        "critical: SPY market filter metrics unavailable/NaN "
        f"(tried={metric_candidates}); using fallback={fallback_if_missing}."
    )
    warnings.warn(msg, UserWarning)
    return fallback_if_missing


'''
    if MARK_SIGNAL not in text:
        text2, n = pattern.subn(replacement, text)
        if n != 1:
            raise RuntimeError("signal_builder.py _evaluate_market_filter replacement failed")
        text = text2
    write(path, text)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", required=True)
    p.add_argument("--package-root", required=True)
    args = p.parse_args()
    repo = Path(args.repo_root).resolve()
    package_root = Path(args.package_root).resolve()
    copy_payload(repo, package_root)
    patch_research_loop(repo)
    patch_run_research_batch(repo)
    patch_signal_builder(repo)
    print("Autonomy Quality v4 applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
