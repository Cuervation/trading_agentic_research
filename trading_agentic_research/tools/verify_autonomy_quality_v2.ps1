param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
Push-Location $RepoRoot

try {
  Write-Host "Checking new files..."
  $files = @(
    ".\scripts\research\pre_run_duplicate_guard.py",
    ".\scripts\research\strategy_effect_signature.py",
    ".\scripts\research\branch_exhaustion.py",
    ".\scripts\research\spy_feature_diagnostics.py",
    ".\scripts\research\autonomy_quality_report.py"
  )
  foreach ($f in $files) {
    if (-not (Test-Path $f)) { throw "Missing required file: $f" }
    Write-Host "OK $f"
  }

  Write-Host ""
  Write-Host "Checking patch markers..."
  Select-String -Path .\scripts\research_loop.py -Pattern "Pre-run duplicate guard|check_pre_run_duplicate|record_completed_strategy_effect" | Out-Host
  Select-String -Path .\scripts\run_research_batch.py -Pattern "update_branch_exhaustion_after_run|write_autonomy_quality_report" | Out-Host
  Select-String -Path .\backtester\signal_builder.py -Pattern "SPY row fallback metric|data_quality_critical|spy_metric_fallback" | Out-Host
  Select-String -Path .\backtester\execution.py -Pattern "caught_warnings|py_warnings" | Out-Host
  Select-String -Path .\backtester\validation.py -Pattern "data_quality_critical" | Out-Host
  Select-String -Path .\scripts\research\feature_space_expansion_factory.py -Pattern "branch_exhausted|branch_key_for_candidate" | Out-Host

  Write-Host ""
  Write-Host "Compiling Python files..."
  python -m py_compile .\scripts\research\strategy_effect_signature.py
  python -m py_compile .\scripts\research\pre_run_duplicate_guard.py
  python -m py_compile .\scripts\research\branch_exhaustion.py
  python -m py_compile .\scripts\research\spy_feature_diagnostics.py
  python -m py_compile .\scripts\research\autonomy_quality_report.py
  python -m py_compile .\scripts\research_loop.py
  python -m py_compile .\scripts\run_research_batch.py
  python -m py_compile .\backtester\signal_builder.py
  python -m py_compile .\backtester\execution.py
  python -m py_compile .\backtester\validation.py
  python -m py_compile .\scripts\research\feature_space_expansion_factory.py

  Write-Host ""
  Write-Host "Building initial strategy-effect index from existing runs..."
  python -c "from scripts.research.pre_run_duplicate_guard import rebuild_strategy_effect_index; r=rebuild_strategy_effect_index(state_dir='state', runs_dir='runs', strategy_registry_path='configs/strategy_registry.json', repo_root='.'); print('runs_indexed=', len(r.get('runs',{})), 'signatures=', len(r.get('signatures',{})))"

  Write-Host ""
  Write-Host "Writing autonomy quality report..."
  python .\scripts\research\autonomy_quality_report.py --state-dir .\state --reports-dir .\reports --runs-dir .\runs

  if (Test-Path ".\sp500_feature_store_weekly_master_all_260330223625.csv") {
    Write-Host ""
    Write-Host "Writing SPY feature diagnostics..."
    python .\scripts\research\spy_feature_diagnostics.py --weekly-file ".\sp500_feature_store_weekly_master_all_260330223625.csv" --reports-dir ".\reports"
  } else {
    Write-Host "Weekly feature file not found; skipping SPY diagnostics."
  }

  Write-Host ""
  Write-Host "Autonomy Quality v2 verification completed."
}
finally {
  Pop-Location
}
