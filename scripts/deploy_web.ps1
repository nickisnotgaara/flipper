# deploy_web.ps1 — собрать Next.js фронт (Flipper, 2026-08).
#
# Что делает:
#   1. Берёт NEXT_PUBLIC_API_BASE из .env (или дефолт).
#   2. npm ci (если нет node_modules) → npm run build (next export → ./out).
#   3. Подсказывает, куда залить ./out.
#
# Использование:
#   .\scripts\deploy_web.ps1                                   # дефолтный API URL
#   $env:NEXT_PUBLIC_API_BASE = "https://api.example.com"; .\scripts\deploy_web.ps1
#
# Парсинг не запускается — собирается только клиентский бандл.
$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# Перейти в корень репо (где лежит web/next/)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $RepoRoot

$WebDir = Join-Path $RepoRoot 'web/next'
if (-not (Test-Path -Path $WebDir -PathType Container)) {
    throw "Не найден каталог $WebDir. Запусти скрипт из корня flipper/."
}

# Загрузить .env из web/next, если есть (просто подтянем NEXT_PUBLIC_API_BASE).
$EnvFile = Join-Path $WebDir '.env'
if (Test-Path -Path $EnvFile -PathType Leaf) {
    Write-Host "→ Загружаю $EnvFile" -ForegroundColor DarkGray
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*#' -or [string]::IsNullOrWhiteSpace($_)) { return }
        $name, $value = $_ -split '=', 2
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -and -not (Test-Path "Env:$name")) { Set-Item "Env:$name" -Value $value }
    }
}

$ApiBase = $env:NEXT_PUBLIC_API_BASE
if (-not $ApiBase) {
    $ApiBase = 'http://localhost:8001'
    Write-Host "→ NEXT_PUBLIC_API_BASE не задан, использую дефолт: $ApiBase" -ForegroundColor Yellow
} else {
    Write-Host "→ NEXT_PUBLIC_API_BASE = $ApiBase" -ForegroundColor Green
}

Set-Location $WebDir

if (-not (Test-Path -Path 'node_modules' -PathType Container)) {
    Write-Host '→ Устанавливаю зависимости (npm ci)…' -ForegroundColor Cyan
    npm ci --no-audit --no-fund
} else {
    Write-Host '→ node_modules уже есть, пропускаю npm ci' -ForegroundColor DarkGray
}

Write-Host '→ Собираю production-бандл (next build → ./out)…' -ForegroundColor Cyan
npm run build

if (-not (Test-Path -Path 'out' -PathType Container)) {
    throw 'Сборка не создала ./out. Проверь вывод next build.'
}

$OutDir = (Resolve-Path 'out').Path
Write-Host ''
Write-Host '=================================================' -ForegroundColor Green
Write-Host '  Готово. Статика лежит в:' -ForegroundColor Green
Write-Host "  $OutDir" -ForegroundColor Green
Write-Host '=================================================' -ForegroundColor Green
Write-Host ''
Write-Host 'Варианты деплоя:' -ForegroundColor Cyan
Write-Host '  1) Vercel:           vercel deploy --prebuilt --prod'
Write-Host '  2) Cloudflare Pages:  wrangler pages deploy out --project-name flipper-web'
Write-Host '  3) Netlify:           netlify deploy --dir=out --prod'
Write-Host '  4) nginx на сервере:  rsync -av out/ user@host:/var/www/flipper/'
Write-Host '  5) S3+CloudFront:     aws s3 sync out/ s3://flipper-web --delete'
Write-Host ''
Write-Host 'Не забудь: CORS у бэка открыт, но в проде лучше заменить' -ForegroundColor Yellow
Write-Host 'allow_origins=["*"] на конкретный домен фронта (см. web/server.py).' -ForegroundColor Yellow
