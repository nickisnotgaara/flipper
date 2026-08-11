# AGENTS.md

> **Audience:** AI-агенты (Mavis, Cursor, Claude Code, Aider и т.д.), работающие
> с этим проектом. Прочитай перед тем, как что-то менять.

## 1. База данных: source of truth = локальный PostgreSQL

**В dev БД = локальный PostgreSQL 18 на `127.0.0.1:5432`, а не Docker.**

| Параметр | Значение |
|---|---|
| Хост | `127.0.0.1` |
| Порт | `5432` |
| БД | `flipper` |
| User | `flipper` |
| Пароль | `flipper_secret` |
| DSN | `postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper` |

Docker-контейнер `app_postgres` (если поднят через `docker compose up -d app_postgres`)
содержит **старые/сырые данные** и **не должен** использоваться для разработки.
Он остался в compose исторически; на dev-машине либо не поднимается, либо
поднимается на другом порту через `docker-compose.override.yml` (`5434:5432`).

### Как проверить, что подключаешься к правильной БД

```bash
# Из shell (psql):
psql -h 127.0.0.1 -U flipper -d flipper -c "SELECT COUNT(*) FROM active_ads;"
# → 5227 (актуальные данные)
# Если 18171 — это Docker app_postgres, ОСТАНОВИСЬ и переключись.

# Из Python:
py -3.11 -c "
import asyncio, asyncpg
async def m():
    c = await asyncpg.connect('postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper')
    print('houses:', await c.fetchval('SELECT COUNT(*) FROM houses'))
    print('active_ads:', await c.fetchval('SELECT COUNT(*) FROM active_ads'))
    await c.close()
asyncio.run(m())
"
# → houses: 30868, active_ads: 5227
```

### Актуальные цифры в локальной БД (на 2026-08-10)

- `active_ads`: 5 227 (все `cian_active`, 92.6% с `house_id`)
- `houses`: 30 868 (cian_ad 759, cian_sold 1 149, domclick_sold 578, flatinfo 28 382)
- `sold_ads`: 233 314

Если видишь другие цифры — скорее всего ходишь в Docker-`app_postgres`, а не
в локальный PG.

## 2. Запуск проекта

**Не нужно поднимать Docker для разработки API/фронта.**

Минимальный сетап (API + фронт + БД):

```powershell
# 1. Убедиться, что PostgreSQL запущен
Get-Service postgresql-x64-18   # Status: Running

# 2. API (нативно, в одном окне)
cd C:\Users\User\Desktop\flipping\flipper
.\\_run_api.cmd
# Лог в _tmp_api.log. Слушает http://127.0.0.1:8001.

# 3. Фронт (в другом окне)
cd C:\Users\User\Desktop\flipping\flipper\web\next
npm run dev
# Слушает http://localhost:3000.
```

**Парсеры в dev обычно не запускаем** — данные уже актуальные. Если надо:
```bash
docker compose up -d app_redis html_to_markdown cookie_manager
cd ../flippercrawl && docker compose up -d
# Парсеры (отдельно, по одному):
docker compose run --rm cian_active --mode offers
```

## 3. Частые ошибки и как их избежать

### `socket.gaierror: [Errno 11001] getaddrinfo failed`
`DATABASE_URL` указывает на `app_postgres` или `host.docker.internal`, а
контейнер не поднят. Проверь `.env`:
```bash
Select-String -Path .env -Pattern "DATABASE_URL"
# Должно быть: postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
```

### API запускается, но `_tmp_api.log` показывает старую ошибку
Файл лога не перезаписывается при перезапуске, если uvicorn не успел получить
truncate. Это нормально — смотри последние 30 строк: `Get-Content _tmp_api.log -Tail 30`.

### `host.docker.internal` не резолвится в PowerShell без активного Docker networking
Всегда используй `127.0.0.1` в `.env` для нативного запуска. `host.docker.internal`
резолвится только когда поднят Docker Desktop.

### Порт 5432 занят → Docker-`app_postgres` перехватил
`app_postgres` в docker-compose.yml пробрасывает порт 5432 наружу. Если поднят —
локальный PG становится недоступен. Решения:
- Не поднимать `app_postgres` в dev (только `app_redis`, `html_to_markdown`, `cookie_manager`).
- Или поднять его на другом порту через `docker-compose.override.yml`:
  ```yaml
  services:
    app_postgres:
      ports: ["5434:5432"]
  ```

## 4. Что НЕ надо делать

- **Не поднимать `app_postgres` как основную БД** — там старые/сырые данные.
- **Не менять `DATABASE_URL` на `app_postgres:5432` для нативного dev-режима** —
  это попытка обойтись без локального PG, но получишь данные не из той базы.
- **Не удалять локальный PostgreSQL-сервис** — там живут все данные проекта.
- **Не запускать парсеры в dev без необходимости** — они затирают `is_active=false`
  записи в `active_ads`, и можно потерять актуальные данные до следующего reparse.

## 5. Полезные ссылки

- [README.md](README.md) — общий обзор
- [DEVELOPMENT.md](DEVELOPMENT.md) — полная инструкция по dev-сетапу
- [SYSTEM.md](SYSTEM.md) — детальная архитектура
- [DEPLOY.md](DEPLOY.md) — prod-сетап (Linux VPS, Docker)
- [PLAN.md](../PLAN.md) — история решений

## 6. Утилиты для проверки состояния БД

Скрипт-однострочник (Python), который проверяет обе БД и говорит, какая «правильная»:

```python
import asyncio, asyncpg

LOCAL = "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"
DOCKER = "postgresql://flipper:flipper_secret@127.0.0.1:5434/flipper"  # см. override

async def stats(dsn, label):
    try:
        c = await asyncpg.connect(dsn)
        ads = await c.fetchval("SELECT COUNT(*) FROM active_ads WHERE is_active=true")
        houses = await c.fetchval("SELECT COUNT(*) FROM houses")
        print(f"{label}: active_ads={ads}, houses={houses}")
        await c.close()
    except Exception as e:
        print(f"{label}: ERR {e}")

asyncio.run(stats(LOCAL, "LOCAL 127.0.0.1:5432 "))
asyncio.run(stats(DOCKER, "DOCKER 127.0.0.1:5434"))
```

Ожидаемый вывод:
```
LOCAL 127.0.0.1:5432 : active_ads=5227, houses=30868    ← правильная
DOCKER 127.0.0.1:5434: active_ads=18171, houses=187696  ← старая/сырая
```

## 1.1. Grist (UI-таблица для парсера + аналитика)

Self-hosted Grist на `http://localhost:8484` (GRIST_BASE в `.env`). Doc
`Parcing` (`GRIST_DOC=mDaHoGD6yahtxaqugwr5mK`) с 10 таблицами. Полная
схема и контракт API — в [SYSTEM.md](SYSTEM.md) → Grist schema.

**КРИТИЧНО: Grist API принимает только `tableId`** (латиницей, без пробелов),
не display-имя. Display-имена (русские) — только для UI.

| tableId         | Display         | Назначение                                |
|-----------------|-----------------|-------------------------------------------|
| `FILTERS`       | Фильтры         | URL для парсера                           |
| `Active_ads`    | Активные        | Текущие активные объявления               |
| `Sold_Ads`      | **Снятые**      | ⭐ ВСЕ снятые (270k+ строк). Парсер пишет сюда при `is_active=False`. |
| `Arhiv_Prodano` | Архив Продано   | Legacy-таблица 3 119 строк (read-only)    |
| `Offers_Parser` | Парсер Офферс   | Текущие результаты парсера                |
| `Signals_Parser`| Сигналы         | Срабатывания `signal_reason`              |
| `Table2`        | Аванс           | Активные авансовые                        |
| `Table3`        | Аванс_Продано   | Снятые авансовые                          |
| `Balans`        | Баланс          | Ежедневный счётчик `category_counter`     |
| `Houses2`       | База домов      | Реестр домов (lat/lng/year)               |

### Железные правила для AI-агентов

1. **При `is_active=False` парсер пишет в `Sold_Ads`** (а НЕ в `Arhiv_Prodano`).
   `Arhiv_Prodano` — read-only legacy, парсер туда НЕ пишет. Это переименованный
   `Table1` (бывш. «Продано» в Google Sheets).
2. **`status` колонка** есть во всех парсер-таблицах (`Sold_Ads`,
   `Offers_Parser`, `Signals_Parser`, `Table2`, `Table3`). Значения:
   `active | hot (>200 views/day) | signal | deactivated | deposited`.
   Пишется **Python'ом** (не формулой). Conditional formatting — в Grist UI.
3. **НЕ выдумывай display-имя** как аргумент. `g.upsert_dict("Снятые", ...)` →
   `KeyError`. Используй только `tableId` (`"Sold_Ads"`).
4. **Cyrillic в tableId НЕ работает.** Rename `Table1` → `Архив_Продано` тихо
   отбрасывает изменения. Используй латиницу: `Arhiv_Prodano`.
5. **Bulk insert:** `POST /api/docs/{id}/tables/{t}/records` с
   `{"records": [{"fields": {...}}]}` (~415 rows/s при batch=1000).
   НЕ используй `BulkAddRecord` action — у него странная сигнатура в этой
   версии Grist (часто падает с `column_values missing`).
6. **Truncate `description` > 2000** chars перед write — иначе Grist вернёт
   `413 Request entity too large`. `sync_sold_to_grist.py` уже это делает.
7. **Skip-existing по `cian_id`** в batch-скриптах. Повторный запуск
   безопасен (не дублирует).
8. **Grist `/apply` body — raw JSON-массив**, не обёртка `{"actions": ...}`.
9. **Retry на 429/500/502/503/504**, не на 413. `GristClient` обрабатывает
   автоматически.

### Когда менять схему Grist

- **Новая колонка** — через `GistClient.apply([["AddColumn", "Sold_Ads",
  "colname", {"type": "Text", "label": "..."}]])`. Можно и в UI (Settings →
  Columns → Add). После — перезапусти `category_counter` или
  `sync_sold_to_grist.py`, чтобы Python начал писать.
- **Новая таблица** — `apply([["AddTable", "TableId", [{...col spec...}]]])`.
  Потом отдельно `AddColumn` для каждой **формульной** колонки (`isFormula:
  True`).
- **Переименование таблицы** — `apply([["RenameTable", "oldId", "newId"]])`.
  Cyrillic в `newId` — НЕ работает. После — обнови `config.py` парсера и все
  ссылки в коде.
- **Удаление таблицы** — `apply([["RemoveTable", "TableId"]])`. Необратимо.
