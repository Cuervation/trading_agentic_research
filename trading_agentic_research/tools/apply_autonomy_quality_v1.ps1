param(
  [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path $RepoRoot
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$zipRoot = Resolve-Path (Join-Path $scriptDir "..")
$payload = Join-Path $zipRoot "payload"

function Write-Step($msg) { Write-Host "[autonomy-quality-v1] $msg" -ForegroundColor Cyan }
function Read-Text($path) { Get-Content $path -Raw -Encoding UTF8 }
function Write-Text($path, $text) { Set-Content -Path $path -Value $text -Encoding UTF8 }

function Replace-Or-Fail([string]$Text, [string]$Old, [string]$New, [string]$Label) {
  if ($Text.Contains($New)) { return $Text }
  if (-not $Text.Contains($Old)) { throw "Pattern not found for $Label" }
  return $Text.Replace($Old, $New)
}

Write-Step "Repo: $repo"

# 1) Copy new modules.
Write-Step "Copying new research autonomy modules"
$srcResearch = Join-Path $payload "scripts\research"
$dstResearch = Join-Path $repo "scripts\research"
New-Item -ItemType Directory -Force -Path $dstResearch | Out-Null
Copy-Item (Join-Path $srcResearch "*.py") $dstResearch -Force

# 2) Patch run_research_batch.py.
$batchPath = Join-Path $repo "scripts\run_research_batch.py"
Write-Step "Patching $batchPath"
$text = Read-Text $batchPath

# Keep cooldown contract fixed even if an older local file is present.
$text = $text.Replace(
  "from scripts.research.cooldown_governance import hard_active_cooldown_families",
  "from scripts.research.cooldown_governance import hard_active_cooldown_family_names"
)
$text = $text.Replace(
  "return hard_active_cooldown_families(cooldowns)",
  "return hard_active_cooldown_family_names(cooldowns)"
)

if ($text -notmatch "pre_run_duplicate_guard import") {
  $anchor = "from scripts.research.cooldown_governance import hard_active_cooldown_family_names`n"
  if (-not $text.Contains($anchor)) { throw "Cannot find cooldown_governance import anchor in run_research_batch.py" }
  $insert = @'
from scripts.research.pre_run_duplicate_guard import (
    preflight_strategy_effect_duplicate,
    mark_preflight_duplicate_consumed,
    register_strategy_effect_from_run,
    sync_strategy_effect_index_from_consumed,
)
from scripts.research.branch_exhaustion import (
    refresh_branch_exhaustion,
    is_hypothesis_branch_exhausted,
    mark_branch_blocked_hypothesis,
)
from scripts.research.autonomy_quality_report import write_autonomy_quality_report
'@
  $text = $text.Replace($anchor, $anchor + $insert)
}

# Initialize indexes before the loop.
if ($text -notmatch "max_preflight_blocks") {
  $old = @'
    _save_batch_state(args.state_dir, state)

    while state["completed"] < args.max_runs:
'@
  $new = @'
    _save_batch_state(args.state_dir, state)

    # Backfill pre-run indexes from existing local history. This is safe and
    # does not move parents, promote baselines, or delete historical state.
    sync_result = sync_strategy_effect_index_from_consumed(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        generated_configs_dir=args.generated_configs_dir,
        repo_root=ROOT,
        max_rows=500,
    )
    branch_result = refresh_branch_exhaustion(state_dir=args.state_dir)
    state["strategy_effect_index_sync"] = sync_result
    state["branch_exhaustion_refresh"] = branch_result
    state.setdefault("preflight_blocked", 0)
    max_preflight_blocks = max(10, int(args.max_runs) * 3)
    _save_batch_state(args.state_dir, state)

    while state["completed"] < args.max_runs:
        if int(state.get("preflight_blocked", 0) or 0) >= max_preflight_blocks:
            state["status"] = "stopped"
            state["stop_reason"] = f"too_many_preflight_blocks:{state.get('preflight_blocked')}"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: {state['stop_reason']}")
            break
'@
  $text = Replace-Or-Fail $text $old $new "run_research_batch loop initialization"
}

# Insert branch + duplicate preflight immediately after strategy config is resolved/generated.
if ($text -notmatch "duplicate_strategy_effect_signature") {
  $old = @'
        cmd = [
            sys.executable,
            "scripts/research_loop.py",
'@
  $new = @'
        branch_check = is_hypothesis_branch_exhausted(
            hypothesis=hypothesis,
            strategy_config_path=strategy_config,
            state_dir=args.state_dir,
        )
        if branch_check.get("blocked"):
            block_result = mark_branch_blocked_hypothesis(
                state_dir=args.state_dir,
                hypothesis_id=hypothesis_id,
                family=str(hypothesis.get("family")),
                branch_check=branch_check,
            )
            state["preflight_blocked"] = int(state.get("preflight_blocked", 0) or 0) + 1
            state["consecutive_rejections"] = int(state.get("consecutive_rejections", 0) or 0) + 1
            state.setdefault("history", []).append({
                "iteration": None,
                "run_id": block_result.get("event", {}).get("run_id"),
                "hypothesis_id": hypothesis_id,
                "family": str(hypothesis.get("family")),
                "decision": "rejected",
                "value_delivered": "branch_exhausted_preflight_blocked",
                "parent_strategy_config": effective_parent_strategy_config,
                "branch_key": branch_check.get("branch_key"),
            })
            _save_batch_state(args.state_dir, state)
            print(f"Pre-run branch block: {hypothesis_id} branch={branch_check.get('branch_key')} reason={branch_check.get('reason')}")
            continue

        duplicate_check = preflight_strategy_effect_duplicate(
            strategy_config_path=strategy_config,
            state_dir=args.state_dir,
            hypothesis_id=hypothesis_id,
        )
        if duplicate_check.get("blocked"):
            block_result = mark_preflight_duplicate_consumed(
                state_dir=args.state_dir,
                hypothesis_id=hypothesis_id,
                family=str(hypothesis.get("family")),
                duplicate_check=duplicate_check,
            )
            state["preflight_blocked"] = int(state.get("preflight_blocked", 0) or 0) + 1
            state["consecutive_rejections"] = int(state.get("consecutive_rejections", 0) or 0) + 1
            state.setdefault("history", []).append({
                "iteration": None,
                "run_id": block_result.get("row", {}).get("run_id"),
                "hypothesis_id": hypothesis_id,
                "family": str(hypothesis.get("family")),
                "decision": "rejected",
                "value_delivered": "duplicate_preflight_blocked",
                "parent_strategy_config": effective_parent_strategy_config,
                "duplicate_of_run_id": duplicate_check.get("duplicate_of_run_id"),
                "duplicate_of_hypothesis_id": duplicate_check.get("duplicate_of_hypothesis_id"),
            })
            _save_batch_state(args.state_dir, state)
            print(
                "Pre-run duplicate block:",
                hypothesis_id,
                f"duplicate_of_run={duplicate_check.get('duplicate_of_run_id')}",
                f"duplicate_of_hypothesis={duplicate_check.get('duplicate_of_hypothesis_id')}",
            )
            continue

        cmd = [
            sys.executable,
            "scripts/research_loop.py",
'@
  $text = Replace-Or-Fail $text $old $new "run_research_batch pre-run duplicate guard"
}

# Register completed run strategy-effect signature after audit is read.
if ($text -notmatch "register_strategy_effect_from_run") {
  # This should not happen because import insertion includes the symbol. This check is just defensive.
}
if ($text -notmatch "strategy_effect_register_result") {
  $old = @'
        audit = read_json(audit_path)

        state["completed"] += 1
'@
  $new = @'
        audit = read_json(audit_path)
        strategy_effect_register_result = register_strategy_effect_from_run(
            state_dir=args.state_dir,
            strategy_config_path=strategy_config,
            run_id=latest_run,
            hypothesis_id=hypothesis_id,
            family=str(hypothesis.get("family")),
            audit=audit,
        )
        branch_refresh_result = refresh_branch_exhaustion(state_dir=args.state_dir)

        state["completed"] += 1
'@
  $text = Replace-Or-Fail $text $old $new "run_research_batch post-run effect registration"
}

# Write autonomy quality report before returning.
if ($text -notmatch "autonomy_quality_report_result") {
  $old = @'
    print(f"Batch finished. Completed iterations: {state['completed']}")
    return 0
'@
  $new = @'
    autonomy_quality_report_result = write_autonomy_quality_report(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        lookback=30,
    )
    print(f"Autonomy quality report: {autonomy_quality_report_result.get('markdown')}")
    print(f"Batch finished. Completed iterations: {state['completed']}")
    return 0
'@
  $text = Replace-Or-Fail $text $old $new "run_research_batch quality report"
}

Write-Text $batchPath $text

# 3) Patch research_loop.py for direct-run duplicate safety.
$loopPath = Join-Path $repo "scripts\research_loop.py"
Write-Step "Patching $loopPath"
$text = Read-Text $loopPath
if ($text -notmatch "pre_run_duplicate_guard import") {
  $anchor = "from scripts.research.candidate_review_learning import candidate_review_scope_reason`n"
  if (-not $text.Contains($anchor)) { throw "Cannot find import anchor in research_loop.py" }
  $insert = @'
from scripts.research.pre_run_duplicate_guard import (
    preflight_strategy_effect_duplicate,
    mark_preflight_duplicate_consumed,
)
'@
  $text = $text.Replace($anchor, $anchor + $insert)
}
if ($text -notmatch "Direct research_loop duplicate block") {
  $old = @'
    strategy_config = read_json(inputs.strategy_config_path)
    hypothesis = find_hypothesis(inputs.hypothesis_id)
'@
  $new = @'
    strategy_config = read_json(inputs.strategy_config_path)
    duplicate_check = preflight_strategy_effect_duplicate(
        strategy_config_path=inputs.strategy_config_path,
        state_dir=args.state_dir,
        hypothesis_id=inputs.hypothesis_id,
    )
    if duplicate_check.get("blocked"):
        mark_preflight_duplicate_consumed(
            state_dir=args.state_dir,
            hypothesis_id=inputs.hypothesis_id,
            family=inputs.family,
            duplicate_check=duplicate_check,
            source="research_loop_direct_preflight",
        )
        update_research_state(args.state_dir, inputs.run_id, "blocked_pre_run_duplicate", "Direct research_loop duplicate block before backtest.")
        print(f"Research loop blocked before backtest: duplicate_strategy_effect_signature {inputs.hypothesis_id}")
        return 2
    hypothesis = find_hypothesis(inputs.hypothesis_id)
'@
  $text = Replace-Or-Fail $text $old $new "research_loop direct duplicate guard"
}
Write-Text $loopPath $text

# 4) Patch signal_builder.py to use direct SPY row metric before fallback and mark strict missing as critical.
$signalPath = Join-Path $repo "backtester\signal_builder.py"
Write-Step "Patching $signalPath"
$text = Read-Text $signalPath
if ($text -notmatch "critical_market_filter_missing_spy_metric") {
  $pattern = '(?s)def _evaluate_market_filter\(snapshot: pd\.DataFrame, strategy_config: dict, benchmark_ticker: str\) -> bool:.*?\n\ndef _apply_risk_filters'
  $replacement = @'
def _evaluate_market_filter(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> bool:
    market_filter_cfg = strategy_config.get("market_filter", {})
    require_positive_trend = bool(market_filter_cfg.get("require_positive_trend", True))
    fallback_if_missing = bool(
        market_filter_cfg.get("fallback_allow_if_missing_spy_metric", True)
    )

    if not require_positive_trend:
        return True

    spy_rows = snapshot[snapshot["ticker"] == benchmark_ticker]
    if spy_rows.empty:
        msg = f"Market filter could not find {benchmark_ticker} row on signal date; using fallback."
        if not fallback_if_missing:
            msg = f"critical_market_filter_missing_spy_row: {msg}"
        warnings.warn(msg, UserWarning)
        return fallback_if_missing

    row = spy_rows.iloc[0]
    metric_candidates = ["spy_close_vs_sma50_pct", "close_vs_sma50_pct", "close_vs_sma52w_pct"]
    for metric in metric_candidates:
        if metric not in spy_rows.columns:
            continue
        value = pd.to_numeric(row[metric], errors="coerce")
        if not pd.isna(value):
            return bool(value > 0)

    msg = (
        "SPY market-filter metrics are missing/NaN "
        f"({metric_candidates}); using market filter fallback."
    )
    if not fallback_if_missing:
        msg = f"critical_market_filter_missing_spy_metric: {msg}"
    warnings.warn(msg, UserWarning)
    return fallback_if_missing


def _apply_risk_filters'@
  $newText = [regex]::Replace($text, $pattern, $replacement, 1)
  if ($newText -eq $text) { throw "Could not replace _evaluate_market_filter in signal_builder.py" }
  $text = $newText
}
Write-Text $signalPath $text

# 5) Patch autonomous_hypothesis_factory.py so new preflight values influence exhausted axis memory.
$factoryPath = Join-Path $repo "scripts\research\autonomous_hypothesis_factory.py"
if (Test-Path $factoryPath) {
  Write-Step "Patching $factoryPath"
  $text = Read-Text $factoryPath
  $text = $text.Replace(
    'BAD_VALUE_DELIVERED = {"duplicate_blocked", "metric_no_effect_blocked"}',
    'BAD_VALUE_DELIVERED = {"duplicate_blocked", "duplicate_preflight_blocked", "metric_no_effect_blocked", "branch_exhausted_preflight_blocked"}'
  )
  Write-Text $factoryPath $text
}

Write-Step "Patch complete. Run tools\verify_autonomy_quality_v1.ps1 next."
