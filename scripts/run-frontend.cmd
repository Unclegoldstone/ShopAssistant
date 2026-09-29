@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
if not exist "%PROJECT_ROOT%\frontend\node_modules" (
  echo [ERROR] frontend\node_modules was not found. Run: npm --prefix frontend install
  exit /b 1
)

cd /d "%PROJECT_ROOT%\frontend"
npm run dev -- --host 127.0.0.1 --port 5173
exit /b %ERRORLEVEL%

