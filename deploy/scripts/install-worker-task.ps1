param(
    [switch]$UseFakeEngine
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $scriptDir)
$supervisor = Join-Path $scriptDir "worker-supervisor.ps1"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$valueName = "GEO-Celery-Supervisor"

if (-not (Test-Path $supervisor)) {
    throw "supervisor script not found: $supervisor"
}

$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$supervisor`""
if ($UseFakeEngine) { $arguments += " -UseFakeEngine" }
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $powershell)) {
    throw "powershell executable not found: $powershell"
}
$command = "`"$powershell`" $arguments"

New-Item -Path $runKey -Force | Out-Null
New-ItemProperty -Path $runKey -Name $valueName -Value $command -PropertyType String -Force | Out-Null
Write-Output "registered per-user logon entry: $valueName"
Get-ItemProperty -Path $runKey -Name $valueName | Select-Object -ExpandProperty $valueName