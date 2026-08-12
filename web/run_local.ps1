# web/run_local.ps1
# Запуск web/server.py на Windows для разработки.
#
# Использование:
#   pwsh -File web\run_local.ps1
#   pwsh -File web\run_local.ps1 -Port 8001 -Reload
#
# Что делает:
# 1. Устанавливает DATABASE_URL с 127.0.0.1 (по умолчанию код ожидает
#    Docker-hostname `app_postgres`, который не резолвится на Windows).
# 2. Запускает uvicorn с авто-reload.
# 3. Слушает на 0.0.0.0 чтобы работало из браузера.
#
# Требования:
#   * Docker Desktop запущен, контейнер `app_postgres` жив
#   * `py -3.11` (или `python`) с установленными requirements
#
# Проверка: curl http://127.0.0.1:<port>/api/stats

[CmdletBinding()]
param(
    [int]$Port = 8001,
    [switch]$Reload,
    [string]$DbHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot) | Split-Path -Parent

# На Windows Postgres опубликован на 127.0.0.1:5432 (см. docker-compose.yml: ports 5432:5432)
$env:DATABASE_URL = "postgresql+asyncpg://flipper:flipper_secret@${DbHost}:5432/flipper"
$env:PYTHONPATH = (Get-Location).Path

Write-Host "[run_local] DATABASE_URL=$env:DATABASE_URL" -ForegroundColor Cyan
Write-Host "[run_local] Listening on 0.0.0.0:$Port" -ForegroundColor Cyan

$reloadFlag = ""
if ($Reload) { $reloadFlag = "--reload" }

$cmd = "py -3.11 -m uvicorn web.server:app --host 0.0.0.0 --port $Port $reloadFlag"
Write-Host "[run_local] Running: $cmd" -ForegroundColor Yellow
Invoke-Expression $cmd
