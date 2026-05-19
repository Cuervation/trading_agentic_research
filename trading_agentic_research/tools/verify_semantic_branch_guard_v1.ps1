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
  Write-Host "OK file: $f"
}

$checks = @(
  @{Path=".\scripts\research\pre_run_duplicate_guard.py"; Pattern="SEMANTIC_BRANCH_GUARD_V1|check_semantic_branch_block|semantic_branch_exhausted"},
  @{Path=".\scripts\evaluate_candidate.py"; Pattern="SEMANTIC_BRANCH_GUARD_V1_REFRESH|refresh_semantic_branch_exhaustion|Semantic branch exhausted"},
  @{Path=".\scripts\research\feature_space_expansion_factory.py"; Pattern="SEMANTIC_BRANCH_GUARD_V1_GENERATOR_SKIP|semantic_branch_status|semantic_branch_exhausted"}
)
foreach ($c in $checks) {
  $found = Select-String -Path $c.Path -Pattern $c.Pattern
  if (-not $found) { throw "Pattern not found in $($c.Path): $($c.Pattern)" }
  Write-Host "OK patch: $($c.Path)"
}

python -m py_compile `
  .\scripts\research\semantic_branch_guard.py `
  .\scripts\research\pre_run_duplicate_guard.py `
  .\scripts\evaluate_candidate.py `
  .\scripts\research\feature_space_expansion_factory.py `
  .\scripts\research_loop.py `
  .\backtester\signal_builder.py

python - <<'PY'
from scripts.research.semantic_branch_guard import refresh_semantic_branch_exhaustion
result = refresh_semantic_branch_exhaustion(state_dir='state', runs_dir='runs')
exhausted = [k for k, v in result.get('branches', {}).items() if v.get('status') == 'exhausted']
print('semantic_exhausted_count=', len(exhausted))
print('semantic_exhausted_sample=', exhausted[:10])
PY

Write-Host "Semantic branch guard v1 verification passed."
Pop-Location
