# Flipper

Единая система парсинга недвижимости Москвы. **2 автоматических парсера** +
ручной re-parse pipeline + UI-карта + Grist-дашборд. Цель — находить
квартиры для классического флиппинга (покупка дешевле рынка → ремонт → продажа
дороже).

**Текущее состояние (dev):** API + фронт подняты нативно, БД — **локальный
PostgreSQL 18 на 127.0.0.1:5432**. В ней 5 227 active_ads, 30 868 houses,
247 638 sold_ads (уникальных cian_id), 270 387 строк в Grist `Sold_Ads`.
Подробности — [DEVELOPMENT.md](DEVELOPMENT.md) и [CHANGELOG.md](CHANGELOG.md).

## Документация (навигация)

| Файл | Что внутри |
|------|------------|
| [README.md](README.md) | Этот файл — high-level обзор + quick start |
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | Бизнес-домен (флиппинг, рынок), метрики, 5-lens анализ |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Техническая архитектура, data flow, как добавить парсер |
| [SYSTEM.md](SYSTEM.md) | Sequence-диаграммы, сервисы, расписание |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Локальная разработка, troubleshooting |
| [CHANGELOG.md](CHANGELOG.md) | История изменений (по датам) |
| [AGENTS.md](AGENTS.md) | Инструкции для AI-агентов (Mavis и т.п.) |
| [_tmp_archive/parsers_manual/README.md](_tmp_archive/parsers_manual/README.md) | Как запустить заархивированные парсеры |
| [docs/](docs/) | Планы, вайрфреймы, дизайн-доки |

## Что внутри

2 автоматических парсера + 4 ручных/архивных + 2 batch-скрипта синхронизации
PG → Grist + 1 scheduler + 1 web API + 1 frontend:

| Сервис / Скрипт | Что делает | Расписание | Где живёт |
|---|---|---|---|
| `cian_active` | Активные CIAN через Flippercrawl → PG + Grist | **ежедневно 10:00, 18:00** | `services/parsers/cian_active/` (active) |
| `domclick_sold` | Снятые domclick.ru → PG `sold_ads` | **еженедельно Sun 07:00** | `services/parsers/domclick_sold/` (active) |
| `flatinfo_houses` | Реестр домов flatinfo.ru → PG `houses` | **вручную** | `_tmp_archive/parsers_manual/flatinfo_houses/` |
| `winners_sold` | baza-winner.ru → PG `sold_ads` | **вручную** | `_tmp_archive/parsers_manual/winners_sold/` |
| `cian_sold` | Снятые CIAN (deactivated) → PG `sold_ads` | **вручную** | `_tmp_archive/parsers_manual/cian_sold/` |
| `pipeline_runner` | Ежедневный re-parse всех active ads через flippercrawl | 02:00 (через scheduler) | `services/pipeline_runner/` |
| `category_counter` | Подсчёт по категориям → Grist `Balans` | 09:00 (через scheduler) | `services/category_counter/` |
| `scripts/sync_active_to_grist.py` | PG `active_ads` → Grist `Active_ads` | 19:00 (через scheduler) | `scripts/` |
| `scripts/sync_sold_to_grist.py` | PG `sold_ads` → Grist `Sold_Ads` (270k+) | 19:30 (через scheduler) | `scripts/` |

**Почему только 2 авто-парсера:** дома обновляются раз в несколько месяцев
(новых ЖК мало), снятые объявления уже почти все в БД (270k+ за 2 года),
а разные источники (winners, cian_sold) дублируют друг друга. Данные
которые не меняются каждый день, нет смысла парсить ежедневно.

**Архитектурный принцип:** "сначала данные — потом аналитика". Сейчас фокус на
том, чтобы дневной цикл CIAN (→ 5000 active → 5-50 deactivations) работал
надёжно. Аналитика (скоринг "выгодности", ML) — следующий этап.

Все парсеры пишут в единую PostgreSQL БД (`houses`, `active_ads`, `sold_ads`)
через пакет `packages/flipper_db/`. Grist используется как **read-only дашборд**
для аналитики (через iframe в Next.js) + как write-таблица для парсера
`cian_active` и batch-sync-скриптов.

## Структура

```
flipper/
├── services/
│   ├── parsers/                      # 2 активных парсера
│   │   ├── _common.py                # общий код
│   │   ├── cian_active/              # активные CIAN (Flippercrawl + Grist)
│   │   └── domclick_sold/            # снятые domclick.ru
│   ├── api/                          # FastAPI backend (web/server.py)
│   ├── category_counter/             # подсчёт объявлений → Grist Balans
│   ├── cookie_manager/               # Chromium + FastAPI для Flippercrawl
│   ├── html_to_markdown/             # Go-сервис HTML → Markdown
│   ├── pipeline_runner/              # ежедневный fetch-missing через flippercrawl
│   └── scheduler/                    # APScheduler (cron-подобный)
│
├── _tmp_archive/                     # НЕ импортируется; живая история решений
│   ├── parsers_manual/               # 3 ручных парсера (flatinfo/winners/cian_sold)
│   │   └── README.md                 # инструкция по ручному запуску
│   ├── parser_cian_legacy/           # старый HTML-парсинг Cian
│   ├── sheets_py_legacy.py           # Google Sheets → Grist миграция
│   └── filters_page/ + settings_page/ + pipeline_page/  # удалённые Next.js pages
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

### 6. Grist: подсветка строк по `status`

```bash
py -3.11 scripts/grist_apply_conditional_formatting.py
# --dry-run — показать, что будет сделано, без изменений
# --tables Sold_Ads,Offers_Parser — только указанные таблицы
```

Раскрашивает ячейку `status` (cell-style) в нужный цвет:

| status        | fill      | где |
|---------------|-----------|-----|
| `deactivated` | `#E5E7EB` серый | Sold_Ads, Offers_Parser, Table2, Table3, Arhiv_Prodano |
| `hot`         | `#D1FAE5` зелёный | Offers_Parser |
| `signal`      | `#FEF3C7` жёлтый | Signals_Parser |
| `deposited`   | `#FEF3C7` жёлтый | Table2, Table3 |

Скрипт идемпотентен — повторный запуск обновляет цвета, не плодит дубли.

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

# Flippercrawl — наш self-hosted парсер Cian
FLIPPERCRAWL_API_KEY=local
FLIPPERCRAWL_BASE_URL=http://flippercrawl-api-1:3002

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
