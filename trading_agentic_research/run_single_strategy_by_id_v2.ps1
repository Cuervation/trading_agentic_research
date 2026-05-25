<#
.SYNOPSIS
  Corre una sola estrategia del repo trading_agentic_research pasando strategy_id.

.DESCRIPTION
  Resuelve el strategy_id desde configs/strategy_registry.json y ejecuta una única corrida.

  Pensado para tu caso:
    - El CSV semanal y los CSV diarios están siempre en la misma carpeta.
    - Pasás -DataFolder y el script detecta automáticamente el weekly usando -WeeklyPattern.
    - DailyFolder queda igual a DataFolder.

  Modos:
    - BacktestOnly: corre solo scripts/run_backtest.py. No toca governance, no consume hipótesis y evita el duplicate guard.
    - BacktestAndEvaluate: corre backtest + scripts/evaluate_candidate.py. Escribe audit.json y actualiza memoria/state.
    - ResearchLoop: corre scripts/research_loop.py. Respeta preflight, duplicate guard, audit y governance; puede bloquear si la estrategia ya fue corrida.

.EXAMPLE
  .\run_single_strategy_by_id.ps1 `
    -StrategyId "HYP_REFINE_AUTO002_TOPN_6_V1" `
    -DataFolder "C:\Pythons\ML-Trading\Momentum\trading_agentic_research\data" `
    -Mode BacktestOnly

.EXAMPLE
  .\run_single_strategy_by_id.ps1 `
    -StrategyId "HYP_REFINE_AUTO002_TOPN_6_V1" `
    -DataFolder "C:\Pythons\ML-Trading\Momentum\trading_agentic_research\data" `
    -WeeklyPattern "*weekly*master*.csv" `
    -Mode BacktestOnly
#>

param(
  [string]$RepoRoot = "C:\Pythons\ML-Trading\Momentum\trading_agentic_research",
  [string]$Python = "python",

  [string]$StrategyId = "HYP_REFINE_AUTO002_TOPN_6_V1",

  # Si weekly y daily están en la misma carpeta, usá solo este parámetro.
  [string]$DataFolder = "",

  # Opcional: para forzar archivo/carpeta puntuales.
  [string]$WeeklyFile = "",
  [string]$DailyFolder = "",

  # Patrón para detectar el archivo semanal dentro de DataFolder.
  [string]$WeeklyPattern = "*weekly*.csv",

  [ValidateSet("BacktestOnly", "BacktestAndEvaluate", "ResearchLoop")]
  [string]$Mode = "BacktestOnly",

  [string]$RunId = "",

  [string]$ProjectConfig = "configs\project_config.json",
  [string]$StrategyRegistry = "configs\strategy_registry.json",
  [string]$RunsDir = "runs",
  [string]$ReportsDir = "reports",
  [string]$StateDir = "state",

  [string]$ParentRunId = "AUTO_002",
  [string]$ParentStrategyConfig = "configs\generated\HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json",

  [switch]$AllowParentUpdate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot {
  param([string]$Root)

  $rootPath = Resolve-Path -Path $Root -ErrorAction Stop
  $candidate = $rootPath.Path

  if (Test-Path (Join-Path $candidate "scripts\run_backtest.py")) {
    return $candidate
  }

  $nested = Join-Path $candidate "trading_agentic_research"
  if (Test-Path (Join-Path $nested "scripts\run_backtest.py")) {
    return $nested
  }

  throw "No encuentro scripts\run_backtest.py en '$candidate' ni en '$nested'. Revisá -RepoRoot."
}

function Resolve-AnyPath {
  param(
    [string]$Base,
    [string]$PathValue
  )

  if ([string]::IsNullOrWhiteSpace($PathValue)) {
    return ""
  }

  if ([System.IO.Path]::IsPathRooted($PathValue)) {
    return $PathValue
  }

  return (Join-Path $Base $PathValue)
}

function Find-WeeklyFileInFolder {
  param(
    [string]$Folder,
    [string]$Pattern
  )

  if (-not (Test-Path $Folder)) {
    throw "No existe DataFolder: $Folder"
  }

  $files = @(Get-ChildItem -Path $Folder -File -Filter $Pattern | Sort-Object LastWriteTime -Descending)

  if ($files.Count -eq 0) {
    return ""
  }

  if ($files.Count -gt 1) {
    Write-Host "Encontré varios weekly. Uso el más reciente:" -ForegroundColor Yellow
    $files | Select-Object -First 5 | ForEach-Object {
      Write-Host "  $($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))  $($_.Name)" -ForegroundColor DarkYellow
    }
  }

  return $files[0].FullName
}

function Has-DailyFeatureFiles {
  param([string]$Folder)

  if (-not (Test-Path $Folder)) {
    return $false
  }

  return @(
    Get-ChildItem -Path $Folder -File -Filter "sp500_feature_store_daily_master_*.csv"
    Get-ChildItem -Path $Folder -File -Filter "sp500_feature_store_spy_daily_master_*.csv"
  ).Count -gt 0
}

function Invoke-Step {
  param(
    [string]$Title,
    [string[]]$CommandArgs
  )

  Write-Host ""
  Write-Host "=== $Title ===" -ForegroundColor Cyan
  Write-Host "$Python $($CommandArgs -join ' ')" -ForegroundColor DarkGray

  & $Python @CommandArgs
  $exitCode = $LASTEXITCODE

  if ($exitCode -ne 0) {
    throw "Falló '$Title' con exit code $exitCode"
  }
}

$ProjectRoot = Resolve-ProjectRoot -Root $RepoRoot
Set-Location $ProjectRoot

$projectConfigPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $ProjectConfig
$strategyRegistryPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $StrategyRegistry
$runsDirPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $RunsDir
$reportsDirPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $ReportsDir
$stateDirPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $StateDir
$parentStrategyConfigPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $ParentStrategyConfig

if (-not (Test-Path $projectConfigPath)) {
  throw "No existe ProjectConfig: $projectConfigPath"
}
if (-not (Test-Path $strategyRegistryPath)) {
  throw "No existe StrategyRegistry: $strategyRegistryPath"
}

$registry = Get-Content -Path $strategyRegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$strategy = @($registry.strategies | Where-Object { $_.strategy_id -eq $StrategyId }) | Select-Object -First 1

if ($null -eq $strategy) {
  throw "No encontré strategy_id '$StrategyId' en $strategyRegistryPath"
}

$strategyConfigPath = Resolve-AnyPath -Base $ProjectRoot -PathValue ([string]$strategy.config_path)
if (-not (Test-Path $strategyConfigPath)) {
  throw "El strategy_id existe, pero no encontré su config_path: $strategyConfigPath"
}

$projectCfg = Get-Content -Path $projectConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

# Prioridad:
# 1) WeeklyFile/DailyFolder explícitos
# 2) DataFolder: weekly detectado + daily folder = DataFolder
# 3) project_config.json
if (-not [string]::IsNullOrWhiteSpace($DataFolder)) {
  $dataFolderPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $DataFolder

  if ([string]::IsNullOrWhiteSpace($WeeklyFile)) {
    $WeeklyFile = Find-WeeklyFileInFolder -Folder $dataFolderPath -Pattern $WeeklyPattern
    if ([string]::IsNullOrWhiteSpace($WeeklyFile)) {
      $parentFolder = Split-Path -Parent $dataFolderPath
      if (-not [string]::IsNullOrWhiteSpace($parentFolder) -and (Test-Path $parentFolder)) {
        Write-Host "No encontré weekly en DataFolder; pruebo en el padre: $parentFolder" -ForegroundColor Yellow
        $WeeklyFile = Find-WeeklyFileInFolder -Folder $parentFolder -Pattern $WeeklyPattern
      }
    }
  }

  if ([string]::IsNullOrWhiteSpace($DailyFolder)) {
    $DailyFolder = $dataFolderPath
  }

  $dailyFolderCandidate = Resolve-AnyPath -Base $ProjectRoot -PathValue $DailyFolder
  if (-not (Has-DailyFeatureFiles -Folder $dailyFolderCandidate)) {
    $parentFolder = Split-Path -Parent $dataFolderPath
    if (-not [string]::IsNullOrWhiteSpace($parentFolder) -and (Test-Path $parentFolder) -and (Has-DailyFeatureFiles -Folder $parentFolder)) {
      Write-Host "No encontré daily en DataFolder; uso el padre: $parentFolder" -ForegroundColor Yellow
      $DailyFolder = $parentFolder
    }
  }
}
else {
  if ([string]::IsNullOrWhiteSpace($WeeklyFile)) {
    $WeeklyFile = [string]$projectCfg.data_paths.weekly_file_path
  }
  if ([string]::IsNullOrWhiteSpace($DailyFolder)) {
    $DailyFolder = [string]$projectCfg.data_paths.daily_folder_path
  }
}

if ([string]::IsNullOrWhiteSpace($WeeklyFile)) {
  throw "Falta -WeeklyFile o -DataFolder. En configs\project_config.json weekly_file_path está vacío."
}
if ([string]::IsNullOrWhiteSpace($DailyFolder)) {
  throw "Falta -DailyFolder o -DataFolder. En configs\project_config.json daily_folder_path está vacío."
}

$weeklyFilePath = Resolve-AnyPath -Base $ProjectRoot -PathValue $WeeklyFile
$dailyFolderPath = Resolve-AnyPath -Base $ProjectRoot -PathValue $DailyFolder

if (-not (Test-Path $weeklyFilePath)) {
  throw "No existe WeeklyFile: $weeklyFilePath"
}
if (-not (Test-Path $dailyFolderPath)) {
  throw "No existe DailyFolder: $dailyFolderPath"
}

if ([string]::IsNullOrWhiteSpace($RunId)) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $safeStrategyId = $StrategyId -replace '[^A-Za-z0-9_]+', '_'
  $RunId = "MANUAL_${safeStrategyId}_${stamp}"
}

$family = if ($strategy.strategy_family) { [string]$strategy.strategy_family } else { "manual_single_strategy" }

Write-Host ""
Write-Host "ProjectRoot:      $ProjectRoot"
Write-Host "Mode:             $Mode"
Write-Host "RunId:            $RunId"
Write-Host "StrategyId:       $StrategyId"
Write-Host "Strategy family:  $family"
Write-Host "Strategy config:  $strategyConfigPath"
Write-Host "Weekly file:      $weeklyFilePath"
Write-Host "Daily folder:     $dailyFolderPath"
Write-Host "Runs dir:         $runsDirPath"

New-Item -ItemType Directory -Force -Path $runsDirPath | Out-Null
New-Item -ItemType Directory -Force -Path $reportsDirPath | Out-Null
New-Item -ItemType Directory -Force -Path $stateDirPath | Out-Null

if ($Mode -eq "ResearchLoop") {
  $argsList = @(
    "scripts\research_loop.py",
    "--strategy-config", $strategyConfigPath,
    "--weekly-file", $weeklyFilePath,
    "--daily-folder", $dailyFolderPath,
    "--project-config", $projectConfigPath,
    "--run-id", $RunId,
    "--hypothesis-id", $StrategyId,
    "--family", $family,
    "--runs-dir", $runsDirPath,
    "--reports-dir", $reportsDirPath,
    "--state-dir", $stateDirPath,
    "--strategy-registry", $strategyRegistryPath
  )

  if (-not [string]::IsNullOrWhiteSpace($ParentRunId)) {
    $argsList += @("--parent-run-id", $ParentRunId)
  }
  if ((-not [string]::IsNullOrWhiteSpace($parentStrategyConfigPath)) -and (Test-Path $parentStrategyConfigPath)) {
    $argsList += @("--parent-strategy-config", $parentStrategyConfigPath)
  }
  if ($AllowParentUpdate) {
    $argsList += "--allow-parent-update"
  }

  Invoke-Step -Title "Research loop single run" -CommandArgs $argsList
}
else {
  $argsList = @(
    "scripts\run_backtest.py",
    "--weekly-file", $weeklyFilePath,
    "--daily-folder", $dailyFolderPath,
    "--strategy-config", $strategyConfigPath,
    "--project-config", $projectConfigPath,
    "--run-id", $RunId,
    "--runs-dir", $runsDirPath
  )

  if (-not [string]::IsNullOrWhiteSpace($ParentRunId)) {
    $argsList += @("--parent-run-id", $ParentRunId)
  }
  if ((-not [string]::IsNullOrWhiteSpace($parentStrategyConfigPath)) -and (Test-Path $parentStrategyConfigPath)) {
    $argsList += @("--parent-strategy-config", $parentStrategyConfigPath)
  }

  Invoke-Step -Title "Backtest single strategy" -CommandArgs $argsList

  if ($Mode -eq "BacktestAndEvaluate") {
    $evalArgs = @(
      "scripts\evaluate_candidate.py",
      "--run-id", $RunId,
      "--runs-dir", $runsDirPath,
      "--hypothesis-id", $StrategyId,
      "--family", $family,
      "--state-dir", $stateDirPath
    )

    if (-not [string]::IsNullOrWhiteSpace($ParentRunId)) {
      $evalArgs += @("--parent-run-id", $ParentRunId)
    }
    if ($AllowParentUpdate) {
      $evalArgs += "--allow-parent-update"
    }

    Invoke-Step -Title "Evaluate/audit completed run" -CommandArgs $evalArgs

    if (Test-Path (Join-Path $ProjectRoot "scripts\summarize_runs.py")) {
      $summaryArgs = @(
        "scripts\summarize_runs.py",
        "--runs-dir", $runsDirPath,
        "--output", (Join-Path $reportsDirPath "runs_summary.csv")
      )
      Invoke-Step -Title "Refresh runs summary" -CommandArgs $summaryArgs
    }
  }
}

$runFolder = Join-Path $runsDirPath $RunId
Write-Host ""
Write-Host "Listo. Carpeta generada:" -ForegroundColor Green
Write-Host $runFolder -ForegroundColor Green

if (Test-Path (Join-Path $runFolder "summary.md")) {
  Write-Host ""
  Write-Host "Resumen:" -ForegroundColor Cyan
  Get-Content (Join-Path $runFolder "summary.md") -TotalCount 40
}
