# Flipper

Единая система парсинга недвижимости с 5 источниками. Все парсеры
работают в одном docker-compose, пишут в общую PostgreSQL БД и **Grist**
(для аналитики/UI), подходят для интерактивной карты 2gis-style.

**Текущее состояние (dev):** API + фронт подняты нативно, БД — **локальный
PostgreSQL 18 на 127.0.0.1:5432**. В ней 5 227 active_ads, 30 868 houses,
247 638 sold_ads (уникальных cian_id), 270 387 строк в Grist `Sold_Ads`.
Подробности — [DEVELOPMENT.md](DEVELOPMENT.md) и [CHANGELOG.md](CHANGELOG.md).

## Что внутри

5 парсеров + 2 batch-скрипта синхронизации PG → Grist:

| Сервис / Скрипт | Что делает | Расписание |
|---|---|---|
| `cian_active` | Активные CIAN через Firecrawl → Grist `Offers_Parser`/`Signals_Parser`/`Sold_Ads` | 10:00, 18:00 |
| `cian_sold` | Снятые CIAN (deactivated_offers) → PG `sold_ads` | **вручную** |
| `winners_sold` | baza-winner.ru → PG `sold_ads` | **Sun 06:00** |
| `domclick_sold` | domclick.ru → PG `sold_ads` | **Sun 07:00** |
| `flatinfo_houses` | flatinfo.ru → PG `houses` | **вручную** |
| `scripts/sync_active_to_grist.py` | PG `active_ads` → Grist `Active_ads` | 19:00 |
| `scripts/sync_sold_to_grist.py` | PG `sold_ads` → Grist `Sold_Ads` (270k+) | 19:30 |
| `category_counter` | Подсчёт по категориям → Grist `Balans` | 09:00 |

Все парсеры пишут в единую PostgreSQL БД (`houses`, `active_ads`, `sold_ads`)
через пакет `packages/flipper_db/`. Grist используется как **read-only дашборд**
для аналитики (через iframe в Next.js) + как write-таблица для парсера
`cian_active` и batch-sync-скриптов.

## Структура

```
flipper/
├── services/
│   ├── parsers/                      # 5 парсеров
│   │   ├── _common.py                # общий код
│   │   ├── cian_active/              # активные CIAN (Firecrawl + Grist)
│   │   ├── cian_sold/                # снятые CIAN
│   │   ├── winners_sold/             # baza-winner.ru
│   │   ├── domclick_sold/            # domclick.ru
│   │   └── flatinfo_houses/          # flatinfo.ru
│   ├── api/                          # FastAPI backend (web/server.py)
│   ├── category_counter/             # подсчёт объявлений → Grist Balans
│   ├── cookie_manager/               # Chromium + FastAPI для Firecrawl
│   ├── html_to_markdown/             # Go-сервис HTML → Markdown
│   └── scheduler/                    # APScheduler (cron-подобный)
│
├── packages/
│   ├── flipper_core/                 # grist, utils, proxy_loader, html_to_md
│   ├── flipper_db/                   # ⭐ SQLAlchemy: houses, active_ads, sold_ads
│   └── go-html-to-md/                # Go-сервис
│
├── scripts/                          # утилиты (включая sync_*_to_grist.py)
├── web/
│   ├── server.py                     # FastAPI бэкенд
│   └── next/                         # Next.js 14 фронтенд (UI карты)
│
├── data/                             # proxies.txt, logs/
├── _tmp_archive/                     # ⭐ legacy-код (sheets.py, parser_cian/)
│
├── docker-compose.yml                # инфра (Flippercrawl, cookie_manager, app_postgres)
├── docker-compose.override.yml       # dev override (app_postgres на 5434)
├── .env.example                      # шаблон переменных окружения
├── _run_api.cmd                      # ⭐ запуск API нативно на Windows
├── _run_front.cmd                    # запуск Next.js dev
├── CHANGELOG.md                      # ⭐ история изменений
├── SYSTEM.md                         # детальная архитектура
├── DEVELOPMENT.md                    # ⭐ запуск dev-окружения
├── DEPLOY.md                         # развёртывание на сервере
├── AGENTS.md                         # правила для AI-агентов
└── README.md                         # этот файл
```

## Быстрый старт (dev)

**Предпосылка:** локальный PostgreSQL 18 уже установлен, БД `flipper` создана
с пользователем `flipper`/`flipper_secret` и заполнена актуальными данными
(5 227 active_ads, 30 868 houses).

### 1. Подготовка

```bash
# Скопировать и заполнить .env
cp .env.example .env
notepad .env  # проверить GRIST_API_KEY, GRIST_BASE, TG_BOT_TOKEN, TG_CHAT_ID
              # DATABASE_URL должен указывать на 127.0.0.1:5432

# Убедиться, что PostgreSQL запущен
Get-Service postgresql-x64-18   # Status: Running
```

### Grist (для парсера cian_active + аналитики)

Self-hosted Grist поднят на `http://localhost:8484`. Doc `Parcing`
(`mDaHoGD6yahtxaqugwr5mK`) с 10 таблицами (см. [SYSTEM.md](SYSTEM.md) → Grist
schema). Парсер `cian_active` пишет в `Offers_Parser / Signals_Parser /
Sold_Ads` напрямую, batch-скрипты — `Active_ads / Sold_Ads` из PG.

### 2. Запуск API

```powershell
# В корне flipper/
.\\_run_api.cmd
# Лог в _tmp_api.log. Слушает http://127.0.0.1:8001.
```

Проверка: `curl http://localhost:8001/api/stats` — JSON с houses/active_ads.

### 3. Запуск фронта

```bash
cd web/next
npm install        # один раз
npm run dev        # http://localhost:3000
```

### 4. (Опц.) Поднять Docker-инфру для парсеров

```bash
# Только если собираемся запускать парсеры
cd ../flippercrawl && docker compose up -d && cd ../flipper
docker compose up -d app_redis html_to_markdown cookie_manager
```

**Парсеры в dev обычно не запускаем** — данные уже актуальные.

### 5. Просмотр логов

```bash
# API: _tmp_api.log в корне flipper/
# Docker: docker compose logs <service>
```

## Тестирование

```bash
# Все тесты (pytest.ini настроен на все testpaths)
py -m pytest -v

# Или локально (без docker):
cd C:\Users\User\Desktop\flipping\flipper
py -m pytest packages/flipper_db/tests services/parsers scripts/tests -v
```

Покрытие: **118+ тестов** в 9 группах. Тесты используют SQLite in-memory
(не трогают PostgreSQL).

## Конфигурация (.env)

Основные переменные (полный список в `.env.example`):

```env
# БД — локальный PostgreSQL на 127.0.0.1:5432
DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
POSTGRES_PASSWORD=flipper_secret

# Flippercrawl (НЕ firecrawl AI extract)
FIRECRAWL_API_KEY=local
FIRECRAWL_BASE_URL=http://flippercrawl-api-1:3002

# Grist (заменил Google Sheets для cian_active)
GRIST_API_KEY=flipper_prod_xxxxxxxxxxxx
GRIST_BASE=http://localhost:8484
GRIST_DOC=mDaHoGD6yahtxaqugwr5mK

# Telegram (уведомления)
TG_BOT_TOKEN=your-telegram-bot-token
TG_CHAT_ID=your-telegram-chat-id

# Расписание еженедельных парсеров
WEEKLY_RUN_DAY_OF_WEEK=sun
WEEKLY_WINNERS_HOUR=6
WEEKLY_DOMCLICK_HOUR=7
```

> ⚠️ **DATABASE_URL в dev указывает на локальный PG (127.0.0.1)**, не на
> `app_postgres:5432`. Для prod (Docker-compose) — наоборот. См. [DEVELOPMENT.md](DEVELOPMENT.md).

## Документация

- **[DEVELOPMENT.md](DEVELOPMENT.md)** — ⭐ запуск dev-окружения, troubleshooting
- [SYSTEM.md](SYSTEM.md) — детальная архитектура, таблицы, расписание
- [DEPLOY.md](DEPLOY.md) — развёртывание на VPS
- [PLAN.md](../PLAN.md) — история решений по реструктуризации
- [AGENTS.md](AGENTS.md) — правила для AI-агентов, работающих с проектом
- [archive/scorer/README.md](archive/scorer/README.md) — как восстановить скоринг
