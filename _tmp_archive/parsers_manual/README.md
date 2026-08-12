# Архив ручных парсеров (запускаются вручную при необходимости)

> **Зачем архивировать?** Эти парсеры собирают разовые или редко нужные данные:
> дома (обновляются раз в несколько месяцев), старые снятые объявления (уже
> есть в БД, новые редки), вторичные источники. Автоматически их гонять
> нет смысла — зря тратят ресурсы и пишут в БД то, что уже там.

**Активные парсеры (НЕ трогать):** `services/parsers/cian_active/` (ежедневно),
`services/parsers/domclick_sold/` (еженедельно).

---

## Что здесь

| Папка | Что это | Источник | Объём данных | Когда запускать |
|-------|---------|----------|--------------|------------------|
| `flatinfo_houses/` | Реестр домов flatinfo.ru (Москва) | `https://flatinfo.ru/` | ~28 000 домов | Раз в 2-3 месяца (новых ЖК мало) |
| `winners_sold/` | Снятые публикации baza-winner.ru | `https://baza-winner.ru/` | ~5 000 ad/нед | Если нужен второй источник для сверки |
| `cian_sold/` | Снятые CIAN (deactivated_offers) | `https://www.cian.ru/...` | ~270 000 уже в БД | Если хочется свежих за последние дни |

---

## Как запустить вручную

### Подготовка

1. **Docker-стек должен быть поднят** (Postgres, Grist — обязательно):
   ```bash
   docker compose up -d
   ```
2. **Нужны актуальные cookies** — проверь что в `services/cookie_manager/cookies.json`
   есть валидные cookies для соответствующего сайта.
3. **Прокси** — для cian/winners парсеров нужен `data/proxies.txt`.

### Способ 1: через Docker compose (предпочтительно)

> Внимание: эти сервисы удалены из `docker-compose.yml`. Чтобы запустить,
> нужно либо временно вернуть их в compose, либо поднять руками (способ 2).

Восстанови блок сервиса в `docker-compose.yml` (см. как выглядит
`domclick_sold`), затем:
```bash
# Поднять домклик + плоский инфо разово
docker compose run --rm flatinfo_houses              # ~30 мин на 28k домов
docker compose run --rm winners_sold                 # ~2ч на 5k объявлений
docker compose run --rm cian_sold                    # ~4ч на свежие deactivated
```

### Способ 2: нативно (без Docker, через `_run_parser.cmd`)

> Применимо только к `flatinfo_houses` (для остальных нужно
> скопировать логику Docker-entrypoint.sh в cmd).

```cmd
# flatinfo — нативно
py -3.11 services\parsers\flatinfo_houses\main.py

# cian_sold / winners_sold — там Docker-only entrypoint,
# проще через способ 1.
```

### Способ 3: через `scripts/` (для одиночных прогонов)

Если нужен только импорт (без парсинга), используй `scripts/`:
```bash
# Импорт домов из data/result.xlsx → PG houses
py scripts/load_flatinfo_houses.py

# Импорт снятых из data/result.xlsx → PG sold_ads
py scripts/reparse_cian_sold_offerdata.py
```

---

## Где лежат данные после парсинга

| Парсер | Куда пишет | Что делать с данными |
|--------|------------|----------------------|
| `flatinfo_houses` | `data/result.json`, `data/result.xlsx`, `data/house_pages_result.xlsx` | Скрипт импорта: `py scripts/load_flatinfo_houses.py` |
| `winners_sold` | `data/result.json`, `data/result.xlsx` | Скрипт импорта: встроен в Dockerfile, или вручную через `packages/flipper_db/` |
| `cian_sold` | `data/result.json`, `data/result.jsonl`, `data/result.xlsx` | Скрипт: `py scripts/reparse_cian_sold_offerdata.py` (re-парс через flippercrawl) |

---

## Если нужно вернуть парсер в активный код

1. **Скопируй обратно:**
   ```bash
   cp -r _tmp_archive/parsers_manual/flatinfo_houses services/parsers/
   cp -r _tmp_archive/parsers_manual/winners_sold services/parsers/
   cp -r _tmp_archive/parsers_manual/cian_sold services/parsers/
   ```
2. **Восстанови блок** соответствующего сервиса в `docker-compose.yml`
   (можно скопировать с `domclick_sold` как шаблона).
3. **Если хочешь по расписанию** — добавь job в `services/scheduler/main.py`
   (пример — `job_weekly_domclick`).
4. **Обнови `services/parsers/__init__.py`** — раскомментируй.

---

## История архивации

- **2026-08-12** — выделены в `_tmp_archive/parsers_manual/`. Причина: ручной
  запуск достаточен, автозапуск не нужен (дома редко новые, снятые уже
  почти все в БД). Сэкономит CPU/прокси/cookie_manager.

  Сопутствующие правки:
  - `services/parsers/__init__.py` — обновлён docstring со списком
  - `services/parsers/_common.py` — обновлены примеры имён в docstring
  - `services/scheduler/main.py` — убран `job_weekly_winners` (больше не нужен)
  - `docker-compose.yml` — убраны сервисы `flatinfo_houses`, `winners_sold`, `cian_sold`
  - `AGENTS.md`, `README.md`, `SYSTEM.md` — обновлены (отдельный коммит)
