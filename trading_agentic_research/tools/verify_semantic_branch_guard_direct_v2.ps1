param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
Push-Location $RepoRoot

$required = @(
  ".\scripts\research\semantic_branch_guard.py",
  ".\scripts\research\pre_run_duplicate_guard.py",
  ".\scripts\evaluate_candidate.py",
  ".\scripts\research\feature_space_expansion_factory.py"
)

foreach ($f in $required) {
  if (-not (Test-Path $f)) { throw "Missing file: $f" }
}

$checks = @(
  @{Path=".\scripts\research\pre_run_duplicate_guard.py"; Pattern="semantic_branch_preflight|SEMANTIC_BRANCH_GUARD_DIRECT_V2"},
  @{Path=".\scripts\evaluate_candidate.py"; Pattern="refresh_semantic_branch_state|SEMANTIC_BRANCH_REFRESH_DIRECT_V2"},
  @{Path=".\scripts\research\feature_space_expansion_factory.py"; Pattern="is_semantic_branch_exhausted|SEMANTIC_BRANCH_SKIP_DIRECT_V2"}
)

foreach ($c in $checks) {
  $found = Select-String -Path $c.Path -Pattern $c.Pattern
  if (-not $found) { throw "Pattern not found in $($c.Path): $($c.Pattern)" }
  Write-Host "OK: $($c.Path)"
  $found | Select-Object -First 6
}

python -m py_compile `
  .\scripts\research\semantic_branch_guard.py `
  .\scripts\research\pre_run_duplicate_guard.py `
  .\scripts\evaluate_candidate.py `
  .\scripts\research\feature_space_expansion_factory.py

python .\scripts\research\semantic_branch_guard.py --state-dir .\state --runs-dir .\runs

Write-Host "Semantic Branch Guard direct v2 verification passed."
Pop-Location
