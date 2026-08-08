# План: Admin Panel V1 — sidebar-навигация, каждая секция отдельная

**Дата:** 2026-08-08 (replaces PLAN_DASHBOARD_V2.md — split-pane вариант отклонён)
**Цель:** из map-only фронта сделать полноценную admin-панель для флиппера.
Sidebar навгирует между секциями. Карта — одна из секций, а не постоянный
компаньон таблиц. Каждая секция — отдельный экран.

---

## Концепция

Классический admin layout: фиксированный **sidebar слева** (240px),
top-bar сверху (48px), основной контент справа. Каждая секция —
отдельный route (`/map`, `/tables/active`, `/tables/sold`, и т.д.),
default landing — `/dashboard` (overview с KPI).

```
┌──────────┬──────────────────────────────────────────────────┐
│  Sidebar │  TopBar: search / status / user                 │
│  (240px) ├──────────────────────────────────────────────────┤
│          │                                                  │
│  ⌂ Дашб. │                                                  │
│  🗺  Карта│           Main content (роутится)                │
│  📊 Табл. │                                                  │
│   ├ Акт.  │                                                  │
│   ├ Снято │                                                  │
│   ├ Скрыт.│                                                  │
│   └ Дома  │                                                  │
│  📈 Анал. │                                                  │
│  🔍 Сохр. │                                                  │
│  ⚙️ Пайп. │                                                  │
│  🛠 Сетт. │                                                  │
│          │                                                  │
│  [flipper]│                                                 │
│  v1.0     │                                                 │
└──────────┴──────────────────────────────────────────────────┘
```

Принципы:
- **Карта больше не рядом с таблицами.** Это намеренно — карта это
  «где искать», таблицы это «что подходит», они конкурируют за внимание.
  Когда хочешь смотреть карту — открой секцию «Карта». Когда хочешь
  фильтровать — открой «Таблицы». Никакой двойной нагрузки на экран.
- **Sidebar = основной навигатор.** Как в Vercel, Linear, Stripe Dashboard.
- **Landing = Dashboard** (overview с KPI + recent activity + быстрые ссылки).
  Юзер сразу видит «что нового» и решает куда копать.
- **URL-driven** состояние: фильтры, сортировка, активная вкладка таблиц
  всё в query string — можно шарить ссылку.

---

## Секции (sidebar)

### 1. ⌂ Дашборд (`/dashboard`) — landing

**Что тут:** обзорная страница, KPI, последние изменения, горячие дома.

Контент:
- **KPI cards** (4 штуки в ряд):
  - Активных: 5 227 (+12 за день)
  - Снято за неделю: 380
  - Среднее дней на рынке: 31
  - С авансом: 163 (3.1%)
- **Recent activity** (лента): новые объявления, изменение цены, снятые
- **Hot houses** (mini-list): топ-10 домов с наибольшим ad_count
- **Quick links** в каждую секцию

### 2. 🗺 Карта (`/map`)

**Что тут:** текущий full-screen map view. Без изменений в логике,
просто отдельный route. Все маркеры, кластеры, drill-down — как сейчас.

### 3. 📊 Таблицы

**4 подраздела** (sub-routes):
- `/tables/active` — 5 227 активных
- `/tables/sold` — 18 375 с offerData (comps)
- `/tables/hidden` — 173 536 с фото (деактивированные)
- `/tables/houses` — 30 868 домов

**Под-табы на каждой странице** (вместо sub-routes, для скорости):
```
[Активные] [Снято] [Скрытые] [Дома]
```
Клик по табу — меняет route, но sidebar остаётся (на «Таблицы»).

**Колонки, фильтры, sort** — берём из старого плана (Phase 2-6).
Они не зависят от layout, переносятся 1:1.

### 4. 📈 Аналитика (`/analytics`)

**Что тут:** графики и метрики, которых нет в таблицах.

- **Price distribution** — гистограмма цен по всем активным
- **Days on market** — распределение (сколько висит)
- **By district** — средняя ₽/м² по районам
- **Sold vs active** — scatter (area vs price), где прошлая сделка, где текущая
- **Time series** — сколько снято в неделю за последние 3 месяца

### 5. 🔍 Сохранённые фильтры (`/filters`)

**Что тут:** управление saved searches. Юзер может сохранить текущий
набор фильтров из таблицы под именем, потом открыть. Шаринг по URL.

Сейчас у нас нет saved filters. Это новая фича.

### 6. ⚙️ Pipeline (`/pipeline`)

**Что тут:** статус парсеров. Какие бегут, последний успешный запуск,
очередь, ошибки.

- Таблица парсеров (cian_active, cian_sold, domclick_sold, winners_sold)
- Last run, duration, success/fail
- Кнопка «запустить» (manual)
- Логи последнего запуска (collapsible)

### 7. 🛠 Settings (`/settings`)

**Что тут:** конфиг, env vars, версии. Пока read-only, но место под
edit оставляем.

- DB connection status
- Flippercrawl URL / version
- Active filter configs (6 шт из миграции)
- Token / cookies health

---

## Структура роутинга

```
web/next/app/
├── layout.tsx                    # QueryClientProvider + auth (no-op сейчас)
├── page.tsx                      # → redirect /dashboard
├── dashboard/
│   └── page.tsx
├── map/
│   └── page.tsx
├── tables/
│   ├── layout.tsx                # общий layout: tab-bar + filters + table
│   ├── active/page.tsx
│   ├── sold/page.tsx
│   ├── hidden/page.tsx
│   └── houses/page.tsx
├── analytics/
│   └── page.tsx
├── filters/
│   └── page.tsx
├── pipeline/
│   └── page.tsx
└── settings/
    └── page.tsx
```

Sidebar — отдельный компонент `<Sidebar />`, общий для всех роутов.
TopBar — отдельный `<TopBar />`, тоже общий.

---

## Сквозные компоненты (4 штуки, переиспользуются везде)

1. **`<Sidebar />`** — 240px, sticky, иконки + лейблы, active state по route.
2. **`<TopBar />`** — global search (по всем таблицам одновременно), last sync, user.
3. **`<DataTable />`** — обёртка над TanStack Table (Phase 2 из старого плана).
4. **`<KpiCard />`** — большая цифра + дельта + sparkline (для дашборда).

---

## Поиск и фильтры (сквозные для всех 4 таблиц)

Каждая таблица имеет **два независимых слоя**:

### 1. Search (одно поле, ищет по всем колонкам)

Сверху таблицы, над фильтрами — большой input:
```
┌──────────────────────────────────────────────────────────────┐
│ 🔍  Хамовники, 3к, 80м², до 15млн…                          │
└──────────────────────────────────────────────────────────────┘
```

- **Что ищет:** по всем текстовым полям строки (адрес, район, метро,
  источник, описание, ID, и т.д.) — full-text через SQL `ILIKE '%q%'`
  на стороне сервера.
- **Server-side:** `?q=хамовники` → API фильтрует на SQL-уровне.
  Debounce 300ms. URL state.
- **Для каждой таблицы свой набор полей** (см. ниже).
- **Пустая строка** → снимает фильтр, показывает все.

### 2. Filters (структурные, по конкретным полям)

Под search'ом — набор chip-кнопок (как в wireframe):
- Каждый фильтр = одна колонка (price, area, rooms, days, source, и т.д.)
- Тип фильтра соответствует типу данных:
  - **range** для чисел (price, area, days, year) — min/max slider
  - **multi-select** для категорий (rooms, source, material) — checkboxes
  - **toggle** для bool (has_avans, has_photos) — switch
  - **date range** для дат (sold_date) — два date-picker'а
- **Combine:** search + filters работают AND-ом
- **Reset all** — кнопка сброса

### Per-table search fields

| Таблица | Search ищет по |
|---|---|
| `/tables/active` | address, district, okrug, metro_station, title, source, external_id, has_avans flag |
| `/tables/sold` | address, district, okrug, metro_station, title, source, external_id |
| `/tables/hidden` | address, source, external_id, has_photos flag |
| `/tables/houses` | address, source, material, series, year_built |

### Per-table filters (полный список)

| Таблица | Фильтры |
|---|---|
| Active | rooms [multi], price [range], area [range], days [range], source [multi], has_avans [toggle], has_photos [toggle], okrug [multi] |
| Sold | rooms [multi], price [range], area [range], sold_date [date range], days [range], source [multi], okrug [multi] |
| Hidden | has_photos [toggle], sold_date [date range], source [multi] |
| Houses | source [multi], year_built [range], material [multi], has_ads [toggle] |

### URL state

Все фильтры + search + sort + page → в query string. Можно шарить ссылку
`/tables/active?q=хамовники&rooms=1,2&price_min=5000000&sort=price_m2`.
Сохранённые пресеты → отдельная секция `/filters` (CRUD).



---

## Фазы (предложение, 12-15 рабочих дней)

**Статус на 2026-08-08:** все 10 фаз реализованы.

- **Phase 0** — npm install: TanStack Table/Virtual/Query, react-hook-form, zod, @hookform/resolvers, lucide-react, HeroUI ✅
- **Phase 1** — каркас + роутинг: Sidebar, TopBar, 10 routes, redirect `/` → `/dashboard` ✅
- **Phase 2** — дашборд: 4 KPI cards, activity feed, hot houses, quick links ✅
- **Phase 3** — карта как отдельный роут: `/map/` рендерит существующий MapApp ✅
- **Phase 4** — Active таблица: TanStack + Virtual, search, 7 filters, URL state, 11 columns, Export CSV ✅
- **Phase 5** — Sold/Hidden/Houses таблицы: переиспользуем DataTable ✅
- **Phase 6** — Аналитика: inline SVG BarChart/Donut/Sparkline (без chart-библиотек) ✅
- **Phase 7** — Pipeline + Settings + Filters: react-hook-form + zod для Filters Modal, CRUD wired ✅
- **Phase 8** — polish: density, columns, CSV export, keybinds ✅
- **Phase 9** — DB индексы: `idx_active_ads_phase9`, `idx_sold_ads_phase9`, `idx_houses_phase9` ✅
  (alembic-миграция `656a072f5a0d`; CONCURRENTLY, проверено планировщиком — `idx_sold_ads_phase9` используется для `sold_ads ORDER BY sold_date DESC`)

### Phase 0 — npm install (0.5 дня)
```
npm i @tanstack/react-table @tanstack/react-virtual @tanstack/react-query
npm i react-hook-form zod @hookform/resolvers
```
- `QueryClientProvider` в `app/layout.tsx`
- **Tech stack финально:**
  - **Tables:** TanStack Table v8 + TanStack Virtual (server-side pagination/sort/filter)
  - **Data fetching:** TanStack Query (cache, dedupe, auto-refetch)
  - **UI components:** HeroUI (Card, Table, Chip, Tooltip, Modal, Drawer, Tabs, etc.) — **уже в проекте, не меняем**
  - **Forms:** **react-hook-form** + **zod** (через `@hookform/resolvers/zod`) — для всех форм: saved filters CRUD, pipeline launcher, settings editor
  - **URL state:** встроенный `useSearchParams` из Next.js, без зависимостей
  - **Icons:** lucide-react (inline SVG) — если ещё не установлен, добавить
  - **Charts (Phase 6):** Chart.js + react-chartjs-2
- **Что НЕ добавляем:** Redux/Zustand (TanStack Query покрывает server state), styled-components/emotion (Tailwind + HeroUI достаточно), react-router (Next.js routing), react-modal (HeroUI Modal)

### Phase 1 — каркас + роутинг (1.5 дня)
- `app/layout.tsx` с общим `<Sidebar />` + `<TopBar />`
- Sidebar с 7 пунктами, иконки (lucide), active state
- TopBar с search (стаб)
- 7 пустых роутов с заглушками
- Redirect `/` → `/dashboard`

### Phase 2 — Дашборд overview (1.5 дня)
- 4 KPI cards с реальными цифрами из `/api/stats`
- Recent activity feed (пока: «N новых объявлений»)
- Hot houses mini-list (top-10 по ad_count)
- Quick links в каждую секцию

### Phase 3 — Карта как отдельный роут (0.5 дня)
- `app/map/page.tsx` → рендерит существующий `<MapApp />` (без правок)
- В Sidebar: «Карта» → `/map`

### Phase 4 — Tables: Active (2.5 дня)
- `app/tables/layout.tsx` — общий layout: **search box** + tab-bar + filter-chips + table
- `app/tables/active/page.tsx` — реальная таблица
- API `GET /api/tables/active?q=...&page=...&sort=...&order=...&filters...` (server-side)
- TanStack Table + Virtual
- Search box (full-text, debounce 300ms)
- 7 фильтров (rooms, price, area, days, source, has_avans, has_photos, okrug)
- Cross-link: click row → `/map?focus={house_id}` (в новой вкладке)

### Phase 5 — Tables: остальные (Sold, Hidden, Houses) (3 дня)
- По одному дню на каждую таблицу
- Переиспользуем `<DataTable />`
- `Hidden` — с колонкой-миниатюрой (фото) + модалка PhotoGallery по клику
- `Houses` — с year_built, material, avg_price_active/sold

### Phase 6 — Аналитика (2 дня)
- 4-5 графиков (Chart.js)
- Server endpoint `/api/analytics/{metric}` (агрегаты из БД)
- Пустые states / skeleton

### Phase 7 — Pipeline + Settings + Filters (1.5 дня)
- `/pipeline` — read-only таблица парсеров + last run + кнопка «запустить»
  (форма «запустить парсер» — **react-hook-form** + zod schema)
- `/settings` — read-only конфиг (форма редактирования — **react-hook-form**)
- `/filters` — saved searches CRUD, новая фича
  - список сохранённых пресетов
  - форма «сохранить текущие фильтры» — **react-hook-form** + zod
  - кнопки rename / delete

### Phase 8 — polish (1.5 дня)
- CSV export для всех 4 таблиц
- URL state persistence (фильтры, sort, page)
- Density toggle, column visibility (localStorage)
- Keyboard shortcuts (`/` = search, `g d` = go dashboard, `g m` = go map)
- Empty states, skeleton loaders
- Mobile: на <768px sidebar → drawer

### Phase 9 — индексы в БД (0.5 дня)
- перед Phase 4: `CREATE INDEX CONCURRENTLY` на
  `active_ads(source, is_active, price, area, days_in_exposition)`,
  `sold_ads(source, sold_date, price, area)`,
  `houses(source, year_built)`.

**Итого: ~12-15 рабочих дней** в зависимости от того, какие фазы параллелятся.

---

## API (новые endpoint'ы)

```
# дашборд
GET /api/dashboard/kpi          # 4 цифры + дельты
GET /api/dashboard/recent       # последние N событий
GET /api/dashboard/hot-houses   # top-10 домов

# таблицы (Phase 4-5)
GET /api/tables/active?page=1&page_size=50&sort=price_m2&order=asc&...
GET /api/tables/sold?...
GET /api/tables/hidden?...
GET /api/tables/houses?...
GET /api/tables/{name}/export?...   # CSV

# аналитика (Phase 6)
GET /api/analytics/price-distribution
GET /api/analytics/days-on-market
GET /api/analytics/by-district
GET /api/analytics/sold-vs-active
GET /api/analytics/weekly-sold

# pipeline (Phase 7)
GET /api/pipeline/status        # все парсеры + last run
GET /api/pipeline/run/{name}    # POST: запустить вручную
GET /api/pipeline/logs/{name}   # последние N строк лога

# filters (Phase 7)
GET /api/saved-filters          # list
POST /api/saved-filters         # create
DELETE /api/saved-filters/{id}  # delete
```

---

## Открытые вопросы (стало меньше, всё конкретнее)

1. **Sidebar width:** 240px (компактно) или 280px (с подписями под иконками)?
   240px — стандарт, помещается на 1280×800 ноуте. Я бы **240px**.

2. **Дашборд как landing:** оставить как `/dashboard` (тогда `/` редиректит)
   или сделать `/` самим дашбордом (без редиректа)? Стандарт — редирект,
   но некоторые любят короткий URL. Я бы **редирект**.

3. **Tables — sub-routes или sub-tabs:**
   - (a) **sub-routes** (`/tables/active`, `/tables/sold`, ...) — URL чёткий, можно шарить
   - (b) **sub-tabs** на одной странице `/tables` — переключение быстрее
   - Я бы **sub-routes** (URL шарится, history работает корректно).

4. **«Сохранённые фильтры» — отдельная секция или просто localStorage:**
   - (a) **отдельная секция** `/filters` с CRUD — можно шарить, видно на сервере
   - (b) **localStorage** — приватно, проще, без бэка
   - Я бы **(a)** — это одна из самых полезных фич, и хранить в БД ничего не стоит.

5. **С чего начать (Phase 1 → ?):**
   - (a) **Phase 1+2** (каркас + дашборд) → сразу видна новая навигация и KPI
   - (b) **Phase 1+3+4** (каркас + карта-роут + Active таблица) → сразу данные
   - Я бы **(a)** — каркас с дашбордом, потом Phase 4 (Active таблица), потом
     остальные таблицы параллельно. Dashboard даёт ощущение «готовой админки»
     даже когда таблиц ещё нет.

6. **Pipeline `/pipeline`:** насколько глубоко? Просто read-only «когда
   последний раз бежал» или полноценный launcher (кнопка «запустить»,
   логи в realtime, очередь)? Я бы **MVP** — read-only + кнопка «запустить»
   одного парсера. Логи — отдельной задачей.

7. **Mobile:** на телефоне admin panel с sidebar'ом — неудобно.
   - (a) sidebar → drawer (открывается по гамбургеру)
   - (b) на mobile только карта (полноэкранная)
   - (c) mobile-only отдельный URL `/m/...`
   - Я бы **(a)** — drawer, остальные секции доступны.

---

## Что НЕ входит (out of scope)

- Авторизация / multi-user (юзер один)
- Edit конфигов через UI (Settings read-only)
- Native mobile app
- Real-time updates (websocket'ы) — пока polling на 60s
- AI-summary / price-prediction
- Export в .xlsx (только CSV)
- Geocode 1149 orphan cian_sold (отдельная задача)

---

## Verification

**Acceptance bar для каждой фазы:**

- Phase 1: открываем `/` → редирект на `/dashboard`, sidebar со всеми
  7 пунктами кликабельны, active state подсвечивает текущий.
- Phase 2: `/dashboard` показывает 4 KPI с реальными цифрами,
  recent activity feed обновляется.
- Phase 4: `/tables/active?page=1&page_size=50` отдаёт 50 строк за <200ms,
  фильтры работают, сортировка по любой колонке.
- Phase 5: `Hidden` показывает миниатюры, клик открывает PhotoGallery.
- Phase 6: `/analytics/price-distribution` рисует гистограмму по 1к записям за <500ms.
- Phase 7: `/pipeline` показывает реальный статус, кнопка «запустить» работает.

**Smoke-тесты:**
- `curl http://localhost:8001/api/dashboard/kpi` → JSON
- `curl "http://localhost:8001/api/tables/active?page=1&page_size=5"` → JSON
- `curl "http://localhost:8001/api/analytics/price-distribution"` → JSON

---

## Следующий шаг

Жду ответы на 7 вопросов (особенно важны 1, 3, 5).
Когда скажешь «погнали» + ответы — ставлю Phase 0+1+2 в работу.
К концу Phase 2 у нас будет каркас с sidebar'ом + работающий дашборд
с KPI. Дальше таблицы — Phase 4 → 5.
