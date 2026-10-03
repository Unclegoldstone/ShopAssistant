@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHON=%PROJECT_ROOT%\backend\.venv\python.exe"
if not exist "%PYTHON%" set "PYTHON=%PROJECT_ROOT%\backend\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo [ERROR] Python was not found in backend\.venv.
  exit /b 1
)

if not exist "%PROJECT_ROOT%\.env" (
  echo [ERROR] .env was not found.
  exit /b 1
)

cd /d "%PROJECT_ROOT%\backend"
"%PYTHON%" -m scripts.build_knowledge all
exit /b %ERRORLEVEL%
