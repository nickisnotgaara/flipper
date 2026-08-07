# Flipper — Система мониторинга недвижимости

## Архитектура

Система состоит из нескольких Docker-контейнеров, управляемых через `docker-compose.yml`:

| Сервис | Назначение | Расписание |
|--------|-----------|------------|
| `app_postgres` | PostgreSQL — единая БД для всех парсеров (таблицы `houses`, `active_ads`, `sold_ads`) | always-on |
| `app_redis` | Redis для `cookie_manager` | always-on |
| `html_to_markdown` | Go-сервис конвертации HTML → Markdown (для `cian_active`) | always-on |
| `cookie_manager` | Микросервис управления cookies для Firecrawl (Chromium + FastAPI) | always-on |
| `scheduler` | APScheduler: cron-подобный запуск парсеров | always-on |
| `cian_active` | **Активные** объявления CIAN через Firecrawl + Google Sheets | 10:00, 18:00 |
| `category_counter` | Подсчёт объявлений CIAN по категориям (вкладка `Balans`) | 09:00 |
| `cian_sold` | **Снятые публикации** CIAN (deactivated_offers) → PostgreSQL | **вручную** |
| `winners_sold` | Снятые публикации baza-winner.ru → PostgreSQL | **Sun 06:00** (еженедельно) |
| `domclick_sold` | Снятые публикации domclick.ru → PostgreSQL | **Sun 07:00** (еженедельно) |
| `flatinfo_houses` | Реестр домов flatinfo.ru → PostgreSQL | **вручную** |

Внешняя зависимость: **self-hosted Firecrawl** (отдельный docker-compose, сеть `firecrawl_backend`).

---

## Архитектура данных

Все парсеры пишут в **единую PostgreSQL БД** (`app_postgres` Docker-контейнер,
том `pgdata`) через пакет `packages/flipper_db/`. Native PostgreSQL на хосте
**не используется** — все сервисы (api, парсеры, scheduler, pipeline_runner)
ходят в `app_postgres:5432` (изнутри compose-сети) через единый `DATABASE_URL`
в `.env`. Схема-миграции — через Alembic (см. раздел "Схема-миграции" ниже).

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

`active_ads.filter_id` — связь с `cian_filters` (Google Sheets → вкладки):
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
Step 2: Инициализация (SQLite, Google Sheets, Firecrawl)
Step 3: Получение поисковых URL
         offers  → из вкладки FILTERS (Google Sheets)
         avans   → статичный URL из config
Step 4: Извлечение ссылок объявлений из поисковых страниц
         (cianparser + ротация прокси из data/proxies.txt)
Step 5: Парсинг каждого объявления через Firecrawl
         (N параллельных воркеров, QueueManager)
Step 6: Итоговый отчёт
```

### Парсинг одного объявления (AdParser)

Данные собираются из **трёх источников**:

1. **Firecrawl AI-экстракция** — JSON-схема через LLM (цена, адрес, описание, история цен, ремонт, площадь, этажи и т.д.)
2. **rawHtml** — `creationDate` из встроенных JSON-LD скриптов страницы (точная дата публикации)
3. **Cian Statistics API** — `days_in_exposition`, `total_views`, `unique_views` (через API `/api/analytics/`)

Результат: модель `ParsedAdData` (Pydantic).

### Логика Worker (`QueueManager.worker`)

#### Режим `avans`

1. Парсим объявление → `ParsedAdData`
2. AI определяет `has_avans_deposit` (внесён ли аванс/задаток)
3. **Если AI нашла аванс**:
  - Если AI определила аванс/задаток и `days_in_exposition ≤ 7` → записать в **«Аванс_Продано»**, удалить строку из **«Аванс»** и удалить из БД (перестать отслеживать)
4. **Если снято с публикации** (`is_active = False`):
   - Удалить из **«Аванс»** + из БД
   - «Продано» фиксируется только для `mode=offers` и только если `days_in_exposition ≤ 7`
5. **Иначе** (активное, аванс не внесён):
   - Записать/обновить в **«Аванс»** (без цвета), обновить БД
   - Объявление будет спарсено повторно при следующем запуске

#### Режим `offers`

1. Парсим объявление → `ParsedAdData`
2. Вычисляем `signal_reason` (снижение цены ≥ 5% или ≥ 3 снижений за 30 дней)
3. **Если снято с публикации** (`is_active = False`):
   - Удаляем из `active_ads` в БД → больше не парсим
   - Описание → «Объявление снято с публикации»
   - Если `days_in_exposition ≤ 7` → записываем во вкладку **«Продано»**
4. **Если активно**:
   - Если `unique_views ≥ 200` → **Offers_Parser** + Telegram-уведомление
   - Если сработал `signal_reason` → **Signals_Parser** + Telegram-уведомление
   - Если критерий больше не выполняется → строка удаляется из соответствующей вкладки

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
| 09:00 | `category_counter` |
| 10:00 | `cian_active --mode avans`, затем `--mode offers` |
| 18:00 | `cian_active --mode avans`, затем `--mode offers` |
| **Sun 06:00** | `winners_sold` (еженедельно) |
| **Sun 07:00** | `domclick_sold` (еженедельно) |

Остальные парсеры (`cian_sold`, `flatinfo_houses`) — **только вручную** через `docker compose run --rm <service>`.

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
├── cian_active/                     # активные CIAN (Firecrawl + Google Sheets)
│   ├── main.py                      # оркестратор
│   ├── config.py                    # Pydantic Settings (.env)
│   ├── importer.py                  # импорт из data/parser_cian.db → active_ads (filter_id 1-6)
│   ├── acquirer/                    # всё что нужно для парсинга
│   │   ├── cards.py                 # parse individual ads (Firecrawl)
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

### Текущее состояние (после полной миграции данных)

- **houses**: 181,454
  - `cian_sold`: 28,242
  - `domclick_sold`: 2,000
  - `flatinfo_houses`: 41,489
  - `winners_sold`: 109,723
- **active_ads**: 3,393 (все `cian_active`)
  - `filter_id=1` (offers: до 2000г не-ЦАО): 1,451
  - `filter_id=2` (offers: после 2000г не-ЦАО): 1,287
  - `filter_id=3` (offers: до 2000г ЦАО): 468
  - `filter_id=4` (offers: после 2000г ЦАО): 160
  - `filter_id=5` (signals: Опека): 18
  - `filter_id=6` (advance: Запрет долги): 9
- **sold_ads**: 343,044
  - `cian_active`: 2
  - `cian_sold`: 231,319
  - `domclick_sold`: 2,000
  - `winners_sold`: 109,723

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
  ↓ парсинг Firecrawl
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

Firecrawl работает со своими прокси/без прокси (отдельная инфраструктура).

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
