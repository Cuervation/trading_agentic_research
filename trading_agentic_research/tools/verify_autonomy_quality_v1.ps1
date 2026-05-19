param(
  [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

Write-Host "[verify] Python compile checks" -ForegroundColor Cyan
$files = @(
  ".\scripts\research\strategy_effect_signature.py",
  ".\scripts\research\pre_run_duplicate_guard.py",
  ".\scripts\research\branch_exhaustion.py",
  ".\scripts\research\spy_feature_diagnostics.py",
  ".\scripts\research\autonomy_quality_report.py",
  ".\scripts\run_research_batch.py",
  ".\scripts\research_loop.py",
  ".\backtester\signal_builder.py",
  ".\backtester\validation.py"
)
foreach ($f in $files) {
  if (Test-Path $f) {
    python -m py_compile $f
    Write-Host "  OK $f"
  } else {
    throw "Missing expected file: $f"
  }
}

Write-Host "[verify] Strategy effect index backfill dry run" -ForegroundColor Cyan
python - <<'PY'
from scripts.research.pre_run_duplicate_guard import sync_strategy_effect_index_from_consumed
print(sync_strategy_effect_index_from_consumed(state_dir='state', strategy_registry_path='configs/strategy_registry.json', generated_configs_dir='configs/generated', repo_root='.', max_rows=50))
PY

Write-Host "[verify] Branch exhaustion refresh" -ForegroundColor Cyan
python .\scripts\research\branch_exhaustion.py --state-dir .\state

Write-Host "[verify] Autonomy quality report" -ForegroundColor Cyan
python .\scripts\research\autonomy_quality_report.py --state-dir .\state --reports-dir .\reports --lookback 30

Write-Host "[verify] Done" -ForegroundColor Green
