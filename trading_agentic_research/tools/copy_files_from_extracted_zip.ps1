Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Uso recomendado:
# 1) Extraer el ZIP en una carpeta temporal.
# 2) Desde el root del repo, ejecutar este script indicando la carpeta extraida:
#    powershell -ExecutionPolicy Bypass -File .\tools\copy_files_from_extracted_zip.ps1 -ExtractedFixRoot "C:\ruta\cooldown_contract_fix_ready"

param(
  [Parameter(Mandatory=$true)]
  [string]$ExtractedFixRoot
)

$repoRoot = (Get-Location).Path
$srcRunBatch = Join-Path $ExtractedFixRoot "scripts\run_research_batch.py"
$srcCooldown = Join-Path $ExtractedFixRoot "scripts\research\cooldown_governance.py"
$dstRunBatch = Join-Path $repoRoot "scripts\run_research_batch.py"
$dstCooldown = Join-Path $repoRoot "scripts\research\cooldown_governance.py"

if (!(Test-Path $srcRunBatch)) { throw "Missing source file: $srcRunBatch" }
if (!(Test-Path $srcCooldown)) { throw "Missing source file: $srcCooldown" }
if (!(Test-Path $dstRunBatch)) { throw "Missing destination file: $dstRunBatch. Are you in the repo root?" }
if (!(Test-Path $dstCooldown)) { throw "Missing destination file: $dstCooldown. Are you in the repo root?" }

Copy-Item $srcRunBatch $dstRunBatch -Force
Copy-Item $srcCooldown $dstCooldown -Force

Write-Host "Copied:" -ForegroundColor Green
Write-Host "- $dstRunBatch"
Write-Host "- $dstCooldown"
