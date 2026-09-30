@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON=%PROJECT_ROOT%\backend\.venv\python.exe"
if not exist "%PYTHON%" set "PYTHON=%PROJECT_ROOT%\backend\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo [ERROR] Python was not found in backend\.venv. Create the Python 3.12 environment first.
  exit /b 1
)

if not exist "%PROJECT_ROOT%\.env" (
  echo [ERROR] .env was not found. Copy .env.example to .env and fill in the settings.
  exit /b 1
)

cd /d "%PROJECT_ROOT%\backend"
"%PYTHON%" -m alembic -c alembic.ini upgrade head
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON%" -m scripts.seed_demo_data
exit /b %ERRORLEVEL%
