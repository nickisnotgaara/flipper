# flipper_db

Единый data layer для всех парсеров проекта Flipper. PostgreSQL-схема, общая
для 5 парсеров: `cian_active`, `cian_sold`, `winners_sold`, `domclick_sold`,
`flatinfo_houses`.

## Зачем

- **Одна схема БД** для всех источников — данные не разбросаны по файлам.
- **Под будущую карту 2gis-style**: дома (`houses`) с `lat/lng` + `source`-тегом;
  активные объявления (`active_ads`) и снятые (`sold_ads`) линкуются к домам
  через `house_id`. Клик на дом → SELECT по двум таблицам.
- **Идемпотентность**: повторный запуск парсера не плодит дубликаты.

## Использование

```python
from packages.flipper_db import (
    init_db, FlipperRepository, House, SoldAd, Source,
)

# 1. Инициализация
init_db("postgresql+asyncpg://flipper:secret@app_postgres:5432/flipper")
repo = FlipperRepository()
await repo.init_db()

# 2. Подготовить объекты
houses = [
    House(
        source=Source.WINNERS_SOLD.value,
        external_house_id="abc-123",
        address="Москва, ул. Ленина, 1",
        lat=55.7558, lng=37.6173,
        year_built=1985, levels=9,
        package="old_fund",
        raw_data={"original_field": "...", ...},
    ),
    ...
]
sold_ads = [
    SoldAd(
        source=Source.WINNERS_SOLD.value,
        external_id="offer-1",
        price=15_000_000, area=65.0, rooms=2,
        publish_date=date(2024, 1, 15),
        sold_date=date(2024, 3, 1),
        raw_data={...},
    ),
    ...
]

# 3. Upsert (идемпотентно)
await repo.upsert_houses_batch(houses)
await repo.upsert_sold_offers_batch(sold_ads)
```

## Схема

### `houses` (реестр домов)
- `id` BIGSERIAL PK
- `source` + `external_house_id` — уникальный ключ источника
- `cian_house_id` — для кросс-источниковой сшивки на карте
- `lat`, `lng` — для отображения на карте
- `package` — классификация (`old_fund` | `modern` | `new_building` | `elite` | `unknown`)
- `raw_data` JSONB — fallback для ненормализованных полей

### `active_ads` (активные объявления)
- Сейчас пишет только `cian_active` (через Flippercrawl + Grist).
- `source` + `cian_id` — уникальный ключ.
- `house_id` FK → `houses.id` (nullable, до первой нормализации).
- `is_active` — флаг (если False, запись считается "снятой").

### `sold_ads` (снятые/проданные)
- Пишут: `cian_active` (за последнюю неделю), `cian_sold`, `winners_sold`, `domclick_sold`.
- `source` + `external_id` — уникальный ключ.
- `house_id` FK → `houses.id`.

## Source-теги

| Сервис | Source | Что пишет |
|---|---|---|
| `services/parsers/cian_active` | `cian_active` | `active_ads` + (sold <7д) `sold_ads` |
| `services/parsers/cian_sold` | `cian_sold` | `houses` + `sold_ads` (вся история) |
| `services/parsers/winners_sold` | `winners_sold` | `houses` + `sold_ads` |
| `services/parsers/domclick_sold` | `domclick_sold` | `houses` + `sold_ads` |
| `services/parsers/flatinfo_houses` | `flatinfo_houses` | `houses` (только дома) |

## Тестирование

```bash
pytest packages/flipper_db/tests/
```

Тесты используют SQLite in-memory для скорости (не требует PostgreSQL).
