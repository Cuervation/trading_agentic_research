param(
  [string]$RepoRoot = "C:\Pythons\ML-Trading\Momentum\trading_agentic_research",
  [string]$DataFolder = "C:\Pythons\ML-Trading\Momentum\trading_agentic_research\data",
  [string]$StrategyRegistry = "configs\strategy_registry.json",
  [string]$Mode = "BacktestOnly",
  [string]$BatchId = "FULL_HISTORY_RETEST_$(Get-Date -Format 'yyyyMMdd_HHmmss')",
  [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path -Path $RepoRoot -ErrorAction Stop
Set-Location $root.Path

$registryPath = Join-Path $root.Path $StrategyRegistry
if (-not (Test-Path $registryPath)) {
  throw "No existe StrategyRegistry: $registryPath"
}

$outDir = Join-Path $root.Path ("runs\batches\" + $BatchId)
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$manifest = Join-Path $outDir "manifest.csv"
$summary = Join-Path $outDir "summary.txt"
$startedAt = Get-Date

if (-not (Test-Path $manifest)) {
  "batch_id,strategy_id,status,run_id,started_at,finished_at,exit_code,log_path" | Set-Content -Path $manifest -Encoding UTF8
}

$registry = Get-Content -Path $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$strategies = @($registry.strategies | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.strategy_id) })

$done = @{}
if ($Resume -and (Test-Path $manifest)) {
  Import-Csv $manifest | Where-Object { $_.status -eq "ok" } | ForEach-Object { $done[$_.strategy_id] = $true }
}

"BatchId: $BatchId" | Set-Content -Path $summary -Encoding UTF8
"Started: $startedAt" | Add-Content -Path $summary -Encoding UTF8
"Total strategies: $($strategies.Count)" | Add-Content -Path $summary -Encoding UTF8
"DataFolder: $DataFolder" | Add-Content -Path $summary -Encoding UTF8
"" | Add-Content -Path $summary -Encoding UTF8

$index = 0
foreach ($strategy in $strategies) {
  $index++
  $strategyId = [string]$strategy.strategy_id
  if ($Resume -and $done.ContainsKey($strategyId)) {
    Write-Host "[$index/$($strategies.Count)] SKIP $strategyId" -ForegroundColor DarkGray
    continue
  }

  $safeId = $strategyId -replace '[^A-Za-z0-9_]+', '_'
  $runId = "RETEST_${safeId}_1999_2026_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
  $logPath = Join-Path $outDir ("$safeId.log")
  $errPath = Join-Path $outDir ("$safeId.err.log")
  $start = Get-Date

  Write-Host "[$index/$($strategies.Count)] RUN $strategyId" -ForegroundColor Cyan

  $proc = Start-Process -FilePath powershell.exe -ArgumentList @(
    '-ExecutionPolicy','Bypass',
    '-File', '.\run_single_strategy_by_id_v2.ps1',
    '-StrategyId', $strategyId,
    '-DataFolder', $DataFolder,
    '-Mode', $Mode,
    '-RunId', $runId
  ) -WorkingDirectory $root.Path -RedirectStandardOutput $logPath -RedirectStandardError $errPath -PassThru -Wait -WindowStyle Hidden

  $exit = $proc.ExitCode
  if (Test-Path $errPath) {
    Get-Content $errPath | Add-Content -Path $logPath
    Remove-Item $errPath -Force
  }
  $finish = Get-Date
  $status = if ($exit -eq 0) { "ok" } else { "failed" }

  ('"{0}","{1}","{2}","{3}","{4:o}","{5:o}","{6}","{7}"' -f $BatchId,$strategyId,$status,$runId,$start,$finish,$exit,$logPath) |
    Add-Content -Path $manifest -Encoding UTF8

  "[$($finish.ToString('yyyy-MM-dd HH:mm:ss'))] $status $strategyId $runId exit=$exit" | Add-Content -Path $summary -Encoding UTF8

  if ($exit -ne 0) {
    Write-Host "FAILED $strategyId exit=$exit; sigo con la siguiente. Log: $logPath" -ForegroundColor Yellow
  }
}

$finishedAt = Get-Date
"" | Add-Content -Path $summary -Encoding UTF8
"Finished: $finishedAt" | Add-Content -Path $summary -Encoding UTF8
"Elapsed: $($finishedAt - $startedAt)" | Add-Content -Path $summary -Encoding UTF8

Write-Host "Batch terminado: $outDir" -ForegroundColor Green
