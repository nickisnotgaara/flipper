# Архитектура v2: единая система парсинга → карта

Дата: 2026-07-31
Область: `C:\Users\User\Desktop\flipping\flipper`
Цель: перейти от "миграции" (одноразовый скрипт) к "системе" (going-forward автопайплайн)

---

## 0. Требования (от пользователя)

| # | Требование | Источник |
|---|---|---|
| 1 | При парсинге новых данных, если дома нет в `houses` — спарсить его (cian house page) и добавить | "если видим что такого дома нет в flatinfo то нужно спарсить дом и добавить в базу" |
| 2 | Все объявления cian должны иметь полный `offerData` (как в `flippercrawl\cian-flat.html`) в `raw_data` | "Все объявления циана должны иметь данные offersData из страницы" |
| 3 | Архитектура должна поддерживать cian, domclick (новый, лучший парсинг) и winners (legacy) единообразно | "добавим еще домклик и виннерс... нужна какая то архитектура" |
| 4 | Это НЕ одноразовый скрипт — система должна работать going-forward | "не должна быть одноразовым скриптом, система так должна работать" |
| 5 | Текущие активные ad, которые на самом деле снялись — перенести в `sold_ads` | "те данные которые сейчас активные но на самом деле снялись из публикации добавив в снятые" |
| 6 | UI должен показывать "снятые" (сейчас "не вижу в списках снятые") | — |
| 7 | Не сломать существующее: legacy cian_active service продолжает работать, UI работает, старые данные работают | "не сломав ничего" |
| 8 | Текущие данные старые, скоро будет обновление | "сейчас данные старые" |

---

## 1. Текущая архитектура (as-is)

```
┌──────────────────────────────────────────────────────────┐
│ services/parsers/cian_active/    (legacy service, ~1k LOC)│
│   main.py → AdParser + QueueManager + DatabaseRepository │
│   parse_offer() → dict → upsert_active_ads_batch        │
│   cian_house_id cross-ref читается при link-фазе        │
└──────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────┐
│ services/parsers/cian_sold/      (file-based, JSONL)    │
│   run.py → cli.main() → import_cian_sold_jsonl()        │
│   result.jsonl → House + SoldAd                          │
└──────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────┐
│ services/parsers/domclick_sold/  (file-based, JSON)     │
│   import_cian_domclick_result() → House + SoldAd        │
└──────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────┐
│ services/parsers/winners_sold/   (file-based, JSON)     │
│   import_winners_json() → House + SoldAd (без шитья)   │
└──────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────┐
│ packages/flipper_db/                                       │
│   models.py: House, ActiveAd, SoldAd (unified schema)   │
│   repository.py: FlipperRepository (SQLAlchemy upserts) │
│   linker.py: link_ads / link_ads_by_cian_ids (added 31.07)│
│   geocoder.py: Nominatim/Photon (для сирот)             │
└──────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────┐
│ web/server.py (FastAPI :8000) → /api/houses, /api/stats │
│ web/next/ (Next.js :3000) → Leaflet map                  │
└──────────────────────────────────────────────────────────┘
```

**Проблемы:**
- ❌ Нет общего интерфейса парсера (каждый делает по-своему)
- ❌ Нет авто-парсинга дома при отсутствии
- ❌ Нет stale-cleanup (активные, которые cian уже снял)
- ❌ Cross-reference только `cian_house_id` (для domclick/winners нет)
- ❌ Pipeline не идемпотентен при добавлении нового источника
- ❌ raw_data местами хранит только `{"cian_id": "..."}` (старая миграция), не полный offerData

---

## 2. Целевая архитектура (v2)

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1: Schema — packages/flipper_db/models.py                │
│   House(source, external_house_id, cian_house_id,               │
│         domclick_house_id, winners_house_id, ...)              │
│   ActiveAd(source, external_id, domclick_id/winners_id,         │
│             is_active, house_id, raw_data=FULL offerData)     │
│   SoldAd(source, external_id, house_id, raw_data=FULL)         │
└──────────────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2: Common Types — packages/flipper_db/parser_types.py     │
│   @dataclass AdRecord:                                           │
│       external_id, external_house_id, url, is_active,           │
│       price, area, rooms, lat, lng, address, ...                │
│       raw_data: dict  # FULL source data (offerData, domclick) │
│   @dataclass HouseRecord:                                        │
│       external_house_id, address, lat, lng, year_built, ...     │
│       raw_data: dict  # FULL house data                         │
│   class SourceParser(Protocol):                                  │
│       source_name, source_label, is_alive                       │
│       fetch_ad_page(external_id) -> str|None                    │
│       fetch_house_page(external_house_id) -> str|None           │
│       parse_ad(html) -> AdRecord|None                           │
│       parse_house(html) -> HouseRecord|None                     │
└──────────────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3: Source Implementations — packages/flipper_db/sources/   │
│   cian.py:      CianSource (full parsing, house page fetcher)  │
│   domclick.py:  DomclickSource (good parsing, JSON-based)      │
│   winners.py:   WinnersSource (legacy JSON, no house page)     │
└──────────────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4: Pipeline — packages/flipper_db/pipeline.py              │
│   async def run_source_pipeline(source, ad_ids, options):       │
│       1. For each ad_id: fetch HTML → parse AdRecord            │
│       2. If AdRecord.external_house_id NOT IN houses:           │
│              fetch house page → parse → upsert_house            │
│       3. Upsert ad (with house_id FK + FULL raw_data)           │
│       4. If ad was active, is_active=False:                     │
│              move to sold_ads (event-driven cleanup)            │
│       5. Run linker on any unlinked ads                          │
│   async def run_house_pipeline(source, house_id):               │
│       1. Fetch house page → parse → upsert                      │
└──────────────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 5: Orchestrator — scripts/run_pipeline.py                 │
│   CLI:  py scripts/run_pipeline.py --source cian_active         │
│         --ad-ids ids.txt --houses auto                          │
│         --stale-cleanup auto                                     │
│   Uses scheduler/cron for going-forward runs                     │
└──────────────────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────────┐
│ Layer 6: UI — web/next/                                         │
│   Source badge на house marker (cian/domclick/winners/flatinfo)│
│   Filter "только снятые" + "только cian" / "только domclick"    │
│   Click house → panel показывает FULL offerData (если есть)    │
└──────────────────────────────────────────────────────────────────┘
```

**Ключевые отличия от v1:**
- ✅ Общий `SourceParser` Protocol — каждый источник реализует один контракт
- ✅ Auto-house-ingestion встроен в pipeline
- ✅ Event-driven stale-cleanup (cian сигнализирует, мы переносим)
- ✅ Multi-source cross-references (cian_house_id + domclick_house_id + winners_house_id)
- ✅ FULL raw_data для всех источников
- ✅ Pipeline детерминирован и идемпотентен

---

## 3. Схема БД (изменения)

### 3.1. `houses` — добавить cross-reference колонки

```sql
ALTER TABLE houses
  ADD COLUMN IF NOT EXISTS domclick_house_id BIGINT,
  ADD COLUMN IF NOT EXISTS winners_house_id TEXT;
```

**Логика:**
- `source='cian'` → `external_house_id=str(cian_house_id)`, `cian_house_id=...`
- `source='domclick'` → `external_house_id=str(domclick_id)`, `domclick_house_id=...`
- `source='winners'` → `external_house_id=guid`, `winners_house_id=guid`
- `source='flatinfo'` → `external_house_id=flatinfo_id`, опционально `cian_house_id` если был cross-ref

**Сшивка cross-source:** `find_house_by_source_ref(source, ext_id) → House|None`

### 3.2. `active_ads` — generalize `cian_id` → `external_id`

**Стратегия: не ломаем.** Добавляем `external_id` рядом с `cian_id`:

```sql
ALTER TABLE active_ads
  ADD COLUMN IF NOT EXISTS external_id TEXT;
-- backfill: UPDATE active_ads SET external_id = cian_id WHERE source LIKE 'cian%';
-- backfill: UPDATE active_ads SET external_id = domclick_id WHERE source LIKE 'domclick%';
```

Долгосрочно: `external_id` — основной ключ, `cian_id` остаётся для backwards compat.

### 3.3. `raw_data` — FULL source data, всегда

Миграция (одноразовая, безопасная):
- Для всех cian active_ads, у которых `raw_data` содержит только `{"cian_id": "..."}`: re-fetch и перезаписать
- Покрытие 3,399 ad, ~10 минут

---

## 4. Общий интерфейс (SourceParser)

```python
# packages/flipper_db/parser_types.py
from dataclasses import dataclass, field
from typing import Protocol, Optional, runtime_checkable

@dataclass
class AdRecord:
    external_id: str
    external_house_id: Optional[str] = None
    url: Optional[str] = None
    is_active: bool = True
    raw_data: dict = field(default_factory=dict)
    # Нормализованные поля
    price: Optional[int] = None
    price_per_m2: Optional[int] = None
    area: Optional[float] = None
    rooms: Optional[int] = None
    floor_current: Optional[int] = None
    floor_total: Optional[int] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    publish_date: Optional[str] = None
    metro_station: Optional[str] = None
    metro_walk_time: Optional[int] = None
    district: Optional[str] = None
    okrug: Optional[str] = None
    renovation: Optional[str] = None


@dataclass
class HouseRecord:
    external_house_id: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    year_built: Optional[int] = None
    levels: Optional[int] = None
    building_type: Optional[str] = None
    series: Optional[str] = None
    ceiling_height: Optional[float] = None
    raw_data: dict = field(default_factory=dict)


@runtime_checkable
class SourceParser(Protocol):
    """Единый контракт для всех источников (cian, domclick, winners, ...)."""
    source_name: str          # 'cian_active' | 'cian_sold' | 'domclick_sold' | ...
    source_label: str         # 'ЦИАН' | 'ДомКлик' | 'Победители'

    async def fetch_ad_page(self, external_id: str) -> Optional[str]: ...
    async def fetch_house_page(self, external_house_id: str) -> Optional[str]: ...
    def parse_ad(self, html: str) -> Optional[AdRecord]: ...
    def parse_house(self, html: str) -> Optional[HouseRecord]: ...
```

**Реализации** в `packages/flipper_db/sources/`:
- `CianSource`: полный парсинг offerData, умеет `fetch_house_page` для /house/{id}/
- `DomclickSource`: парсит domclick JSON API
- `WinnersSource`: legacy, `fetch_house_page` возвращает None (нет страницы дома)

---

## 5. Pipeline (going-forward)

```python
# packages/flipper_db/pipeline.py
async def run_source_pipeline(
    source: SourceParser,
    ad_external_ids: list[str],
    *,
    auto_fetch_houses: bool = True,
    cleanup_stale: bool = True,
    link_after: bool = True,
    db_url: str = ...,
) -> dict:
    """Generic pipeline — работает для любого SourceParser.

    Returns: {
      "ads_processed": N,
      "houses_created": N,
      "moved_to_sold": N,
      "linked": N,
    }
    """
    conn = await asyncpg.connect(db_url)
    try:
        n_ads = n_houses_created = n_moved = 0

        for ext_id in ad_external_ids:
            # 1. Fetch ad page
            html = await source.fetch_ad_page(ext_id)
            if not html:
                continue
            ad = source.parse_ad(html)
            if not ad:
                continue

            # 2. Auto-fetch house if needed
            if auto_fetch_houses and ad.external_house_id:
                if not await _house_exists(conn, source.source_name, ad.external_house_id):
                    house_html = await source.fetch_house_page(ad.external_house_id)
                    if house_html:
                        house = source.parse_house(house_html)
                        if house:
                            await _upsert_house(conn, source.source_name, house)
                            n_houses_created += 1

            # 3. Upsert ad (with FULL raw_data)
            await _upsert_ad(conn, source.source_name, ad)
            n_ads += 1

            # 4. Stale cleanup: was active, now is_active=False → move to sold_ads
            if cleanup_stale and not ad.is_active:
                was_active = await _was_previously_active(conn, source.source_name, ext_id)
                if was_active:
                    await _move_to_sold(conn, source.source_name, ad)
                    n_moved += 1

        # 5. Link
        link_stats = {}
        if link_after:
            link_stats = await link_ads(conn, ad_source=source.source_name, apply=True)

        return {
            "ads_processed": n_ads,
            "houses_created": n_houses_created,
            "moved_to_sold": n_moved,
            "linked": link_stats.get("applied", 0),
        }
    finally:
        await conn.close()
```

---

## 6. План реализации (по фазам)

| # | Фаза | Сложность | Время | Зависит от |
|---|---|---|---|---|
| 1 | **Common types** — `parser_types.py` (AdRecord, HouseRecord, SourceParser Protocol) | M | 2h | — |
| 2 | **Schema migration** — добавить `domclick_house_id`, `winners_house_id`, `external_id` | S | 1h | — |
| 3 | **CianSource** — обёртка над `scripts/cian_db.py` + `services/parsers/cian_sold/` | M | 4h | 1 |
| 4 | **DomclickSource** — обёртка над `services/parsers/domclick_sold/` | M | 3h | 1 |
| 5 | **WinnersSource** — обёртка (legacy, минимальные изменения) | S | 1h | 1 |
| 6 | **Pipeline** — `pipeline.py::run_source_pipeline` (auto-house, stale cleanup, link) | L | 6h | 1, 3, 4, 5 |
| 7 | **Orchestrator** — `scripts/run_pipeline.py` CLI + scheduler hook | S | 2h | 6 |
| 8 | **Legacy migration** — `services/parsers/cian_active/main.py` → новый pipeline | L | 6h | 6 |
| 9 | **UI improvements** — source badge, "только снятые" filter, full offerData в HousePanel | M | 4h | 3 |
| 10 | **Данные: full offerData** — re-fetch для старых ad без полного raw_data (one-time) | S | 30min | 3 |
| 11 | **Данные: stale cleanup batch** — разовая чистка: все ad, у которых cian вернул is_active=false | S | 30min | 3 |
| 12 | **Домклик активный** — `parsers/domclick_active/` (новый source) | L | 8h | 4 |

**Итого:** ~38 часов работы, **8 недель** в спокойном темпе (1 фаза = 1 неделя).

---

## 7. Решения (подтверждены 2026-07-31)

| # | Решение | Выбор |
|---|---|---|
| Q1 | `external_id` для `active_ads` | **(b) Переименовать `cian_id` → `external_id`** ✅ DONE |
| Q2 | Cross-references для sources | **(a) Колонки в `houses`** (`domclick_house_id`, `winners_house_id`) ✅ DONE |
| Q3 | Stale cleanup | **(a) Move в `sold_ads`** (агрессивно, чисто) ✅ DONE |
| Q4 | Auto-house-ingestion | **(a) Sync inline** (простой код, rate-limit 1 fetch/sec) ✅ DONE |
| Q5 | Legacy cian_active service | **(a) Мигрировать на новый pipeline** (single source of truth) |

---

## 8. Статус реализации (на сейчас)

### Готово ✅

| # | Фаза | Что сделано |
|---|---|---|
| 1 | Common types | `packages/flipper_db/parser_types.py` (AdRecord, HouseRecord, SourceParser Protocol) |
| 2 | Schema migration | SQL: `active_ads.cian_id → external_id`, `houses.domclick_house_id`, `houses.winners_house_id`. Models.py, repository.py, linker.py, web/server.py, web/next/lib/api.ts — все обновлены |
| 3 | CianSource | `packages/flipper_db/sources/cian.py` (SourceParser impl с auto-house-fallback через offerData) |
| 6 | Pipeline | `packages/flipper_db/pipeline.py::run_source_pipeline` (auto-house, stale cleanup, **deactivated** для 404, link) |
| 6a | Cookie auto-refresh | `CianSource._fetch()` ловит 403 → refresh куки → retry один раз. В chunk1 сработал 5 раз без потерь |
| 6b | Deactivated metric | Новый `PipelineResult.deactivated`: при fetch fail (404) + ad был active → `is_active=false` (без переноса в sold_ads, потому что HTML нет) |
| 7 | Orchestrator | `scripts/run_pipeline.py` (CLI: `--fetch-missing / --recent / --ids`, **+ `--offset`** для chunked runs) |
| 9a | 3-state filter | `MapApp.tsx` — `filterMode: 'all' \| 'active' \| 'sold_only'` ("Только снятые" кнопка) |

### Smoke test (5 ad) подтвердил

- ✅ 5/5 ads processed за 84 секунды
- ✅ 5 cian-домов создано через auto-ingestion (2 через fallback, 3 через /house/ страницу)
- ✅ Все 5 ads теперь имеют FULL `offerData` в `raw_data`
- ✅ Linker: 0 newly linked (все 5 уже были линкованы), 0 broken

### Smoke test на 6 known 404 (2026-07-31 16:37) — новый код

- 4 из 6 ad'ов (которые 404-нули на cian) → `is_active=false` ✅
- 2 ads (315000842 fetch удался, 310880175 timeout с retry) → остались active
- **Новая `deactivated` метрика работает**

### Chunk1 (первый production batch, 400 ad, 2026-07-31 03:32-03:47)

- 367/400 processed, 6 fetch_fail, 27 parse_fail, 0 moved_to_sold
- 915 секунд, ~2.5 sec/ad
- **5 cookie refreshes** (403) — auto-refresh работает
- ❌ Все 5 fetch_failed 404-ad'ов остались `is_active=true` (старая логика, до `deactivated` фикса)
- ✅ Chunk1 результат: 367 ads обновлены с full offerData

### Осталось ⏳

| # | Фаза | Что |
|---|---|---|
| chunk2-N | Stale cleanup batch | 8 chunks × 400 ad = 3,200+ (chunk2: offset=400; ...; chunk8: offset=2800). Каждый ~15 мин |
| 4 | DomclickSource | Обёртка над domclick_sold (новый source). Note: domclick = JSON import, не fetcher. |
| 5 | WinnersSource | Legacy обёртка. Note: winners = JSON import. |
| 8 | Миграция cian_active service | `services/parsers/cian_active/main.py` → новый pipeline (single source of truth) |
| 9b | UI source badge | Бейдж cian/domclick/winners на маркерах карты |
| 9c | Full offerData в HousePanel | UI отображение raw_data |
| 12 | Домклик активный | `parsers/domclick_active/` (новый source, fetch-based) |

---

## 8. Обратная совместимость

**Принцип:** каждое изменение — добавочное, ни одно не ломает существующее.

- Существующие `cian_id` колонки остаются (для обратной совместимости с SQL запросами в `web/server.py`)
- Существующие parser modules (`services/parsers/*/importer.py`) остаются работать
- `web/server.py` API не меняется
- `web/next/` UI не меняется до Phase 9

**Phase ordering гарантирует:**
- Phase 1-2: только добавление, ничего не ломает
- Phase 3-7: новые модули, существующие продолжают работать
- Phase 8: миграция cian_active service — *только* после того, как новый pipeline проверен
- Phase 9: UI — изолированно
- Phase 10-12: данные и новые источники

---

## 9. Acceptance bar (по завершении всех фаз)

1. **Coverage**: 100% (3,386 → 3,399 — дотянуть 13 edge cases новостроек)
2. **Auto house ingestion**: новые ad без дома → дом парсится автоматически
3. **Stale cleanup**: ad, которые cian снял, переносятся в `sold_ads` при следующем re-fetch
4. **Multi-source**: cian + domclick + winners в одной системе, единый pipeline
5. **Full offerData**: каждое cian ad имеет полный `raw_data` (offerData)
6. **UI**: source badge, фильтр по source, фильтр "только снятые"
7. **Going-forward**: новые ad приходят → автопарсятся дома → автолинкуются → авто-обновляется is_active
8. **No breaking changes**: legacy code работает до явной миграции

---

## 10. Следующий шаг

Подтвердить **5 ключевых решений** (Q1-Q5) → приступаю к **Phase 1-2** (common types + schema migration, ~3ч, без breaking changes).

---

## 11. Phase status (актуально на 2026-07-31)

| Phase | Что | Статус | Заметки |
|---|---|---|---|
| **1** | `parser_types.py` (`AdRecord`, `HouseRecord`, `SourceParser` Protocol) | ✅ done | `packages/flipper_db/parser_types.py` |
| **2** | Schema migration: `active_ads.cian_id` → `external_id`, `houses.{domclick,winners}_house_id` | ✅ done | `scripts/_migration_v2_external_id.sql` |
| **3** | `CianSource` через **flippercrawl `/v2/cian/scrape`** (rawOfferData в raw_data) | ✅ done (2026-07-31) | `packages/flipper_db/sources/cian.py`, подробнее в `docs/PLAN_CIAN_FLIPPERCRAWL_REWRITE.md`. Smoke 15 → 13/15, 500 ids в процессе. |
| **3a** | `packages/flipper_db/cian_state.py` (Python-порт `stateParser.ts`) | ✅ done | 8/8 unit-tests pass. Fallback для LLM-fallback пути. |
| **3b** | flippercrawl side: `rawOfferData` в `data.json` | ✅ done | `lib/cian/types.ts`, `scraperURL/transformers/cianStaticExtract.ts`, `scraperURL/transformers/llmExtract.ts`, `controllers/v2/cian-scrape.ts`, `lib/cian/mappingEngine.ts` |
| **4** | `DomclickSource` | ⏳ deferred | после стабилизации cian |
| **5** | `WinnersSource` | ⏳ deferred | после domclick |
| **6** | `run_source_pipeline` (auto-house, stale cleanup, link) | ✅ done | `packages/flipper_db/pipeline.py` |
| **7** | CLI `run_pipeline.py` (`--fetch-missing` / `--recent` / `--ids` / `--offset` / `--limit` / `--no-houses` / `--no-cleanup` / `--no-link`) | ✅ done | `scripts/run_pipeline.py` |
| **8** | Миграция `services/parsers/cian_active/main.py` на новый pipeline | ⏳ deferred | additive, после 3,399 backfill |
| **9** | UI: 3-state filter, source badge, full offerData в HousePanel | 🟡 partial | 3-state filter (`MapApp.tsx`) ✅. Source badge ⏳. Full offerData в HousePanel ⏳. |
| **9b** | Дашборд (новый UI вместо только карты) | ⏳ deferred | большая UI-фаза |

**Главный unlock Phase 3:** flippercrawl — единственный fetcher для cian (никакого
прямого HTTP в cian.ru, никаких куков на стороне flipper). Cookie rotation,
proxy, anti-bot, static extract + LLM-fallback — всё в flippercrawl. CianSource
только делает POST и парсит JSON.

**Что стало возможно (но ещё не сделано):**
- `AdRecord.raw_data` = полный `offerData` (offer, agent, photos, priceChanges, bti, seoData, breadcrumbs, ...)
- `is_active` = flippercrawl static extract (`status === "published" && !isArchived`)
- House auto-creation из `offer.building + offer.bti + offer.geo` без отдельного fetch на `/house/{id}/`
- Multi-source ready: `SourceParser` Protocol не меняется

**Что осталось от старого code (легаси, удалить после 3,399 backfill):**
- `scripts/cian_fetch.py`
- `scripts/cian_parse.py`
- `scripts/cian_db.py`
- `scripts/cian_pipeline.py`
- `scripts/_backfill_ads_geo.py`, `_backfill_ads_geo_parallel.py`
- `scripts/test_cian_fetch.py`, `test_cian_parse.py`
- `data/logs/_refetch_*.py` (ad-hoc отладка)
- `services/parsers/cian_active/main.py` (мигрирует в Phase 8)

Эти скрипты больше никто регулярно не запускает. Оставлены до явного
подтверждения, что 3,399 backfill через новый pipeline прошёл.

---

## 9. v3 — address + coordinates as canonical house key (2026-07-31 23:50)

**Поворот:** cian house id НЕ надёжен как канонический ключ (разнобой между источниками, смена id при пере-назначении дома). Решили: **address + lat/lng = канонический идентификатор дома**, cian_house_id остаётся как high-confidence cross-ref, но **не** как primary key.

### 9.1 Новые правила

1. **House identity = (lat, lng) + address**. cian_house_id — только cross-ref.
2. **Pipeline НЕ создаёт новый дом по external_house_id** (как было в v2 — это дало 711 spatial-дубликатов).
3. **Linker = spatial-first** (cKDTree), cian_house_id используется как high-confidence fallback.
4. **Новые дома (без spatial match) создаются с source='auto'** — НЕ cian_active (чтобы не плодить дубликаты).
5. **Стоимость ongoing = 0**: адрес + lat/lng извлекаются из payload самого объявления (cian offer, domclick offer, winners offer). Никаких DaData/ФИАС для каждого объявления.

### 9.2 Линкер v3 (packages/flipper_db/linker.py)

`python
async def match_or_create_house(conn, ad, *, source_name='auto', auto_create=True):
    # 1. cian_house_id cross-ref (если есть в houses)
    if ad.cian_house_id:
        row = SELECT id FROM houses WHERE cian_house_id= LIMIT 1
        if row: return row['id']

    # 2. Spatial match (cKDTree, ~75m, ambiguity guard)
    if ad.lat and ad.lng:
        tree = cKDTree(houses_coords_in_GOOD_SOURCES)
        best, distance = tree.query(ad.coords)
        if distance <= 75m: return best.id

    # 3. Auto-create (если auto_create=True и есть lat/lng)
    if auto_create and ad.lat and ad.lng:
        INSERT INTO houses (source='auto', external_house_id=f'auto:{lat},{lng}', ...)
        return new.id
`

**GOOD_SOURCES** = (flatinfo, cian, cian_api_house, auto) — реальные дома.
**EXCLUDED_SOURCES** = (cian_active, cian_active_ad) — pipeline pollution v2, исключены из matching.

### 9.3 One-shot миграция (2026-07-31 23:45) — _migration_merge_duplicates.py

Обнаружено: **1,206 cian_active / cian_active_ad домов** — точные spatial-дубликаты latinfo/cian/cian_api_house (distance 0.0m, **711 штук**). Они появились из v2-pipeline, который создавал новый houses row per external_house_id.

**Что сделано:**
- **243 ads** (12.5% из 3,386 линкованных) перелинкованы с cian_active-дубликатов → правильный flatinfo/cian.
- **711 cian_active домов** удалены (были exact duplicates).
- **495 cian_active домов** оставлены (truly unique, новые дома без flatinfo аналога).
- **13 ads** остались без house (нет координат и нет cian_house_id — это новостройки в edge cases).

### 9.4 Pipeline v3 (packages/flipper_db/pipeline.py)

Каждый ad:
1. source.fetch_ad_page(ext_id) → raw response
2. source.parse_ad(html) → AdRecord (raw_data + lat/lng/address/cian_house_id)
3. linker.match_or_create_house(ad) → house_id (cross-ref → spatial → auto-create)
4. Upsert ad в ctive_ads с house_id + full aw_data
5. Stale cleanup: если was_active=True и ad.is_active=False → переносим в sold_ads

**Результат smoke-теста (5 ads, 2026-07-31 23:48):**
`
ads_processed: 5
houses_matched_exact: 5    (все через cian_house_id cross-ref)
houses_matched_geo: 0
houses_created: 0          (нет дубликатов!)
fetch_failures: 0
parse_failures: 0
`

### 9.5 v2 vs v3

| | v2 | v3 |
|---|---|---|
| House key | source + external_house_id | (lat, lng) + address |
| House creation | Per external_house_id (1 row per cian house) | Only on spatial miss (with source='auto') |
| Linker priority | cian_house_id exact → spatial fallback | cian_house_id cross-ref → spatial |
| Pollution | 1,206 duplicate houses | 0 (GOOD_SOURCES excludes cian_active) |
| Per-ad cost | 0 (spatial match) | 0 (same) |
| DaData/ФИАС needed? | No | No (only for orphan geocoding, edge case) |

### 9.6 Дальше

- [x] Migration: 711 dups deleted
- [x] Pipeline v3: spatial-first, no pollution
- [ ] Full pipeline run on 2,962 active cian_ads (in progress, PID 384, started 23:52, ETA 23:55+3h)
- [ ] UI: заменить MapApp.tsx endpoints на новые (если ещё не сделано)
- [ ] domclick (по запросу пользователя — позже)
- [ ] Cleanup: удалить legacy services/parsers/cian_active/, scripts/cian_fetch.py, scripts/cian_parse.py
- [ ] Memory: сохранить learnings про spatial-first matching
