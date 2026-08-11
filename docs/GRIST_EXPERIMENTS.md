# Grist Experiments — практические кейсы

> **Setup:** у тебя уже залиты `Houses2` (30 868 строк) и `Active_ads` (5 227 строк)
> в doc `parsing` (`mDaHoGD6yahtxaqugwr5mK`) на http://localhost:8484.
> Этот файл — набор готовых экспериментов, которые можно делать прямо в UI.

## Базовый workflow

В UI Grist: **кликни на заголовок колонки** → `Add column to the right` → `Formula`.
Вставляй формулы ниже. После ввода жми **Enter** (или кликни в сторону).

## Эксперимент 1: Возраст и характеристики дома

**На таблице:** `Houses2`

| Formula | Описание | Что покажет |
|---|---|---|
| `=2026 - $year_built` | Возраст дома | Старые vs новые |
| `=IF($year_built < 1900, "дореволюционный", IF($year_built < 1950, "сталинка", IF($year_built < 1990, "советский", IF($year_built < 2010, "современный", "новостройка"))))` | Классификация по эпохе | Распределение по типам |
| `=FLOOR($year_built / 10) * 10` | Десятилетие | Histogram |
| `=IF($lat == null OR $lng == null, "нет", "есть")` | Есть ли координаты | Покрытие |
| `=IF($levels == null, "unknown", IF($levels <= 5, "малоэтажка", IF($levels <= 9, "среднеэтажка", IF($levels <= 17, "высотка", "небоскрёб"))))` | Тип этажности | Сегментация |
| `=$okrug != "" AND $okrug.contains("ЦАО")` | В ЦАО? | Центральный район |

## Эксперимент 2: Цены и скидки (Active_ads)

**На таблице:** `Active_ads`

| Formula | Описание |
|---|---|
| `=IF($area == null OR $area == 0, null, $price / $area)` | Цена за м² (если null в БД) |
| `=$price_per_m2 < 200000` | Подозрительно дёшево (<200k/м²) |
| `=$price_per_m2 > 600000` | Дорого (>600k/м²) |
| `=$days_in_exposition > 60` | Залежалось (>60 дней) |
| `=IF($days_in_exposition > 0, ROUND($total_views / $days_in_exposition, 1), null)` | Просмотров в день |
| `=IF($total_views > 0, ROUND($unique_views * 100.0 / $total_views, 1), null)` | % уникальных (engagement) |
| `=$rooms == 0` | Студия (rooms=0 обычно) |
| `=$rooms == 1` | Однушка |
| `=$floor_current == $floor_total` | Последний этаж |
| `=$floor_current == 1` | Первый этаж (часто дешевле) |
| `=$filter_id` | Название фильтра: `=IF($filter_id==1, "offers_до2000", IF($filter_id==2, "offers_после2000", IF($filter_id==3, "offers_ЦАО_до2000", IF($filter_id==4, "offers_ЦАО_после2000", IF($filter_id==5, "signals_Опека", IF($filter_id==6, "advance_Запрет", "other"))))))` |
| `=$area * $price_per_m2 / 1000000` | Оценка в миллионах (кросс-проверка) |

## Эксперимент 3: Сводные (Summary tables)

**Add table → Summary → выбрать источник → настроить.**

### 3.1. Houses by district (главная)
- Source: `Houses2`
- Group by: `district`
- Aggregations:
  - Count: `=len($group)`
  - Средний год: `=AVG($group.year_built)`
  - Самый старый: `=MIN($group.year_built)`
  - С координатами: `=SUM(IF($group.lat != null, 1, 0))`
  - % с координатами: `=ROUND(100 * SUM(IF($group.lat != null, 1, 0)) / len($group), 1)`

### 3.2. Active ads by filter
- Source: `Active_ads`
- Group by: `filter_id`
- Aggregations:
  - Count, Avg price, Avg price/m², Avg days_in_exposition, Avg views

### 3.3. Active ads by month (тренды)
- Source: `Active_ads`
- Group by: `publish_date` (Truncate to Month если возможно)
- Aggregations:
  - Count, Avg price, Avg price/m²

### 3.4. Houses by source
- Source: `Houses2`
- Group by: `source`
- Aggregations:
  - Count, % от общего

## Эксперимент 4: Чарты

На любой сводной таблице или на основной:
- **Bar chart** (вертикальные/горизонтальные столбики)
- **Pie chart** (доли)
- **Line chart** (тренды по дате)
- **Scatter** (price vs area)
- **Map chart** (lat/lng) — Grist умеет!

### 4.1. Карта домов
- На `Houses2`: `+ Add widget` → Chart → **Map**
- X = `lat`, Y = `lng`
- Color by = `year_built` (heatmap по возрасту)
- Radius by = `count` или фиксированный

### 4.2. Карта активных
- На `Active_ads`: нужно сначала геокодировать (у `Active_ads` нет lat/lng)
- Или джойним через `house_id` → `Houses2.lat/lng`
- Потом scatter plot

## Эксперимент 5: Cross-table links

**Reference** тип колонки = связь между таблицами.

В `Houses2`: Add column → Reference → `Active_ads` (по `house_id` → `Houses2.id`).
После этого в UI у каждого дома можно раскрыть "его объявления".

Или наоборот — в `Active_ads` Reference → `Houses2` (по `house_id` → `Houses2.id`).

## Эксперимент 6: Conditional formatting

**На любой колонке:** Format column → Color scale / Rules.
- `price_per_m2`: зелёный для дешёвых, красный для дорогих
- `days_in_exposition`: красный для >90 дней
- `year_built`: синий для новых, серый для старых
- `unique_views`: жёлтый для >200 (популярные)

## Эксперимент 7: Filters & Saved views

В UI Grist: **Filter bar сверху таблицы**.
- `Houses2` → фильтр: `lat != null AND district != ""`
- `Active_ads` → фильтр: `is_active = true AND price_per_m2 < 300000`

Save view: иконка дискеты → **Save as new view**. Будет ссылка.

## Эксперимент 8: Custom pages / Dashboards

**Add page** → Grid layout → вставляй widgets:
- Chart (Bar)
- Chart (Pie)
- Summary table
- Big number (=COUNT(Active_ads))
- Table view

→ Получается как Tableau/Metabase dashboard, но в self-hosted.

## Полезные Grist docs

- [Formulas reference](https://support.getgrist.com/formulas/) — все функции
- [Column types](https://support.getgrist.com/column-types/) — Text/Numeric/Bool/Date/Reference/...
- [Summary tables](https://support.getgrist.com/summary-tables/) — group by, aggregations
- [Charts](https://support.getgrist.com/charts/) — bar/line/pie/scatter/map
- [Conditional formatting](https://support.getgrist.com/conditional-formatting/)
- [Custom pages](https://support.getgrist.com/custom-pages/) — dashboards

## Что почистить

В `parsing` doc сейчас есть **3 пустые summary-таблицы** от моих попыток через API:
- `HousesByDistrict` (пустая)
- `HousesByDistrict_v2` (пустая)
- `HousesByDistrict_v3` (пустая)

Удалить в UI: правый клик на таблицу → **Delete**.
