param(
    [int]$Port = 5173
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot 'frontend'

if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules'))) {
    throw '未找到 frontend/node_modules。请先在 frontend 目录运行 npm install。'
}

Push-Location $frontendRoot
try {
    npm run dev -- --host 127.0.0.1 --port $Port
    $commandExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $commandExitCode

