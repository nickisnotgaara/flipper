"""Audit: how many unlinked active_ads have a parseable address for cian API."""
import asyncio
import asyncpg

DB_URL = "postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper"

async def main():
    con = await asyncpg.connect(DB_URL.replace("postgresql+asyncpg://", "postgresql://"))
    rows = await con.fetch("""
        SELECT id, cian_id, raw_data::text as raw
        FROM active_ads
        WHERE source='cian_active' AND cian_house_id IS NULL
        ORDER BY id
        LIMIT 30
    """)
    print(f"sample 30 unlinked:")
    for r in rows:
        import json
        d = json.loads(r['raw'])
        addr = d.get('address', {})
        full = addr.get('full', '?') if isinstance(addr, dict) else '?'
        # check if address has house number
        import re
        m = re.search(r'\b(д\.|д\s|\d+\s*к\s*\d+|дома)\s*\d+', full, re.IGNORECASE)
        m2 = re.search(r',\s*\d+', full)  # trailing number
        has_num = bool(m) or bool(m2)
        print(f"  id={r['id']} cian_id={r['cian_id']} has_house_num={has_num} addr={full[:120]}")

    # total counts
    rows = await con.fetch("""
        WITH parsed AS (
            SELECT
                id,
                cian_id,
                raw_data->'address'->>'full' as full_addr
            FROM active_ads
            WHERE source='cian_active' AND cian_house_id IS NULL
        )
        SELECT
            COUNT(*) as total,
            COUNT(full_addr) as with_addr,
            COUNT(CASE WHEN full_addr ~ ',\s*\d' OR full_addr ~* 'д\.\s*\d' THEN 1 END) as with_house_num
        FROM parsed
    """)
    r = rows[0]
    print(f"\nTotals: {r['total']} candidates, {r['with_addr']} have full addr, {r['with_house_num']} have house number in addr")

asyncio.run(main())
