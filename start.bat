@echo off
setlocal
set "ROOT=%~dp0"

echo ============================================================
echo TradeSathi AI - Start
echo Project: %ROOT%
echo ============================================================

if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
    echo [ERROR] Backend virtual environment was not found:
    echo         %ROOT%backend\.venv\Scripts\python.exe
    echo Check that backend\.venv exists.
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\package.json" (
    echo [ERROR] Frontend package.json was not found:
    echo         %ROOT%frontend\package.json
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\node_modules" (
    echo [WARNING] frontend\node_modules is missing.
    echo Run "npm install" in the frontend folder before starting.
    pause
    exit /b 1
)

echo Starting backend at http://127.0.0.1:8000 ...
start "TradeSathi Backend" cmd /k "title TradeSathi Backend && cd /d ""%ROOT%"" && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --app-dir ""%ROOT%backend"" --host 127.0.0.1 --port 8000"

timeout /t 2 /nobreak >nul

echo Starting frontend (Vite) ...
start "TradeSathi Frontend" cmd /k "title TradeSathi Frontend && cd /d ""%ROOT%frontend"" && npm.cmd run dev -- --host 127.0.0.1"

echo.
echo Startup commands launched in separate windows.
echo Backend:  http://127.0.0.1:8000
echo API docs: http://127.0.0.1:8000/docs
echo Frontend: check the Vite URL shown in the frontend window,
echo           commonly http://127.0.0.1:5173
echo.
echo This script does not reset or modify the database or documents.
echo To stop these windows, run stop.bat from the same folder.
echo.
pause
endlocal
