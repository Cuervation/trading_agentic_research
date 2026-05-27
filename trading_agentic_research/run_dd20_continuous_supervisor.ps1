$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repo

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = "logs/dd20_supervisor_$stamp.log"
$stopFile = "stop_dd20_supervisor.txt"

$cmd = @(
  "scripts/run_dd20_continuous_supervisor.py",
  "--cycle-max-batches", "5",
  "--cycle-max-total-attempts", "50",
  "--max-cycles", "100",
  "--max-wall-clock-hours", "168",
  "--per-run-timeout-minutes", "45",
  "--continue-after-first-valid",
  "--weekly-file", "data/sp500_feature_store_weekly_master_260523155332.csv",
  "--daily-folder", "data",
  "--parent-strategy-config", "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json",
  "--parent-run-id", "RETEST_HYP_AUTO_TIME_SERIES_MOMENTUM_SEED_1999_2026_20260524_174409",
  "--project-config", "configs/project_config.json",
  "--strategy-registry", "configs/strategy_registry.json",
  "--runs-dir", "runs",
  "--reports-dir", "reports",
  "--state-dir", "state",
  "--resume"
)

function Show-Status {
  if (Test-Path "state/dd20_supervisor_state.json") {
    $state = Get-Content "state/dd20_supervisor_state.json" -Raw | ConvertFrom-Json
    Write-Host ("DD20 supervisor cycle={0} status={1} next={2}" -f $state.cycle, $state.status, $state.next_action)
  }
  if (Test-Path "reports/dd20_best_so_far.md") {
    Select-String -Path "reports/dd20_best_so_far.md" -Pattern "Best near-valid|Best valid|Next axis" | ForEach-Object { Write-Host $_.Line }
  }
  Write-Host "Manual stop file: $stopFile"
}

for ($attempt = 1; $attempt -le 2; $attempt++) {
  Show-Status
  "[$(Get-Date -Format o)] Starting supervisor attempt $attempt" | Tee-Object -FilePath $log -Append
  & python @cmd 2>&1 | Tee-Object -FilePath $log -Append
  $exitCode = $LASTEXITCODE
  Show-Status
  if ($exitCode -eq 0) {
    exit 0
  }
  if ($attempt -eq 1 -and -not (Test-Path $stopFile)) {
    "[$(Get-Date -Format o)] Supervisor exited $exitCode; retrying once." | Tee-Object -FilePath $log -Append
    Start-Sleep -Seconds 30
    continue
  }
  exit $exitCode
}
