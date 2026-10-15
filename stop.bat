@echo off
setlocal
echo ============================================================
echo TradeSathi AI - Stop
echo ============================================================
echo Stopping only the TradeSathi windows launched with start.bat...
echo.

taskkill /FI "WINDOWTITLE eq TradeSathi Backend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] TradeSathi Backend window was not found or already stopped.
) else (
    echo [OK] Backend window and its child processes stopped.
)

taskkill /FI "WINDOWTITLE eq TradeSathi Frontend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo [INFO] TradeSathi Frontend window was not found or already stopped.
) else (
    echo [OK] Frontend window and its child processes stopped.
)

echo.
echo Done. This does not intentionally stop unrelated Python or Node processes.
echo It will not delete or change the SQLite database or document storage.
echo Note: processes started manually or with a different window title may remain running.
echo.
pause
endlocal
