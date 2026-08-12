# Changelog

All notable changes to Flipper. Format: [Keep a Changelog](https://keepachangelog.com/).
Dates: YYYY-MM-DD.

---

## [Unreleased] — 2026-08-12

### Changed — Архивированы 3 ручных парсера

- **Заархивированы** (больше не запускаются автоматически):
  - `services/parsers/flatinfo_houses/` → `_tmp_archive/parsers_manual/flatinfo_houses/`
  - `services/parsers/winners_sold/` → `_tmp_archive/parsers_manual/winners_sold/`
  - `services/parsers/cian_sold/` → `_tmp_archive/parsers_manual/cian_sold/`
- **Причина:** дома обновляются раз в 2-3 мес, снятые уже почти все в БД (270k+),
  разные источники дублируют друг друга. Автозапуск — зря расход ресурсов.
- **Сопутствующие правки:**
  - `docker-compose.yml` — убраны сервисы `flatinfo_houses`, `winners_sold`, `cian_sold`
  - `services/scheduler/main.py` — убран `job_weekly_winners` (больше не нужен)
  - `services/parsers/__init__.py` — обновлён docstring (2 авто + 3 архив)
  - `_tmp_archive/parsers_manual/README.md` — инструкция по ручному запуску

### Changed — Ручные парсеры всё ещё доступны

Если нужно разово поднять `flatinfo_houses` или `winners_sold`:
```bash
cp -r _tmp_archive/parsers_manual/<parser> services/parsers/
# (опционально) добавить блок в docker-compose.yml
docker compose run --rm <parser>
```

### Changed — Полный rename брендинга на Flippercrawl

- Все упоминания старого scrape-сервиса → `flippercrawl` в коде, .env,
  _run_*.cmd, docker-compose, docs
- Старые имена env vars → `FLIPPERCRAWL_*` (`FLIPPERCRAWL_API_KEY`,
  `FLIPPERCRAWL_BASE_URL`)
- Legacy fallback в `grist.py` / `cards.py` / `config.py` / `queue.py` удалён
  (clean break — внешних scrape-сервисов для нас не существует)
- Документация: `README.md`, `SYSTEM.md`, `DEVELOPMENT.md`, `CHANGELOG.md`,
  `AGENTS.md`, `PROJECT_OVERVIEW.md`, `ARCHITECTURE.md`
- Переименован старый debug-скрипт `scripts/dump_*_scrape_body.py` →
  `scripts/dump_flippercrawl_scrape_body.py` (git mv сохранил историю)

### Fixed — `NameError: status_active is not defined`

- **Баг:** переменная `status_active` создавалась в `_process_url` но использовалась
  в `_handle_offers` без передачи параметром. Все НЕснятые объявления падали с ошибкой.
- **Фикс:** `status_active` теперь параметр `_handle_offers(..., status_active)`.

### Fixed — При `is_active=False` строка не удалялась из Grist Active_ads

- **Баг:** парсер при деактивации оставлял строку в Grist `Active_ads` (orphan).
- **Фикс:** добавлен вызов `grist.delete_by_external_id("Active_ads", cian_id)` при `is_active=False`.
- **Заодно:** добавлены методы `find_by_external_id` / `delete_by_external_id` в
  `packages/flipper_core/grist.py` (старый `find_by_cian_id` падал с "no such column:
  cian_id" на таблицах с `external_id` колонкой).

### Verified — Integration test деактивации

- Создан `_tmp_test_deactivation.py` который вызывает `_handle_offers(..., is_active=False)`
- Все три поведения проверены и работают:
  - PG: `cian_active_ads` → удалено, `cian_sold_ads` → добавлено
  - Grist `Offers_Parser`: status="deactivated" (НЕ удалено, помечено)
  - Grist `Active_ads`: удалено (фикс работает)
- Тестовые данные откачены.

### Added — Условное форматирование Grist

- **`scripts/grist_apply_conditional_formatting.py`** — навешивает cell-style правила
  на колонку `status` во всех 6 парсер-таблицах через Grist user-actions:
  - `AddEmptyRule(table_id, 0, status_col_ref)` создаёт helper-колонку
    `gristHelper_ConditionalRule*` с `formula` + `widgetOptions.rulesOptions`.
  - Идемпотентно: если правило с такой формулой уже есть — обновляет только цвет;
    если нет — создаёт новое.
  - Цвета: `deactivated` → серый `#E5E7EB`, `hot` → зелёный `#D1FAE5`,
    `signal` / `deposited` → жёлтый `#FEF3C7`.
  - Идемпотентен, поддерживает `--dry-run` и `--tables Sold_Ads,Offers_Parser`.
- 9 правил применены к: `Sold_Ads`, `Offers_Parser` (×2), `Signals_Parser`,
  `Table2` (×2), `Table3` (×2), `Arhiv_Prodano`.

### Notes — почему cell-style, а не row-style

В Grist row-style правила (`gristHelper_RowConditionalRule*`) применяются только к
`rawViewSectionRef`, не к primary view section, которая отображается в UI по
умолчанию. Cell-style на колонке `status` гарантированно красит ячейку во всех
view и не зависит от section-иерархии.

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

- `services/parsers/cian_active` — новый активный парсер на self-hosted
  Flippercrawl. Pipeline: `FILTERS` → DB → `Offers_Parser/Sold_Ads`.
- 6 reference-таблиц в Grist: Houses2 ↔ Active_ads ↔ AdPhotos (cross-table Refs).
- Pre-aggregated chart tables: HousesByDistrict_v2/v3, ActiveAdsByFilter/Month,
  HousesByDecade/Era/Height, PriceByDecade.
- `docs/GRIST_EXPERIMENTS.md` — набор формул-экспериментов.

---

## [0.2.0] — 2026-07-30

### Added

- `flippercrawl` — self-hosted парсер Cian. Static-путь `data.json.rawOfferData`.
- `services/cookie_manager` — Chromium + FastAPI для cookie rotation.
- `services/html_to_markdown` — Go-сервис HTML → Markdown.

### Changed

- `parsers/cian_active` переехал с прямого HTML-парсинга на Flippercrawl.

---

## [0.1.0] — 2026-07-15

### Added

- Инициализация проекта.
- `parsers/cian_active` (через google-api-python-client) + Google Sheets backend.
- PostgreSQL schema: `houses`, `active_ads`, `sold_ads`.
- FastAPI backend (`web/server.py`) с `/api/stats`.
- Next.js 14 фронтенд с картой Leaflet.
