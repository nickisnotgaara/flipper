#!/usr/bin/env bash
# deploy_web.sh — собрать Next.js фронт (Flipper, 2026-08).
#
# Что делает:
#   1. Берёт NEXT_PUBLIC_API_BASE из .env (или дефолт).
#   2. npm ci (если нет node_modules) → npm run build (next export → ./out).
#   3. Подсказывает, куда залить ./out.
#
# Использование:
#   ./scripts/deploy_web.sh
#   NEXT_PUBLIC_API_BASE=https://api.example.com ./scripts/deploy_web.sh
#
# Парсинг не запускается — собирается только клиентский бандл.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

WEB_DIR="$REPO_ROOT/web/next"
if [ ! -d "$WEB_DIR" ]; then
  echo "Не найден $WEB_DIR. Запусти скрипт из корня flipper/." >&2
  exit 1
fi

# Подтянуть .env из web/next (без перезаписи уже заданных переменных).
if [ -f "$WEB_DIR/.env" ]; then
  echo "→ Загружаю $WEB_DIR/.env"
  set -a
  # shellcheck disable=SC1090,SC1091
  . "$WEB_DIR/.env"
  set +a
fi

API_BASE="${NEXT_PUBLIC_API_BASE:-http://localhost:8001}"
echo "→ NEXT_PUBLIC_API_BASE = $API_BASE"

cd "$WEB_DIR"

if [ ! -d node_modules ]; then
  echo "→ Устанавливаю зависимости (npm ci)…"
  npm ci --no-audit --no-fund
else
  echo "→ node_modules уже есть, пропускаю npm ci"
fi

echo "→ Собираю production-бандл (next build → ./out)…"
npm run build

if [ ! -d out ]; then
  echo "Сборка не создала ./out. Проверь вывод next build." >&2
  exit 1
fi

OUT_DIR="$(cd out && pwd)"
cat <<EOF

=================================================
  Готово. Статика лежит в:
  $OUT_DIR
=================================================

Варианты деплоя:
  1) Vercel:           vercel deploy --prebuilt --prod
  2) Cloudflare Pages:  wrangler pages deploy out --project-name flipper-web
  3) Netlify:           netlify deploy --dir=out --prod
  4) nginx на сервере:  rsync -av out/ user@host:/var/www/flipper/
  5) S3+CloudFront:     aws s3 sync out/ s3://flipper-web --delete

Не забудь: CORS у бэка открыт, но в проде лучше заменить
allow_origins=["*"] на конкретный домен фронта (см. web/server.py).
EOF
