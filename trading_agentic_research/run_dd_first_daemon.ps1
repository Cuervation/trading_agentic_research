param(
  [int]$BatchSize = 5,
  [int]$MaxBatches = 20,
  [int]$MaxTotalAttempts = 150,
  [int]$MaxWallClockHours = 24,
  [int]$TargetChampions = 5
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = "logs/dd_first_daemon_$stamp.log"

$argsList = @(
  "scripts/run_dd_first_autonomous_daemon.py",
  "--batch-size", "$BatchSize",
  "--max-batches", "$MaxBatches",
  "--max-total-attempts", "$MaxTotalAttempts",
  "--max-wall-clock-hours", "$MaxWallClockHours",
  "--target-champions", "$TargetChampions",
  "--generation-mode", "causal",
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

function Show-State {
  $statePath = "state/dd_first_daemon_state.json"
  if (Test-Path $statePath) {
    $s = Get-Content $statePath -Raw | ConvertFrom-Json
    Write-Host ("batch={0} attempts={1} champions={2} last_run={3} last_error={4}" -f $s.current_batch,$s.total_attempts,$s.champions_found,$s.last_run_id,$s.last_error)
  }
}

$attempt = 0
do {
  $attempt++
  Write-Host "Starting DD_FIRST daemon attempt $attempt. Log: $log"
  & python @argsList *>> $log
  $exit = $LASTEXITCODE
  Show-State
  if ($exit -eq 0) { exit 0 }
  Write-Host "Daemon exited with code $exit"
} while ($attempt -lt 2)

exit $exit
