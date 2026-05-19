param(
  [string]$RepoRoot = "."
)
$ErrorActionPreference = "Stop"
$PackageRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot = (Resolve-Path $RepoRoot).Path
python "$PSScriptRoot\apply_semantic_branch_guard_v1.py" --repo-root "$RepoRoot" --package-root "$PackageRoot"
Write-Host "Semantic branch guard v1 applied to $RepoRoot"
