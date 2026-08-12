# Flipper — Система мониторинга недвижимости

## Архитектура

Система состоит из **нативных** (API, фронт) и **Docker** (Flippercrawl, cookie
manager, html_to_markdown, опц. `app_postgres`) компонентов.

| Сервис | Назначение | Где живёт | Расписание |
|--------|-----------|-----------|------------|
| **PostgreSQL 18** (натив) | **Единая БД** для всех (таблицы `houses`, `active_ads`, `sold_ads`) | Windows-native, `127.0.0.1:5432` | always-on |
| FastAPI `web/server.py` | REST API для фронта | Натив, через `_run_api.cmd` | dev only |
| Next.js | UI карты 2gis-style | Натив, `npm run dev` | dev only |
| `flippercrawl-api-1` | Self-hosted парсер Cian (Flippercrawl) | Docker, `:3002` | always-on (опц. в dev) |
| `app_postgres` (Docker) | **Устаревшая** копия БД со старыми/сырыми данными. Не использовать для dev! | Docker, `:5432` | always-on (опц.) |
| `app_redis` | Redis для `cookie_manager` | Docker, `:6379` | always-on (опц. в dev) |
| `html_to_markdown` | Go-сервис конвертации HTML → Markdown (для `cian_active`) | Docker, `:8090` | always-on (опц. в dev) |
| `cookie_manager` | Микросервис управления cookies для Flippercrawl (Chromium + FastAPI) | Docker, `:8000` | always-on (опц. в dev) |
| `scheduler` | APScheduler: cron-подобный запуск парсеров | Docker, prod only | prod only |
| `cian_active` | **Активные** объявления CIAN через Flippercrawl + Grist (вместо Google Sheets) | Docker | 10:00, 18:00 |
| `category_counter` | Подсчёт объявлений CIAN по категориям (таблица `Balans` в Grist) | Docker | 09:00 |
| `cian_sold` | **Снятые публикации** CIAN (deactivated_offers) → PostgreSQL | Docker | **вручную** |
| `winners_sold` | Снятые публикации baza-winner.ru → PostgreSQL | Docker | **Sun 06:00** (еженедельно) |
| `domclick_sold` | Снятые публикации domclick.ru → PostgreSQL | Docker | **Sun 07:00** (еженедельно) |
| `flatinfo_houses` | Реестр домов flatinfo.ru → PostgreSQL | Docker | **вручную** |

Внешняя зависимость: **self-hosted Flippercrawl** (отдельный docker-compose, сеть `flippercrawl_backend`).

---

## Архитектура данных

Все парсеры и API пишут в **единую PostgreSQL БД** через пакет
`packages/flipper_db/`. В dev это **локальный PostgreSQL 18 на 127.0.0.1:5432**
(Windows-native, source of truth), в prod — Docker-контейнер `app_postgres`.
Источник правды — переменная `DATABASE_URL` в `.env` (см. [DEVELOPMENT.md](DEVELOPMENT.md)
для dev-сетапа, [DEPLOY.md](DEPLOY.md) — для prod).

> ⚠️ **Docker `app_postgres` сейчас содержит старые/сырые данные** (18 171 ads
> без привязки к домам, 187 696 houses, 82% без координат). Это данные до
> merge/dedup/геокодирования. **Для разработки и просмотра UI используй
> локальный PG (127.0.0.1:5432) — там актуальные 5 227 ads / 30 868 houses.**

```
┌─────────────────┐
│     houses      │ ◄────────────┐
│─────────────────│              │
│ id              │              │
│ source          │              │  FK house_id
│ external_house_id│             │
│ cian_house_id   │              │
│ address, lat, lng│             │
│ year, levels    │              │
│ building_type   │              │
│ package         │              │
│ raw_data (JSONB)│              │
└─────────────────┘              │
                                 │
        ┌────────────────────────┴────────┐
        ▼                                 ▼
┌──────────────────┐              ┌──────────────────┐
│   active_ads     │              │     sold_ads     │
│──────────────────│              │──────────────────│
│ id               │              │ id               │
│ source           │              │ source           │
│ cian_id          │              │ external_id      │
│ house_id (FK)    │              │ house_id (FK)    │
│ price, area      │              │ price, area      │
│ floor, rooms     │              │ floor, rooms     │
│ views, price_hist│              │ exposition_days  │
│ is_active        │              │ sold_date        │
└──────────────────┘              └──────────────────┘
```

### Source-теги

| Сервис | Source | Что пишет |
|---|---|---|
| `parsers/cian_active` | `cian_active` | `active_ads` (с `filter_id` 1-6) + (sold <7д) `sold_ads` |
| `parsers/cian_sold` | `cian_sold` | `houses` + `sold_ads` (вся история) |
| `parsers/winners_sold` | `winners_sold` | `houses` + `sold_ads` |
| `parsers/domclick_sold` | `domclick_sold` | `houses` + `sold_ads` |
| `parsers/flatinfo_houses` | `flatinfo_houses` | `houses` (только дома) |

`active_ads.filter_id` — связь с таблицей `FILTERS` в Grist:
- `1-4` = **offers** (фильтры по году постройки и ЦАО)
- `5` = **signals** (Опека)
- `6` = **advance** (Запрет долги / аванс)

### Маппинг источников → таблицы

| Сервис | `houses` | `active_ads` | `sold_ads` | Когда |
|---|---|---|---|---|
| `parsers/cian_active` | + | + | + (sold <7д) | 10:00, 18:00 |
| `parsers/cian_sold` | + | — | + (вся история) | **вручную** |
| `parsers/winners_sold` | + | — | + | **Sun 06:00 weekly** |
| `parsers/domclick_sold` | + | — | + | **Sun 07:00 weekly** |
| `parsers/flatinfo_houses` | + | — | — | **вручную** |

---

## Grist schema (Parcing doc, `mDaHoGD6yahtxaqugwr5mK`)

Self-hosted Grist на `http://localhost:8484` — **единая UI-таблица** для аналитики
(вместо Google Sheets, который использовался до 2026-08). Используется парсером
`cian_active` для записи результатов и как read-only дашборд для команды.

**10 таблиц (tableId → display, строк):**

| tableId         | Display        | Rows   | Назначение                                       |
|-----------------|----------------|--------|--------------------------------------------------|
| `FILTERS`       | Фильтры        | ~10    | URL для `cian_active` (бывш. вкладка Sheets)      |
| `Active_ads`    | Активные       | 5 227  | Текущие активные объявления                      |
| `Sold_Ads`      | **Снятые**     | 270 387| Все снятые публикации (вместо старой «Продано»)  |
| `Arhiv_Prodano` | Архив Продано  | 3 119  | Legacy-данные старой вкладки «Продано» (read-only) |
| `Offers_Parser` | Парсер Офферс  | ~5k    | Текущие результаты парсера                       |
| `Signals_Parser`| Сигналы        | ~500   | Объявления с признаком «сигнал»                  |
| `Table2`        | Аванс          | ~1k    | Активные авансовые                               |
| `Table3`        | Аванс_Продано  | ~400   | Снятые авансовые                                 |
| `Balans`        | Баланс         | daily  | Дневной счётчик `category_counter`               |
| `Houses2`       | База домов     | 30 868 | Реестр домов (lat/lng/year/...)                  |

> **Важно:** Grist API принимает **только `tableId`** (внутренний, латиницей),
> не display-имя. Display-имена (русские) — для UI. Исключение: `FILTERS` (tableId =
> display). См. [docs/GRIST_EXPERIMENTS.md](docs/GRIST_EXPERIMENTS.md).

### Таблица `Sold_Ads` (главная для аналитики снятых)

> **Эволюция:** до 2026-08 была вкладка `Table1/Продано` в Google Sheets (3 119
> строк, write-only). Теперь это `Sold_Ads` в Grist — большая чистая таблица со
> всеми 270k+ снятыми публикациями из PG `sold_ads`.

**Колонки (30 + 2 формулы):**
- `source` (Text) — `cian_deactivated | cian_active | domclick_sold | winners_sold`
- `cian_id` (Numeric) — `= sold_ads.external_id` (UNIQUE для upsert)
- `url`, `house_id`, `price`, `price_per_m2`, `area`, `rooms`
- `floor_current`, `floor_total`, `floor_info` (combined "X/Y")
- `housing_type`, `construction_year`, `renovation`
- `title`, `address`, `description`
- `district`, `okrug`, `metro_station`, `metro_walk_time`
- `publish_date` (Date), `sold_date` (Date), `exposition_days`
- `total_views`, `unique_views`, `parsed_at`
- `status` (Text) — `deactivated` всегда; для UI conditional formatting
- **`photos_url`** (Formula) → `http://localhost:3000/map?photoAd={cian_id}`
- **`map_url`** (Formula) → `http://localhost:3000/map?house={house_id}`

**Заполняется тремя путями:**
1. **Парсер `cian_active`** (online) — при `is_active=False` пишет в `Sold_Ads` через
   `GristClient.upsert_dict()`. Также обновляет `Offers_Parser` со status=`deactivated`.
2. **`scripts/sync_sold_to_grist.py`** (batch) — `sold_ads` (PG) → `Sold_Ads` (Grist).
   POST `/api/docs/{id}/tables/{t}/records` батчами по 1000, ~415 rows/s.
3. **`parsers/cian_sold` / `parsers/domclick_sold`** — добавляют новые строки в
   `sold_ads` (PG), затем sync-script переносит в Grist.

> **Skip-existing** в sync-script проверяет `existing_cian_ids` из Grist (один
> раз в начале), чтобы повторный запуск не дублировал. Truncate `title ≤ 300`,
> `address ≤ 300`, `description ≤ 2000` чтобы не получать `413 Request entity too
> large` от Grist.

### Таблица `Arhiv_Prodano` (legacy read-only)

Это бывшая `Table1` (вкладка «Продано» в Google Sheets). Содержит 3 119 строк
исторических данных, написанных до Grist-миграции. **Read-only** — парсер туда
больше не пишет, новые снятые идут в `Sold_Ads`. Если в UI нужно посмотреть
историю — открывайте `Arhiv_Prodano` параллельно с `Sold_Ads`.

### Таблица `Balans` (ежедневный счётчик)

Пишется `services/category_counter` ежедневно. 8 колонок (A-H):
- `A`: дата MSK (DateTime:UTC)
- `B-E`: вторичка Мск, первичка Мск, первичка МО, вторичка МО (Numeric)
- `F`: Всего = B+C+D+E (записывается Python'ом, не формулой)
- `G`: точка равновесия (default 150 000)
- `H`: резерв

**Dedup:** `category_counter` перед записью проверяет, есть ли уже строка за
сегодня (Grist SQL: `now() - 36h`), чтобы не плодить дубликаты при повторных запусках.

### Status-колонка и условное форматирование

Колонка `status` (Text) есть в `Sold_Ads`, `Offers_Parser`, `Signals_Parser`,
`Table2` (Аванс), `Table3` (Аванс_Продано). Значения:

| Значение       | Когда ставится                          | UI цвет (Grist)  |
|----------------|-----------------------------------------|------------------|
| `active`       | Парсер нашёл активное, `views_per_day ≤ 200` | без цвета (default) |
| `hot`          | Активное с `views_per_day > 200`        | зелёный          |
| `signal`       | Сработал `signal_reason` (падение цены)  | жёлтый           |
| `deactivated`  | `is_active=False` при парсинге           | серый            |
| `deposited`    | Аванс/задаток внесён (режим avans)      | оранжевый        |

Conditional formatting настраивается **в Grist UI** (sidebar → column → Rules) —
не код. Парсер только пишет значение.

### Grist API контракт (важно)

- `GET /api/docs/{docId}/sql?q=<query>` — SELECT, возвращает `[{id, fields: {...}}]`
- `POST /api/docs/{docId}/apply` — body = **raw JSON-массив** action-ов
- `POST /api/docs/{docId}/tables/{tableId}/records` — body = `{"records": [{"fields": {...}}]}` (быстрее чем `/apply` с per-row `AddRecord`)
- `AddRecord` namedtuple: `(table_id, row_id, columns_dict)`, `row_id=None` для новых
- `BulkAddRecord` namedtuple: 4 поля, не всегда работает стабильно — предпочитаем `/records`
- Retry на 429/500/502/503/504 (до 5 раз с exponential backoff)
- Throttle через `GRIST_READ_SPACING_SEC` (default 0.05s)

### Синхронизация PG → Grist (batch)

| Скрипт                          | Источник (PG)   | Цель (Grist)  | Когда запускать            |
|---------------------------------|-----------------|---------------|----------------------------|
| `scripts/sync_sold_to_grist.py` | `sold_ads`      | `Sold_Ads`    | раз в сутки, после парсера |
| `scripts/sync_active_to_grist.py`| `active_ads`    | `Active_ads`  | раз в сутки, после парсера |
| `services/category_counter`     | Cian HTML       | `Balans`      | раз в сутки (09:00 MSK)    |
| `parsers/cian_active`           | flippercrawl    | `Offers_Parser / Signals_Parser / Sold_Ads` | каждые 6-12ч (10:00, 18:00 MSK) |

`sync_sold_to_grist.py` поддерживает:
- `--source cian_deactivated|cian_sold|domclick_sold|winners_sold` — фильтр
- `--limit N` — первые N строк (для теста)
- `--batch N` — размер пачки (default 2000, рекомендую 1000 для прод)
- `--dry-run` — только показать план без записи
- Skip-existing по `cian_id` — повторный запуск безопасен


---

## Сервис `parser_cian` → `parsers/cian_active`

### Режимы работы

Запускается с флагом `--mode`:

```
docker compose run --rm cian_active --mode offers
docker compose run --rm cian_active --mode avans
```

Дополнительные флаги:
- `--skip-links` — пропустить сбор ссылок, парсить только те URL, что уже есть в БД
- `--only-links` — только собрать ссылки с поисковых страниц в БД, без парсинга карточек

### Пайплайн выполнения

```
Step 1: Валидация конфигурации (.env)
Step 2: Инициализация (SQLite, Grist, Flippercrawl)
Step 3: Получение поисковых URL
         offers  → из таблицы FILTERS (Grist)
         avans   → статичный URL из config
Step 4: Извлечение ссылок объявлений из поисковых страниц
         (cianparser + ротация прокси из data/proxies.txt)
Step 5: Парсинг каждого объявления через Flippercrawl
         (N параллельных воркеров, QueueManager)
Step 6: Итоговый отчёт
```

### Парсинг одного объявления (AdParser)

Данные собираются из **трёх источников**:

1. **Flippercrawl static-экстракция** — JSON из state.offerData (цена, адрес, описание, история цен, ремонт, площадь, этажи и т.д.)
2. **rawHtml** — `creationDate` из встроенных JSON-LD скриптов страницы (точная дата публикации)
3. **Cian Statistics API** — `days_in_exposition`, `total_views`, `unique_views` (через API `/api/analytics/`)

Результат: модель `ParsedAdData` (Pydantic).

### Логика Worker (`QueueManager.worker`)

#### Режим `avans`

1. Парсим объявление → `ParsedAdData`
2. AI определяет `has_avans_deposit` (внесён ли аванс/задаток)
3. **Если AI нашла аванс**:
  - Если AI определила аванс/задаток и `days_in_exposition ≤ 7` → записать в **`Table3` (Аванс_Продано)** со status=`deposited`, удалить строку из **`Table2` (Аванс)** и удалить из БД
4. **Если снято с публикации** (`is_active = False`):
   - Удалить из **`Table2` (Аванс)** + из БД
   - Запись в `Sold_Ads` (status=`deactivated`) только для `mode=offers`
5. **Иначе** (активное, аванс не внесён):
   - Записать/обновить в **`Table2` (Аванс)** со status=`active`, обновить БД
   - Объявление будет спарсено повторно при следующем запуске

#### Режим `offers`

1. Парсим объявление → `ParsedAdData`
2. Вычисляем `signal_reason` (снижение цены ≥ 5% или ≥ 3 снижений за 30 дней)
3. Вычисляем `views_per_day = unique_views / days_in_exposition`
4. **Если снято с публикации** (`is_active = False`):
   - Удаляем из `active_ads` в БД → больше не парсим
   - Описание → «Объявление снято с публикации»
   - Если `days_in_exposition ≤ 7` → записываем в **`Sold_Ads`** со status=`deactivated` + удаляем/обновляем `Offers_Parser`
5. **Если активно**:
   - `views_per_day > 200` → `Offers_Parser` со status=`hot` + Telegram-уведомление
   - Сработал `signal_reason` → `Offers_Parser` + `Signals_Parser` со status=`signal` + Telegram
   - Иначе → `Offers_Parser` со status=`active`
   - Если критерий больше не выполняется → строка удаляется из соответствующей таблицы

> **С 2026-08-11 парсер пишет в `Sold_Ads` (Grist)** вместо legacy `Table1` (бывш.
> «Продано»). Запись через `GristClient.upsert_dict()` — атомарный upsert по `cian_id`.

---

## Сервис `category_counter`

Подсчитывает количество активных объявлений на Cian по четырём категориям:
- Вторичка Москва
- Первичка Москва
- Первичка МО
- Вторичка МО

Результат записывается во вкладку **Balans** (дата + количество по категориям + формула суммы + точка равновесия 150,000).

Скрейпинг HTML страниц Cian через `curl_cffi` с ротацией прокси из `data/proxies.txt`.

---

## Сервис `scheduler`

`scheduler` — единственный always-on сервис парсинга. Запускает остальные контейнеры через `docker compose run --rm` по расписанию.

### Расписание (MSK)

| Время | Задача |
|---|---|
| 09:00 | `category_counter` (Grist `Balans`) |
| 10:00 | `cian_active --mode avans`, затем `--mode offers` |
| 18:00 | `cian_active --mode avans`, затем `--mode offers` |
| 19:00 | `scripts/sync_active_to_grist.py` (Grist `Active_ads`) |
| 19:30 | `scripts/sync_sold_to_grist.py` (Grist `Sold_Ads`) |
| **Sun 06:00** | `winners_sold` (еженедельно) |
| **Sun 07:00** | `domclick_sold` (еженедельно) |

Остальные парсеры (`cian_sold`, `flatinfo_houses`) — **только вручную** через `docker compose run --rm <service>`.

> **Sync-скрипты** запускаются **после** парсера `cian_active`, чтобы подтянуть
> свежие deactivated в `Sold_Ads`. Skip-existing защищает от дублей при
> повторных запусках.

Scheduler автоматически:
- Запускает контейнеры через `docker compose run --rm` (тот же сценарий, что и при ручном запуске по SSH)
- Повторяет при ошибке (до 3 попыток с exponential backoff)
- Отправляет Telegram-алерты при сбоях
- Использует lock чтобы задачи не пересекались

---

## Структура парсеров (services/parsers/)

Все 5 парсеров следуют единому шаблону:

```
services/parsers/
├── _common.py                       # общий код (setup_logging, run_subprocess, safe_*)
│
├── cian_active/                     # активные CIAN (Flippercrawl + Grist)
│   ├── main.py                      # оркестратор
│   ├── config.py                    # Pydantic Settings (.env)
│   ├── importer.py                  # импорт из data/parser_cian.db → active_ads (filter_id 1-6)
│   ├── acquirer/                    # всё что нужно для парсинга
│   │   ├── cards.py                 # parse individual ads (Flippercrawl)
│   │   ├── search.py                # parse search pages
│   │   ├── queue.py                 # concurrency
│   │   ├── models.py                # Pydantic models
│   │   └── legacy_db/               # legacy CianFilter/CianActiveAd/CianSoldAd
│   │       ├── base.py
│   │       └── repository.py
│   ├── cianparser/                  # vendored
│   └── tests/                       # test_acquirer.py (15) + test_importer.py (5)
│
├── cian_sold/                       # снятые CIAN (deactivated_offers)
│   ├── main.py                      # оркестратор
│   ├── importer.py                  # result.jsonl → houses + sold_ads
│   └── acquirer/                    # subpackage (тяжёлый парсер)
│       ├── cli.py                   # CLI (--workers, --failed, ...)
│       ├── runner.py                # threading executor
│       ├── pipeline.py              # HousePipeline
│       ├── models.py
│       ├── config.py, cookies.py, errors.py, io.py, ...
│       ├── clients/                 # HTTP-клиенты
│       ├── test_cookies.py          # acquirer-internal unit tests
│       └── test_models.py
│   └── tests/                       # test_importer.py (13 тестов)
│
├── winners_sold/                    # baza-winner.ru (новостройки + вторичка)
│   ├── main.py
│   ├── acquirer.py                  # CLI парсера (--category new|secondary)
│   ├── filters.py                   # утилита (фильтр по круглой цене)
│   ├── exporter.py                  # JSON → xlsx
│   ├── importer.py
│   └── tests/                       # test_importer.py
│
├── domclick_sold/                   # domclick.ru (снятые)
│   ├── main.py
│   ├── acquirer.py                  # CLI (--mode list|cards|full)
│   ├── exporter.py                  # JSON → xlsx
│   ├── importer.py
│   └── tests/                       # test_importer.py
│
└── flatinfo_houses/                 # flatinfo.ru (реестр домов)
    ├── main.py
    ├── acquirer.py                  # детальные страницы домов
    ├── exporter.py                  # JSON → xlsx
    ├── houses.py                    # утилита (фильтрация списка)
    ├── houses_to_excel.py           # утилита
    ├── importer.py
    └── tests/                       # test_importer.py
```

**Единый шаблон** для всех парсеров:
- `main.py` — оркестратор (acquire → load → export)
- `acquirer.py` (или `acquirer/` для сложных) — данные из источника → JSON/JSONL
- `importer.py` — JSON → House/ActiveAd/SoldAd (через `packages/flipper_db`)
- `exporter.py` (опц.) — JSON → .xlsx
- `tests/` — pytest

---

## Ручной запуск парсеров

```bash
# Любой парсер можно дёрнуть руками:
docker compose run --rm cian_active --mode offers
docker compose run --rm cian_sold
docker compose run --rm winners_sold
docker compose run --rm domclick_sold
docker compose run --rm flatinfo_houses
```

---

## Общая БД (packages/flipper_db/)

Все парсеры используют единый пакет `packages/flipper_db/`:

```python
from packages.flipper_db import (
    init_db, FlipperRepository, House, ActiveAd, SoldAd, Source,
)
```

Схема в `packages/flipper_db/models.py` (cross-dialect — работает с PostgreSQL и SQLite для тестов).

### Идемпотентность

Все upsert-операции идемпотентны: `ON CONFLICT (source, external_id) DO UPDATE`. Повторный запуск парсера не плодит дубликаты.

### Source-теги

`Source` enum в `packages/flipper_db/enums.py`:
- `CIAN_ACTIVE = "cian_active"`
- `CIAN_SOLD = "cian_sold"`
- `WINNERS_SOLD = "winners_sold"`
- `DOMCLICK_SOLD = "domclick_sold"`
- `FLATINFO_HOUSES = "flatinfo_houses"`

---

## База данных (PostgreSQL)

### Таблицы

| Таблица | Назначение |
|---------|-----------|
| `houses` | Реестр домов (с `lat/lng`, `source`, `cian_house_id` для будущей карты) |
| `active_ads` | Активные объявления (только от `cian_active`); `filter_id` 1-6 = offers/signals/advance |
| `sold_ads` | Снятые/проданные объявления (от всех источников) |
| `geo_cache` | Кэш геокодирования (для будущей карты) |

### Текущее состояние (локальная БД, dev)

Актуальные цифры в **локальной PostgreSQL** (127.0.0.1:5432, `flipper`):

- **houses**: 30 868
  - `cian_ad`: 759
  - `cian_sold`: 1 149
  - `domclick_sold`: 578
  - `flatinfo_houses`: 28 382
- **active_ads**: 5 227 (все `cian_active`, 92.6% с `house_id`)
  - `filter_id=1-4` (offers): ~5 200
  - `filter_id=5` (signals: Опека): <50
  - `filter_id=6` (advance: Запрет долги): <50
- **sold_ads**: 233 314
  - `cian_active`: 18 375
  - `cian_deactivated`: 231 316
  - `domclick_sold`: 1 998

> Цифры меняются по мере reparse. Запросить свежие: `psql -h 127.0.0.1 -U flipper -d flipper -c "..."`.

### Миграция из старых источников

```bash
# 1. Из secondary/ JSON/JSONL
py -m scripts.migrate_secondary_files_to_postgres \
    --secondary ../secondary \
    --db "sqlite+aiosqlite:///data/secondary_migrated.db"

# 2. Из старой data/parser_cian.db (cian_active)
py -m scripts.migrate_cian_active_db \
    --source data/parser_cian.db \
    --db "sqlite+aiosqlite:///data/secondary_migrated.db"
```

Оба скрипта идемпотентны (ON CONFLICT DO UPDATE), BATCH_SIZE=1000.

### Схема-миграции (Alembic)

Сдекс-схема управляется через Alembic (`alembic/` dir, `alembic.ini` в корне).
Модели — в `packages/flipper_db/models.py`. См. `alembic/README.md` для
инструкций по adoption на существующей БД (`alembic stamp head`).

```bash
# Применить миграции в Docker:
docker compose run --rm api alembic upgrade head

# Сгенерировать миграцию из изменений моделей:
docker compose run --rm api alembic revision --autogenerate -m "add X to houses"
```

### Жизненный цикл записи (active_ads)

```
Новая ссылка с поисковой страницы (cian_active)
  ↓
houses (source=cian_active, external_house_id=...)
  ↓ парсинг Flippercrawl
active_ads (source=cian_active, filter_id=1..6, is_parsed=True)
  ↓
  ├─ is_active=True → остаётся, парсится повторно при следующем запуске
  ├─ is_active=False → перемещается в sold_ads, удаляется из active_ads
```

---

## Прокси

Файл: `data/proxies.txt` (формат: `host:port:user:password`, по строке).

Используются для:
- Скрейпинга поисковых страниц Cian (`cianparser`, `curl_cffi`)
- Скрейпинга категорий (`category_counter`)

Ротация: случайный выбор из списка для каждого запроса.

Flippercrawl работает со своими прокси/без прокси (отдельная инфраструктура).

---

## Telegram-уведомления

Отправляются при:
- `Offers_Parser Match` — объявление набрало ≥ 200 уникальных просмотров (подсветка)
- `Signals_Parser Match` — сработал сигнал снижения цены
- `Avans Match` — объявление из режима avans набрало ≥ 200 просмотров
- `Scheduler: <task> FAILED` — задача упала после 3 попыток

---

## Будущее: интерактивная карта

Архитектура закладывается под будущую интерактивную карту (2gis-style):
- Клик на дом → окошко с активными (`active_ads`) и снятыми (`sold_ads`) объявлениями
- Карта строится через `SELECT * FROM houses WHERE lat IS NOT NULL AND lng IS NOT NULL`
- Сшивка домов из разных источников через `cian_house_id`
- Данные готовы — нужна только визуализация (FastAPI + Leaflet/Mapbox)

См. `PLAN.md` секция 0 — это зафиксированный план.

---

## См. также

- `DEPLOY.md` — развёртывание на сервере
- `README.md` — общий обзор
- `PLAN.md` — детальный план реструктуризации 2026-07-25
- `archive/scorer/README.md` — как восстановить скоринг, если понадобится
