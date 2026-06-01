@echo off
echo Restarting OMS Order Server...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_oms_services.ps1" -Restart
echo.
echo Done. You can close this window.
pause
