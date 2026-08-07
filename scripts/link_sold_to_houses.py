"""scripts/link_sold_to_houses - установить house_id у sold_ads/active_ads.

Для cian_sold: у объявления есть cian_house_id, ищем дом (source='cian_sold',
cian_house_id=...). У дома source=cian_sold, cian_house_id=cian_house_id.

Аналогично для cian_active: ищем дом в любых source (cian_sold приоритет, потом cian_active)
по cian_house_id.

Идемпотентен (UPDATE по cian_house_id, проверяя IS NULL).
"""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from packages.flipper_db import init_engine, get_session_factory

logger = logging.getLogger("link_sold_to_houses")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


async def main():
    init_engine("postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper")
    sf = get_session_factory()

    async with sf() as s:
        # 1. sold_ads.cian_sold: привязать к houses.cian_sold
        print("=" * 70)
        print("=== 1. cian_sold.sold_ads -> houses (по cian_house_id) ===")
        result = await s.execute(text("""
            UPDATE sold_ads sa
            SET house_id = h.id
            FROM houses h
            WHERE sa.source = 'cian_sold'
              AND sa.cian_house_id IS NOT NULL
              AND sa.house_id IS NULL
              AND h.source = 'cian_sold'
              AND h.cian_house_id = sa.cian_house_id;
        """))
        await s.commit()
        print(f"  обновлено: {result.rowcount} строк")

        # 2. sold_ads.cian_active: cian_id -> cian_active_ads.cian_id
        # (это снятые, которые parser_cian переместил из cian_active_ads)
        print("\n=== 2. cian_active.sold_ads -> houses (по cian_house_id) ===")
        # У cian_active sold_ads есть cian_house_id, ищем дом в cian_sold
        result = await s.execute(text("""
            UPDATE sold_ads sa
            SET house_id = h.id
            FROM houses h
            WHERE sa.source = 'cian_active'
              AND sa.cian_house_id IS NOT NULL
              AND sa.house_id IS NULL
              AND h.source = 'cian_sold'
              AND h.cian_house_id = sa.cian_house_id;
        """))
        await s.commit()
        print(f"  обновлено: {result.rowcount} строк")

        # 3. active_ads.cian_active: cian_house_id -> houses
        print("\n=== 3. cian_active.active_ads -> houses (по cian_house_id) ===")
        result = await s.execute(text("""
            UPDATE active_ads aa
            SET house_id = h.id
            FROM houses h
            WHERE aa.source = 'cian_active'
              AND aa.cian_house_id IS NOT NULL
              AND aa.house_id IS NULL
              AND h.source = 'cian_sold'
              AND h.cian_house_id = aa.cian_house_id;
        """))
        await s.commit()
        print(f"  обновлено: {result.rowcount} строк")

        # 4. Финальная статистика
        print("\n" + "=" * 70)
        print("Финальная статистика:")
        rows = (await s.execute(text("""
            SELECT source,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE house_id IS NOT NULL) AS linked
            FROM sold_ads
            GROUP BY source
            ORDER BY total DESC;
        """))).all()
        for r in rows:
            pct = 100 * r.linked / r.total if r.total else 0
            print(f"  sold_ads {r[0]:20s} {r.linked:>8,}/{r.total:>8,} ({pct:5.1f}%) linked")

        row = (await s.execute(text("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE house_id IS NOT NULL) AS linked
            FROM active_ads;
        """))).first()
        pct = 100 * row.linked / row.total if row.total else 0
        print(f"  active_ads cian_active    {row.linked:>8,}/{row.total:>8,} ({pct:5.1f}%) linked")

        # 5. Дома с привязанными объявлениями (для карты)
        print("\n[5] Дома с привязанными sold_ads/active_ads (для дашборда):")
        rows = (await s.execute(text("""
            SELECT h.id, h.source, h.external_house_id, h.address,
                   (SELECT COUNT(*) FROM active_ads WHERE house_id = h.id) AS active_n,
                   (SELECT COUNT(*) FROM sold_ads WHERE house_id = h.id) AS sold_n
            FROM houses h
            WHERE h.lat IS NOT NULL
              AND h.lng IS NOT NULL
              AND (
                EXISTS (SELECT 1 FROM active_ads WHERE house_id = h.id)
                OR EXISTS (SELECT 1 FROM sold_ads WHERE house_id = h.id)
              )
            ORDER BY h.source, h.id
            LIMIT 5;
        """))).all()
        for r in rows:
            print(f"  id={r[0]} {r[1]} ext={r[2][:20]} active={r[4]} sold={r[5]}")
            print(f"    address: {r[3]}")

        # Общее число домов с привязанными объявлениями
        row = (await s.execute(text("""
            SELECT COUNT(DISTINCT h.id)
            FROM houses h
            WHERE h.lat IS NOT NULL
              AND h.lng IS NOT NULL
              AND (
                EXISTS (SELECT 1 FROM active_ads WHERE house_id = h.id)
                OR EXISTS (SELECT 1 FROM sold_ads WHERE house_id = h.id)
              );
        """))).scalar()
        print(f"\n  ИТОГО домов с координатами И привязанными объявлениями: {row}")

        print("\n" + "=" * 70)
        print("OK")


asyncio.run(main())
