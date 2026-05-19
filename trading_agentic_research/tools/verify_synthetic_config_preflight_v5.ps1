param(
  [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
Push-Location $RepoRoot

$checks = @(
  @{Path=".\scripts\research\effective_hypothesis_filter.py"; Pattern="SYNTHETIC_CONFIG_PREFLIGHT_DIRECT_PATCH_V5|synthetic_duplicate_status|duplicate_strategy_effect_signature_synthetic_config"}
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

Write-Host "Synthetic config preflight v5 verification passed."
Pop-Location
