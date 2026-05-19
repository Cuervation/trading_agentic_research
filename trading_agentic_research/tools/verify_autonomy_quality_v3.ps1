param([string]$RepoRoot = ".")
$ErrorActionPreference = "Stop"
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
    if (-not (Test-Path $f)) { throw "Missing $f" }
    Write-Host "OK $f"
  }

  Write-Host "Checking patches..."
  Select-String -Path .\scripts\research_loop.py -Pattern "check_pre_run_duplicate_guard|return 3" | Out-Host
  Select-String -Path .\scripts\run_research_batch.py -Pattern "code == 3|pre-run guard blocked" | Out-Host
  Select-String -Path .\backtester\signal_builder.py -Pattern "metric_candidates|critical: SPY market filter" | Out-Host
  Select-String -Path .\scripts\research\feature_space_expansion_factory.py -Pattern "branch_exhausted|refresh_branch_exhaustion" | Out-Host

  Write-Host "Compiling..."
  python -m py_compile .\scripts\research\pre_run_duplicate_guard.py
  python -m py_compile .\scripts\research\strategy_effect_signature.py
  python -m py_compile .\scripts\research\branch_exhaustion.py
  python -m py_compile .\scripts\research\spy_feature_diagnostics.py
  python -m py_compile .\scripts\research\autonomy_quality_report.py
  python -m py_compile .\scripts\research_loop.py
  python -m py_compile .\scripts\run_research_batch.py
  python -m py_compile .\backtester\signal_builder.py
  python -m py_compile .\scripts\research\feature_space_expansion_factory.py

  Write-Host "Building strategy effect index..."
  python .\scripts\research\pre_run_duplicate_guard.py `
    --strategy-config ".\configs\generated\HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json" `
    --state-dir ".\state" `
    --runs-dir ".\runs" `
    --hypothesis-id "VERIFY_ONLY" `
    --family "verify" `
    --attempted-run-id "VERIFY_ONLY" | Out-Host

  Write-Host "Generating autonomy report..."
  python .\scripts\research\autonomy_quality_report.py --state-dir ".\state" --reports-dir ".\reports" | Out-Host
  Write-Host "Autonomy Quality v3 verification completed."
} finally {
  Pop-Location
}
