"""scripts/link_active_by_address - привязать active_ads к houses по адресу.

cian_active в raw_data не хранит cian_house_id, но хранит полный адрес.
Пробуем сшить по нормализованному адресу с houses.cian_sold (там lat/lng есть).

Алгоритм:
  1. Извлекаем address.full из raw_data активных объявлений.
  2. Нормализуем: lowercase, убираем лишние пробелы, "г." и т.п.
  3. Ищем дом в houses (source=cian_sold) с таким же normalized address.
  4. Если находим — ставим house_id и cian_house_id.

Идемпотентен (UPDATE проверяет IS NULL).
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

logger = logging.getLogger("link_active_by_address")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _normalize_address(s: str | None) -> str | None:
    """Нормализует адрес для сравнения: lowercase, без лишних символов."""
    if not s:
        return None
    s = s.lower().strip()
    # Убираем " г.", " г ", " город " в конце
    s = re.sub(r"[,\s]+г\.?$", "", s)
    # Убираем "москва, " в начале (везде одинаково)
    s = re.sub(r"^москва[,\s]+", "", s)
    # Унифицируем пробелы
    s = re.sub(r"\s+", " ", s)
    # Убираем точки, запятые в конце
    s = s.rstrip(".,")
    return s


async def main():
    init_engine("postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper")
    sf = get_session_factory()

    async with sf() as s:
        # 1. Проверим сколько активных объявлений и сколько имеют адрес
        row = (await s.execute(text("""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE raw_data->'address'->>'full' IS NOT NULL
                                AND raw_data->'address'->>'full' != '') AS with_address
            FROM active_ads WHERE source='cian_active';
        """))).first()
        print(f"active_ads.cian_active: всего {row[0]}, с адресом {row[1]}")

        # 2. Сколько домов cian_sold имеют ненулевой address
        row = (await s.execute(text("""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE address IS NOT NULL AND address != '') AS with_address
            FROM houses WHERE source='cian_sold';
        """))).first()
        print(f"houses.cian_sold: всего {row[0]}, с адресом {row[1]}")

        # 3. Sample: посмотрим как выглядят адреса
        print("\n=== Sample адресов active_ads ===")
        rows = (await s.execute(text("""
            SELECT raw_data->'address'->>'full' FROM active_ads
            WHERE source='cian_active' AND raw_data->'address'->>'full' IS NOT NULL
            LIMIT 5;
        """))).all()
        for r in rows:
            print(f"  '{r[0]}'")

        print("\n=== Sample адресов houses.cian_sold ===")
        rows = (await s.execute(text("""
            SELECT address FROM houses WHERE source='cian_sold' AND address IS NOT NULL
            LIMIT 5;
        """))).all()
        for r in rows:
            print(f"  '{r[0]}'")

        # 4. Попробуем через нормализацию (через CTE и подобие по нормализованной форме)
        # В PostgreSQL: создаём временную функцию или используем выражение.
        # Сделаем через UPDATE с подзапросом, используя lower + замену.

        # Стратегия: для каждого active_ads, ищем дом по точному совпадению
        # LOWER + REPLACE('москва, ', '').
        print("\n=== Попытка 1: точный LIKE по нормализованному адресу ===")

        result = await s.execute(text("""
            UPDATE active_ads aa
            SET
              house_id = h.id,
              cian_house_id = h.cian_house_id
            FROM houses h
            WHERE aa.source = 'cian_active'
              AND aa.house_id IS NULL
              AND h.source = 'cian_sold'
              AND aa.raw_data->'address'->>'full' IS NOT NULL
              AND LOWER(REGEXP_REPLACE(
                    REGEXP_REPLACE(TRIM(aa.raw_data->'address'->>'full'),
                                    '[,\\s]+г\\.?$', '', 'g'),
                    '^москва[,\\s]+', '', 'i'
                  )) = LOWER(REGEXP_REPLACE(
                    REGEXP_REPLACE(TRIM(h.address),
                                    '[,\\s]+г\\.?$', '', 'g'),
                    '^москва[,\\s]+', '', 'i'
                  ));
        """))
        await s.commit()
        print(f"  обновлено: {result.rowcount} строк")

        # 5. Финальная статистика
        print("\n=== Финальная статистика active_ads.cian_active ===")
        row = (await s.execute(text("""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE house_id IS NOT NULL) AS linked,
              COUNT(*) FILTER (WHERE cian_house_id IS NOT NULL) AS with_cian
            FROM active_ads WHERE source='cian_active';
        """))).first()
        pct = 100 * row.linked / row.total if row.total else 0
        print(f"  всего: {row[0]}")
        print(f"  привязано к дому: {row.linked} ({pct:.1f}%)")
        print(f"  с cian_house_id: {row.with_cian}")


asyncio.run(main())
