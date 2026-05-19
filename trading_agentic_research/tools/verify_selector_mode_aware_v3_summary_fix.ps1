param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
Push-Location $RepoRoot

$checks = @(
  @{Path=".\scripts\research\effective_hypothesis_filter.py"; Pattern="selector_equivalent|_selector_equivalent_block_reason|family_stalled_literature_mode"}
)

foreach ($c in $checks) {
  $found = Select-String -Path $c.Path -Pattern $c.Pattern
  if (-not $found) { throw "Pattern not found in $($c.Path): $($c.Pattern)" }
  Write-Host "OK: $($c.Path)"
  $found | Select-Object -First 8
}

python -m py_compile .\scripts\research\effective_hypothesis_filter.py
python -m py_compile .\scripts\research\hypothesis_eligibility.py
python -m py_compile .\scripts\select_next_hypothesis.py

python .\scripts\research\hypothesis_eligibility.py --state-dir .\state --hypothesis-bank .\bibliography\hypothesis_bank.jsonl

Write-Host "Selector mode-aware v3 summary verification passed."
Pop-Location
