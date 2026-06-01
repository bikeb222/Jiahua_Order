param(
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$mobileFrontendDir = Join-Path $root "frontend-mobile"
$logDir = Join-Path $root "logs"

if (!(Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

function Get-ListenerProcessId {
    param([int]$Port)
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        return [int]$listener.OwningProcess
    }
    return $null
}

function Stop-PortListener {
    param([int]$Port)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Start-Backend {
    $out = Join-Path $logDir "backend.out.log"
    $err = Join-Path $logDir "backend.err.log"
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $backendDir "run_backend.ps1")) `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -PassThru
    $process.Id | Set-Content -Path (Join-Path $backendDir ".server.pid")
}

function Start-Frontend {
    $out = Join-Path $logDir "frontend.out.log"
    $err = Join-Path $logDir "frontend.err.log"
    $process = Start-Process `
        -FilePath "python.exe" `
        -ArgumentList @((Join-Path $frontendDir "dev_server.py")) `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -PassThru
    $process.Id | Set-Content -Path (Join-Path $frontendDir ".server.pid")
}

function Start-MobileFrontend {
    $out = Join-Path $logDir "frontend-mobile.out.log"
    $err = Join-Path $logDir "frontend-mobile.err.log"
    $process = Start-Process `
        -FilePath "python.exe" `
        -ArgumentList @((Join-Path $mobileFrontendDir "dev_server.py")) `
        -WorkingDirectory $mobileFrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -PassThru
    $process.Id | Set-Content -Path (Join-Path $mobileFrontendDir ".server.pid")
}

if ($Restart) {
    Stop-PortListener -Port 5173
    Stop-PortListener -Port 5174
    Stop-PortListener -Port 8008
    Start-Sleep -Seconds 1
}

if (!(Get-ListenerProcessId -Port 8008)) {
    Start-Backend
}

if (!(Get-ListenerProcessId -Port 5173)) {
    Start-Frontend
}

if ((Test-Path $mobileFrontendDir) -and !(Get-ListenerProcessId -Port 5174)) {
    Start-MobileFrontend
}

Start-Sleep -Seconds 8

$backendPid = Get-ListenerProcessId -Port 8008
$frontendPid = Get-ListenerProcessId -Port 5173
$mobileFrontendPid = Get-ListenerProcessId -Port 5174

if (!$backendPid) {
    throw "OMS backend is not listening on port 8008."
}

if (!$frontendPid) {
    throw "OMS frontend is not listening on port 5173."
}

if ((Test-Path $mobileFrontendDir) -and !$mobileFrontendPid) {
    throw "OMS mobile frontend is not listening on port 5174."
}

Write-Host "OMS backend listening on port 8008, PID $backendPid"
Write-Host "OMS frontend listening on port 5173, PID $frontendPid"
if ($mobileFrontendPid) {
    Write-Host "OMS mobile frontend listening on port 5174, PID $mobileFrontendPid"
}
