@echo off
REM Launch TradingView Desktop (MSIX/winget) with CDP for MCP control.
set PORT=%1
if "%PORT%"=="" set PORT=9222

taskkill /F /IM TradingView.exe >nul 2>&1
timeout /t 2 /nobreak >nul

for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "(Get-AppxPackage -Name 'TradingView.Desktop' -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.InstallLocation 'TradingView.exe' })"`) do set "TV_EXE=%%i"

if "%TV_EXE%"=="" (
    echo TradingView Desktop not found. Install: winget install TradingView.TradingViewDesktop
    exit /b 1
)

echo Starting: %TV_EXE%
start "" "%TV_EXE%" --remote-debugging-port=%PORT%

echo Waiting for CDP on port %PORT%...
:wait
powershell -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/json/version' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 2 /nobreak >nul
    goto wait
)

echo CDP ready at http://127.0.0.1:%PORT%
powershell -NoProfile -Command "Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT%/json/version' | ConvertTo-Json -Compress"
