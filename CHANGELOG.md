# Changelog

All notable changes to Flipper. Format: [Keep a Changelog](https://keepachangelog.com/).
Dates: YYYY-MM-DD.

---

## [Unreleased] — 2026-08-11

### Migration: Google Sheets → Grist (major)

`parsers/cian_active` (и все хелперы) переехали с **Google Sheets API** на
**self-hosted Grist** (http://localhost:8484). Причины: rate limits Google Sheets,
отсутствие `apply` с батчами, тяжёлый OAuth, дороговизна при 270k+ строках.

**Grist doc:** `Parcing` (`mDaHoGD6yahtxaqugwr5mK`). 10 таблиц (вместо 27):

| tableId        | Display         | Rows   | Назначение                                        |
|----------------|-----------------|--------|---------------------------------------------------|
| `FILTERS`      | Фильтры         | ~10    | URL для `cian_active` (бывш. вкладка Sheets)       |
| `Active_ads`   | Активные        | 5 227  | Текущие активные объявления                       |
| `Sold_Ads`     | **Снятые** (new)| 270 387| Все снятые публикации (вместо старой «Продано»)   |
| `Arhiv_Prodano`| Архив Продано   | 3 119  | Legacy-данные старой вкладки «Продано» (read-only)|
| `Offers_Parser`| Парсер Офферс   | ~5k    | Текущие результаты парсера                        |
| `Signals_Parser`| Сигналы        | ~500   | Объявления с признаком «сигнал»                   |
| `Table2`       | Аванс           | ~1k    | Активные авансовые                                |
| `Table3`       | Аванс_Продано   | ~400   | Снятые авансовые                                  |
| `Balans`       | Баланс          | ~rows  | Дневной счётчик category_counter                  |
| `Houses2`      | База домов      | 30 868 | Реестр домов (lat/lng/year/...)                   |

**Удалены** legacy таблицы: `Table4` (6 428 rows) и `Table6` (70 680 rows) — старые
импорты, дублирующие данные в PG.

### Added

- **`packages/flipper_core/grist.py`** — Grist-клиент (замена `sheets.py`):
  `sql()`, `apply()`, `upsert_dict()`, `sync_offers_and_signals_with_status()`,
  `add_balans_row()`, поиск/удаление по `cian_id`.
- **`scripts/sync_sold_to_grist.py`** — `sold_ads` (PG) → `Sold_Ads` (Grist).
  Batched через `POST /tables/{t}/records` (~415 rows/s). Skip-existing по
  `cian_id`. Truncate `title/address/description` чтобы влезть в Grist payload.
- **`scripts/sync_active_to_grist.py`** — `active_ads` (PG) → `Active_ads` (Grist).
- **Колонки `status` (Text)** во всех парсер-таблицах (`Offers_Parser`,
  `Signals_Parser`, `Table2`, `Table3`, `Sold_Ads`) — для conditional formatting.
  Значения: `active | hot | signal | deactivated | deposited`.
- **Колонки `photos_url` + `map_url`** (формулы) в `Sold_Ads`, `Active_ads`,
  `Houses2` → `/map?photoAd={cian_id}` и `/map?house={house_id}`.
- **Sidebar.tsx (Next.js)**: урезана до 3 пунктов — `Дашборд / Карта / Таблицы`.
  Удалены `filters / pipeline / settings / analytics` (всё ушло в Grist).
- **Page files**: перенесены в `_tmp_archive/` (`filters/`, `pipeline/`,
  `settings/`, `analytics/`, `GristTable.tsx`).
- **Sidebar → Дашборд как home**, `/` → `/dashboard`.
- **AdPhotosModal** в `web/next/components/` — UI-компонент для галереи фото
  (открывается по `photos_url`).
- **HousePanel/MapApp/PhotoGallery** — поддержка query-параметров
  `?house=...&photoAd=...`.

### Changed

- **`services/parsers/cian_active/config.py`**:
  `sheet_tab_sold: "Table1"` → `sheet_tab_sold: "Sold_Ads"` (теперь
  `Sold_Ads` = «Снятые» — основная таблица для deactivated, archive = read-only).
- **`acquirer/queue.py`**: при `is_active=False` пишет в `Sold_Ads` (а не в
  legacy `Table1`). Статус: `deactivated` / `deposited` / `hot` / `active`.
- **`acquirer/queue.py`**: добавлен `_views_per_day()` — определяет `hot` при
  `>200 unique_views/day`.
- **`services/category_counter/main.py`**: использует `GristClient.add_balans_row()`.
  Добавлен dedup по дню (MSK) — один ряд в день, остальные skip.
- **`.env.example`**: `SPREADSHEET_ID/CREDENTIALS_PATH` → `GRIST_API_KEY/GRIST_BASE/GRIST_DOC`.
- **`packages/flipper_core/`**: `sheets.py` перенесён в `_tmp_archive/`.
- **`services/parser_cian/`** (legacy, 13 файлов) — перенесён в
  `_tmp_archive/parser_cian_legacy/`. Активный парсер — `services/parsers/cian_active/`.
- **`tests/parser_cian/`** (3 файла) — удалены (legacy).
- **`pyproject.toml`**: `ruff.exclude` обновлён (`_tmp_archive/` вместо
  `services/parser_cian/`).

### Removed

- `packages/flipper_core/sheets.py` (SheetsManager) — заменён на GristClient.
- `services/parser_cian/` целиком — legacy parser.
- `tests/parser_cian/` — legacy tests.
- `web/next/app/(dashboard)/{filters,pipeline,settings,analytics}/` — перенесены
  в `_tmp_archive/`.
- `web/next/components/admin/GristTable.tsx` — не используется (Grist отдаётся
  через iframe).
- `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib` из
  requirements.

### Fixed

- `services/parsers/cian_active/config.py` — `sheet_tab_sold` теперь внутренний
  `tableId` (`"Sold_Ads"`), а не display-имя. Без этого каждый write падал с
  `KeyError 'таблица не найдена'`.
- `queue.py` — NULL-safe для `external_id`/`house_id` (иначе TypeError на
  формулах в Grist).
- `category_counter` — раньше дублировал строку каждый запуск (без dedup), теперь
  один row/день.

### Operational notes

- Grist API endpoint: `http://localhost:8484` (GRIST_BASE).
- API-ключ в `.env` (`GRIST_API_KEY`) — НЕ коммитить.
- `/api/apply` принимает body как raw JSON-массив, `/sql?q=...` для SELECT.
- Batching в Grist: `BulkAddRecord` имеет странную сигнатуру, надёжнее
  `POST /api/docs/{id}/tables/{t}/records` с `{"records": [{"fields": {...}}]}`.
- Bulk sync 270к строк занимает ~12 мин (415 rows/s на batch=1000).
- Truncate `description > 2000` chars чтобы не получать `413 Request entity too large`.

---

## [0.4.0] — 2026-08-09

### Added

- Photo gallery в `web/next/components/PhotoGallery.tsx` — карусель постов.
- `/api/ads/{external_id}/photos` endpoint в `web/server.py` — отдаёт фото
  поста из PG.
- House-zoom на карте через query-параметр `?house=...` (MapApp.tsx).

### Changed

- MapApp.tsx — переход на TanStack Query для `/api/stats`, `/api/ads/{id}/photos`.
- Sidebar: убран `Скоринг`, `Настройки`, `Парсинг` — сведено к минимуму.

---

## [0.3.0] — 2026-08-04

### Added

- `services/parsers/cian_active` — новый активный парсер на flippercrawl (НЕ
  firecrawl AI extract). Pipeline: `FILTERS` → DB → `Offers_Parser/Sold_Ads`.
- 6 reference-таблиц в Grist: Houses2 ↔ Active_ads ↔ AdPhotos (cross-table Refs).
- Pre-aggregated chart tables: HousesByDistrict_v2/v3, ActiveAdsByFilter/Month,
  HousesByDecade/Era/Height, PriceByDecade.
- `docs/GRIST_EXPERIMENTS.md` — набор формул-экспериментов.

---

## [0.2.0] — 2026-07-30

### Added

- `flippercrawl` — self-hosted Firecrawl (НЕ AI extract). Static-путь
  `data.json.rawOfferData`.
- `services/cookie_manager` — Chromium + FastAPI для cookie rotation.
- `services/html_to_markdown` — Go-сервис HTML → Markdown.

### Changed

- `parsers/cian_active` переехал с прямого HTML-парсинга на Firecrawl.

---

## [0.1.0] — 2026-07-15

### Added

- Инициализация проекта.
- `parsers/cian_active` (через google-api-python-client) + Google Sheets backend.
- PostgreSQL schema: `houses`, `active_ads`, `sold_ads`.
- FastAPI backend (`web/server.py`) с `/api/stats`.
- Next.js 14 фронтенд с картой Leaflet.
