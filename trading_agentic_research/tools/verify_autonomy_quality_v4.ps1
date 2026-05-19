param(
  [string]$RepoRoot = "."
)
$ErrorActionPreference = "Stop"
Push-Location $RepoRoot

$required = @(
  ".\scripts\research\pre_run_duplicate_guard.py",
  ".\scripts\research\strategy_effect_signature.py",
  ".\scripts\research\branch_exhaustion.py",
  ".\scripts\research\spy_feature_diagnostics.py",
  ".\scripts\research\autonomy_quality_report.py"
)
foreach ($f in $required) {
  if (-not (Test-Path $f)) { throw "Missing required file: $f" }
  Write-Host "OK file: $f"
}

$checks = @(
  @{Path=".\scripts\research_loop.py"; Pattern="check_pre_run_duplicate_guard|return 3"},
  @{Path=".\scripts\run_research_batch.py"; Pattern="code == 3|pre-run guard blocked"},
  @{Path=".\backtester\signal_builder.py"; Pattern="metric_candidates|critical: SPY market filter"}
)
foreach ($c in $checks) {
  $found = Select-String -Path $c.Path -Pattern $c.Pattern
  if (-not $found) { throw "Pattern not found in $($c.Path): $($c.Pattern)" }
  Write-Host "OK patch: $($c.Path) -> $($c.Pattern)"
}

python -m py_compile `
  .\scripts\research\pre_run_duplicate_guard.py `
  .\scripts\research\strategy_effect_signature.py `
  .\scripts\research\branch_exhaustion.py `
  .\scripts\research\spy_feature_diagnostics.py `
  .\scripts\research\autonomy_quality_report.py `
  .\scripts\research_loop.py `
  .\scripts\run_research_batch.py `
  .\backtester\signal_builder.py

Write-Host "Autonomy Quality v4 verification passed."
Pop-Location
