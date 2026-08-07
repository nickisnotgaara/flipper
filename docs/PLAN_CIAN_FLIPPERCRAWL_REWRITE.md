# План: CianSource → flippercrawl, полный offerData в raw_data, 500 ads

**Дата:** 2026-07-31
**Цель:** backfill 3,399 cian ads (начнём с 500) с полным `offerData` в `raw_data`, корректной
auto-линковкой к домам и правильным `is_active` через flippercrawl. Готовим multi-source
архитектуру (Domclick, Winners — следующими фазами).

---

## Контекст

- `flippercrawl/cian-flat.html` (1.05 MB) — реальный пример cian offer-страницы.
  Внутри лежит `_cianConfig['frontend-offer-card']` → `defaultState.value.state.offerData` —
  это и есть полный source-of-truth для всех данных объявления.
- flippercrawl уже умеет **статически** извлекать ~20 полей через mapping-config
  (`lib/cian/defaultMapping.ts`) + LLM-fallback. Но `offerData` целиком в response не отдаёт —
  можно достать либо из `rawHtml` (мой Python-парсер), либо попросить flippercrawl пробросить.
- Текущий `packages/flipper_db/sources/cian.py` (250 LOC) **НЕ использует** flippercrawl —
  стучится в cian.ru через старый `scripts/cian_fetch.py`. Из-за этого:
  - `is_active` детектится неправильно (нет правила `status==="published" && !isArchived`)
  - `raw_data` хранит обрезанный JSON, не полный offerData
  - ручная возня с cookies/proxy, которая уже автоматизирована в flippercrawl
- `SourceParser` Protocol, `pipeline.run_source_pipeline()`, `linker`, `repository` —
  **не трогаем**. Архитектура v2 уже собрана (Phase 1-2, 6, 7, 9) и работает.
- backend (FastAPI :8000) сейчас мёртв; frontend (:3000) жив. Перед тестами поднять backend.

---

## Scope

**В scope (Phase 3 — этот план):**
1. Расширить flippercrawl: пробросить полный `offerData` в `data.json` ответа `/v2/cian/scrape`.
2. Python-парсер `cian_state.py` (порт stateParser.ts) как fallback, если flippercrawl отдал
   только `rawHtml` (LLM-fallback случай).
3. Переписать `packages/flipper_db/sources/cian.py` под flippercrawl POST + парсинг response.
4. Тест на 10-15 ids (smoke), потом 500 ads (acceptance).
5. Документация: обновить `docs/ARCHITECTURE_V2.md` (статус Phase 3 + ссылка на этот план).

**Out of scope (позже):**
- Domclick (Phase 4) — отложен до стабилизации Cian
- Winners (Phase 5) — отложен
- Phase 8: миграция `services/parsers/cian_active/main.py` на новый pipeline — после 3,399 backfill
- Phase 9b: source badge в MapApp UI — после Domclick
- Phase 9c: full offerData в HousePanel UI — после 3,399 backfill
- Дашборд (новый UI) — следующая большая итерация, требует HousePanel + сортировки

---

## Архитектура потока (после Phase 3)

```
                     ┌────────────────────────────────────┐
                     │        flippercrawl :3002          │
cian.ru  ─fetch──►   │  POST /v2/cian/scrape              │
                     │   ├─ stateParser (static extract) │
                     │   ├─ mappingEngine                 │
                     │   ├─ LLM-fallback (если надо)      │
                     │   └─ Response assembly             │
                     │                                    │
                     │  data.json: {                      │
                     │    cian_id, price, area, is_active,│
                     │    address.full, lat, lng,         │
                     │    building, ...                   │
                     │    rawOfferData: {                 │  ← NEW: полный offerData
                     │      offer, agent, photos,         │
                     │      priceChanges, breadcrumbs,    │
                     │      seoData, ...                  │
                     │    },                              │
                     │    _extraction_mode: "static"      │
                     │  }                                 │
                     │  data.rawHtml: <1MB>               │  ← для double-check
                     └─────────────┬──────────────────────┘
                                   │ HTTP POST
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ flipper CianSource  (packages/flipper_db/sources/cian.py)            │
│  POST через httpx.AsyncClient                                        │
│  parse_ad(json, rawHtml) → AdRecord:                                 │
│    - normalized fields из data.json                                  │
│    - raw_data = data.json.rawOfferData  (ПОЛНЫЙ offerData)           │
│    - если rawOfferData нет (LLM-fallback) → парсим rawHtml           │
│      через cian_state.extract_offer_data(rawHtml)                    │
└──────────────────────────┬───────────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ pipeline.run_source_pipeline()  (УЖЕ ГОТОВО, не трогаем)            │
│   1. parse_ad → AdRecord                                             │
│   2. house_record_from_ad(ad, html) → HouseRecord (auto-ingest)      │
│   3. _upsert_ad(raw_data=full offerData) → active_ads                │
│   4. stale cleanup: is_active=False → sold_ads                       │
│   5. linker.link_ads() по lat/lng → house_id                         │
└──────────────────────────────────────────────────────────────────────┘
                           ▼
                  active_ads.raw_data = полный offerData (jsonb)
                  active_ads.house_id = FK к houses
                  активные / снятые — через 3-state filter на UI
```

---

## Что меняем

### A. flippercrawl (TypeScript, ~3 файла, 30-50 LOC правок)

**Файлы:**

1. `apps/api/src/lib/cian/types.ts`
   - `CianStaticResult.success: true.data` → расширить: добавить поле `rawOfferData: unknown`.

2. `apps/api/src/scraper/scrapeURL/transformers/cianStaticExtract.ts`
   - В `tryCianStaticExtract()`: после успешного `applyCianMapping()` положить
     `rawOfferData: pageState.offerData` в `result.data`.
   - Логирование не трогаем (уже пишет phase=cian_static_hit).

3. `apps/api/src/controllers/v2/cian-scrape.ts` (или общий response-ассемблер)
   - Убедиться что `data.json` (после `scrapeController`) включает `rawOfferData`.
   - Если `scrapeController` фильтрует `data.json` по `_internal` префиксам — добавить
     `rawOfferData` в whitelist.
   - **Внимание**: LLM-fallback (когда static не сработал) НЕ даст `rawOfferData` — там
     останется только `rawHtml` для парсинга на стороне flipper.

**Сборка и рестарт:**
```bash
cd C:\Users\User\Desktop\flipping\flippercrawl
# TS rebuild
docker compose up -d --force-recreate api
# sanity
curl -X POST http://127.0.0.1:3002/v2/cian/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.cian.ru/sale/flat/330637131/"}' \
  | jq '.data.json | keys'
# ожидаем: [..., "rawOfferData", "is_active", "_extraction_mode", ...]
```

### B. flipper — Python парсер (NEW, ~80 LOC)

**Файл:** `packages/flipper_db/cian_state.py`

Прямой порт `flippercrawl/apps/api/src/lib/cian/stateParser.ts` на Python.
Назначение: когда flippercrawl отдал LLM-fallback (нет `rawOfferData` в `data.json`),
парсим `rawHtml` и достаём полный `offerData`.

```python
# Сигнатура (одна публичная функция):
def extract_offer_data(raw_html: str) -> dict | None:
    """Возвращает state.offerData из rawHtml карточки cian, или None."""
```

**Использует** тот же алгоритм:
- `CONFIG_MARKER = "_cianConfig['frontend-offer-card']"`
- `scan_balanced_array(html, open_bracket)` — manual JSON-bracket counter
- `entries.find(e => e.key === "defaultState")` → `value.offerData`

**Тесты:** `packages/flipper_db/tests/test_cian_state.py` (минимум 3 кейса):
- Happy path: реальный HTML из `data/logs/_flippercrawl_sample.json` (есть там rawHtml)
- Marker not found → None
- Malformed JSON внутри marker → None (не raise)

### C. flipper — CianSource (REWRITE, ~250 LOC → ~280 LOC)

**Файл:** `packages/flipper_db/sources/cian.py`

**Удалить** зависимости: `scripts/cian_fetch.py`, `scripts/cian_parse.py` (после успешного
теста 500 — отдельным PR).

**Заменить** на:
```python
class CianSource:
    source_name: str = "cian_active"
    source_label: str = "ЦИАН"
    has_house_pages: bool = False  # больше НЕ ходим в /house/{id}/ — flippercrawl не использует

    FLIPPERCRAWL_URL: str = "http://127.0.0.1:3002/v2/cian/scrape"

    def __init__(self, flippercrawl_url: str | None = None, max_concurrent: int = 8):
        self._url = flippercrawl_url or self.FLIPPERCRAWL_URL
        self._sem = asyncio.Semaphore(max_concurrent)

    async def fetch_ad_page(self, external_id: str) -> str | None:
        """POST /v2/cian/scrape. Возвращает JSON-строку (data.json+metadata),
        или None на 404/network fail. Параллелизм через semaphore."""
        async with self._sem:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(self._url, json={
                    "url": f"https://www.cian.ru/sale/flat/{external_id}/",
                })
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.text  # JSON, парсим в parse_ad

    def parse_ad(self, response_json: str) -> AdRecord | None:
        data = json.loads(response_json).get("data", {})
        json_block = data.get("json", {}) or {}
        raw_html = data.get("rawHtml", "") or ""

        # 1) raw_offer_data: приоритет — из data.json, fallback — из rawHtml
        raw_offer = json_block.get("rawOfferData")
        if not raw_offer and raw_html:
            raw_offer = extract_offer_data(raw_html)  # из cian_state.py
        if not raw_offer:
            return None

        offer = raw_offer.get("offer", {}) or {}
        geo = offer.get("geo", {}) or {}
        building = offer.get("building", {}) or {}
        address_arr = geo.get("address", []) or []
        house_addr_elem = next((a for a in address_arr if a.get("type") == "house"), None)
        coords = geo.get("coordinates", {}) or {}

        return AdRecord(
            external_id=str(offer.get("id") or json_block.get("cian_id", "")),
            external_house_id=str(house_addr_elem["id"]) if house_addr_elem else None,
            url=json_block.get("url") or f"https://www.cian.ru/sale/flat/{external_id}/",
            is_active=bool(json_block.get("is_active", True)),
            raw_data=raw_offer,  # ← ПОЛНЫЙ offerData
            price=offer.get("bargainTerms", {}).get("price"),
            price_per_m2=offer.get("priceInfo", {}).get("pricePerSquareValue"),
            area=_to_float(offer.get("totalArea")),
            rooms=offer.get("roomsCount"),
            floor_current=offer.get("floorNumber"),
            floor_total=building.get("floorsCount"),
            address=json_block.get("address", {}).get("full"),
            lat=_to_float(coords.get("lat")),
            lng=_to_float(coords.get("lng")),
            publish_date=str(offer.get("added") or ""),
            metro_station=json_block.get("address", {}).get("metro_station"),
            metro_walk_time=json_block.get("address", {}).get("metro_walk_time"),
            district=json_block.get("address", {}).get("district"),
            okrug=json_block.get("address", {}).get("okrug"),
            renovation=json_block.get("renovation"),
        )

    def house_record_from_ad(self, ad: AdRecord, html: str) -> HouseRecord | None:
        """Auto-house-ingest из raw_offer_data (offer.building + offer.geo)."""
        if not ad.raw_data:
            return None
        offer = ad.raw_data.get("offer", {})
        building = offer.get("building", {})
        geo = offer.get("geo", {})
        bti_house = (offer.get("bti") or {}).get("houseData", {}) or {}
        address_arr = geo.get("address", []) or []
        street = next((a for a in address_arr if a.get("type") == "street"), None)
        house = next((a for a in address_arr if a.get("type") == "house"), None)
        if not house:
            return None
        return HouseRecord(
            external_house_id=str(house["id"]),
            address=ad.address,
            street=street["name"] if street else None,
            house_num=house["name"],
            district=ad.district,
            okrug=ad.okrug,
            lat=ad.lat,
            lng=ad.lng,
            year_built=building.get("buildYear") or bti_house.get("yearRelease"),
            levels=building.get("floorsCount") or bti_house.get("floorMax"),
            building_type=building.get("materialType") or bti_house.get("houseMaterialType"),
            series=building.get("series") or bti_house.get("seriesName"),
            ceiling_height=_to_float(building.get("ceilingHeight")),
            raw_data={"building": building, "bti": offer.get("bti"), "geo": geo},
        )
```

**Ключевые отличия от текущего:**
- `fetch_ad_page` возвращает JSON (не HTML) — идём через flippercrawl.
- `parse_ad` принимает JSON-строку (не HTML).
- `raw_data` теперь = полный `offerData` (с offer/agent/photos/priceChanges/breadcrumbs/seoData).
- `has_house_pages = False` — flippercrawl **не использует** cian `/house/{id}/` страницы; всё
  есть в offerData. Это упрощает и ускоряет: -1 fetch на ad.
- `house_record_from_ad` строит дом **только** из offer.building + bti (не ходит в `/house/`).

**Адаптер для `scripts/run_pipeline.py`:**
- Сейчас pipeline вызывает `source.fetch_ad_page(ext_id)` → ожидает HTML/JSON-строку.
- CianSource теперь возвращает JSON-строку от flippercrawl.
- Pipeline передаёт её в `source.parse_ad(...)` — там уже парсим.
- **Никаких изменений в pipeline не нужно** — Protocol уже source-agnostic.

### D. Тест на 10-15 ids (smoke)

**Подготовка:**
```bash
# 1) поднять backend
cd C:\Users\User\Desktop\flipping\flipper
py -3.11 -m uvicorn web.server:app --host 127.0.0.1 --port 8000

# 2) выбрать 15 ids из существующих active_ads
psql ... -c "SELECT external_id FROM active_ads WHERE source='cian_active' AND is_active=true ORDER BY id LIMIT 15" > data/logs/_smoke_15_ids.txt
```

**Smoke:**
```bash
py -3.11 scripts/run_pipeline.py --source cian_active \
    --ids data/logs/_smoke_15_ids.txt \
    --no-houses --no-cleanup --no-link
```

**Проверка (SQL):**
```sql
-- 1) raw_data не пустой и содержит offer
SELECT external_id, raw_data ? 'offer' AS has_offer, raw_data ? 'agent' AS has_agent
FROM active_ads WHERE source='cian_active' AND external_id IN (...);

-- 2) lat/lng заполнены
SELECT external_id, lat, lng FROM active_ads WHERE source='cian_active'
  AND external_id IN (...) AND lat IS NOT NULL AND lng IS NOT NULL;

-- 3) is_active корректно
SELECT external_id, is_active FROM active_ads WHERE source='cian_active'
  AND external_id IN (...) ORDER BY external_id;

-- 4) _extraction_mode сохранён
SELECT external_id, raw_data->'_extraction_mode' AS mode FROM ...;
```

**Acceptance smoke:**
- ≥13/15 обработаны без ошибок
- 100% имеют `lat/lng`
- 100% имеют `raw_data` с ключом `offer`
- 100% `is_active` соответствует cian

### E. Тест на 500 ads

```bash
# Полный прогон
py -3.11 scripts/run_pipeline.py --source cian_active \
    --offset 0 --limit 500 --no-houses --no-cleanup   # сначала без link/houses, чисто данные
# Потом с houses+link+cleanup:
py -3.11 scripts/run_pipeline.py --source cian_active \
    --offset 0 --limit 500
```

**Acceptance 500:**
- 500 ads processed (или >450 если есть 404 — нормально)
- ≥95% имеют lat/lng
- ≥95% имеют `raw_data` с offer
- houses created ≥ уникальных cian_house_id в выборке
- linked ≥80% (linker сработал)
- moved_to_sold / deactivated = 0 (мы не знаем заранее какие сняты)

**Если latency >10 sec/ad:**
- Проверить что flippercrawl не упёрся в rate-limit / cookie issue
- Подумать про `--concurrency` (сейчас max 8)

### F. Документация

**Файл:** `docs/ARCHITECTURE_V2.md`
- Обновить Phase 3 статус: ✅ done
- Добавить ссылку на этот план
- Отметить: `is_active` теперь из flippercrawl, `raw_data` = full offerData

---

## Multi-source готовность

`SourceParser` Protocol **не меняется**. Добавление Domclick = новый файл:

```
packages/flipper_db/sources/domclick.py     # Phase 4
  class DomclickSource:
    source_name = "domclick_active"
    async def fetch_ad_page(ext_id) -> ...   # /v2/domclick/scrape
    def parse_ad(json) -> AdRecord: ...
    def house_record_from_ad(...) -> ...

packages/flipper_db/sources/winners.py      # Phase 5
  ...
```

`run_source_pipeline` уже работает с любым `SourceParser`. Подключение:
```python
# domclick
res = await run_source_pipeline(DomclickSource(), domclick_ad_ids)

# winners
res = await run_source_pipeline(WinnersSource(), winners_ad_ids)
```

Сшивка cian ↔ domclick ↔ winners на уровне дома:
- Уже есть `houses.cian_house_id` (BIGINT), `houses.domclick_house_id` (BIGINT),
  `houses.winners_house_id` (TEXT) — миграция Phase 2.
- `linker.py` ищет совпадения по `cian_house_id` (точное) или `lat/lng` (cKDTree).
- Когда появятся domclick-объявления — добавим точное совпадение по
  `domclick_house_id` в `link_ads_by_*_ids()` (Phase 4).

---

## Риски и митигация

| Риск | Митигация |
|---|---|
| flippercrawl падает → pipeline встаёт | Catch в `CianSource.fetch_ad_page` → None → pipeline `deactivated` flow |
| LLM-fallback медленный (10-20 sec/ad) | Мониторим `_extraction_mode`; если >30% "llm" — log warning, но не падаем |
| flippercrawl TS rebuild долгий | Один раз пересобрать + рестарт api контейнера; далее hot-reload не нужен |
| raw_data разрастается (1-2 MB per row) | `jsonb` сжатие Postgres TOAST решает; не лимитируем размер |
| Cookie rotation flippercrawl | Уже работает в flippercrawl; нам не нужно в CianSource |
| 500 ads прогон >2 часа | 8 параллельных запросов; smoke 15 → ожидаемая 1-2 мин; 500 → 30-60 мин |

---

## Стратегия после 500

- **Если всё ok** → прогон 500-1000 → 1500 → 2000 → 2500 → 3000 → 3399. Чанками.
  Каждый чанк: проверка метрик, is_active detection, link accuracy.
- **Если что-то сломано** → фикс → smoke 15 → повтор 500.
- **Параллельно** можно начать Phase 8 (миграция `services/parsers/cian_active/main.py` на
  новый pipeline) — это additive, не ломает ничего.
- **Phase 4 (Domclick)** — только после 3,399 backfill + стабилизации.

---

## Чеклист реализации

- [ ] A.1 Расширить `types.ts` (rawOfferData)
- [ ] A.2 Обновить `cianStaticExtract.ts` (положить rawOfferData)
- [ ] A.3 Проверить `cian-scrape.ts` / response assembler (rawOfferData в data.json)
- [ ] A.4 Rebuild + restart api контейнера; smoke curl с тестовым id
- [ ] B.1 Написать `packages/flipper_db/cian_state.py`
- [ ] B.2 Написать `packages/flipper_db/tests/test_cian_state.py` (3+ кейса)
- [ ] C.1 Переписать `packages/flipper_db/sources/cian.py` под flippercrawl
- [ ] C.2 Проверить что `run_source_pipeline` принимает новый source без правок
- [ ] D.1 Поднять backend
- [ ] D.2 Выбрать 15 ids, прогнать smoke
- [ ] D.3 SQL-проверки (raw_data/lat/lng/is_active)
- [ ] E.1 Прогон 500 ads
- [ ] E.2 SQL-проверки 500
- [ ] F.1 Обновить `docs/ARCHITECTURE_V2.md`

---

## Что НЕ делаем в этой фазе (важно)

- ❌ Не пишем дашборд — это UI, отдельная фаза
- ❌ Не трогаем `services/parsers/cian_active/main.py` — additive после стабилизации
- ❌ Не удаляем `scripts/cian_fetch.py` / `cian_parse.py` сразу — оставляем до подтверждения
  что 500 ads прошли
- ❌ Не подключаем Domclick / Winners — они Phase 4 / 5
- ❌ Не добавляем source badge на UI — после Phase 4

---

## Next step

**Жду от тебя ОК** (или замечаний) — и начинаю по чеклисту. Если хочешь сначала обсудить
какой-то конкретный пункт (например, concurrency, или "а точно ли оставлять
`has_house_pages = False`", или rawOfferData через какой ключ лучше отдавать) — давай сейчас,
перепишу план.
