param(
    [switch]$UseFakeEngine,
    [int]$RestartDelaySeconds = 5
)

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $scriptDir)
$backend = Join-Path $repo "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$varDir = Join-Path $backend "var"
$logDir = Join-Path $varDir "logs"
$pidFile = Join-Path $varDir "celery-supervisor.pid"
$workerLog = Join-Path $logDir "celery-worker.log"
$workerErr = Join-Path $logDir "celery-worker.err.log"
$beatLog = Join-Path $logDir "celery-beat.log"
$beatErr = Join-Path $logDir "celery-beat.err.log"

New-Item -ItemType Directory -Force -Path $varDir, $logDir | Out-Null

if (-not (Test-Path $python)) {
    throw "python executable not found: $python"
}

# 已有 supervisor 时不重复拉起，避免两个 beat 同时投递。
if (Test-Path $pidFile) {
    $oldPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($oldPid -match '^[0-9]+$') {
        $old = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue
        if ($old) {
            $oldCmd = [string]$old.CommandLine
            if ($oldCmd.Contains("worker-supervisor.ps1")) {
                Write-Output "supervisor already running: pid=$oldPid"
                exit 0
            }
        }
    }
}

Set-Content -Path $pidFile -Value $PID
$env:PYTHONUNBUFFERED = "1"
if ($UseFakeEngine) {
    $env:MONITORING_FAKE_ENGINE_ENABLED = "true"
}

function Start-CeleryWorker {
    $workerArgs = @("-m", "celery", "-A", "app.worker.celery_app", "worker", "--pool=solo", "--loglevel=info")
    Start-Process -FilePath $python -ArgumentList $workerArgs -WorkingDirectory $backend `
        -RedirectStandardOutput $workerLog -RedirectStandardError $workerErr `
        -WindowStyle Hidden -PassThru
}

function Start-CeleryBeat {
    $beatArgs = @("-m", "celery", "-A", "app.worker.celery_app", "beat", "--loglevel=info")
    Start-Process -FilePath $python -ArgumentList $beatArgs -WorkingDirectory $backend `
        -RedirectStandardOutput $beatLog -RedirectStandardError $beatErr `
        -WindowStyle Hidden -PassThru
}

$worker = $null
$beat = $null

try {
    $worker = Start-CeleryWorker
    Start-Sleep -Seconds 3
    $beat = Start-CeleryBeat
    Write-Output "supervisor started: pid=$PID worker=$($worker.Id) beat=$($beat.Id) fake=$UseFakeEngine"

    while ($true) {
        if ($worker.HasExited) {
            Write-Output "worker exited code=$($worker.ExitCode); restarting in $RestartDelaySeconds s"
            Start-Sleep -Seconds $RestartDelaySeconds
            $worker = Start-CeleryWorker
        }
        if ($beat.HasExited) {
            Write-Output "beat exited code=$($beat.ExitCode); restarting in $RestartDelaySeconds s"
            Start-Sleep -Seconds $RestartDelaySeconds
            $beat = Start-CeleryBeat
        }
        Start-Sleep -Seconds 5
    }
}
finally {
    foreach ($proc in @($worker, $beat)) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
