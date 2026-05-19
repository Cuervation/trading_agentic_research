param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
Push-Location $RepoRoot

$checks = @(
  @{Path=".\scripts\research\effective_hypothesis_filter.py"; Pattern="duplicate_override_signature|infer_family_from_hypothesis_id|selector_equivalent"}
)

foreach ($c in $checks) {
  $found = Select-String -Path $c.Path -Pattern $c.Pattern
  if (-not $found) { throw "Pattern not found in $($c.Path): $($c.Pattern)" }
  Write-Host "OK: $($c.Path)"
  $found | Select-Object -First 10
}

python -m py_compile .\scripts\research\effective_hypothesis_filter.py
python -m py_compile .\scripts\research\hypothesis_eligibility.py
python -m py_compile .\scripts\select_next_hypothesis.py

python .\scripts\research\hypothesis_eligibility.py --state-dir .\state --hypothesis-bank .\bibliography\hypothesis_bank.jsonl

Write-Host "Selector mode-aware v4 signature summary verification passed."
Pop-Location
