param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$candidates = @(
    (Join-Path $projectRoot 'backend\.venv\python.exe'),
    (Join-Path $projectRoot 'backend\.venv\Scripts\python.exe')
)
$python = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $python) {
    throw '未找到 backend/.venv 中的 Python。请先按 README 创建 Python 3.12 环境。'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
    throw '未找到项目根目录 .env。请复制 .env.example 并填写真实阿里云配置。'
}

Push-Location (Join-Path $projectRoot 'backend')
try {
    Write-Host '[INFO] 首次启动前请确认 MySQL healthy，并运行 scripts\migrate-and-seed.cmd。'
    & $python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port
    $commandExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $commandExitCode
