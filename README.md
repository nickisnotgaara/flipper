# Flipper

Единая система парсинга недвижимости с 5 источниками. Все парсеры
работают в одном docker-compose, пишут в общую PostgreSQL БД, подходят
для будущей интерактивной карты 2gis-style.

## Что внутри

5 парсеров:

| Сервис | Что парсит | Расписание |
|---|---|---|
| `cian_active` | Активные объявления CIAN (через Firecrawl + Google Sheets) | 10:00, 18:00 |
| `cian_sold` | Снятые публикации CIAN (deactivated_offers) | **вручную** |
| `winners_sold` | Снятые публикации baza-winner.ru | **Sun 06:00** (еженедельно) |
| `domclick_sold` | Снятые публикации domclick.ru | **Sun 07:00** (еженедельно) |
| `flatinfo_houses` | Реестр домов flatinfo.ru | **вручную** |

Все парсеры пишут в единую PostgreSQL БД (`houses`, `active_ads`, `sold_ads`)
через пакет `packages/flipper_db/`.

## Структура

```
flipper/
├── services/
│   ├── parsers/                      # 5 парсеров
│   │   ├── _common.py                # общий код
│   │   ├── cian_active/              # активные CIAN
│   │   ├── cian_sold/                # снятые CIAN
│   │   ├── winners_sold/             # baza-winner.ru
│   │   ├── domclick_sold/            # domclick.ru
│   │   └── flatinfo_houses/          # flatinfo.ru
│   ├── category_counter/             # подсчёт объявлений по категориям
│   ├── cookie_manager/               # Chromium + FastAPI для Firecrawl
│   ├── html_to_markdown/             # Go-сервис HTML → Markdown
│   └── scheduler/                    # APScheduler (cron-подобный)
│
├── packages/
│   ├── flipper_core/                 # sheets, utils, proxy_loader, html_to_md
│   ├── flipper_db/                   # ⭐ SQLAlchemy: houses, active_ads, sold_ads
│   └── go-html-to-md/                # Go-сервис
│
├── data/                             # proxies.txt, logs/
├── scripts/                          # миграция, утилиты
├── archive/                          # ⭐ scorer (в архиве, см. README внутри)
│
├── docker-compose.yml                # ⭐ 11 сервисов в одном compose
├── .env.example                      # шаблон переменных окружения
├── SYSTEM.md                         # детальная документация
├── DEPLOY.md                         # развёртывание на сервере
├── PLAN.md                           # история решений по реструктуризации
└── README.md                         # этот файл
```

## Быстрый старт

### 1. Подготовка

```bash
# Скопировать и заполнить .env
cp .env.example .env
nano .env  # заполнить FIRECRAWL_API_KEY, SPREADSHEET_ID, TG_BOT_TOKEN и т.д.

# Установить credentials Google
cp /path/to/credentials.json .

# Создать прокси-файл (если нужен)
echo "host:port:user:password" > data/proxies.txt
```

### 2. Запуск инфраструктуры

```bash
docker compose up -d              # app_postgres, app_redis, html_to_markdown,
                                # cookie_manager, scheduler
```

### 3. Первый запуск парсера вручную

```bash
docker compose run --rm cian_active --mode offers
docker compose run --rm cian_sold
docker compose run --rm winners_sold
docker compose run --rm domclick_sold
docker compose run --rm flatinfo_houses
```

### 4. Просмотр логов

```bash
docker compose logs -f scheduler
docker compose logs cian_active
docker compose logs winners_sold
```

## Тестирование

```bash
# Все тесты (pytest.ini настроен на все testpaths)
PYTHONPATH=. pytest -v

# Или локально (без docker):
cd /opt/flipper
PYTHONPATH=. pytest packages/flipper_db/tests services/parsers scripts/tests -v
```

Покрытие: **118 тестов** в 9 группах:
- `packages/flipper_db/tests/` — модели + repository (14)
- `services/parsers/tests/test_common.py` — общий код парсеров (9)
- `services/parsers/cian_active/tests/test_acquirer.py` — AdParser: Firecrawl, captcha, retry, URL fallback, cian_id='null'→URL (15)
- `services/parsers/cian_active/tests/test_importer.py` — маппинг ActiveAd + filter_id (6)
- `services/parsers/cian_sold/{acquirer,tests}/` — маппинг JSON → БД + acquirer-юниты (24)
- `services/parsers/winners_sold/tests/` — маппинг JSON → БД (11)
- `services/parsers/domclick_sold/tests/` — маппинг JSON → БД (11)
- `services/parsers/flatinfo_houses/tests/` — legacy + real format (16)
- `scripts/tests/` — миграция secondary + cian_active (12)

Все парсеры следуют единому шаблону:
- `main.py` — оркестратор (acquire → load → export)
- `acquirer.py` (или `acquirer/` для сложных) — данные из источника
- `importer.py` — JSON → `House/ActiveAd/SoldAd` через `packages/flipper_db`
- `exporter.py` (опц.) — JSON → .xlsx
- `tests/` — pytest

## Конфигурация (.env)

Основные переменные (полный список в `.env.example`):

```env
FIRECRAWL_API_KEY=local
FIRECRAWL_BASE_URL=http://flippercrawl-api-1:3002

SPREADSHEET_ID=your-spreadsheet-id
CREDENTIALS_PATH=/app/credentials.json

POSTGRES_PASSWORD=flipper_secret

TG_BOT_TOKEN=your-telegram-bot-token
TG_CHAT_ID=your-telegram-chat-id

# Расписание еженедельных парсеров
WEEKLY_RUN_DAY_OF_WEEK=sun
WEEKLY_WINNERS_HOUR=6
WEEKLY_DOMCLICK_HOUR=7
```

## Миграция существующих данных (один раз)

### 1. Из `secondary/` (JSON/JSONL от старых парсеров)

```bash
docker compose up -d app_postgres
docker compose run --rm cian_sold \
    python -m scripts.migrate_secondary_files_to_postgres \
        --secondary ../secondary \
        --db "postgresql+asyncpg://flipper:${POSTGRES_PASSWORD:-flipper_secret}@app_postgres:5432/flipper"
```

Что зальётся:
- `houses`: cian_sold 28k + domclick_sold 2k + flatinfo_houses 41k + winners_sold 110k
- `sold_ads`: cian_sold 231k + domclick_sold 2k + winners_sold 110k

### 2. Из старой `data/parser_cian.db` (SQLite с cian_active + offers/signals/advance)

```bash
docker compose run --rm cian_active \
    python -m scripts.migrate_cian_active_db \
        --source /app/data/parser_cian.db \
        --db "postgresql+asyncpg://flipper:${POSTGRES_PASSWORD:-flipper_secret}@app_postgres:5432/flipper"
```

Что зальётся:
- `active_ads`: cian_active 3,393 (filter_id 1-4 = offers, 5 = signals/Опека, 6 = advance/Запрет долги)
- `sold_ads`: cian_active 2

### 3. Проверить

```bash
docker compose exec app_postgres psql -U flipper -c "
  SELECT source, COUNT(*) FROM houses GROUP BY source;
  SELECT source, COUNT(*) FROM active_ads GROUP BY source;
  SELECT source, COUNT(*) FROM sold_ads GROUP BY source;
"
```

После успешной миграции можно удалить `secondary/` и `data/parser_cian.db`.

## Документация

- [SYSTEM.md](SYSTEM.md) — детальная архитектура, таблицы, расписание
- [DEPLOY.md](DEPLOY.md) — развёртывание на VPS
- [PLAN.md](../PLAN.md) — история решений по реструктуризации
- [archive/scorer/README.md](archive/scorer/README.md) — как восстановить скоринг

## Roadmap (за пределами этого этапа)

- 🌐 REST API (FastAPI) для UI
- 🗺️ Интерактивная карта 2gis-style (Leaflet/Mapbox)
- 📊 Своя веб-таблица вместо Google Sheets
- 🔄 Alembic для миграций схемы БД
