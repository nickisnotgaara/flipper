# Запуск проекта (dev mode)

Полное руководство для запуска Flipper в режиме разработки на Windows.
Режим dev = Docker-инфраструктура + нативный API/фронт с hot-reload.

---

## 0. Что нужно установить (один раз)

| Инструмент | Версия | Зачем | Где взять |
|---|---|---|---|
| Docker Desktop | latest | Все инфра-сервисы (PG, redis, cookie, firecrawl) | https://www.docker.com/products/docker-desktop/ |
| Python | 3.11+ | API/парсеры/тесты локально | https://www.python.org/downloads/ |
| Node.js | 18+ | Next.js фронтенд | https://nodejs.org/ |
| PostgreSQL client (опц.) | 16+ | `psql` для ad-hoc запросов к БД | https://www.postgresql.org/download/ |

Проверка:
```bash
docker --version          # Docker version 24+
py --version              # Python 3.11+
node --version            # v18+
```

---

## 1. Структура .env

`.env` (в корне `flipper/`) — единственный источник истины для всех сервисов.
Главное правило: **все сервисы ходят в `app_postgres`** (Docker-контейнер), не
в нативный PostgreSQL на хосте.

```env
# БД — единая для всех сервисов (api, парсеры, scheduler, pipeline)
DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper
POSTGRES_PASSWORD=flipper_secret

# Firecrawl (self-hosted, отдельный docker-compose)
FIRECRAWL_API_KEY=local
FIRECRAWL_BASE_URL=http://flippercrawl-api-1:3002

# Google Sheets (для cian_active)
SPREADSHEET_ID=your-spreadsheet-id
CREDENTIALS_PATH=/app/credentials.json

# Telegram (уведомления)
TG_BOT_TOKEN=your-telegram-bot-token
TG_CHAT_ID=your-telegram-chat-id

# CORS для API (dev = * , prod = домен фронта)
CORS_ORIGINS=*
```

Полный список переменных — в `.env.example`. Скопировать и заполнить:
```bash
cp .env.example .env
# отредактировать: SPREADSHEET_ID, TG_BOT_TOKEN, TG_CHAT_ID
```

Для фронтенда — отдельный `.env.local` в `web/next/`:
```bash
# web/next/.env.local
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

---

## 2. Порты (шпаргалка)

| Порт | Сервис | Проект | Доступ |
|---|---|---|---|
| **3000** | Next.js dev | flipper (натив) | http://localhost:3000 |
| **3002** | Firecrawl API | flippercrawl (Docker) | http://localhost:3002 |
| **5432** | PostgreSQL | flipper (Docker `app_postgres`) | localhost:5432 |
| **6379** | Redis | flipper (Docker `app_redis`) | localhost:6379 |
| **8000** | Cookie Manager | flipper (Docker) | http://localhost:8000 |
| **8001** | FastAPI API | flipper (Docker `api-dev`) | http://localhost:8001 |
| **8090** | HTML → Markdown | flipper (Docker) | http://localhost:8090 |

Конфликты портов: если порт занят — измените в `docker-compose.yml` (левая часть `8001:8000`).

---

## 3. Запуск (пошагово)

### 3.1. Запустить Docker Desktop

```bash
# Windows: запустить Docker Desktop через Start Menu, или:
powershell.exe -Command "Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'"
# подождать ~30-60 сек пока daemon поднимется
docker ps   # проверка — должен вывести заголовок таблицы без ошибок
```

### 3.2. Поднять инфраструктуру (Docker)

В корне `flipper/`:

```bash
# Поднимает: app_postgres, app_redis, html_to_markdown, cookie_manager
docker compose up -d app_postgres app_redis html_to_markdown cookie_manager
```

Проверить что все healthy:
```bash
docker compose ps
# Ожидаемо:
#   app_postgres       running (healthy)
#   app_redis          running (healthy)
#   html_to_markdown   running (healthy)
#   cookie_manager     running (healthy)   # start_period 180s — подождать
```

### 3.3. Поднять Firecrawl (отдельный docker-compose)

Firecrawl живёт в `../flippercrawl/` — отдельный compose, общая сеть `firecrawl_backend`.

```bash
cd ../flippercrawl
docker compose up -d
cd ../flipper
```

Проверить:
```bash
curl http://localhost:3002/    # должен ответить (200 OK)
```

Если сети `firecrawl_backend` нет — Firecrawl создаст её автоматически при первом запуске.

### 3.4. Поднять API (Docker, hot-reload)

API живёт в Docker (`api-dev` профиль) с volume-монтированием исходников —
правки в `web/server.py` подхватываются uvicorn `--reload` мгновенно.

```bash
docker compose --profile dev up -d --build api-dev
```

Проверить:
```bash
docker logs flipper_api_dev --tail 10
# должно: "Uvicorn running on http://0.0.0.0:8000"
#         "Application startup complete."

curl http://localhost:8001/api/stats
# JSON с houses: 187696, active_total: 3393, ...
```

> **Почему api в Docker, а не нативно?** API импортирует `packages/flipper_db`
> который тянет `sqlalchemy[asyncio]`, `asyncpg`, `numpy`, `scipy`. Проще держать
> всё в Docker-образе, чем ставить Python-зависимости на хост. Volume-mount
> даёт hot-reload — разницы с нативным `uvicorn --reload` нет.

### 3.5. Поднять фронтенд (нативно, hot-reload)

Next.js запускается нативно (быстрее, чем в Docker, и правки мгновенны):

```bash
cd web/next
npm install        # один раз (если node_modules отсутствует)
npm run dev        # http://localhost:3000
```

Проверить:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
# 200
```

Открыть в браузере: **http://localhost:3000** — карта должна работать.

### 3.6. Проверить данные в БД (опц.)

```bash
# Сколько домов / объявлений
docker exec app_postgres psql -U flipper -d flipper -c "
  SELECT 'houses' AS t, COUNT(*) FROM houses
  UNION ALL SELECT 'active_ads', COUNT(*) FROM active_ads
  UNION ALL SELECT 'sold_ads', COUNT(*) FROM sold_ads;
"

# По источникам
docker exec app_postgres psql -U flipper -d flipper -c "
  SELECT source, COUNT(*) FROM houses GROUP BY source ORDER BY source;
  SELECT source, COUNT(*) FROM sold_ads GROUP BY source ORDER BY source;
"
```

Ожидаемо (после полной миграции):
- `houses`: ~187k (cian_sold 34k, domclick 2k, flatinfo 41k, winners 110k)
- `active_ads`: ~3.4k (cian_active)
- `sold_ads`: ~231k (cian_deactivated 231k)

---

## 4. Быстрый старт (всё одной пачкой)

Если всё уже настроено (`.env` заполнен, `npm install` сделан, образы собраны):

```bash
# 1. Docker Desktop запущен
# 2. Поднять инфраструктуру + firecrawl + api-dev:
cd flipper
docker compose up -d app_postgres app_redis html_to_markdown cookie_manager
cd ../flippercrawl && docker compose up -d && cd ../flipper
docker compose --profile dev up -d api-dev

# 3. Фронт (в отдельном терминале):
cd web/next && npm run dev
```

Открыть http://localhost:3000 — готово.

---

## 5. Ручной запуск парсеров (dev)

Парсеры запускаются как одноразовые контейнеры через compose:

```bash
# Активные CIAN (через Firecrawl + Google Sheets) — основной парсер
docker compose run --rm cian_active --mode offers
docker compose run --rm cian_active --mode avans

# Снятые CIAN (тяжёлый, часы) — по запросу
docker compose run --rm cian_sold

# Еженедельные (обычно scheduler запускает сам, но можно вручную)
docker compose run --rm winners_sold
docker compose run --rm domclick_sold

# Реестр домов flatinfo — по запросу
docker compose run --rm flatinfo_houses

# Подсчёт категорий CIAN (вкладка Balans в Google Sheets)
docker compose run --rm category_counter

# Daily pipeline (re-fetch активных объявлений через flippercrawl)
docker compose run --rm pipeline_runner
```

Логи парсера:
```bash
docker compose logs cian_active
# или:
docker exec app_postgres cat /dev/null  # no-op
tail -f data/logs/cian_active.log       # на хосте (монтировано через volume)
```

---

## 6. Запуск тестов

```bash
cd flipper

# Все тесты (pytest читает config из pyproject.toml)
py -m pytest -v

# Только DB-пакет
py -m pytest packages/flipper_db/tests/ -v

# Только парсеры
py -m pytest services/parsers/ -v --continue-on-collection-errors

# Один тест
py -m pytest services/parsers/cian_active/tests/test_importer.py -v
```

Покрытие: **111+ тестов** в `packages/flipper_db/tests/`, `services/parsers/`,
`scripts/tests/`. Тесты используют SQLite in-memory (не трогают PostgreSQL).

---

## 7. Линтинг (ruff)

```bash
py -m ruff check .              # показать проблемы
py -m ruff check --fix .        # авто-фикс (Optional→X|Y, unused imports)
py -m ruff format .             # форматирование
```

Config — в `pyproject.toml` `[tool.ruff]`. Excludes: `archive/`, `services/parser_cian/`, `data/`.

---

## 8. Миграции схемы (Alembic)

Alembic настроен, но **ещё не применён** к существующей БД (структура создана,
baseline не застампован). См. `alembic/README.md` для деталей.

Когда нужно применить миграцию:
```bash
# Внутри Docker (api-образ содержит alembic + psycopg):
docker compose run --rm api alembic upgrade head

# Сгенерировать миграцию из изменений моделей:
docker compose run --rm api alembic revision --autogenerate -m "add X to houses"
```

One-time adoption на существующей БД:
```bash
docker compose run --rm api alembic stamp head   # пометить текущую схему как baseline
```

---

## 9. Типовые проблемы (troubleshooting)

### Docker не отвечает
```bash
docker ps
# error during connect... → Docker Desktop не запущен.
# Запустить Docker Desktop, подождать 30-60 сек.
```

### app_postgres не healthy
```bash
docker compose logs app_postgres
# Если "port 5432 already in use" — на хосте запущен нативный PostgreSQL.
# Остановить его:  Stop-Service postgresql-x64-18  (PowerShell admin)
# Или сменить порт в docker-compose.yml:  "5433:5432"
```

### api-dev не стартует
```bash
docker compose --profile dev logs api-dev
# Частые причины:
#   - app_postgres не healthy → дождаться
#   - .env не заполнен (DATABASE_URL пустой)
#   - образ не пересобран после изменения requirements.txt:
#       docker compose --profile dev up -d --build api-dev
```

### Фронт не подключается к API
```bash
# Проверить .env.local:
cat web/next/.env.local
# NEXT_PUBLIC_API_BASE=http://localhost:8001  ← должен быть

# Проверить API:
curl http://localhost:8001/api/stats
# Должен вернуть JSON. Если 502 — api-dev упал, смотреть логи.
```

### Cookie Manager долго стартует (180 сек)
Это нормально — `start_period: 180s` в compose. Cookie Manager поднимает
Chromium + NoVNC, это медленно. Дождаться статуса `healthy`.

### Firecrawl не отвечает
```bash
cd ../flippercrawl && docker compose ps
# Все сервисы должны быть Up:
#   flippercrawl-api-1, flippercrawl-redis-1, flippercrawl-rabbitmq-1,
#   flippercrawl-nuq-postgres-1

curl http://localhost:3002/   # 200 OK
```

### Порт занят
```bash
# Кто слушает порт 8001:
netstat -ano | findstr :8001      # Windows
# Или изменить порт в docker-compose.yml:  "8002:8000"
```

### Парсер не видит данные в БД
Парсеры пишут в `app_postgres` (Docker). API тоже читает `app_postgres`.
Если данные "разные" — значит кто-то ходит в нативный PG. Проверить:
```bash
docker compose run --rm cian_active env | grep DATABASE_URL
# Должно быть: ...@app_postgres:5432/...
# Если @host.docker.internal или @127.0.0.1 — это баг, поправить .env.
```

---

## 10. Остановка

```bash
# Остановить всё Flipper:
cd flipper
docker compose down                    # инфра + api-dev
# Не удаляет тома — данные БД сохраняются (pgdata volume).

# Остановить Firecrawl:
cd ../flippercrawl && docker compose down

# Остановить фронт: Ctrl+C в терминале `npm run dev`

# Полная очистка (ОСТОРОЖНО — удалит БД):
# docker compose down -v               # удаляет тома (pgdata)
```

---

## 11. Режимы: dev vs prod

| | Dev (Windows) | Prod (Linux VPS) |
|---|---|---|
| Инфра | Docker | Docker |
| API | Docker `api-dev` (uvicorn --reload, volume-mount) | Docker `api` (gunicorn, без reload) |
| Фронт | Натив `npm run dev` (hot-reload) | Статика `npm run build` → Vercel/nginx |
| БД | `app_postgres` (Docker, порт 5432 наружу) | `app_postgres` (Docker, только внутренний) |
| Scheduler | (обычно не запускают в dev) | Docker `scheduler` (always-on) |
| Парсеры | `docker compose run --rm <name>` | Scheduler запускает по cron |

Подробнее про prod — в [DEPLOY.md](DEPLOY.md).

---

## 12. Архитектура (краткая)

```
┌──────────────────────────────────────────────────────────────────┐
│  flipper/ (docker-compose.yml)                                   │
│                                                                  │
│  Инфра (always-on):                                              │
│    app_postgres :5432   ← ЕДИНАЯ БД для всех                     │
│    app_redis    :6379   ← для cookie_manager                     │
│    html_to_markdown :8090                                        │
│    cookie_manager :8000                                          │
│                                                                  │
│  API (dev):                                                      │
│    api-dev  :8001  ← FastAPI (uvicorn --reload, volume-mount)    │
│                  ← web/server.py → packages/flipper_db           │
│                                                                  │
│  Парсеры (manual, profiles: [manual]):                           │
│    cian_active, cian_sold, winners_sold,                         │
│    domclick_sold, flatinfo_houses, category_counter              │
│                                                                  │
│  Scheduler (prod-only):                                          │
│    scheduler  ← APScheduler, запускает парсеры по cron           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                          ↕
┌──────────────────────────────────────────────────────────────────┐
│  flippercrawl/ (отдельный docker-compose, сеть firecrawl_backend)│
│    flippercrawl-api-1 :3002   ← self-hosted Firecrawl            │
│    flippercrawl-redis-1       ← кэш Firecrawl                    │
│    flippercrawl-rabbitmq-1    ← очередь Firecrawl                │
│    flippercrawl-nuq-postgres-1 ← БД Firecrawl (отдельная)         │
└──────────────────────────────────────────────────────────────────┘
                          ↕
┌──────────────────────────────────────────────────────────────────┐
│  web/next/ (нативно в dev)                                       │
│    Next.js dev server :3000                                      │
│    NEXT_PUBLIC_API_BASE=http://localhost:8001                    │
│    → ходит в api-dev (Docker)                                    │
└──────────────────────────────────────────────────────────────────┘
```

Все сервисы ходят в **один** `app_postgres` через единый `DATABASE_URL` в `.env`.
Native PostgreSQL на хосте **не используется**.

---

## См. также

- [SYSTEM.md](SYSTEM.md) — детальная архитектура, таблицы БД, расписание
- [DEPLOY.md](DEPLOY.md) — развёртывание на Linux VPS (prod)
- [.env.example](.env.example) — полный список переменных окружения
- [alembic/README.md](alembic/README.md) — миграции схемы (Alembic)
- [PLAN.md](../PLAN.md) — история решений по реструктуризации