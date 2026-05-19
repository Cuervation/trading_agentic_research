param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path $RepoRoot).Path
Push-Location $RepoRoot

python .\tools\apply_selector_mode_aware_v1.py

Pop-Location
