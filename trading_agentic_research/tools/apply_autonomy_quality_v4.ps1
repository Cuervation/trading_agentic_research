param(
  [string]$RepoRoot = "."
)
$ErrorActionPreference = "Stop"
$PackageRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = Resolve-Path $RepoRoot
python "$PSScriptRoot\apply_autonomy_quality_v4.py" --repo-root "$RepoRoot" --package-root "$PackageRoot"
Write-Host "Applied Autonomy Quality v4 to $RepoRoot"
