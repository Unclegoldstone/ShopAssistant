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
  echo [ERROR] .env was not found. Copy .env.example to .env and fill in the Alibaba Cloud settings.
  exit /b 1
)

cd /d "%PROJECT_ROOT%\backend"
echo [INFO] Ensure MySQL is healthy and run scripts\migrate-and-seed.cmd before first start.
"%PYTHON%" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
exit /b %ERRORLEVEL%
