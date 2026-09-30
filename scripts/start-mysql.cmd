@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "DOCKER=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe"
if exist "%DOCKER%" goto docker_found
for /f "delims=" %%I in ('where docker 2^>nul') do set "DOCKER=%%I"

:docker_found

if not exist "%DOCKER%" (
  echo [ERROR] Docker CLI was not found. Start Docker Desktop and verify docker --version.
  exit /b 1
)

cd /d "%PROJECT_ROOT%"
"%DOCKER%" compose up -d mysql
if errorlevel 1 exit /b %ERRORLEVEL%
"%DOCKER%" compose ps mysql
exit /b %ERRORLEVEL%
