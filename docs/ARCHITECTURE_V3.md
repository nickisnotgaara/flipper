# Архитектура v3: houses = union(flatinfo + cian_ad + cian_sold)

Дата: 2026-08-02
Область: `C:\Users\User\Desktop\flipping\flipper`
Предыдущая версия: [ARCHITECTURE_V2.md](ARCHITECTURE_V2.md)

---

## 0. Что изменилось относительно v2

**Главное:** v2 планировал универсальный `SourceParser` Protocol для cian/domclick/winners.
**v3 по факту:** жёсткий pivot — `houses` стал union трёх источников, без protocol-абстракции.

| Аспект | v2 план | v3 факт |
|---|---|---|
| Houses | `source` enum: `flatinfo/cian/domclick/winners` | `source` enum: `flatinfo/cian_ad/cian_sold` |
| Auto-create house | Только при парсинге, через `SourceParser.fetch_house_page` | Bulk roll-out скриптами: `_rollout_active.py`, `_rollout_sold_houses.py` |
| Lat/lng для новых домов | Fetch с cian house page | cian_ad берёт из `raw.offer.geo.coordinates`; **cian_sold НЕ имеет lat/lng** (старая схема) |
| Metadata в `/api/clusters` | Один дом = один набор метаданных | **Три приоритета:** house_id (cian_ad/flatinfo) > cKDTree flatinfo fallback > None |
| Pipeline v4 (re-parse) | Планировался как coverage extension | **Отменён** — только refresh prices/deactivate |
| Domclick | В плане | **DEFERRED** — нет публичного read API |
| Winners | В плане | **DEFERRED** — 180d задержка, дубликаты cian/avito |
| `enriched_from_source` | Не было | **DONE** — `flatinfo` (готовая) / `cian_ad` (из объявления) / `manual` |
| Active ads linked | 1 817 / 2 962 (61%) | **2 962 / 2 962 (100%)** |
| Sold ads linked | 31 635 / 232 211 (14%) | **232 211 / 232 217 (99.99%)** |

---

## 1. Текущее состояние БД (snapshot 2026-08-02 00:30)

```
=== houses (47,918 total) ===
  flatinfo     28,382  with_lat=28,382  with_addr=28,382  with_year=28,382
  cian_sold    18,135  with_lat=    0  with_addr=17,946  with_year=17,800
  cian_ad       1,401  with_lat= 1,401  with_addr= 1,401  with_year=  930

=== active_ads (2,962 total) ===
  cian_active   2,962  linked=2,962  (100%)

=== sold_ads (232,217 total) ===
  cian_deactivated  231,316  linked=231,316
  cian_active           901  linked=    895  (6 corruption, не критично)

=== sold_ads.house_id -> houses.source ===
  cian_sold    200,570
  flatinfo      31,641
```

---

## 2. Houses — три источника

### 2.1. `flatinfo` (28 382) — primary base

- Импортировано из flatinfo (csv/БД)
- **Полные данные**: lat, lng, address, street, house_num, year_built, levels, building_type, series
- `external_house_id` = flatinfo_id
- `enriched_from_source = 'flatinfo'`
- Создан ДО этой работы, источник правды для legacy данных

### 2.2. `cian_ad` (1 401) — auto-created from active ads

- Создано скриптом `_rollout_active.py` (см. `data/logs/`)
- Источник: `raw.offer.geo.coordinates.{lat,lng}` + `raw.offer.geo.address[]` (cian API)
- `external_house_id` = `cian:{cian_house_id}`
- `enriched_from_source = 'cian_ad'`
- `created_from_ad = 'active_ads'`
- **Покрытие:** 1 044/1 401 (74.5%) с address, 930/1 401 (66.4%) с year_built
- Backfill адреса: `_backfill_address.py` (фикс JSON path `raw.offer.geo.address`, не `raw.geo.address`)

### 2.3. `cian_sold` (18 135) — auto-created from sold ads

- Создано скриптом `_rollout_sold_houses.py` (см. `data/logs/`)
- Источник: `raw_data->>'address'`, `'street'`, `'house_num'`, `'build_year'`, `'materialType'` (top-level в raw_data)
- **НЕТ lat/lng** — sold_ads используют старую схему, где координаты не сохранялись
- `external_house_id` = `cian:{cian_house_id}`
- `enriched_from_source = 'cian_sold'`
- `created_from_ad = 'sold_ads'`
- Используется для связки sold_ads → house_id, **но НЕ для карты** (нет координат)

### 2.4. Схема объединения (union)

```
            ┌─────────────────────────────────────┐
            │  houses                              │
            │  source IN ('flatinfo',             │
            │           'cian_ad',                │
            │           'cian_sold')              │
            └──────────┬──────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
   flatinfo (28k)  cian_ad (1.4k)  cian_sold (18k)
   полные данные   полные данные    только мета
        │              │              │
        └──────┬───────┴──────┬───────┘
               │              │
         active_ads       sold_ads
         2 962/100%       232 211/99.99%
```

**Правила:**
- Один `cian_house_id` может быть в `cian_ad` (с lat/lng) и `cian_sold` (без) одновременно
- В `linker.match_or_create_house()` приоритет: cian_ad > flatinfo > cian_sold (по полноте)
- В `/api/clusters` метаданные берутся с `house_id` напрямую (без cross-source merging)

---

## 3. Metadata priority в `/api/clusters`

Файл: `web/server.py:906` (endpoint `clusters`)

```python
# 1. Собрать house_ids из synthetic cluster
WITH grp AS (...)
SELECT array_agg(DISTINCT house_id) FILTER (WHERE house_id IS NOT NULL) AS house_ids

# 2. Batch lookup
SELECT id, source, year_built, levels, building_type, series, address,
       street, house_num, enriched_from_source
FROM houses WHERE id = ANY(:hids)

# 3. Priority для каждого cluster:
#    a) house_id (cian_ad) > house_id (flatinfo) > house_id (cian_sold)
#    b) fallback: cKDTree до ближайшего flatinfo дома
#    c) None (если ничего)
```

Файл: `web/server.py:1211` (endpoint `cluster_ads`)

```python
# 1. Получить все house_id из ad в bbox
SELECT DISTINCT house_id FROM active_ads
WHERE source='cian_active' AND house_id IS NOT NULL
  AND lat BETWEEN ... AND ...

# 2. Fetch house row, prefer cian_ad > flatinfo
# 3. Return house metadata
```

---

## 4. Что в процессе / сделано

### ✅ Сделано (закрыто)

- [x] `houses.source` миграция: добавлены `cian_ad`, `cian_sold`
- [x] `houses.enriched_from_source` + `_source` поля (year_built_source, levels_source, etc)
- [x] `linker.match_or_create_house()` умеет auto-create для активных ad
- [x] `_rollout_active.py` — 1 145 cian_ad домов из active_ads
- [x] `_rollout_sold_houses.py` — 18 135 cian_sold домов из sold_ads
- [x] `_backfill_address.py` — 1 044 адресов для cian_ad (исправлен JSON path)
- [x] `_backfill_sold_house_id.py` — 200 576 sold_ads → house_id
- [x] `/api/clusters` использует cian_ad приоритет
- [x] `/api/clusters/{id}/ads` использует house_id ad (не cKDTree)
- [x] 100% active_ads linked (2 962/2 962)
- [x] 99.99% sold_ads linked (232 211/232 217)

### 🔄 В процессе

- [ ] **Reparse pipeline (PID 15628)** — обновляет цены/деактивирует, ~5.6 ads/min
- [ ] **UI testing** — ждём фидбэк на http://127.0.0.1:3000 (Q1: инфа о доме стабильна?)

### 📋 В очереди (можно без блокировки UI)

- [ ] **Sold-only map view** — `/api/clusters?include_sold=true` (без lat/lng, через synthetic clusters)
- [ ] **deact count badge** — "X снято" на маркере дома (per house, не per cluster)
- [ ] **`/api/stats` дополнить** — добавить `houses_by_source`, `sold_ads_by_source`
- [ ] **2-parallel reparse** — ускорить обновление (сейчас 1 поток ~5 ads/min)
- [ ] **deact-stale cleanup** — ads неактивные >180 дней → перенести в sold_ads

### ⏸ Deferred (явно отложено)

- [ ] **domclick** — нет публичного read API
- [ ] **winners** — 180d задержка, дубликаты cian/avito
- [ ] **ФИАС/GAR** — gold standard, но внешний сервис (забанено)
- [ ] **dom.mos.ru loader** — 34 413 паспортов, stale since 2021-07-16
- [ ] **OpenStreetMap import** — внешний, забанено
- [ ] **Pipeline v4 (coverage)** — отменён, только refresh prices

---

## 5. Скрипты (см. `data/logs/`)

| Скрипт | Что делает | Артефакт |
|---|---|---|
| `_rollout_active.py` | 1 145 cian_ad домов из active_ads | houses WHERE source='cian_ad' |
| `_rollout_sold_houses.py` | 18 135 cian_sold домов из sold_ads | houses WHERE source='cian_sold' |
| `_backfill_address.py` | 1 044 адресов для cian_ad (fix path) | houses.address/street/house_num |
| `_backfill_sold_house_id.py` | 200 576 sold_ads → house_id | sold_ads.house_id |
| `_inspect_schema.py` | dump schema houses/sold_ads/active_ads | stdout |
| `_snapshot.py` | общий snapshot БД | stdout |

---

## 6. Известные ограничения

1. **cian_sold без lat/lng** — 200 570 sold_ads привязаны, но не покажутся на карте (нет координат)
2. **active_ads 6 corruption** — 6 ad с `source='cian_active'` в sold_ads (legacy, не критично)
3. **Кодировка sold_ads** — windows-1251 в БД (видно как "�����" в psql), нужно парсить через utf-8 ignore
4. **UI не показывает source badge** — пока все дома выглядят одинаково, надо добавить визуальный индикатор
5. **reparse медленный** — 1 поток, ~5 ads/min; ~2 200/час. На 232k уйдёт ~100 часов. Нужно 2+ параллельных.

---

## 7. Решения (лог)

| Дата | Решение | Контекст |
|---|---|---|
| 2026-08-01 | houses = union(flatinfo + cian_ad) | пользователь: "Это уже будет не flatinfo база а база домов" |
| 2026-08-01 | cian_sold как 3-й source | sold_ads без lat/lng, но нужны для связи с домами |
| 2026-08-01 | enriched_from_source + _source per field | аудит где откуда пришло |
| 2026-08-01 | Metadata priority: house_id > cKDTree | ad знает свой дом точнее, чем cKDTree до flatinfo |
| 2026-08-01 | pipeline v4 = отменён | только refresh prices, не новые дома |
| 2026-08-01 | domclick = DEFERRED | нет публичного read API |
| 2026-08-01 | winners = DEFERRED | 180d delay, дубликаты |
| 2026-08-01 | MAX 2 DAYS | пользователь: "не решаешь сколько времени займёт разработка" |
| 2026-08-02 | bulk roll-out, не incremental | 200k sold_ads за 20 сек, vs инкремент за часы |

---

## 8. Что осталось до "готово к продакшну"

**Must have (Q1 пользователя):**
- [x] 100% active_ads linked → house info видна на UI
- [ ] UI визуально подтверждает: каждый дом имеет year/type/address

**Should have:**
- [ ] Sold-only кластеры на карте (счётчик "X снято" на маркере)
- [ ] `/api/stats` показывает источники

**Nice to have:**
- [ ] 2-parallel reparse (ускорение в 2x)
- [ ] Source badge в UI (cian_ad vs flatinfo цвет)

**Won't have (эта итерация):**
- Domclick, Winners, ФИАС, dom.mos.ru, OSM
