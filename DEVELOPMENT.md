# Запуск проекта (dev mode)

Полное руководство для запуска Flipper в режиме разработки на Windows.
Режим dev = **нативный PostgreSQL** + нативный API/фронт + Docker для
вспомогательных сервисов (Flippercrawl, cookie manager, html_to_markdown).

> **TL;DR (для себя):**
> 1. Локальный PostgreSQL на `127.0.0.1:5432` уже поднят, база `flipper` создана,
>    в ней лежат актуальные данные (5227 active_ads, 30 868 houses).
> 2. `.env` указывает на `127.0.0.1:5432` — **не** на `app_postgres:5432`.
> 3. Запуск API и фронта — нативно, без Docker, через `_run_api.cmd` + `npm run dev`.

---

## 0. Что нужно установить (один раз)

| Инструмент | Версия | Зачем | Где взять |
|---|---|---|---|
| **PostgreSQL 18** | 18+ | **Локальная БД проекта (source of truth)** | https://www.postgresql.org/download/windows/ |
| **Python** | 3.11+ | API/парсеры/тесты локально | https://www.python.org/downloads/ |
| **Node.js** | 18+ | Next.js фронтенд | https://nodejs.org/ |
| Docker Desktop | latest | Только для Flippercrawl + cookie manager + html_to_markdown (опц.) | https://www.docker.com/products/docker-desktop/ |
| PostgreSQL client (опц.) | 16+ | `psql` для ad-hoc запросов к БД | https://www.postgresql.org/download/ |

Проверка:
```bash
psql --version           # PostgreSQL 18+
py --version             # Python 3.11+
node --version           # v18+
docker --version         # Docker version 24+ (опц., только для Flippercrawl)
```

---

## 1. База данных

**В dev-режиме БД = локальный PostgreSQL на `127.0.0.1:5432`**, а не Docker-контейнер.
Это решение принято осознанно: миграция + reparse писали напрямую в Windows-native
PostgreSQL 18, и теперь Docker-`app_postgres` с старыми/сырыми данными не синхронизирован.

### Что в БД (актуальные цифры)

- **active_ads**: 5 227 (все `cian_active`), 92.6% с `house_id`
- **houses**: 30 868, 96.3% с координатами, 99.4% с непустым адресом
- **sold_ads**: 233 314 (cian_deactivated/domclick_sold/cian_active)
- **Источники домов**: `cian_ad` 759, `cian_sold` 1 149, `domclick_sold` 578, `flatinfo` 28 382

### Структура

Один пользователь `flipper`, одна база `flipper`, пароль `flipper_secret`.
В `.env`:
```env
DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
POSTGRES_PASSWORD=flipper_secret
```

### Проверка подключения

```bash
# psql напрямую
psql -h 127.0.0.1 -U flipper -d flipper -c "SELECT COUNT(*) FROM active_ads;"
# → 5227

# через Python
py -3.11 -c "
import asyncio, asyncpg
async def m():
    c = await asyncpg.connect('postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper')
    print('houses:', await c.fetchval('SELECT COUNT(*) FROM houses'))
    await c.close()
asyncio.run(m())
"
```

### Если порт 5432 занят / БД не поднята

```bash
# Проверить, что PostgreSQL-сервис запущен (Windows)
Get-Service postgresql-x64-18
# Если Stopped:
Start-Service postgresql-x64-18

# Если хочется пересоздать базу (ОСТОРОЖНО — стирает все данные):
psql -h 127.0.0.1 -U postgres -c "DROP DATABASE flipper;"
psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE flipper OWNER flipper;"
# Затем заново прогнать миграции (см. секцию 8).
```

### Почему НЕ Docker `app_postgres`

`app_postgres` (Docker) содержит **старые/сырые данные**: 18 171 active_ads без
привязки к домам (97% unlinked), 187 696 houses, из которых 82% без координат.
Это данные, которые парсеры записали до merge/dedup/геокодирования. **Использовать
для отладки и просмотра можно, для разработки — нельзя.** Если когда-нибудь
захочется снести — `docker compose down -v` (удалит том `pgdata`).

---

## 1.1. Структура .env

`.env` (в корне `flipper/`) — единый источник истины. **DATABASE_URL смотрит
на локальный PG** (см. секцию 1).

```env
# БД — локальный PostgreSQL на 127.0.0.1:5432
DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
POSTGRES_PASSWORD=flipper_secret

# Flippercrawl — наш self-hosted парсер Cian.
# Отдельный docker-compose: ../flippercrawl/ на :3002.
# Только static-путь (data.json.rawOfferData). LLM/AI fallback НЕ используем.
FLIPPERCRAWL_API_KEY=local
FLIPPERCRAWL_BASE_URL=http://flippercrawl-api-1:3002

# Grist (self-hosted UI-таблица для cian_active + аналитика)
# Заменил Google Sheets в 2026-08 — поддержка batch apply, нет OAuth-геморроя,
# читаемые формулы в UI. Doc `Parcing` с 10 таблицами (см. SYSTEM.md → Grist).
GRIST_API_KEY=flipper_prod_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GRIST_BASE=http://localhost:8484
GRIST_DOC=mDaHoGD6yahtxaqugwr5mK

# Telegram (уведомления о сигналах/авансах)
TG_BOT_TOKEN=your-telegram-bot-token
TG_CHAT_ID=your-telegram-chat-id

# CORS для API (dev = * , prod = домен фронта)
CORS_ORIGINS=*
```

Полный список переменных — в `.env.example`. Скопировать и заполнить:
```bash
cp .env.example .env
# отредактировать: GRIST_API_KEY, TG_BOT_TOKEN, TG_CHAT_ID
```

> **Grist обязателен для парсера `cian_active` и batch-скриптов sync.** Без
> `GRIST_API_KEY` в `.env` парсер упадёт при первом write в `Offers_Parser`.

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
| **3002** | **Flippercrawl** | flippercrawl (Docker, опц.) | http://localhost:3002 |
| **5432** | **PostgreSQL (локальный)** | flipper (натив) | localhost:5432 |
| **6379** | Redis | flipper (Docker, опц.) | localhost:6379 |
| **8000** | Cookie Manager | flipper (Docker, опц.) | http://localhost:8000 |
| **8001** | FastAPI API | flipper (**натив**, через `_run_api.cmd`) | http://localhost:8001 |
| **8090** | HTML → Markdown | flipper (Docker, опц.) | http://localhost:8090 |

Минимальный набор для запуска фронта+API+работы с данными: **5432 (PG), 3000 (front), 8001 (API)**.
Остальное — нужно только если запускаем парсеры.

---

## 3. Запуск (пошагово)

### 3.1. Убедиться, что PostgreSQL запущен

```bash
Get-Service postgresql-x64-18   # Status: Running
psql -h 127.0.0.1 -U flipper -d flipper -c "SELECT 1;"   # OK
```

### 3.2. Запустить API (нативно, hot-reload)

API запускается **нативно** через `_run_api.cmd` (в корне `flipper/`).
Скрипт подгружает `.env` в окружение и стартует `uvicorn` с `--reload`.

```powershell
# Из PowerShell в корне flipper/
.\\_run_api.cmd
# Лог пишется в _tmp_api.log. После старта:
#   INFO:     Uvicorn running on http://127.0.0.1:8001
```

Проверка:
```bash
curl http://localhost:8001/api/stats
# {"houses":30868,"active_total":5227,"active_linked":4842,...}
```

> **Почему нативно, а не Docker?** Так быстрее, и не нужно возиться со сборкой
> образа. `uvicorn --reload` ловит правки в `web/`, `packages/`, `services/`.
> Зависимости (`fastapi`, `asyncpg`, `numpy`, `scipy`) уже стоят в системном
> Python 3.11 на этой машине.

### 3.3. Запустить фронтенд (нативно, hot-reload)

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

### 3.4. (Опц.) Запустить Flippercrawl + cookie manager

Эти сервисы нужны только для парсеров (`cian_active` и т.д.). Для разработки
фронта/правок API они не нужны.

```bash
# Flippercrawl
cd ../flippercrawl
docker compose up -d
cd ../flipper

# Cookie manager + html_to_markdown (если будете запускать парсеры)
docker compose up -d app_redis html_to_markdown cookie_manager
```

### 3.5. Проверить данные в БД (опц.)

```bash
psql -h 127.0.0.1 -U flipper -d flipper -c "
  SELECT 'houses' AS t, COUNT(*) FROM houses
  UNION ALL SELECT 'active_ads', COUNT(*) FROM active_ads
  UNION ALL SELECT 'sold_ads', COUNT(*) FROM sold_ads;
"

# По источникам
psql -h 127.0.0.1 -U flipper -d flipper -c "
  SELECT source, COUNT(*) FROM houses GROUP BY source ORDER BY source;
"
```

Ожидаемо:
- `houses`: 30 868
- `active_ads`: 5 227 (все cian_active)
- `sold_ads`: 233 314

---

## 4. Быстрый старт (всё одной пачкой)

Если PostgreSQL уже запущен и `.env` заполнен:

```powershell
# 1. API (в одном окне терминала)
cd C:\Users\User\Desktop\flipping\flipper
.\\_run_api.cmd

# 2. Фронт (в другом окне)
cd C:\Users\User\Desktop\flipping\flipper\web\next
npm run dev
```

Открыть http://localhost:3000 — готово.

---

## 5. Ручной запуск парсеров (dev)

> **Парсеры сейчас не запускаем в dev** — данные уже в локальной БД, и они
> полные (5227 ads / 30 868 houses). Запускать парсеры имеет смысл только
> для backfill или проверки новой логики. Если всё-таки надо — Docker
> обязателен (Flippercrawl, cookie_manager, html_to_markdown).

Парсеры запускаются как одноразовые контейнеры через compose:

```bash
# Активные CIAN (через Flippercrawl + Grist) — основной парсер
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

> ⚠️ **Парсеры пишут в свой `app_postgres` (Docker), не в локальный PG.**
> Если хочется писать в локальный — переопределите DATABASE_URL в `.env` для
> парсера: `--env DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper`.

---

## 5.5. Grist: setup + sync scripts

Grist — self-hosted UI-таблица (аналог Airtable). Заменил Google Sheets для
парсера `cian_active` в 2026-08. Doc `Parcing` (`mDaHoGD6yahtxaqugwr5mK`)
содержит 10 таблиц — полный список в [SYSTEM.md](SYSTEM.md) → Grist schema.

### Запуск Grist

```bash
# В корне flipper/ — Grist уже в docker-compose.yml
docker compose up -d grist
# UI: http://localhost:8484
# API: http://localhost:8484/api/docs/{docId}/...
```

API-ключ и docId берутся из `.env`:
```env
GRIST_API_KEY=flipper_prod_xxxxxxxx
GRIST_BASE=http://localhost:8484
GRIST_DOC=mDaHoGD6yahtxaqugwr5mK
```

### Batch-скрипты синхронизации PG → Grist

После того как парсер `cian_active` (или `cian_sold` / `domclick_sold`)
написал в PG, нужно перенести в Grist `Sold_Ads` / `Active_ads` для UI.
Делается двумя скриптами:

```bash
# Синхронизировать ВСЕ снятые публикации из PG → Grist Sold_Ads
# (skip-existing по cian_id, безопасно запускать повторно)
py -3.11 scripts/sync_sold_to_grist.py
# Примерно 12 мин на 200k строк (batch=1000, ~415 rows/s)

# Только активные
py -3.11 scripts/sync_active_to_grist.py
# ~30 сек на 5k строк

# С фильтром по source (cian_deactivated/cian_active/domclick_sold/winners_sold)
py -3.11 scripts/sync_sold_to_grist.py --source cian_active

# Тестовая выборка
py -3.11 scripts/sync_sold_to_grist.py --limit 1000 --dry-run
```

**Параметры:**
- `--source` — фильтр по `sold_ads.source` (для sync_sold)
- `--limit N` — только первые N строк
- `--batch N` — размер пачки (default 1000, рекомендую не больше 2000 из-за 413)
- `--dry-run` — показать план без записи

**Автоматизация:** в `services/scheduler` добавить 2 задачи:
- `19:00` — `sync_active_to_grist.py`
- `19:30` — `sync_sold_to_grist.py`

Оба скрипта идемпотентны (skip по `cian_id`), повторный запуск не дублирует.

### Conditional formatting (раскраска строк по `status`)

```bash
py -3.11 scripts/grist_apply_conditional_formatting.py        # применить
py -3.11 scripts/grist_apply_conditional_formatting.py --dry-run
py -3.11 scripts/grist_apply_conditional_formatting.py --tables Sold_Ads,Offers_Parser
```

Создаёт cell-style правила через Grist `AddEmptyRule(table_id, 0, status_col_ref)`
на колонке `status`. Каждое правило = helper-колонка `gristHelper_ConditionalRule*`
с `formula` (например `$status == 'deactivated'`) + `widgetOptions.rulesOptions`
(JSON `{fillColor, textColor}`).

| status        | fill      | text      | таблицы |
|---------------|-----------|-----------|---------|
| `deactivated` | `#E5E7EB` | `#374151` | Sold_Ads, Offers_Parser, Table2, Table3, Arhiv_Prodano |
| `hot`         | `#D1FAE5` | `#065F46` | Offers_Parser |
| `signal`      | `#FEF3C7` | `#92400E` | Signals_Parser |
| `deposited`   | `#FEF3C7` | `#92400E` | Table2, Table3 |

Идемпотентен: повторный запуск не дублирует правила. Row-style (`AddEmptyRule(t,
0, 0)`) не работает — применяется только к `rawViewSectionRef`, который
не показывается в UI; используй cell-style.

### Ручная запись в Grist (для тестов)

```python
from packages.flipper_core.grist import GristClient

g = GristClient()
# Upsert по cian_id (если есть — обновит, иначе вставит)
g.upsert_dict("Sold_Ads", {
    "source": "cian_deactivated",
    "url": "https://www.cian.ru/sale/flat/123456/",
    "house_id": 381553,
    "price": 50000000,
    "cian_id": 123456,
    "status": "deactivated",
}, cian_id=123456)

# SELECT через SQL (Grist принимает SQLite-синтаксис)
records = g.sql("SELECT * FROM Sold_Ads WHERE cian_id = 123456")
for r in records:
    print(r["id"], r["fields"])
```

> **Grist API принимает только `tableId`** (внутреннее имя), не display. Для
> `Sold_Ads` tableId = `Sold_Ads` (не «Снятые»). Полный маппинг в
> [SYSTEM.md](SYSTEM.md) → Grist schema.

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

Config — в `pyproject.toml` `[tool.ruff]`. Excludes: `archive/`, `_tmp_archive/`, `data/`.

---

## 8. Миграции схемы (Alembic)

Alembic настроен, но **ещё не применён** к существующей БД (структура создана,
baseline не застампован). См. `alembic/README.md` для деталей.

Когда нужно применить миграцию (нативно):
```bash
cd flipper
py -3.11 -m alembic upgrade head

# Сгенерировать миграцию из изменений моделей:
py -3.11 -m alembic revision --autogenerate -m "add X to houses"
```

One-time adoption на существующей БД:
```bash
py -3.11 -m alembic stamp head   # пометить текущую схему как baseline
```

---

## 9. Типовые проблемы (troubleshooting)

### API возвращает 500 на любой запрос
Смотри `_tmp_api.log` (если запускал через `_run_api.cmd`). Почти всегда —
DATABASE_URL указывает не туда или хост не резолвится. Проверить:
```bash
# Из того же окружения, что и API:
echo %DATABASE_URL%
# Должно быть postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
```

### `socket.gaierror: [Errno 11001] getaddrinfo failed` в логе API
`DATABASE_URL` указывает на `app_postgres` или `host.docker.internal`, а
контейнер не поднят. Поправить `.env` на `127.0.0.1:5432` (см. секцию 1) и
перезапустить API.

### API не видит .env
`_run_api.cmd` явно подгружает `.env` через `set`. Если запускаешь uvicorn
руками — не забудь либо подгрузить env, либо передать `DATABASE_URL=...` в env.

### `relation "houses" does not exist` / похожие ошибки
БД не инициализирована. Создать таблицы через миграции (см. секцию 8) или
накатить бэкап.

### Фронт не подключается к API
```bash
# Проверить .env.local:
cat web/next/.env.local
# NEXT_PUBLIC_API_BASE=http://localhost:8001  ← должен быть

# Проверить API:
curl http://localhost:8001/api/stats
# Должен вернуть JSON.
```

### Порт занят
```bash
netstat -ano | findstr :8001      # Windows
# Убить процесс:  Stop-Process -Id <PID> -Force
```

### Docker-`app_postgres` мешает (порт 5432)
Если поднят `app_postgres` из docker-compose — он займёт 5432 и локальный
PG перестанет быть доступен. Решения:
- Остановить:  `docker compose stop app_postgres`
- Или поднять `app_postgres` на другом порту через `docker-compose.override.yml`:
  ```yaml
  services:
    app_postgres:
      ports: ["5434:5432"]
  ```

### Cookie Manager долго стартует (180 сек)
Это нормально — `start_period: 180s` в compose. Cookie Manager поднимает
Chromium + NoVNC, это медленно. Дождаться статуса `healthy`.

### Flippercrawl не отвечает
```bash
cd ../flippercrawl && docker compose ps
# Все сервисы должны быть Up:
#   flippercrawl-api-1, flippercrawl-redis-1, flippercrawl-rabbitmq-1,
#   flippercrawl-nuq-postgres-1

curl http://localhost:3002/   # 200 OK
```

---

## 10. Остановка

```bash
# Остановить API: Ctrl+C в окне, где запущен _run_api.cmd
# Остановить фронт: Ctrl+C в окне, где запущен npm run dev

# Остановить Docker-сервисы Flippercrawl + cookie manager (если подняты):
cd flipper
docker compose stop app_redis html_to_markdown cookie_manager

cd ../flippercrawl && docker compose stop

# Полная очистка Docker-стека (ОСТОРОЖНО — удалит данные `app_postgres`):
# cd flipper && docker compose down -v
```

Локальный PostgreSQL **не останавливать** — там живут все данные проекта.

---

## 11. Режимы: dev vs prod

| | Dev (Windows) | Prod (Linux VPS) |
|---|---|---|
| БД | **Локальный PostgreSQL 18 на 127.0.0.1:5432** | Docker `app_postgres` (внутри compose-сети) |
| API | **Натив** через `_run_api.cmd` (uvicorn --reload) | Docker `api` (gunicorn, без reload) |
| Фронт | Натив `npm run dev` (hot-reload) | Статика `npm run build` → Vercel/nginx |
| Flippercrawl / cookie manager / html_to_markdown | Docker, опц. (нужны только для парсеров) | Docker, always-on |
| Scheduler | (не запускают в dev) | Docker `scheduler` (always-on) |
| Парсеры | (не запускают в dev) | Scheduler по cron / `docker compose run --rm <name>` |

Подробнее про prod — в [DEPLOY.md](DEPLOY.md).

---

## 12. Архитектура (краткая)

```
┌──────────────────────────────────────────────────────────────────┐
│  Windows-хост (dev)                                              │
│                                                                  │
│  PostgreSQL 18 (натив)  127.0.0.1:5432                           │
│  user=flipper, db=flipper  ← source of truth в dev               │
│                                                                  │
│  uvicorn (натив)  127.0.0.1:8001                                 │
│  web/server.py → packages/flipper_db  (--reload)                 │
│                                                                  │
│  Next.js dev (натив)  localhost:3000                             │
│  web/next/  → ходит в 127.0.0.1:8001                            │
│                                                                  │
│  Docker (опц., только для парсеров):                             │
│    flippercrawl-api-1   :3002                                    │
│    app_redis            :6379                                    │
│    cookie_manager       :8000                                    │
│    html_to_markdown     :8090                                    │
│    app_postgres         :5432   ← старые данные, не source       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

В dev `DATABASE_URL` указывает на **локальный PostgreSQL 127.0.0.1:5432**.
В prod — на `app_postgres:5432` внутри compose-сети (см. [DEPLOY.md](DEPLOY.md)).

---

## См. также

- [SYSTEM.md](SYSTEM.md) — детальная архитектура, таблицы БД, расписание
- [DEPLOY.md](DEPLOY.md) — развёртывание на Linux VPS (prod)
- [.env.example](.env.example) — полный список переменных окружения
- [alembic/README.md](alembic/README.md) — миграции схемы (Alembic)
- [PLAN.md](../PLAN.md) — история решений по реструктуризации