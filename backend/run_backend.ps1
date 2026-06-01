$ErrorActionPreference = "Stop"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path $venvPython)) {
    Write-Host "Creating backend virtual environment..."
    python -m venv (Join-Path $PSScriptRoot ".venv")
}

& $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
& $venvPython -m uvicorn app.main:app --app-dir "$PSScriptRoot" --host 0.0.0.0 --port 8008
