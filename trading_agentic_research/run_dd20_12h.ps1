param(
  [int]$Hours = 12
)

$ErrorActionPreference = "Continue"

$repo = "C:\Pythons\ML-Trading\Momentum\trading_agentic_research"
Set-Location $repo

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $repo "reports\overnight_dd20"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$log = Join-Path $logDir "overnight_dd20_$stamp.log"
Start-Transcript -Path $log -Append

$end = (Get-Date).AddHours($Hours)

Write-Host "DD20 overnight started: $(Get-Date)"
Write-Host "Will stop after: $end"
Write-Host "Log: $log"

while ((Get-Date) -lt $end) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "Iteration started: $(Get-Date)"
    Write-Host "============================================================"

    python -m py_compile .\scripts\run\run_dd20_controlled_batch.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "py_compile failed. Stopping." -ForegroundColor Red
        break
    }

    python -m pytest .\tests\test_dd20_controlled_batch_runner.py -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "DD20 tests failed. Stopping." -ForegroundColor Red
        break
    }

    python .\scripts\run\run_dd20_controlled_batch.py

    $latestBatch = Get-ChildItem .\reports\dd20_controlled_batch -Directory |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -ne $latestBatch) {
        Write-Host ""
        Write-Host "Latest batch: $($latestBatch.FullName)" -ForegroundColor Cyan

        $statusPath = Join-Path $latestBatch.FullName "batch_status.json"
        $summaryPath = Join-Path $latestBatch.FullName "batch_summary.csv"

        if (Test-Path $statusPath) {
            Write-Host "batch_status.json:"
            Get-Content $statusPath -Raw
        }

        if (Test-Path $summaryPath) {
            Write-Host "batch_summary.csv first rows:"
            Import-Csv $summaryPath | Select-Object -First 10 | Format-Table -AutoSize
        }

        if (Test-Path $statusPath) {
            $status = Get-Content $statusPath -Raw | ConvertFrom-Json
            if ($status.batch_invalid_translation_collapse -eq $true) {
                Write-Host "Translation collapse detected. Stopping overnight run." -ForegroundColor Red
                break
            }
        }
    }

    Write-Host "Iteration finished: $(Get-Date)"
    Write-Host "Sleeping 60 seconds..."
    Start-Sleep -Seconds 60
}

Write-Host ""
Write-Host "DD20 overnight finished: $(Get-Date)"
Stop-Transcript
