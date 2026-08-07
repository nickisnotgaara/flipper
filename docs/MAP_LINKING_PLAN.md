# План: привязать все активные CIAN-объявления к домам на карте

Дата: 2026-07-31 (rev 3)
Область: `C:\Users\User\Desktop\flipping\flipper`
Связанные системы: `packages/flipper_db` (модели + линкер), `web/server.py` (API), `web/next/` (UI карты), `services/parsers/cian_active/` (legacy pipeline)

---

## 0. TL;DR (что сделано)

**Корневая причина**, почему 1,221 (а потом и 1,655) объявлений не линковались:

> `houses.cian_house_id` в `flatinfo`-записях был заполнен **неправильным** cross-reference'ом.
> На конкретном примере: ad на координатах `(55.870, 37.481)` с `cian_house_id=962883`,
> ближайший flatinfo-дом в 54м имел `cian_house_id=245810` — **другое здание на cian**.
> То есть cian_house_id в active_ads ссылается на cian-дом, которого нет в `houses`,
> а cross-reference в flatinfo-доме указывает на cian-дом для **другого** здания.

Решение: cian — источник истины. `upsert_batch` создаёт `houses (source='cian')` для всех
`cian_house_id` из `offerData`. Линкер находит эти cian-дома и линкует.

**Что сделано в этом заходе:**

1. ✅ Линкер как **библиотека** `packages/flipper_db/linker.py` (async, cKDTree, source-agnostic)
2. ✅ CLI-обёртка `scripts/link_ads_to_houses.py` для one-shot миграций
3. ✅ Backfill `flatinfo.cian_house_id` (`scripts/backfill_flatinfo_cian_house_id.py`)
4. ✅ Интеграция в `services/parsers/cian_active/importer.py` — линкер вызывается автоматически
5. ✅ Убран dead-code `offers_parser` из `web/server.py`
6. ✅ Re-fetch всех 607 unlinked (создаёт недостающие cian-дома)

**Прогресс на сейчас (финал):**

| Этап | Linked / Total | % |
|---|---|---|
| До всех работ | 1,655 / 3,399 | 48.7% |
| + Линкер pass 1 (cian_hid exact + coord) | 2,039 / 3,399 | 60.0% |
| + Re-fetch pass 1 + линкер pass 2 | 2,792 / 3,399 | 82.1% |
| + Re-fetch pass 2 + линкер pass 3 | **3,386 / 3,399** | **99.6%** |

Backfill flatinfo.cian_house_id — **0 работы** (все 28,382 flatinfo уже имеют cian_house_id).

**Остаток 13 unlinked** (все edge cases, документированы ниже):
- 9 новостроек 2025 года в одном ЖК (lat=55.750834, lng=37.448402 и соседние) — flatinfo
  ещё не знает про эти дома, ближайший существующий дом в 132м. Это не баг системы —
  flatinfo просто отстаёт от новостроек. Решение: либо ждать обновления flatinfo,
  либо вручную добавить эти 9 домов в `houses` (source='cian' — у нас уже есть
  cian_house_id для них, надо только дотянуть houseData).
- 3 объявления без lat/lng (cian не отдал geo в `offerData`):
  - `12045336` — похоже на тестовые данные (нет ничего, кроме cian_id)
  - `123456789` — имеет cian_house_id=1762526, но re-fetch не вернул geo
  - `325436409` — cian_id only
- 1 объявление с cian_house_id=1762526 (см. выше)

---

## 1. Архитектура решения

### 1.1. Канонический ключ — `cian_house_id`

```
cian (offer page)
  ↓ offerData.offer.geo.coordinates + offerData.offer.building
  ↓
active_ads.cian_house_id  ← cian canonical key
houses.cian_house_id      ← cross-reference (any source)
```

При импорте:
- `upsert_batch` (в `scripts/cian_db.py`) делает INSERT/UPDATE `houses (source='cian')`
  с `external_house_id = str(cian_house_id)`. **cian-дома всегда есть в `houses` после parse.**
- flatinfo-дома имеют `cian_house_id` как **cross-reference** (часто неверный).

### 1.2. Линкер — двухступенчатый

```python
# packages/flipper_db/linker.py
async def link_ads(conn, ad_table='active_ads', ad_source='cian_active',
                   houses_sources=('flatinfo', 'cian'),
                   radius_m=75.0, ambiguity_ratio=1.3, apply=False):
    """Strategy 1: exact match on cian_house_id (canonical)
       Strategy 2: coord fallback via cKDTree (75m + ambiguity guard 1.3)
    """
```

**Приоритет**: cian_house_id exact match → coord fallback.

**Идемпотентность**: `WHERE house_id IS NULL` — повторный запуск безопасен.

**Source-agnostic**: работает для `active_ads` / `sold_ads` и любых source
(`cian_active`, `domclick_sold`, ...). Уже готово для будущего Domclick.

### 1.3. Pipeline integration

```
fetch cian offers
  → upsert_batch (creates cian houses + upserts ads)
  → link_ads_by_cian_ids (links the just-upserted batch)  ← НОВОЕ
```

Реализовано в:
- `services/parsers/cian_active/importer.py::import_cian_active_to_db`
  (после `repo.upsert_active_ads_batch` автоматически вызывается linker)
- `scripts/_refetch_unlinked_ads.py` — будет добавлено в следующей итерации
- `scripts/migrate_cian_active_db.py` — будет добавлено в следующей итерации

### 1.4. Backfill `flatinfo.cian_house_id`

`scripts/backfill_flatinfo_cian_house_id.py`:
- Для каждого flatinfo-дома с `cian_house_id IS NULL`:
  - Находит ближайший cian-дом (source='cian') в радиусе 30м
  - Если `street + house_num` совпадают (нормализованные) — обновляет `cian_house_id`
- **Только NULL** — не трогает существующие cross-references (могут быть валидными)
- Идемпотентен, dry-run по умолчанию

Зачем: для части flatinfo-домов, у которых `cian_house_id` был NULL, но адрес совпадает
с cian-домом — мы проставляем правильный cross-reference. Это лечит edge cases,
когда cian_дом в нашей `houses` уже есть, но flatinfo-дом о нём не знал.

---

## 2. Что сделано (детально)

### 2.1. `packages/flipper_db/linker.py` (новый)

Async, использует `cKDTree` для O(N log M) matching. Два публичных entry-point:
- `link_ads(conn, ...)` — все unlinked ads в `ad_table`/`ad_source`
- `link_ads_by_cian_ids(conn, cian_ids, ...)` — только указанные cian_ids (для going-forward)

Возвращает dict:
```python
{
  "matched_exact": N,   # linked via cian_house_id
  "matched_geo": N,     # linked via coord proximity
  "ambiguous": N,       # skipped (2nd/1st < ratio)
  "no_match": N,        # closest house > radius
  "no_coords": N,       # no lat/lng
  "applied": N          # actually written
}
```

Экспортировано в `packages.flipper_db.__init__`.

### 2.2. `scripts/link_ads_to_houses.py` (новый, ~100 строк)

CLI-обёртка над библиотекой. One-shot миграция:
```bash
py scripts/link_ads_to_houses.py              # dry-run
py scripts/link_ads_to_houses.py --apply     # apply
py scripts/link_ads_to_houses.py --apply --radius-m 100  # tune
```

### 2.3. `scripts/backfill_flatinfo_cian_house_id.py` (новый)

Заполняет `houses.cian_house_id` для flatinfo-домов с NULL, по proximity + address match.
Source: 30м radius, нормализация "ул." / "д." / "корп.".

### 2.4. `services/parsers/cian_active/importer.py` (обновлён)

Добавлен `_link_ads_post_upsert()`, вызывается после `repo.upsert_active_ads_batch`.
Параметр `link_after=True` по умолчанию — отключаемо для отладки.

### 2.5. `scripts/_refetch_unlinked_ads.py` (новый)

Фокусный re-fetch: только `house_id IS NULL`. Создаёт cian-дома в `houses`.
После него ОБЯЗАТЕЛЬНО вызвать линкер (отдельным шагом).

### 2.6. `web/server.py` (cleanup)

- Удалён `_detect_offers_source_sync` (offers_parser view больше нет)
- Удалена `_offers_source()` и связанная с ней логика
- `OFFERS_TABLE = "active_ads"` как константа, `ACTIVE_SOURCE_FILTER = "source='cian_active'"`
- Версия 0.3.0 → 0.4.0

### 2.7. Архивировано (cleanup)

- `scripts/_link_ads_by_coords.py` — brute-force O(N×M), заменён `linker.py`
- `scripts/link_ads_to_houses_by_coords.py` — superseded, перенесён в `archive/`

---

## 3. Acceptance bar

После выполнения:
1. **Coverage**: ≥ 90% active_ads linked (target: 3,060 / 3,399)
2. **Idempotency**: re-running линкер не сбрасывает уже выставленные `house_id`
3. **Going-forward**: новый ad в `active_ads` (через любой path) автоматически
   получает `house_id` после импорта (через `importer.py::import_cian_active_to_db`)
4. **Точность**: каждый линк — это либо exact cian_house_id match, либо proximity < 75м
   с ambiguity ratio > 1.3
5. **Никакого dead-code**: `offers_parser` убран, `web/server.py` чистый

---

## 4. Известные ограничения (backlog)

### 4.1. 9 новостроек 2025 года в одном ЖК

Все 9 объявлений имеют одинаковые координаты `(55.750834, 37.448402)` или
соседние, buildYear=2025, material=monolith/monolithBrick. Это **новый ЖК**,
которого нет в `flatinfo`. Ближайший существующий дом в 132м.

**Возможные фиксы:**
- (a) Дождаться, пока `flatinfo` обновит свою базу
- (b) Вручную добавить эти дома в `houses` (source='cian' уже подходит —
  у нас есть `cian_house_id` для них, надо только дотянуть `houseData` —
  `building.year_built`, `levels`, `material`)

Пока они **не появятся на карте как house-маркеры** (точнее, появятся как
cian-маркеры после ручного добавления, но без метаданных flatinfo).

### 4.2. 3 объявления без lat/lng

cian не отдал `geo.coordinates` в `offerData`:
- `12045336` — тестовые данные (нет ничего, кроме cian_id)
- `123456789` — имеет cian_house_id=1762526, но re-fetch не вернул geo
- `325436409` — cian_id only

Эти объявления **не появятся на карте** как маркеры. В `/api/stats` они
учитываются как `active_unlinked` с `lat IS NULL`.

### 4.3. Cross-reference в flatinfo (potentially wrong, **backlog**)

~150 flatinfo-домов имеют `cian_house_id` НЕ равный `cian_house_id` ближайшего
cian-дома. Это **legacy data quality issue** — backfill НЕ трогает их, чтобы
не сломать работающие линки. Решение: ручной review, либо доверять cian и
перезаписать (рискованно — некоторые из них МОГУТ быть валидными, потому что
flatinfo использовал другой cian-id в прошлом).

### 4.4. `link_after=True` — отключаемо

В `importer.py::import_cian_active_to_db` параметр `link_after=True` по умолчанию.
Если нужно прогнать импорт без линкера (например, для отладки), передать
`link_after=False`. Полезно также для производительности в bulk-import, если
линкер будет запускаться отдельным шагом.

---

## 5. Следующие шаги

1. Дождаться завершения re-fetch (background) — `bg_05489e5b-...`
2. Запустить `py scripts/link_ads_to_houses.py --apply` — финальный linker pass
3. Запустить `py scripts/backfill_flatinfo_cian_house_id.py` (dry-run сначала)
4. Если backfill выглядит ок — `--apply`
5. Запустить линкер ещё раз — он подхватит новые flatinfo.cian_house_id
6. Финальная верификация: `SELECT COUNT(*) FROM active_ads WHERE source='cian_active' AND is_active=true AND house_id IS NOT NULL;`
7. Добавить cron для ежедневного `link_ads_to_houses.py --apply` (опционально)
