param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
$PackageRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Applying Autonomy Quality v2 to: $RepoRoot"

$researchDir = Join-Path $RepoRoot "scripts\research"
New-Item -ItemType Directory -Force -Path $researchDir | Out-Null

Copy-Item (Join-Path $PackageRoot "scripts\research\strategy_effect_signature.py") (Join-Path $researchDir "strategy_effect_signature.py") -Force
Copy-Item (Join-Path $PackageRoot "scripts\research\pre_run_duplicate_guard.py") (Join-Path $researchDir "pre_run_duplicate_guard.py") -Force
Copy-Item (Join-Path $PackageRoot "scripts\research\branch_exhaustion.py") (Join-Path $researchDir "branch_exhaustion.py") -Force
Copy-Item (Join-Path $PackageRoot "scripts\research\spy_feature_diagnostics.py") (Join-Path $researchDir "spy_feature_diagnostics.py") -Force
Copy-Item (Join-Path $PackageRoot "scripts\research\autonomy_quality_report.py") (Join-Path $researchDir "autonomy_quality_report.py") -Force

python (Join-Path $PackageRoot "tools\apply_autonomy_quality_v2.py") --repo-root $RepoRoot

Write-Host ""
Write-Host "Done. Now run:"
Write-Host ".\autonomy_quality_v2\tools\verify_autonomy_quality_v2.ps1 -RepoRoot `"$RepoRoot`""
