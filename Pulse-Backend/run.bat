@echo off
setlocal
cd /d "%~dp0"
set "PY=%LocalAppData%\Programs\Python\Python314\python.exe"
if exist "%PY%" goto havepython
where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (
  echo Python was not found. Expected: %PY%
  echo Install Python or add it to PATH, then run this file again.
  pause
  exit /b 1
)
:havepython
if not exist ".venv\Scripts\python.exe" (
  echo Creating Pulse backend virtual environment...
  "%PY%" -m venv .venv || goto fail
)
set "PY=.venv\Scripts\python.exe"
echo Installing/updating Pulse backend dependencies...
"%PY%" -m pip install -r requirements.txt || goto fail
echo.
echo Starting Pulse API on http://192.168.1.4:8000 (LAN) / http://127.0.0.1:8000 (this PC)
"%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
exit /b %errorlevel%
:fail
echo.
echo Pulse backend failed to start. The window will stay open so you can read the error.
pause
exit /b 1
