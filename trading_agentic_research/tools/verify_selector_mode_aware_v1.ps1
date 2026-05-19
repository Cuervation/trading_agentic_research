param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
Push-Location $RepoRoot

$checks = @(
  @{Path=".\scripts\research\effective_hypothesis_filter.py"; Pattern="feature_space_stalled_literature_mode|summarize_effective_hypotheses"},
  @{Path=".\scripts\select_next_hypothesis.py"; Pattern="EFFECTIVE_HYPOTHESIS_FILTER_DIRECT_PATCH|effective_hypothesis_status"},
  @{Path=".\scripts\research\hypothesis_eligibility.py"; Pattern="EFFECTIVE_ELIGIBILITY_SUMMARY_DIRECT_PATCH|recommended_mode"},
  @{Path=".\scripts\run_research_batch.py"; Pattern="FEATURE_SPACE_EXHAUSTED_MODE_DIRECT_PATCH|feature_space_exhausted_needs_literature_mode"},
  @{Path=".\scripts\run_research_batch_autonomous.py"; Pattern="AUTONOMOUS_RESEARCH_MODE_DIRECT_PATCH|Research mode recommendation"}
)

foreach ($c in $checks) {
  $found = Select-String -Path $c.Path -Pattern $c.Pattern
  if (-not $found) {
    throw "Pattern not found in $($c.Path): $($c.Pattern)"
  }
  Write-Host "OK: $($c.Path)"
  $found | Select-Object -First 6
}

python -m py_compile `
  .\scripts\research\effective_hypothesis_filter.py `
  .\scripts\select_next_hypothesis.py `
  .\scripts\research\hypothesis_eligibility.py `
  .\scripts\run_research_batch.py `
  .\scripts\run_research_batch_autonomous.py

python .\scripts\research\hypothesis_eligibility.py --state-dir .\state --hypothesis-bank .\bibliography\hypothesis_bank.jsonl

Write-Host "Selector mode-aware v1 verification passed."
Pop-Location
