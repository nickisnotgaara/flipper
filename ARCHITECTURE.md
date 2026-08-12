# Flipper — Техническая архитектура

> **Аудитория:** разработчик, который будет менять/дополнять проект.
> **Что внутри:** пакеты, слои, data flow, design decisions, как добавить
> новый парсер/источник/таблицу.

> **Зачем этот файл:** другие доки (README, SYSTEM) дают high-level
> обзор, но если нужно понять "куда положить код, чтобы не сломать
> существующее" — это здесь.

---

## 1. Структура репозитория (top-level)

```
flipper/
├── services/                    # Сервисы Docker (всё что в compose)
│   ├── parsers/                 # Парсеры (5 штук, см. ниже)
│   ├── api/                     # FastAPI для scheduler'а (legacy)
│   ├── category_counter/        # Подсчёт объявлений по категориям
│   ├── cookie_manager/          # Chromium + FastAPI для cookies CIAN
│   ├── grist_sync/              # Альтернативный sync-сервис (legacy)
│   ├── pipeline_runner/         # CLI-обёртка для ежедневного re-parse
│   └── scheduler/               # APScheduler — запускает docker compose по cron
│
├── packages/                    # Переиспользуемые Python-пакеты
│   ├── flipper_core/            # Grist client, HTML→MD, proxy loader, utils
│   └── flipper_db/              # SQLAlchemy models, pipeline v3, linker
│
├── web/                         # FastAPI backend + Next.js frontend
│   ├── server.py                # REST API для карты
│   ├── next/                    # React + Leaflet
│   └── static/                  # Built Next.js
│
├── scripts/                     # 101 ad-hoc скрипт (sync, migrate, import)
│
├── tests/                       # pytest (общие фикстуры)
│
├── docs/                        # Планы, дизайн-доки, вайрфреймы
│
├── archive/                     # Скоринг (альтернативная версия)
│   └── scorer/                  # Альтернативный подход к скорингу
│
├── alembic/                     # Миграции PostgreSQL
│
├── secrets/                     # credentials.json (НЕ коммитится)
│
├── data/                        # Прокси, логи, runtime data
│
├── _tmp_archive/                # Старый код (НЕ импортируется)
│   ├── parser_cian_legacy/      # Старый HTML-парсинг Cian
│   ├── sheets_py_legacy.py      # Google Sheets → Grist миграция
│   ├── filters_page/            # Удалённые Next.js pages
│   ├── settings_page/
│   ├── pipeline_page/
│   ├── test_parser_cian_legacy/
│   └── parsers_manual/          # 3 ручных парсера (flatinfo/winners/cian_sold)
│
├── docker-compose.yml           # Инфра + активные парсеры (cian, domclick)
├── _run_api.cmd                 # Windows-native запуск FastAPI
├── _run_parser.cmd              # Windows-native запуск cian_active
│
├── README.md                    # High-level entry point
├── SYSTEM.md                    # Архитектурные диаграммы (sequence)
├── DEVELOPMENT.md               # Локальная разработка, troubleshooting
├── PROJECT_OVERVIEW.md          # Бизнес-домен, метрики, анализ
├── ARCHITECTURE.md              # Этот файл — техническая архитектура
├── CHANGELOG.md                 # История изменений
└── AGENTS.md                    # Инструкции для AI-агентов (Mavis и т.п.)
```

---

## 2. Слои приложения (clean architecture-inspired)

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: SCHEDULER (services/scheduler/)                  │
│  - APScheduler: cron-триггеры → docker compose run         │
│  - Локи, retries, Telegram-алерты                          │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: PARSERS (services/parsers/)                       │
│  - Активные: cian_active (auto daily) + domclick_sold (auto weekly) │
│  - Запускаются вручную: flatinfo_houses, winners_sold, cian_sold (архив)  │
│  - Acquirer → QueueManager → DB write + Grist write         │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: DOMAIN (packages/flipper_db/)                     │
│  - SQLAlchemy models: houses, active_ads, sold_ads          │
│  - Pipeline v3: fetch → parse → match_house → upsert_ad    │
│  - Linker: cKDTree spatial match (cian ↔ flatinfo)          │
│  - Sources: protocol-реализации для cian/domclick/winners   │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: INFRA (packages/flipper_core/)                    │
│  - GristClient (REST + SQL)                                 │
│  - ProxyLoader                                                │
│  - HTML→MD конвертор (обёртка над go-html-to-md)           │
│  - Config + logging                                          │
├─────────────────────────────────────────────────────────────┤
│  Layer 0: STORAGE                                            │
│  - PostgreSQL 18 (single source of truth)                  │
│  - Grist (single spreadsheet, SQL-доступ)                  │
│  - Local FS (data/proxies.txt, data/logs/)                 │
└─────────────────────────────────────────────────────────────┘
```

**Где какая логика должна жить:**

| Если код... | Положить в... |
|-------------|---------------|
| Триггеры по cron, алерты | `services/scheduler/` |
| Парсит конкретный источник (CIAN/domclick/...) | `services/parsers/<source>/` |
| Определяет дом (linker, geocoder) | `packages/flipper_db/` |
| SQLAlchemy модель | `packages/flipper_db/models.py` |
| Grist API вызовы | `packages/flipper_core/grist.py` |
| HTTP-эндпоинт для UI | `web/server.py` |
| React-компонент | `web/next/components/` |
| Ad-hoc миграция/скрипт | `scripts/` |

**Антипаттерны (не делать):**
- ❌ Парсеры НЕ должны знать про `web/server.py`
- ❌ `web/server.py` НЕ должен импортировать парсеры
- ❌ SQL-запросы НЕ должны быть в `web/` (только в `packages/flipper_db/`)
- ❌ Grist API вызовы НЕ должны быть в `services/parsers/` (только через GristClient)

---

## 3. Data flow: 4 сценария

### 3.1 Ежедневный парсинг CIAN

```
[scheduler] 02:00 MSK
   ↓ docker compose run --rm pipeline_runner (ежедневно fetch-missing)
   ↓
[pipeline_runner] → scripts/run_pipeline.py
   ↓ packages/flipper_db.pipeline.run_source_pipeline
   ↓
[flippercrawl] ←→ [CIAN.ru]
   ↓ HTML
[flippercrawl:extract] → AdRecord (raw_data + lat/lng/address)
   ↓
[packages/flipper_db.linker.match_or_create_house]
   ├─ 1) cross-ref by cian_house_id (если есть в БД)
   ├─ 2) cKDTree spatial match (~75m) against GOOD_SOURCES
   └─ 3) auto-create with source='auto'
   ↓
[active_ads upsert] OR [moved to sold_ads if is_active=False]
   ↓
[scripts/sync_active_to_grist.py] + [sync_sold_to_grist.py]
   ↓
[Grist: Active_ads / Sold_Ads / Offers_Parser / Signals_Parser]
   ↓
[Next.js UI] ←→ [web/server.py] REST API
```

### 3.2 Парсинг CIAN с деактивацией (отдельный ежедневный ран cian_active)

```
[scheduler → docker compose run --rm cian_active] 10:00, 18:00 MSK
   ↓
[services/parsers/cian_active/main.py]
   ├─ Step 3: Read FILTERS from Grist (6 search URLs)
   ├─ Step 4: Extract ad URLs from search pages (cianparser)
   ├─ Step 5: For each URL: flippercrawl → parse → upsert to PG + Grist
   │   ├─ if is_active=True  → offers_parser (status=active|hot) + active_ads
   │   └─ if is_active=False → sold_ads + offers_parser (status=deactivated)
   │                          + sold_ads (Grist) + DELETE from active_ads (Grist)
   └─ Step 6: Cleanup stale
```

### 3.3 Обработка сигналов (Sneakers/Patterns)

```
[Offer появляется в Offers_Parser] 
   ↓
[web/next UI: пользователь кликает "Watch"]
   ↓
[scripts/sync_signals_urls_to_offers_db.py] (manual)
   ↓
[Offers_Parser] → [Signals_Parser] (сохраняет URL + reason)
   ↓
[При следующем парсинге этого URL]
   ↓
[_handle_offers в queue.py]
   ├─ Проверяет: есть ли в Signals_Parser? 
   ├─ Если есть + ещё матчится сигнал → остаётся в Signals
   ├─ Если есть + НЕ матчится → удаляется из Signals
   └─ Если нет + матчится → добавляется в Signals
```

### 3.4 Запрос из UI

```
[Next.js: User opens /map?bbox=37.5,55.7,37.6,55.8]
   ↓ fetch('/api/clusters?bbox=...')
   ↓
[web/server.py: GET /api/clusters]
   ├─ Cache hit (Redis 30s)? → return
   ├─ SQL: SELECT houses with bbox + LEFT JOIN active_ads (для медианы цены)
   ├─ Response: [{house_id, address, median_price, ad_count, ...}]
   ↓
[Next.js: рендерит Leaflet markers]
```

---

## 4. Database schema (PostgreSQL)

### 4.1 Active tables (production)

```sql
-- Единая таблица домов
houses (
    id SERIAL PK,
    source VARCHAR(20),              -- 'flatinfo' | 'cian_ad' | 'cian_sold' | 'auto' | 'manual'
    external_house_id BIGINT,         -- id в исходной системе
    address TEXT,                     -- полный адрес (для дедупа)
    lat FLOAT, lng FLOAT,             -- координаты
    year_built INT, building_type VARCHAR, levels INT, series VARCHAR,  -- метадата
    enriched_from_source VARCHAR,     -- когда последний раз обновлялась метадата
    created_at TIMESTAMPTZ,
    UNIQUE(source, external_house_id)
);

-- Активные объявления (ежедневно обновляются cian_active)
active_ads (
    id SERIAL PK,
    source VARCHAR(20),              -- 'cian_active' | 'domclick_active' | ...
    external_id BIGINT,              -- cian_id
    url TEXT UNIQUE,
    house_id INT FK → houses(id),
    price INT, price_per_m2 INT, area FLOAT, rooms INT,
    floor_current INT, floor_total INT,
    renovation VARCHAR, is_active BOOLEAN,
    days_in_exposition INT, total_views INT, unique_views INT,
    publish_date DATE, filter_id INT,
    raw_data JSONB,                  -- ← вся инфа от парсера (страховка)
    parsed_at TIMESTAMPTZ,
    lat FLOAT, lng FLOAT,             -- дубликат с house для скорости
    UNIQUE(source, external_id)
);

-- Снятые объявления (исторические)
sold_ads (
    id SERIAL PK,
    source VARCHAR(20),              -- 'cian_active' | 'domclick_sold' | 'winners_sold' | 'cian_deactivated'
    external_id BIGINT,
    url TEXT,
    house_id INT FK,
    price INT, price_per_m2 INT, area FLOAT, rooms INT,
    floor_current INT, floor_total INT,
    renovation VARCHAR, exposition_days INT,
    publish_date DATE, sold_date DATE,
    raw_data JSONB,                   -- ← ПОЛНЫЕ данные (для photo carousel и пр.)
    parsed_at TIMESTAMPTZ,
    lat FLOAT, lng FLOAT,
    UNIQUE(source, external_id)
);

-- Фильтры парсинга (Grist-источник для FILTERS table)
parser_filters (
    id SERIAL PK,
    url TEXT,
    meta JSONB
);
```

### 4.2 Legacy tables (НЕ использовать в новом коде)

```sql
-- Парсеры cian_active пишут СЮДА
cian_active_ads (
    id SERIAL PK, url TEXT, filter_id INT,
    source VARCHAR, parsed_data JSON,  -- ← другой формат
    is_parsed BOOLEAN, last_updated TIMESTAMPTZ
);
cian_sold_ads (id, url, parsed_data JSON, publish_date, sold_at);
cian_filters (id, url);
```

> **Сейчас:** парсер cian_active пишет в `cian_active_ads`, а скрипт
> `sync_active_to_grist.py` отдельно синкает в Grist Active_ads (через
> `active_ads` таблицу). Это работает, но избыточно.

### 4.3 Индексы (критичные для производительности)

```sql
CREATE INDEX idx_active_ads_house_id ON active_ads(house_id);
CREATE INDEX idx_active_ads_source_external ON active_ads(source, external_id);
CREATE INDEX idx_active_ads_publish_date ON active_ads(publish_date);
CREATE INDEX idx_sold_ads_house_id ON sold_ads(house_id);
CREATE INDEX idx_sold_ads_sold_date ON sold_ads(sold_date);
CREATE INDEX idx_houses_latlng ON houses(lat, lng);
CREATE INDEX idx_houses_source_external ON houses(source, external_house_id);
-- GIST-индекс для spatial queries (используется cKDTree в Python)
-- Реально spatial match делается в Python через cKDTree, а не в SQL
```

---

## 5. Grist schema

### 5.1 Таблицы (10 штук)

| Table ID | Display name | Назначение | Источник |
|----------|--------------|------------|----------|
| `FILTERS` | FILTERS | URL-фильтры для парсинга | Ручной ввод |
| `Active_ads` | Активные | Активные объявления (для UI) | `sync_active_to_grist.py` |
| `Sold_Ads` | Снятые | Снятые объявления (для UI) | `sync_sold_to_grist.py` |
| `Offers_Parser` | Циан База | Все распарсенные offers | `sync_offers_and_signals()` |
| `Signals_Parser` | Циан Сигналы | Сигнальные offers (drops/hot) | `sync_offers_and_signals()` |
| `Table2` | Аванс | Активные авансы | `cian_active --mode avans` |
| `Table3` | Аванс_Продано | Снятые авансы | `cian_active --mode avans` |
| `Arhiv_Prodano` | Архив_Продано | Legacy снятые (read-only) | bulk import |
| `Balans` | Баланс | Дневной подсчёт по категориям | `category_counter` |
| `Houses2` | Дома | Реестр домов (UI lookup) | `sync_houses_to_grist.py` |

### 5.2 Важно: почему Grist?

- **SQL-доступ через REST API** (`/api/docs/{doc_id}/sql`) — можем делать
  `SELECT * FROM Active_ads WHERE price < ...` без ORM
- **Conditional formatting** (цвет ячеек) — встроенный, без CSS
- **Cross-table References** — Foreign keys между таблицами
- **Public API** (read-only) — можно поделиться дашбордом
- **Один spreadsheet для всех команд** — легко шерить

### 5.3 Антипаттерны Grist

- ❌ Не делай `bulkAddRecord` с >1000 строк (413 Request entity too large)
- ❌ Не используй display-имя таблицы ("Снятые") в API — только tableId ("Sold_Ads")
- ❌ Не забывай про кириллицу — `ensure_ascii=False` при `json.dumps()`

---

## 6. Парсеры: внутренний контракт

### 6.1 Что должен делать парсер

```
Парсер = pipeline для одного источника данных.

Вход:  (опционально) URL-фильтры из Grist
Выход: записи в PG + записи в Grist
Частота: 1 раз в сутки (или реже)
Идемпотентность: обязательна (повторный запуск = тот же результат)
Ошибки: не падать на одной записи, продолжать остальные
```

### 6.2 Структура парсера (cian_active как образец)

```
services/parsers/cian_active/
├── main.py                  # оркестратор (entry point)
├── config.py                # Pydantic Settings (.env)
├── acquirer/
│   ├── cards.py             # AdParser — парсит одну карточку через flippercrawl
│   ├── queue.py             # QueueManager — concurrency, batch processing
│   ├── search.py            # extract_urls_by_searches — cianparser + прокси
│   ├── models.py            # Pydantic модели (ParsedAdData, etc.)
│   └── legacy_db/           # legacy DB layer (НЕ ИСПОЛЬЗОВАТЬ В НОВОМ КОДЕ)
├── cianparser/              # vendored библиотека для search-страниц
├── tests/                   # pytest
└── Dockerfile
```

### 6.3 Контракт AdParser

```python
class AdParser:
    def __init__(self, cookie_manager_url, flippercrawl_base_url, ...):
        """Инициализация HTTP-клиентов, логгера, кэша cookies."""
    
    async def parse_async(self, url: str) -> ParsedAdData:
        """Парсит одну карточку. Бросает ValueError на captcha/403/empty data."""
        # Шаги:
        # 1. GET cookie_manager /cookies
        # 2. POST flippercrawl /v2/cian/scrape
        # 3. Извлечь cian_id, price, area, address, photos, ...
        # 4. GET api.cian.ru/offer-card-statistic (days_in_exposition, views)
        # 5. Return ParsedAdData
```

### 6.4 Контракт QueueManager

```python
class QueueManager:
    def __init__(self, parser, grist_client, db_repo, concurrency=2, mode='offers'):
        """Парсер + клиенты + лимит concurrency + режим offers/avans."""
    
    async def run(self, urls: List[str]) -> dict:
        """Основной цикл: N воркеров параллельно парсят URLs.
        Возвращает {total, processed, errors, success_rate}.
        """
```

---

## 7. Cookie manager

### 7.1 Архитектура

```
[CIAN] ←→ [Chromium] ←→ [FastAPI: /cookies, /login, /refresh]
                                ↑
                                ├── [cian_active parser]
                                ├── [winners_sold parser]
                                └── [scheduler?]
```

Cookie manager — **это критическая зависимость** для всех парсеров.
Если он упадёт, все парсеры встанут с ValueError "Cookies are empty".

### 7.2 Эндпоинты

- `GET /cookies` — список cookies для CIAN
- `POST /login` — логин нового аккаунта (Chromium открывает UI)
- `POST /refresh` — обновить cookies (если Qrator 403)
- `GET /accounts` — список аккаунтов
- `POST /accounts/unblock` — разблокировать заблокированный аккаунт
- `GET /status` — текущий статус
- `GET /health` — health check

### 7.3 Автозапуск (в парсерах)

Парсеры делают `GET /cookies` каждые ~90 секунд (TTL кэша).
Если cookies пустые — вызывают `POST /check` → `POST /refresh`.

---

## 8. Scheduler (services/scheduler/)

### 8.1 Расписание

| Job | Cron | Сервис | Команда |
|-----|------|--------|---------|
| `cian_active/offers` | 10:00, 18:00 MSK (ежедневно) | `cian_active` | `docker compose run --rm cian_active --mode offers` |
| `domclick_sold` | Sun 07:00 MSK (еженедельно) | `domclick_sold` | `docker compose run --rm domclick_sold --mode full` |
| `pipeline_runner` | 02:00 MSK (ежедневно) | `pipeline_runner` | `docker compose run --rm pipeline_runner` |
| `category_counter` | 09:00 MSK (ежедневно) | `category_counter` | `docker compose run --rm category_counter` |

### 8.2 Особенности

- **Lock per job** — не запускать тот же job параллельно
- **Timeout per job** (env: `SCHEDULER_*_TIMEOUT`) — kill через N секунд
- **Retry with backoff** (env: `SCHEDULER_MAX_RETRIES`, `RETRY_BACKOFF_BASE`)
- **Telegram alert on failure** — если задан `TG_BOT_TOKEN` + `TG_CHAT_ID`

---

## 9. Web server (FastAPI + Next.js)

### 9.1 Endpoints (web/server.py)

```
GET  /                          # старая статика index.html (fallback)
GET  /api/stats                 # счётчики для header
GET  /api/clusters?bbox=        # дома в bbox (карта)
GET  /api/clusters/{id}/ads     # объявления в доме (для popup)
GET  /api/houses                # legacy: дома из cian (без flatinfo)
GET  /api/ads/map               # legacy: все активные как markers
```

### 9.2 Кэширование

- `/api/clusters` кэшируется **30s in-memory** per bbox — для плавного
  паннинга карты
- `/api/clusters/{id}/ads` — без кэша (per-house запрос)

### 9.3 Frontend (Next.js)

- **Leaflet** (open-source, без Google Maps API key)
- **Dynamic imports** для тяжёлых компонентов (карта)
- **Right-side panel** для выбранного дома (PhotoCarousel + AdCard)
- **Filters** — `min_price`, `max_price`, `rooms`, `renovation` (через URL params)

---

## 10. Как добавить новый парсер

> Паттерн: скопировать `services/parsers/cian_active/`, заменить источник.

### 10.1 Структура

```bash
# 1. Скопировать шаблон
cp -r services/parsers/cian_active services/parsers/my_new_source

# 2. Переименовать
mv services/parsers/my_new_source/cian_active/Dockerfile \
   services/parsers/my_new_source/my_new_source.Dockerfile  # нет, лучше просто оставить
# Просто переименуй main.py → main.py (то же), acquirer/cards.py → ...

# 3. Реализовать AdParser (acquirer/cards.py)
# - __init__: HTTP-клиенты, логгер
# - parse_async(url) -> ParsedAdData

# 4. Реализовать QueueManager (acquirer/queue.py)
# - run(urls) -> статистика

# 5. main.py: оркестратор
# - get filter URLs (from Grist / config / static)
# - extract URLs (acquirer)
# - run queue (acquirer)
# - handle deactivations (move to sold, etc.)

# 6. Добавить в docker-compose.yml
# 7. Добавить в scheduler/main.py (если автозапуск)
# 8. Добавить tests
```

### 10.2 Что НЕ нужно делать

- ❌ Писать в legacy таблицы (`cian_active_ads` и т.п.) — пиши в новые (`active_ads`)
- ❌ Использовать `find_by_cian_id` для таблиц с `external_id` колонкой (Active_ads, Houses2)
- ❌ Делать bulk insert >1000 строк (используй `POST /records` с батчами)
- ❌ Забыть про `trust_env=False` в HTTP-клиенте (иначе `HTTP_PROXY` ломает внутренние Docker-адреса)

---

## 11. Design decisions (исторические)

### 11.1 Почему PostgreSQL 18, а не SQLite

- 270k+ строк → SQLite тормозит на JOIN
- Нужен concurrent writes (parsers + UI одновременно)
- Нужен `JSONB` для raw_data (эффективные запросы)
- Alembic-миграции требуют полноценной RDBMS

### 11.2 Почему Grist, а не Google Sheets / Airtable

- Sheets API rate limit (60 req/min) — сломало бы при sync 5k+ rows
- Grist имеет SQL API → можно делать сложные запросы без ORM
- Grist — self-hosted (без зависимости от Google)
- Conditional formatting из коробки (для "deactivated" = серый)

### 11.3 Почему Flippercrawl (self-hosted static-extraction)

- Self-hosted — нет внешних SaaS-зависимостей и rate limits
- Наш код, полный контроль над логикой и форматом
- Static-extraction (regex на HTML) = 1-2s per page
- LLM-fallback намеренно отключён — стабильность важнее гибкости

### 11.4 Почему двойная схема БД (active_ads vs cian_active_ads)

- Исторически cian_active_ads была основной
- При миграции на active_ads не хотели ломать парсеры
- Решили: парсеры пишут в legacy, sync_script переносит в новую
- Tradeoff: избыточность, но безопасная миграция

---

## 12. Anti-patterns в текущем коде (TODO исправить)

| # | Проблема | Где | Почему критично |
|---|----------|-----|-----------------|
| 1 | Двойная схема БД | parser → sync_script → UI | Избыточность, источник багов |
| 2 | Legacy `find_by_cian_id` падает на Active_ads | `grist.py` | Нужен был `find_by_external_id` (добавлено) |
| 3 | `NameError status_active` | queue.py (исправлено) | Падал при is_active=True |
| 4 | Нет CI/CD | весь проект | Ручной деплой через ssh |
| 5 | `flake8`/`mypy` нет | весь проект | Type errors только в рантайме |
| 6 | Нет alert'ов на cookie rotate | cookie_manager | Если Qrator забанит, узнаем через сутки |
| 7 | Hardcoded map urls | docs/ | Карта захардкожена на Москву |

---

## 13. Glossary

| Термин | Что это |
|--------|---------|
| Flippercrawl | Self-hosted scraper (порт 3002) Cian, static-extraction |
| Cianparser | Vendored библиотека для парсинга search-страниц Cian |
| FILTERS | Grist-таблица с URL-фильтрами для парсинга |
| Signal | Объявление с ≥3 снижениями цены за 30д или max_drop ≥5% |
| Hot | Объявление с >200 уникальных просмотров в день |
| Avans | Аванс/задаток — объявление, где уже внесли предоплату |
| Active ad | Объявление ещё не снято с Cian |
| Sold ad | Объявление снято (deactivated/expired) |
| Filter | URL поиска Cian с параметрами (район, цена, ремонт) |
| House | Дом (здание). Может быть из flatinfo/cian/auto |
| Cluster | Группа домов в радиусе 75м (cKDTree) |
| Pipeline | ETL-процесс: fetch → parse → match_house → upsert |
| Worker | Один из N concurrent parser-task'ов |
| Lock | Файл-флаг scheduler'а, чтобы не запускать тот же job параллельно |

---

## 14. См. также

- [README.md](README.md) — quick start
- [SYSTEM.md](SYSTEM.md) — sequence-диаграммы
- [DEVELOPMENT.md](DEVELOPMENT.md) — локальная разработка
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) — бизнес-домен
- [docs/ARCHITECTURE_V3.md](docs/ARCHITECTURE_V3.md) — старая версия архитектуры (v3)
- [CHANGELOG.md](CHANGELOG.md) — что менялось
- [AGENTS.md](AGENTS.md) — инструкции для AI-агентов
