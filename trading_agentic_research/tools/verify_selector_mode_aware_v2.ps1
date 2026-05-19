param(
  [string]$RepoRoot = "."
)
$ErrorActionPreference = "Stop"
Push-Location $RepoRoot
$checks = @(
  @{Path=".\scripts\research\effective_hypothesis_filter.py"; Pattern="family_stalled_literature_mode|def family_stall_status"},
  @{Path=".\scripts\select_next_hypothesis.py"; Pattern="block_family_stall=True"},
  @{Path=".\scripts\run_research_batch_autonomous.py"; Pattern="MODE_RECOVERY_DIRECT_PATCH_V2|Pre-batch mode recovery"}
)
foreach ($c in $checks) {
  $found = Select-String -Path $c.Path -Pattern $c.Pattern
  if (-not $found) { throw "Pattern not found in $($c.Path): $($c.Pattern)" }
  Write-Host "OK: $($c.Path)"
  $found | Select-Object -First 6
}
python -m py_compile `
  .\scripts\research\effective_hypothesis_filter.py `
  .\scripts\select_next_hypothesis.py `
  .\scripts\run_research_batch_autonomous.py
python .\scripts\research\hypothesis_eligibility.py --state-dir .\state --hypothesis-bank .\bibliography\hypothesis_bank.jsonl
Write-Host "Selector mode-aware v2 verification passed."
Pop-Location
