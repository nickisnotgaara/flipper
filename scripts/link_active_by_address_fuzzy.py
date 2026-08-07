"""scripts/link_active_by_address_fuzzy - более гибкая сшивка active_ads по адресу.

Проблема: адреса в active_ads и houses.cian_sold в разных форматах.
  active: "Москва, ЦАО, р-н Арбат, ул. Новый Арбат, 5с"
  house:  "Москва, Арбат, Новый Арбат улица, 5"

Стратегия: берём ПОСЛЕДНИЕ 2 компонента (улица, дом) из active и ищем
  в houses.cian_sold через LIKE '%улица%дом%'.

NB: это эвристика — даст ложные срабатывания на однотипных домах
  (например "5" встречается часто). Используем только при ОДНОЗНАЧНОМ
  совпадении (один дом на адрес).
"""
import asyncio
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from packages.flipper_db import init_engine, get_session_factory

logger = logging.getLogger("link_active_by_address_fuzzy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def extract_street_and_house(full_addr: str) -> tuple[str | None, str | None]:
    """Извлечь (улица, дом) из конца адреса.

    Адрес имеет вид "...улица X, дом Y" или "...ул. X, Y".
    Возвращает последние 2 непустых компонента.
    """
    if not full_addr:
        return None, None
    parts = [p.strip() for p in full_addr.split(",") if p.strip()]
    if len(parts) < 2:
        return None, None
    # Убираем из последнего "д." / "д " префикс
    last = re.sub(r"^д\.?\s*", "", parts[-1]).strip()
    # Улица — второй с конца, убираем сокращения "ул.", "пр-т", etc.
    street = re.sub(r"^(ул\.?|улица|пр-т\.?|проспект|пер\.?|переулок|б-р\.?|бульвар|ш\.?|шоссе|наб\.?|набережная)\s*", "", parts[-2], flags=re.IGNORECASE).strip()
    return street, last


async def main():
    init_engine("postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper")
    sf = get_session_factory()

    async with sf() as s:
        # 1. Получаем все unlinked active_ads
        rows = (await s.execute(text("""
            SELECT id, cian_id, raw_data->'address'->>'full' AS full_addr
            FROM active_ads
            WHERE source='cian_active'
              AND house_id IS NULL
              AND raw_data->'address'->>'full' IS NOT NULL
            ORDER BY id;
        """))).all()

        print(f"Не привязанных: {len(rows)}")

        # 2. Загружаем все дома cian_sold с адресом
        houses = (await s.execute(text("""
            SELECT id, cian_house_id, address FROM houses
            WHERE source='cian_sold' AND address IS NOT NULL;
        """))).all()
        print(f"Домов cian_sold с адресом: {len(houses)}")

        # 3. Индексируем дома по последним 2 компонентам адреса
        from collections import defaultdict
        house_index: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for hid, hcian, haddr in houses:
            street, num = extract_street_and_house(haddr)
            if street and num:
                key = (street.lower(), num.lower())
                house_index[key].append((hid, hcian))

        print(f"Уникальных ключей улица+дом: {len(house_index)}")

        # 4. Идём по active_ads и ищем
        updates = []
        for aid, acid, full_addr in rows:
            street, num = extract_street_and_house(full_addr)
            if not street or not num:
                continue
            key = (street.lower(), num.lower())
            candidates = house_index.get(key, [])
            if len(candidates) == 1:
                hid, hcian = candidates[0]
                updates.append((aid, hid, hcian, acid, full_addr))

        print(f"Однозначных совпадений: {len(updates)}")

        # 5. Покажем sample
        for _, _, _, acid, fa in updates[:5]:
            print(f"  cian_id={acid} -> '{fa}'")
        if len(updates) > 5:
            print(f"  ... +{len(updates) - 5} more")

        # 6. UPDATE batch
        if not updates:
            print("\nНечего обновлять.")
            return

        n_updated = 0
        batch_size = 200
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            # VALUES list
            values_clause = ",".join(
                f"({aid}, {hid}, {hcian})"
                for aid, hid, hcian, _, _ in batch
            )
            result = await s.execute(text(f"""
                UPDATE active_ads
                SET house_id = v.hid,
                    cian_house_id = v.hcian
                FROM (VALUES {values_clause}) AS v(aid, hid, hcian)
                WHERE active_ads.id = v.aid
                  AND active_ads.house_id IS NULL;
            """))
            await s.commit()
            n_updated += result.rowcount

        print(f"\nОбновлено: {n_updated} строк")

        # 7. Финальная статистика
        row = (await s.execute(text("""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE house_id IS NOT NULL) AS linked
            FROM active_ads WHERE source='cian_active';
        """))).first()
        pct = 100 * row.linked / row.total if row.total else 0
        print(f"\n=== Финальная статистика active_ads.cian_active ===")
        print(f"  всего: {row[0]}")
        print(f"  привязано: {row.linked} ({pct:.1f}%)")
        print(f"  осталось без привязки: {row[0] - row.linked}")


asyncio.run(main())
