# Flipper Frontend (Next.js static export)

> С 2026-08 фронт **вынесен из Docker-стека Flipper**. Собирается отдельно как
> статика и деплоится независимо. Правка UI больше не требует рестарта контейнеров.

## Стек

- **Next.js 14** (App Router) + React 18
- **HeroUI 2** + Tailwind CSS
- **react-leaflet** для карты (дом + кластеры)
- `output: 'export'` → чистая статика в `./out/`, без Node.js-сервера

## Структура

```
web/next/
├── app/              # App Router (layout.tsx, page.tsx, globals.css)
├── components/       # React-компоненты (MapApp, HousePanel, …)
├── lib/              # api.ts (клиент FastAPI), useDebounce.ts
├── out/              # ← артефакт сборки (в .gitignore), готов к деплою
├── next.config.mjs   # output: 'export', trailingSlash, images.unoptimized
├── package.json
├── Dockerfile.build  # опциональный build-runner (если собираем в Docker)
├── .env.example      # шаблон для NEXT_PUBLIC_API_BASE
└── .dockerignore
```

## Локальная разработка

```bash
cd web/next
cp .env.example .env       # подкрутить NEXT_PUBLIC_API_BASE под свой бэк
npm install
npm run dev                # http://localhost:3000
```

Бэкенд должен быть поднят отдельно (Docker `api` сервис на `localhost:8001`,
или нативный FastAPI на `127.0.0.1:8000`).

## Сборка для прода

```bash
# Из корня flipper/:
./scripts/deploy_web.sh
# или на Windows:
.\scripts\deploy_web.ps1

# Внутри Docker (если хост без Node.js):
docker build -f web/next/Dockerfile.build -t flipper-web-build web/next
docker create --name wb flipper-web-build
docker cp wb:/app/out ./out
docker rm wb
```

Результат: `web/next/out/` — готов к заливке.

## Куда заливать `out/`

| Платформа | Команда |
|---|---|
| Vercel | `vercel deploy --prebuilt --prod` (из `web/next/`) |
| Cloudflare Pages | `wrangler pages deploy out --project-name flipper-web` |
| Netlify | `netlify deploy --dir=out --prod` |
| nginx (свой сервер) | `rsync -av out/ user@host:/var/www/flipper/` |
| S3 + CloudFront | `aws s3 sync out/ s3://flipper-web/ --delete` |

## Конфигурация

`NEXT_PUBLIC_API_BASE` — единственная обязательная переменная. Это URL бэка,
к которому ходит фронт. Задаётся **до сборки** (попадает в JS-бандл).

Примеры:
- `http://localhost:8001` — локальная сборка против Docker-стека
- `http://127.0.0.1:8000` — локальная сборка против нативного бэка
- `https://api.flipper.example.com` — прод, отдельный домен API
- `https://flipper.example.com` — прод, единый домен (reverse-proxy /api/* → бэк)

> ⚠️ После смены `NEXT_PUBLIC_API_BASE` нужно **пересобрать** фронт
> (`npm run build`) — это значение запекается в JS-бандл.

## CORS

FastAPI бэк (`web/server.py`) сейчас разрешает `allow_origins=["*"]`.
На проде стоит сузить до конкретного домена фронта — см. `DEPLOY.md` §12.5.

## Ограничения `output: 'export'`

- Нет серверного рендеринга. `getServerSideProps` / `cookies()` / `headers()`
  в `app/` работать не будут. Сейчас их и нет — фронт полностью клиентский,
  `MapApp` обёрнут в `dynamic(() => import(...), { ssr: false })`.
- `next/image` отключён (`images.unoptimized: true`) — оптимизатор требует сервер.
- API-запросы идут из браузера, поэтому FastAPI должен быть доступен
  снаружи контейнера (порт 8001 на хосте) или через reverse-proxy.

## Обновление фронта

```bash
cd web/next
# правим код…
npm run build
# заливаем ./out/ (см. таблицу выше)
```

Docker-стек Flipper (api, scheduler, парсеры) при этом **не трогаем**.
