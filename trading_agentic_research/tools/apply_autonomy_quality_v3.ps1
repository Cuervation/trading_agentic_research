param([string]$RepoRoot = ".")
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PackageRoot = Split-Path -Parent $ScriptDir
Push-Location $RepoRoot
try {
  python "$PackageRoot\tools\apply_autonomy_quality_v3.py" --repo-root "." --package-root "$PackageRoot"
} finally {
  Pop-Location
}
