# Domclick v2: интеграция в общий pipeline (SourceParser Protocol)

Дата: 2026-08-05
Область: `C:\Users\User\Desktop\flipping\flipper`
Связанные документы: `docs/ARCHITECTURE_V3.md`, `SYSTEM.md`

**Статус:** ✅ РЕАЛИЗОВАНО (все 5 фаз + Phase 1.0)

---

## Реализация (2026-08-05)

**Phase 1.0 — Расширение Protocol для sold-источников:**
- `packages/flipper_db/parser_types.py`: `is_sold_source: bool` в SourceParser Protocol
- `packages/flipper_db/pipeline.py`: добавлены `_extract_sold_date`, `_extract_exposition_days`, `_upsert_sold_ad`; ветка в `_process_one_ad` для sold-источников
- `packages/flipper_db/sources/cian.py`: CianSource.is_sold_source = False

**Phase 1 — DomclickSource:**
- `packages/flipper_db/sources/domclick.py` (21 KB): SourceParser для domclick.ru
- `packages/flipper_db/sources/tests/test_domclick_source.py` (34 unit-теста)
- `packages/flipper_db/sources/tests/fixtures/domclick-offer.html` (442 KB fixture)
- `packages/flipper_db/sources/__init__.py` + `packages/flipper_db/__init__.py` — экспорт

**Phase 2 — scripts/run_pipeline.py:**
- `scripts/run_pipeline.py` — добавлен `domclick_sold` в SOURCES
- Новые флаги: `--from-links FILE` (читает id из файла/JSON), `--full-cycle` (acquirer + pipeline)
- `_load_ad_ids_from_table` — параметризована через `ad_table` (active_ads / sold_ads)

**Phase 3 — services/parsers/domclick_sold/:**
- `main.py` — переписан как тонкий wrapper v2 (--mode {list, pipeline, backfill, full})
- Удалено: `importer.py`, `exporter.py`, `domclick_result.json`, `domclick_result.xlsx`
- `acquirer.py` — оставлен как есть (list-сборщик)
- `requirements.txt` — очищен (asyncpg, httpx)
- `__init__.py` — обновлён

**Phase 4 — scheduler:**
- `services/scheduler/main.py` — увеличен `JOB_TIMEOUT_WEEKLY` с 2ч до 4ч (для запаса)
- `job_weekly_domclick` уже работает с новым main.py через `python -m services.parsers.domclick_sold.main`
- Расписание: Sun 07:00 MSK weekly (без изменений)

**Phase 5 — E2E verify (локально):**
- ✅ 56/56 unit-тестов прошли (34 Domclick + 22 regression)
- ✅ E2E upsert: `parse_ad(fixture) → _upsert_sold_ad → БД` — работает
- ✅ Idempotent: повторный upsert = update (не insert)
- ✅ В БД: price_history, photos, lat/lng, sold_date, exposition_days — все 100% заполнены
- ⚠️ Live fetch с реального domclick.ru требует валидной cookie (DOMCLICK_PAGE_COOKIE env)

---

## Команды для backfill на проде

### Обновить cookie для domclick

Cookie протухает (Qrator session ~1-3 мес). Способ 1 — env:
```bash
# На сервере (в .env или docker-compose)
DOMCLICK_PAGE_COOKIE="qrator_jsr=...; qrator_jsid2=...; ns_session=...; ..."

# Или в Dockerfile / compose env_file
```

Способ 2 — обновить константу `_DEFAULT_PAGE_COOKIE` в `packages/flipper_db/sources/domclick.py`:
```python
_DEFAULT_PAGE_COOKIE = "<новая cookie из браузера>"
```

### Запустить полный backfill (2 000 записей)

```bash
# На сервере через docker
docker compose run --rm domclick_sold --mode backfill

# Или с локального dev (с прод-БД)
DATABASE_URL=postgresql+asyncpg://flipper:...@app_postgres:5432/flipper \
DOMCLICK_PAGE_COOKIE="..." \
python -m services.parsers.domclick_sold.main --mode backfill
```

### Запустить полный цикл (list + pipeline) — еженедельно Sun 07:00

```bash
# Через scheduler (автоматически)
# Или вручную:
docker compose run --rm domclick_sold --mode full
```

### Chunked backfill (если не влезает в 4ч)

```bash
# По 500 за раз
for offset in 0 500 1000 1500; do
  docker compose run --rm domclick_sold --mode backfill --limit 500 --offset $offset
done
```

### Verify в БД

```sql
-- Сколько всего domclick_sold в БД
SELECT COUNT(*) FROM sold_ads WHERE source='domclick_sold';

-- С price_history
SELECT COUNT(*) FROM sold_ads
WHERE source='domclick_sold'
  AND raw_data->'originalProduct'->'price_info'->'price_history' IS NOT NULL;

-- С lat/lng
SELECT COUNT(*) FROM sold_ads
WHERE source='domclick_sold' AND lat IS NOT NULL AND lng IS NOT NULL;

-- С house_id (linker нашёл)
SELECT COUNT(*) FROM sold_ads
WHERE source='domclick_sold' AND house_id IS NOT NULL;

-- С sold_date
SELECT COUNT(*) FROM sold_ads
WHERE source='domclick_sold' AND sold_date IS NOT NULL;
```

---

## 0. Контекст

**Задача:** подключить domclick.ru к общему pipeline (v2 SourceParser Protocol), наравне с cian. Источник даёт BFF-API для списка + HTML-карточки с SSR JSON. Источник был DEFERRED в v3 ("нет публичного read API") — сейчас read API найден, переходим в active.

**Решения, принятые в ходе grill-me (3/3 по рекомендации):**
1. **Backfill** — оставить 2 000 существующих + перепарсить через v2 (upsert идемпотентный, дубликатов не будет)
2. **Legacy** — заменить старый `services/parsers/domclick_sold/` на v2 pipeline (exporter.py удалить, acquirer.py оставить как list-сборщик)
3. **Расписание** — Sun 07:00 weekly (без изменений)

---

## 1. Цель

- Спарсить **проданные** объявления domclick.ru → PostgreSQL (`sold_ads.source='domclick_sold'`)
- **Расширить набор полей** по сравнению со старым парсером: `price_history`, `sold_price`, `description`, `lat/lng` (из JSON-LD)
- **Backfill** 2 000 уже сохранённых записей через v2 pipeline
- **Расписание:** Sun 07:00 weekly
- **Без Google Sheets** (exporter.py удалить, как и для cian_sold)
- **Повторное использование v2-инфраструктуры:** `SourceParser` Protocol, `AdRecord`, `run_source_pipeline`, `linker.match_or_create_house`

---

## 2. Что уже есть (v2-инфраструктура, НЕ трогаем)

| Компонент | Файл | Назначение |
|---|---|---|
| `SourceParser` Protocol | `packages/flipper_db/parser_types.py` | `AdRecord`, `HouseRecord`, `fetch_ad_page`, `parse_ad`, `house_record_from_ad` |
| `CianSource` | `packages/flipper_db/sources/cian.py` | референс для нашей реализации |
| `run_source_pipeline()` | `packages/flipper_db/pipeline.py` | общий pipeline (fetch → parse → match house → upsert → stale cleanup) |
| `linker.match_or_create_house()` | `packages/flipper_db/linker.py` | address-first + spatial fallback (75m cKDTree) |
| `House` model | `packages/flipper_db/models.py` | `House.domclick_house_id` уже есть (для кросс-источниковой сшивки) |
| `run_pipeline.py` CLI | `scripts/run_pipeline.py` | `--source cian_active --fetch-missing/--recent/--ids` |
| Старый парсер | `services/parsers/domclick_sold/` | работает, но узкий набор полей, не SourceParser |

---

## 3. Архитектура v2 для domclick

### 3.1. Поток данных

```
[Domclick BFF API] → acquirer.py (list, sold_sale, Москва)
                              ↓
                domclick_links.json (slim: path, publishedDate, soldDate, id)
                              ↓
[Domclick HTML /card/sale__flat__ID/] ← DomclickSource.fetch_ad_page()
                              ↓
                       DomclickSource.parse_ad(html)
                              ↓
                          AdRecord (raw_data = productCard.originalProduct)
                              ↓
              run_source_pipeline (generic, v2)
                              ↓
            linker.match_or_create_house (address → spatial fallback)
                              ↓
        upsert houses / sold_ads (идемпотентный ON CONFLICT DO UPDATE)
```

### 3.2. Идентификация и dedup

- **external_id** = `id` (BIGINT, пример: `2069491413`)
- **source** = `'domclick_sold'`
- **Unique key** в `houses`: `(source, external_house_id)` (т.е. `(domclick_sold, id)`)
- **Unique key** в `sold_ads`: `(source, external_id)` (т.е. `(domclick_sold, id)`)
- **is_active** = всегда `False` (domclick_sold парсит **только снятые** объявления, `deal_type=sold_sale`)

### 3.3. Связь с домами

- Linker ищет по `(street, house_num)` через flatinfo-индекс
- Из `address.displayName` ("Москва, улица Саморы Машела, 8 к3") парсим:
  - `street = "Саморы Машела"`, `house_num = "8 к3"` (через `linker.extract_street_house` или новый хелпер)
- Если address не сматчился — spatial fallback (75m) по `lat/lng` из JSON-LD
- Если ничего — `house_id = None`, ad всё равно сохраняется (`sold_ads.house_id NULL`)

---

## 4. Изменения файлов

### 4.0. Phase 1.0 — расширить v2 pipeline для sold-источников (Variant A)

**Проблема:** текущий `run_source_pipeline` всегда UPSERT в `active_ads` и перемещает в `sold_ads` только если ad раньше был в `active_ads` (stale cleanup). Для domclick_sold это не сработает — `is_active=False` всегда, в `active_ads` его никогда не было → попадёт в `active_ads` с `is_active=False` (неправильно).

**Решение:** добавить опциональный флаг `is_sold_source: bool = False` в `SourceParser` Protocol. Если `True` — pipeline пишет сразу в `sold_ads`, минуя `active_ads` и stale cleanup.

**Файлы:**

| Файл | Изменение |
|---|---|
| `packages/flipper_db/parser_types.py` | В `SourceParser` Protocol добавить `is_sold_source: bool` (default False, обратная совместимость) |
| `packages/flipper_db/pipeline.py` | В `_process_one_ad`: проверить `source.is_sold_source` — если True, ветка: сразу `_upsert_sold_ad` + skip stale cleanup |
| `packages/flipper_db/sources/cian.py` | Явно `is_sold_source = False` (для ясности; раньше было implicit) |
| `packages/flipper_db/sources/domclick.py` | `is_sold_source = True` |

**Изменения в pipeline.py (~30 строк):**
- Добавить функцию `_upsert_sold_ad` (по аналогии с `_upsert_ad`, но в `sold_ads`)
- В `_process_one_ad`: если `source.is_sold_source`:
  - вызвать `_upsert_sold_ad(...)` вместо `_upsert_ad(...)`
  - skip `_was_previously_active` и `_move_to_sold` (не нужны)
- `sold_date` берём из `ad.raw_data["originalProduct"]["soldDate"]` или `ad.publish_date` (если нет)

**Совместимость:** CianSource (`is_sold_source=False`) работает как раньше — все существующие тесты и продакшен не ломаются.

### 4.1. Создать

| Файл | Содержимое |
|---|---|
| `packages/flipper_db/sources/domclick.py` | `DomclickSource` класс (~400 строк) — референс `sources/cian.py` |
| `packages/flipper_db/sources/tests/test_domclick_source.py` | unit-тесты на parse_ad (fixture: `services/parsers/domclick_sold/offer-page.html`) |
| `packages/flipper_db/sources/tests/fixtures/domclick-offer.html` | копия offer-page.html для тестов |

### 4.2. Обновить

| Файл | Что меняется |
|---|---|
| `packages/flipper_db/sources/__init__.py` | Экспорт `DomclickSource` |
| `packages/flipper_db/__init__.py` | Добавить в `__all__` |
| `scripts/run_pipeline.py` | Добавить `domclick_sold` в `SOURCES`; флаг `--list-from-acquirer` для первичного сбора |
| `services/parsers/domclick_sold/main.py` | Полностью переписать: list-сбор → v2 pipeline |
| `services/parsers/domclick_sold/acquirer.py` | **Оставить** как есть (list-сборщик, уже работает) |
| `services/scheduler/main.py` | Заменить `domclick_sold` job: вызов нового v2 pipeline через `run_pipeline.py` |

### 4.3. Удалить

| Файл | Почему |
|---|---|
| `services/parsers/domclick_sold/importer.py` | заменён `run_source_pipeline` |
| `services/parsers/domclick_sold/exporter.py` | Google Sheets не нужны (по решению пользователя) |
| `services/parsers/domclick_sold/domclick_result.json` | legacy output |
| `services/parsers/domclick_sold/domclick_result.xlsx` | legacy output |
| `services/parsers/domclick_sold/domclick_links.json` | legacy (но формат совместим — можно оставить как transient артефакт) |

---

## 5. Детальный дизайн `DomclickSource`

### 5.1. SourceParser-атрибуты

```python
class DomclickSource:
    source_name: str = "domclick_sold"   # ключ в БД и run_pipeline.py SOURCES
    source_label: str = "ДомКлик"          # для UI
    has_house_pages: bool = False          # всё в карточке объявления
```

### 5.2. Метод `fetch_ad_page(ext_id)`

```python
async def fetch_ad_page(self, external_id: str) -> Optional[str]:
    url = f"https://domclick.ru/card/sale__flat__{external_id}/"
    # GET с PAGE_COOKIE из acquirer.py + headers
    # 200 → return html text
    # 404 / 401 / 5xx → return None
```

**Reuse:** логика retry и headers — из существующего `acquirer.py:http_get, retry_get, PAGE_HEADERS, PAGE_COOKIE`. Вынести PAGE_COOKIE в env (`DOMCLICK_PAGE_COOKIE`) для ротации.

### 5.3. Метод `parse_ad(html)`

```python
def parse_ad(self, html: str) -> Optional[AdRecord]:
    ssr = extract_ssr_state_json(html)              # переиспользуем из acquirer.py
    pc = ssr.get("productCard") or {}
    orig = pc.get("originalProduct") or {}
    if not orig: return None

    oi = orig.get("object_info") or {}
    house = orig.get("house") or {}
    price_info = orig.get("price_info") or {}
    addr = orig.get("address") or {}
    subways = addr.get("subways") or []
    first_subway = subways[0] if subways else {}

    # lat/lng из JSON-LD schema.org/GeoCoordinates
    lat, lng = _extract_lat_lng_from_jsonld(html)

    return AdRecord(
        external_id=str(orig["id"]),
        external_house_id=str(orig["id"]),  # domclick = id ad == id house (нет отдельного house id)
        cian_house_id=None,
        url=f"https://domclick.ru/card/sale__flat__{orig['id']}",
        is_active=False,                     # всегда sold
        raw_data={                           # ВЕСЬ originalProduct
            "originalProduct": orig,
            "pc_href": pc.get("href"),
            "jsonld_lat": lat,
            "jsonld_lng": lng,
        },
        price=safe_int(price_info.get("price")),
        price_per_m2=safe_int(price_info.get("square_price")),
        area=safe_float(oi.get("area")),
        rooms=safe_int(oi.get("rooms")),
        floor_current=safe_int(oi.get("floor")),
        floor_total=safe_int(house.get("floors")),
        address=addr.get("display_name"),
        lat=lat, lng=lng,
        publish_date=orig.get("published_dt"),  # ISO → парсится в pipeline
        metro_station=first_subway.get("display_name") or first_subway.get("name"),
        metro_walk_time=first_subway.get("remoteness", {}).get("time"),
        district=_extract_parent_by_kind(addr, "district"),
        okrug=_extract_okrug(addr),
        renovation=_extract_renovation(oi),
    )
```

### 5.4. `house_record_from_ad(ad)` (опц.)

- Достаёт `external_house_id = ad.external_id` (тот же id)
- `address`, `lat`, `lng`, `year_built` = `house.build_year`, `levels` = `house.floors`, `building_type` = `house.wall_type.display_name`
- `raw_data = {"house": house, "address": addr}` (slice из `originalProduct`)

### 5.5. Helper'ы

- `_extract_lat_lng_from_jsonld(html)` — regex по `"latitude": (\d+\.\d+).*"longitude": (\d+\.\d+)`
- `_extract_parent_by_kind(addr, kind)` — пройти `address.parents[]`, найти `kind == kind`
- `_extract_okrug(addr)` — пройти `address.parents[]`, найти `name` содержит "округ" (case-insensitive)
- `_extract_renovation(object_info)` — `object_info.renovation.display_name`

### 5.6. Тесты

```python
def test_parse_ad_returns_record():
    html = (Path(__file__).parent / "fixtures" / "offer-page.html").read_text(...)
    src = DomclickSource()
    ad = src.parse_ad(html)
    assert ad is not None
    assert ad.external_id == "2069491413"
    assert ad.price == 12690000
    assert ad.area == 52.0  # или что в fixture
    assert ad.raw_data["originalProduct"]["price_info"]["price_history"]  # есть
    assert ad.lat is not None and ad.lng is not None
```

---

## 6. Phased Execution

### Phase 1: DomclickSource (1.5 часа)

- [ ] **1.1** Создать `packages/flipper_db/sources/domclick.py` (~400 строк)
  - `DomclickSource` класс
  - `fetch_ad_page` (reuse http helper из acquirer.py)
  - `parse_ad` (reuse `extract_ssr_state_json` из acquirer.py)
  - `house_record_from_ad`
  - helpers: `_extract_lat_lng_from_jsonld`, `_extract_parent_by_kind`, `_extract_okrug`, `_extract_renovation`
- [ ] **1.2** Обновить `packages/flipper_db/sources/__init__.py` (экспорт)
- [ ] **1.3** Обновить `packages/flipper_db/__init__.py` (добавить в `__all__`)
- [ ] **1.4** Скопировать fixture: `services/parsers/domclick_sold/offer-page.html` → `packages/flipper_db/sources/tests/fixtures/domclick-offer.html`
- [ ] **1.5** Создать `packages/flipper_db/sources/tests/test_domclick_source.py` (3-5 тестов)
- [ ] **1.6** Прогнать тесты: `pytest packages/flipper_db/sources/tests/`

### Phase 2: run_pipeline.py (30 мин)

- [ ] **2.1** Добавить в `SOURCES = {"cian_active": CianSource, "domclick_sold": DomclickSource}`
- [ ] **2.2** Добавить флаг `--list-from-acquirer` (для domclick_sold): запускает `acquirer.py` → `domclick_links.json`, затем `run_source_pipeline` с этими ids
- [ ] **2.3** Smoke test: `python scripts/run_pipeline.py --source domclick_sold --fetch-missing --limit 5` (должен отработать без ошибок)

### Phase 3: services/parsers/domclick_sold/ (1 час)

- [ ] **3.1** Переписать `main.py` (оркестратор v2):
  - `python main.py --list` → `acquirer.py` → `domclick_links.json`
  - `python main.py --pipeline` → `run_pipeline.py --source domclick_sold --ids domclick_links.json`
  - `python main.py --backfill` → `run_pipeline.py --source domclick_sold --fetch-missing`
- [ ] **3.2** `acquirer.py` оставить как есть (уже работает)
- [ ] **3.3** Удалить `importer.py`, `exporter.py`
- [ ] **3.4** Удалить legacy артефакты: `domclick_result.json`, `domclick_result.xlsx` (опц.)

### Phase 4: Scheduler (30 мин)

- [ ] **4.1** Обновить `services/scheduler/main.py`:
  - Удалить старый `domclick_sold` job (вызов `acquirer.py + importer.py`)
  - Добавить новый: Sun 07:00 → `run_pipeline.py --source domclick_sold --fetch-missing` (через существующий `run_docker_compose` хелпер)
- [ ] **4.2** Обновить расписание в `SYSTEM.md` (таблица)

### Phase 5: Backfill & Verify (1-2 часа на выполнение)

- [ ] **5.1** Локально: `python scripts/run_pipeline.py --source domclick_sold --fetch-missing --limit 5` (smoke)
- [ ] **5.2** Полный backfill: `docker compose run --rm cian_sold python scripts/run_pipeline.py --source domclick_sold --fetch-missing` (или новый service)
  - 2 000 объявлений × ~3 сек (HTML fetch + parse) = ~1.5 часа
- [ ] **5.3** Verify в БД:
  - `SELECT COUNT(*) FROM sold_ads WHERE source='domclick_sold' AND raw_data->'originalProduct'->'price_info'->'price_history' IS NOT NULL;` → должен быть > 0
  - `SELECT COUNT(*) FROM sold_ads WHERE source='domclick_sold';` → должно быть >= 2 000
  - Проверить несколько id вручную через `SELECT * FROM sold_ads WHERE external_id='2069491413';`

---

## 7. Acceptance Criteria

- [ ] `python -c "from packages.flipper_db.sources.domclick import DomclickSource; s=DomclickSource(); print(s.source_name)"` → `domclick_sold`
- [ ] Unit-тесты: `pytest packages/flipper_db/sources/tests/test_domclick_source.py -v` → все passed
- [ ] `python -c "from packages.flipper_db.sources.domclick import DomclickSource; s=DomclickSource(); print(s.parse_ad(open('services/parsers/domclick_sold/offer-page.html').read()))"` → non-None AdRecord с price_history в raw_data
- [ ] `python scripts/run_pipeline.py --source domclick_sold --fetch-missing --limit 5` → отрабатывает без ошибок
- [ ] Backfill прошёл: в `sold_ads.raw_data` есть `price_history` (JSON-массив)
- [ ] `sold_ads.house_id` заполнен для части записей (через linker address-match)
- [ ] Scheduler Sun 07:00 weekly запускает новый pipeline (по логам)
- [ ] Старый exporter.py удалён, Google Sheets не пишутся
- [ ] Поля доступные в domclick (см. таблицу) заполняются; недоступные (kitchen_area, living_area) корректно остаются None

---

## 8. Поля, которые парсятся / НЕ парсятся

| Поле | В cian_sold | В domclick_sold (v2) | Как добываем |
|---|---|---|---|
| `price` | ✅ | ✅ | `price_info.price` |
| `price_per_m2` | ✅ | ✅ | `price_info.square_price` |
| `area` (общая) | ✅ | ✅ | `object_info.area` |
| `kitchen_area` | ✅ | ❌ | domclick не отдаёт |
| `living_area` | ✅ | ❌ | domclick не отдаёт |
| `rooms` | ✅ | ✅ | `object_info.rooms` |
| `floor_current` | ✅ | ✅ | `object_info.floor` |
| `floor_total` | ✅ | ✅ | `house.floors` |
| `renovation` | ✅ | ✅ | `object_info.renovation.display_name` |
| `building_type` | ✅ | ✅ | `house.wall_type.display_name` |
| `year_built` | ✅ | ✅ | `house.build_year` |
| `ceiling_height` | ✅ | ✅ (если есть) | `house.ceiling_height` |
| `address` | ✅ | ✅ | `address.display_name` |
| `lat`, `lng` | ✅ | ✅ | JSON-LD `latitude/longitude` |
| `metro_station` | ✅ | ✅ | `address.subways[0].name` |
| `metro_walk_time` | ✅ | ✅ | `address.subways[0].remoteness.time` |
| `district` | ✅ | ✅ | `address.parents[kind=district].name` |
| `okrug` | ✅ | ✅ | `address.parents[~округ].name` |
| `publish_date` | ✅ | ✅ | `originalProduct.published_dt` |
| `sold_date` | ✅ | ✅ | `originalProduct.soldDate` (если есть) |
| `description` | ✅ | ✅ | `originalProduct.description` |
| `photos` | ✅ | ✅ | `originalProduct.photos[].url` (в raw_data) |
| **`price_history`** | ❌ | ✅ | `price_info.price_history[]` (**новое поле**) |
| **`sold_price`** | ❌ | ✅ | `price_info.sold_price` (**новое поле**) |
| `price_per_m2_for_year` | — | ✅ (бонус) | `price_info.price_for_year` |
| `url` | ❌ | ✅ | `pc.href` |
| `days_in_exposition` | ✅ | ✅ (вычислить) | `soldDate - published_dt` |

---

## 9. Риски и митигация

| Риск | Митигация |
|---|---|
| Page cookie протухнет (Qrator session) | Уже в `acquirer.py`; вынести в env `DOMCLICK_PAGE_COOKIE` для быстрой замены |
| BFF API вернёт 401 / rate-limit | `retry_get` с backoff (уже в acquirer.py) |
| Linker не найдёт дом (address отличается) | spatial fallback 75m (есть); в крайнем случае `house_id=NULL` |
| Lat/lng не в JSON-LD (для каких-то ad) | `lat`/`lng` остаются None, linker пробует address |
| Houses дубли (разные source, один дом) | linkеr уже умеет matчить (address+spatial) |
| Backfill долгий (~1.5-2 часа) | Sun 07:00 weekly — ок, есть окно |
| Расхождение CianSource / DomclickSource | Unit-тесты, fixtures |
| Старый domclick_sold job в scheduler сломается при удалении | Очистить scheduler.main.py + проверить запуск в docker |
| race: пока backfill идёт, новый BFF прогон добавляет новые ad | `ON CONFLICT DO UPDATE` идемпотентный, безопасно |

---

## 10. Связь с существующими документами

- `SYSTEM.md` § "Расписание" — обновить (domclick_sold остаётся Sun 07:00)
- `SYSTEM.md` § "Структура парсеров" — добавить про v2 path
- `docs/ARCHITECTURE_V3.md` § "Deferred" — убрать строку про domclick, добавить "✅ ACTIVE (v2 pipeline)"
- `PLAN.md` — обновить секцию про domclick (если есть)
