# План: Dashboard V2 — карта + таблицы на одном экране

**Дата:** 2026-08-08
**Цель:** из map-only приложения сделать полноценный дашборд для риэлтора-флиппера.
Карта остаётся как discovery-инструмент, но рядом — живые таблицы всех
объявлений/домов с фильтрами, сортировкой, экспортом и cross-link на карту.

---

## Контекст

Сейчас фронт — `MapApp.tsx` (703 LOC) + `HousePanel.tsx` (557 LOC).
Карта на весь экран, `HousePanel` выезжает справа при клике на маркер,
внутри — листинг с фото-каруселью. StatsBar сверху.

Данных в базе уже много:

| домен | строк | в день |
|---|---:|---|
| `houses` | 30 868 | — |
| `active_ads` (cian_active) | 5 227 | живые |
| `sold_ads` (cian_active) | 18 375 | недавние, с offerData |
| `sold_ads` (cian_deactivated) | 231 316 | исторические, 75% с фото |
| `sold_ads` (domclick_sold) | 1 998 | новойдемовский прицеп |

Всё это сидит в БД, а юзер видит только то, что влезло в bbox карты.
**Это главная боль**: чтобы понять «а сколько вообще 1-комнатных
без ремонта в ЮАО с ценой < 10М», надо руками панорамировать, кликать,
листать.

Карта — это «где искать». Таблица — это «что подходит». Drill-down —
это «беру или не беру». Все три нужны на одном экране.

---

## Концепция

**Один экран, без tab-переключений между разделами.**
Слева карта (~40% ширины, фиксированная, не скроллится).
Справа таблица (~60%, скроллится внутри). Сверху — тонкий
stats-bar + search. Внизу таблицы — фильтры-сводка и пагинация.

```
┌──────────────────────────────────────────────────────────────────────┐
│ TopBar: 5 227 активных · 233 314 снято · 30 868 домов  [search…]   │
├────────────────────────────────┬─────────────────────────────────────┤
│                                │  Tabs: [Активные][Снято][Скрытые] │
│                                │      [Дома]                          │
│                                │                                     │
│                                │  Filters: [rooms▼][price→] [area→] │
│                                │          [days▼][source▼][Reset]   │
│                                │                                     │
│         MAP (Leaflet)          │  ┌───────────────────────────────┐ │
│         30k маркеров           │  │ Address │ P │ m² │ R │ Days │<│ │
│         кластеризация          │  ├─────────┼───┼────┼───┼──────┼─┤ │
│         click → highlight      │  │ Мск,ул..│ 9 │ 50 │ 2 │  12  │→│ │
│                                │  │ Мск,ул..│12 │ 65 │ 3 │   4  │→│ │
│                                │  │ …                                  │ │
│                                │  └───────────────────────────────┘ │
│                                │   Page 1 / 1024  [Prev][Next] 50pg │
│                                │   [Export CSV]  [Density: ▭▭▭]      │
└────────────────────────────────┴─────────────────────────────────────┘
```

Когда юзер кликает строку в таблице → карта плавно летит к этому дому,
маркер подсвечивается, в правом нижнем углу выезжает мини-карточка
с фоткой и краткими цифрами (вариант — модалка, вариант — отдельная
правая панель, как сейчас HousePanel).

**Главный принцип:** карта никогда не «прячется» пока пользователь
работает с таблицей. Они синхронизированы (hover row → highlight marker,
click row → fly to), но не зависимы (можно смотреть таблицу без карты
и наоборот).

---

## 4 таблицы — что в каждой

### 1. Активные объявления (5 227 строк)

Самые важные — то, что сейчас продаётся. Столбцы:

| Колонка | Зачем |
|---|---|
| `address` | куда идти, + click → fly map |
| `rooms` | фильтр + сортировка |
| `area` | м² |
| `floor` / `total` | этаж/этажность |
| `price` | ₽ |
| `price_m2` | ₽/м² — основная метрика |
| `days_in_exposition` | сколько висит — старые = подозрительно |
| `renovation` | ремонт (Дизайнерский, Евро, Косметический, Без ремонта) |
| `has_avans` | истина/ложь (риск депозита) |
| `photos` | кол-во (0-30) — фото = доверие |
| `source` | cian_active/avans |
| `metro` | ближайшая станция + walk_min |
| `link` | → cian.ru |
| `parsed_at` | когда мы в последний раз это дёргали |

Фильтры: rooms (множественный), price [min,max], area [min,max],
days [min,max], has_avans (bool), has_photos (>0), source.
Сортировка: по любой колонке. Default: `price_m2 ASC`.
Спецколонка: «days/price_m2» — отношение, перекос рынка.

### 2. Снятые / comps (cian_active) (18 375 строк)

Недавно снятые — у нас есть offerData, фото, цена, sold_date.
Главное — «за сколько такие же ушли». Столбцы:

| Колонка | Зачем |
|---|---|
| `address` | + click → fly map |
| `sold_date` | когда ушло |
| `days_on_mposition` | сколько висело |
| `price` (final) | ₽ |
| `price_m2` | ₽/м² |
| `rooms`, `area`, `floor` | для сравнения |
| `price_history` | был ли дамп (тренд вниз = мотивация) |
| `source` | |

Фильтры: rooms, price, area, sold_date [from,to], days.
Default sort: `sold_date DESC`.
«Это сколько стоили квартиры в этом доме» — самый частый запрос,
он тут.

### 3. Скрытые / cian_deactivated (231 316 строк)

Исторические с 75% фото. Здесь главный фильтр — **есть ли фото**.
Без фото они всё равно бесполезны (не посмотришь состояние).
Столбцы:

| Колонка | Зачем |
|---|---|
| `thumbnail` | первое фото 80x80, lazy load |
| `address` | + click → fly map |
| `sold_date` | |
| `price` (last) | |
| `area`, `rooms` | |
| `photos_count` | |
| `source` | |

Default filter: `photos_count > 0` (≈173k строк).
Default sort: `sold_date DESC`.
Важная фича: `click thumb` → открывает PhotoGallery в модалке
(слайдер, Esc = закрыть, ←/→ = перелистывать).

### 4. Дома (30 868 строк)

Сама таблица. Колонки:

| Колонка | Зачем |
|---|---|
| `address` | |
| `source` | flatinfo/cian_ad/domclick_sold |
| `year_built` | |
| `material` | кирпич/панель/монолит |
| `floors` | |
| `series` | II-49, П-44 и т.д. |
| `active_count` | сколько объявлений сейчас активно |
| `sold_count` | сколько ушло за всё время |
| `avg_price_active` | средняя текущая ₽/м² |
| `avg_price_sold` | средняя по сделкам |
| `last_active` | когда последний раз видели объявление |
| `lat` / `lng` | click → fly map |

Фильтры: source, year_built [min,max], material (multi), has_ads.
Сортировка: по ad_count (самые горячие наверх), по avg_price_sold.
Это **точка входа** для аналитики — «найди дом, где часто продают
и активные прямо сейчас».

---

## Сквозные фичи (для всех таблиц)

| Фича | Реализация |
|---|---|
| Server-side pagination | API возвращает `{rows, total, page, page_size}`. Default page_size=50, можно 100/200. |
| Server-side sort | `?sort=price&order=asc` |
| Server-side filters | per-column, debounce 300ms, encoded в URL query |
| URL state persistence | фильтры и сортировка в query string, шарингом ссылки |
| Density toggle | `compact` (28px row) / `normal` (44px row) |
| Column visibility | глазок в тулбаре, hide/показать |
| Reset filters | одна кнопка |
| Export CSV | GET `/api/tables/{name}/export?...filters` — стримит CSV |
| Cross-link → map | click row → `map.flyTo(lat,lng, 17)`, маркер пульсирует 2с |
| Hover row → preview | preview-pin на карте (мини-цифры, без открытия панели) |
| Bulk select | checkbox column → bulk action: «открыть N ссылок в новых вкладках» |
| Empty state | «Ничего не нашлось, сбросить фильтры?» |
| Loading | skeleton rows, не spinner (UX-конвенция) |

---

## Технический стек

| Слой | Выбор | Почему |
|---|---|---|
| Table | **TanStack Table v8** | headless, server-side flags (`manualPagination`, `manualSorting`, `manualFiltering`), ~70k★, отличная TS-типизация |
| Virtualization | **TanStack Virtual** | 100k+ rows без тормозов, overscan 5-10 |
| Data fetching | **TanStack Query** | cache, dedupe, auto-refetch, prefetch |
| UI | **HeroUI** (уже) | Card, Table, Chip, Tooltip — всё есть |
| Backend | **FastAPI** (уже) | добавим 4 endpoint'а + 1 export |
| DB | **PostgreSQL** (уже) | с уже существующими индексами на (source, house_id, sold_date) |
| URL state | `nuqs` или `useSearchParams` | встроенный в Next.js, без зависимостей |

`npm install @tanstack/react-table @tanstack/react-virtual @tanstack/react-query` — три пакета, ~100KB gzipped.

---

## API (новые endpoint'ы)

```
GET /api/tables/houses?
    page=1 & page_size=50
    & sort=year_built & order=desc
    & source=flatinfo,cian_ad
    & year_min=1950 & year_max=2010
    & material=кирпич,монолит
    & has_ads=true

GET /api/tables/active?
    page=1 & page_size=50
    & sort=price_m2 & order=asc
    & rooms=1,2
    & price_min=5_000_000 & price_max=15_000_000
    & area_min=30 & area_max=80
    & days_min=0 & days_max=60
    & has_avans=false
    & has_photos=true

GET /api/tables/sold?...     # аналогично
GET /api/tables/deactivated?...

GET /api/tables/{name}/export?...   # стримит CSV с теми же фильтрами
```

Все отдают:

```json
{
  "rows": [...],
  "total": 5227,
  "page": 1,
  "page_size": 50,
  "stats": { "avg_price_m2": 312000, "p25": 245000, "p75": 380000 }
}
```

`stats` — заранее посчитанные распределения по текущему фильтру,
чтобы юзер видел «средняя по выборке 312к, медиана 280к» сразу,
а не панорамировал сам.

---

## Файлы и архитектура

```
web/next/
├── app/
│   └── page.tsx                          # теперь рендерит <Dashboard/>
├── components/
│   ├── Dashboard.tsx                     # NEW — главный layout
│   ├── MapApp.tsx                        # refactor → embedded map
│   ├── TablePanel.tsx                    # NEW — общий контейнер (tabs+filters+table)
│   ├── tables/
│   │   ├── HousesTable.tsx               # NEW
│   │   ├── ActiveTable.tsx               # NEW
│   │   ├── SoldTable.tsx                 # NEW
│   │   ├── DeactivatedTable.tsx          # NEW
│   │   ├── DataTable.tsx                 # NEW — обёртка над TanStack Table
│   │   ├── FilterBar.tsx                 # NEW — общие фильтры
│   │   └── ExportButton.tsx              # NEW
│   ├── MapPanel.tsx                      # NEW — extract из MapApp
│   ├── HousePanel.tsx                    # refactor → optional side panel
│   ├── PhotoGallery.tsx                  # уже есть, обновить
│   ├── StatsBar.tsx                      # остаётся, тонкий сверху
│   ├── SearchBox.tsx                     # остаётся
│   └── PhotoCarousel.tsx                 # остаётся
├── lib/
│   ├── api.ts                            # + новые fetchTable* функции
│   ├── useTableState.ts                  # NEW — URL state + TanStack state
│   └── tableColumns.ts                   # NEW — определения колонок

web/server.py                             # + 4 endpoint'а + 1 export
```

---

## Фазы (предложение, 10-14 рабочих дней)

### Phase 0 — подготовка (0.5 дня)
- `npm i @tanstack/react-table @tanstack/react-virtual @tanstack/react-query`
- засунуть QueryClientProvider в `app/layout.tsx`

### Phase 1 — каркас (1.5 дня)
- `Dashboard.tsx` — split-pane layout, табы в правой панели
- `TablePanel.tsx` — пустые табы «Активные / Снято / Скрытые / Дома»
- карта остаётся как есть, просто embedded в левую панель
- `StatsBar` поднимается на самый верх, становится тонким

### Phase 2 — Активные таблица (2 дня)
- API `GET /api/tables/active` (server-side pagination+sort+filter, SQL CTE для stats)
- `ActiveTable.tsx` на TanStack Table
- 4 базовых фильтра: rooms, price, area, days
- 1 column visibility toggle, 1 density toggle
- URL state

### Phase 3 — cross-link карта ↔ таблица (1 день)
- click row → `map.flyTo`, пульсирующий пин
- hover row → preview pin (без клика)
- map event → если юзер pans bbox, фильтр в таблице не меняется (это намеренно)
- table event → map обновляется

### Phase 4 — Снято таблица (1.5 дня)
- API `GET /api/tables/sold` (с sold_date range)
- `SoldTable.tsx`, переиспользует `DataTable` из Phase 2

### Phase 5 — Скрытые с фото (2 дня)
- API `GET /api/tables/deactivated` (по умолчанию `photos_count > 0`)
- `DeactivatedTable.tsx` с колонкой-миниатюрой
- `PhotoGallery` в модалке при клике на миниатюру (Esc/←/→)

### Phase 6 — Дома (1.5 дня)
- API `GET /api/tables/houses`
- `HousesTable.tsx`
- год постройки / материал фильтры
- avg_price_active / avg_price_sold подсчёт

### Phase 7 — polish (1.5 дня)
- CSV export (для всех 4 таблиц)
- saved views (URL bookmark + localStorage)
- density + column visibility persisted в localStorage
- empty state, skeleton loaders
- keyboard shortcuts (`/` — фокус в search, `Esc` — закрыть панель)
- mobile: на <768px карта схлопывается в верхнюю кнопку,
  таблица на весь экран, drill-down → модалка

### Phase 8 — indexы в БД (0.5 дня)
- перед мержем проверить, что есть индексы на:
  - `active_ads(source, is_active)` (уже есть)
  - `active_ads(price)`, `active_ads(area)`, `active_ads(days_in_exposition)`
  - `sold_ads(source, sold_date)`, `sold_ads(price)`, `sold_ads(area)`
  - `houses(source, year_built)` (если нет)
  - `houses(lat, lng)` (есть для карты)
- новые индексы добавить одной миграцией `alembic` или `psql -f`

**Итого: ~10-12 рабочих дней** (зависит от того, какие фазы делаются параллельно).

---

## Открытые вопросы (нужны решения от тебя)

1. **Drill-down при клике на строку:**
   - (a) **side panel** как сейчас — выезжает справа, не закрывает таблицу
   - (b) **expandable row** — клик раскрывает подстроку внутри таблицы
   - (c) **модалка** — full-screen overlay с фото и кнопкой «открыть на cian.ru»
   - Я бы **(a) side panel**, но compact (только фото + цена + 3 цифры), потому что таблица должна остаться видимой. Что выбираешь?

2. **Сохранение видов:** добавлять ли «saved views» (закладка на набор фильтров)?
   Например «1к до 10М в ЮАО», «Новостройки с ремонтом». Если да — нужно ли делиться
   ссылками (URL state уже это даёт) или хранить в localStorage?

3. **Мобильная версия:** на телефоне таблица + карта одновременно не лезут.
   - (a) автоматом скрывать карту, оставлять кнопку «показать карту»
   - (b) mobile-only отдельный экран, на десктопе как обычно
   - Сейчас карта на mobile сжимается, но таблиц ещё не было — как думаешь делать?

4. **Приоритет фаз:** что важнее сначала?
   - Активные (5к, главная боль сейчас) → сразу Phase 2
   - Скрытые с фото (231к, ради них весь этот дашборд) → сразу Phase 5
   - Я бы **Активные первыми** (быстрее сделать, сразу видно пользу), Скрытые вторым заходом.

5. **Bulk actions:** что делать с выбранными строками?
   - «Открыть N ссылок на cian.ru в новых вкладках» (для массового просмотра)
   - «Добавить в watchlist» (новая фича — таблица отобранных объявлений)
   - «Export selected to CSV»
   - Пока думаю только про bulk-open-links, остальное — v2.

6. **Источник `winners_sold` (110к):** в БД есть, но в API не отдаётся (см. SYSTEM.md).
   В дашборд его пока не включаем, или сделать отдельную вкладку?

7. **Charts:** может стоит добавить «price distribution chart» над таблицей?
   Гистограмма цен в текущей выборке — клик по столбику = фильтр по диапазону.
   Я бы **сделал** — это дашбордная фича, не таблица. Но это +1-2 дня.

---

## Что НЕ входит в этот план (out of scope)

- новые парсеры (winners_sold / domclick_sold уже есть)
- изменить pipeline / source-архитектуру
- авторизация / multi-user (юзер один)
- mobile native app
- geocode оставшихся 1149 cian_sold orphan-хаусов (отдельная задача)
- AI-summary по домам (отдельная задача)
- price-prediction модель (отдельная задача)
- export в Excel (.xlsx) — пока только CSV, Excel позже

---

## Верификация (как проверять что готово)

**Acceptance bar для каждой фазы:**

- Phase 1: заходим на `/`, видим split-pane, табы кликаются, карта панорамируется.
- Phase 2: `/api/tables/active?page=1&page_size=50` отдаёт 50 строк за <200ms.
  В UI: сортировка по цене, фильтр «1к» сужает до ~1000 строк за <300ms.
- Phase 3: клик строки → карта плавно летит, marker пульсирует 2с, возврат на исходный вид работает.
- Phase 5: фильтр «с фото» даёт ~173к строк, default view рендерится <500ms,
  click thumb открывает модалку с PhotoGallery, Esc закрывает.
- Phase 7: Export CSV с фильтром — файл скачивается, 50к строк за <10s.
- Performance: scroll таблицы на 50 элементов → 60fps (Chrome DevTools Performance).

**Smoke-тесты:**
- `curl http://localhost:8001/api/tables/active?page=1&page_size=5` → JSON
- `curl "http://localhost:8001/api/tables/active/export?rooms=1" -o /tmp/out.csv` → CSV

---

## Следующий шаг

Я бы начал с **Phase 0 + Phase 1** прямо сейчас (полдня-день) — каркас,
без новых таблиц, только разметка. Когда увидим wireframe в браузере,
можно будет быстро откорректировать пропорции и табы, и пойти в Phase 2.

Если согласен с планом — скажи «погнали», и я ставлю Phase 0+1 в работу.
Если что-то надо переиграть (другая раскладка, другие приоритеты,
добавить/убрать фазу) — скажи прямо, поправлю за 5 минут.

Сначала жду ответы на 7 открытых вопросов выше, особенно 1, 3, 4.
