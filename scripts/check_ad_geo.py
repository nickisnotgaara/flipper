"""Check what lat/lng info is in active_ads.raw_data for new cian_house_ids."""
import asyncio
import asyncpg
import json

async def main():
    con = await asyncpg.connect("postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper")
    rows = await con.fetch("""
        SELECT a.cian_id, a.cian_house_id, a.raw_data
        FROM active_ads a
        WHERE a.source='cian_active' AND a.cian_house_id IS NOT NULL
          AND a.cian_house_id NOT IN (SELECT cian_real_house_id FROM houses WHERE cian_real_house_id IS NOT NULL)
        LIMIT 5
    """)
    for r in rows:
        d = json.loads(r['raw_data']) if isinstance(r['raw_data'], str) else r['raw_data']
        addr = d.get('address', {})
        geo = addr.get('geo', {}) if isinstance(addr, dict) else {}
        coords = geo.get('coordinates')
        print(f"cian_id={r['cian_id']}, cian_house_id={r['cian_house_id']}")
        print(f"  full_addr: {addr.get('full', '?')[:80]}")
        print(f"  geo: {json.dumps(geo, ensure_ascii=False)[:300]}")
        print()
    await con.close()

asyncio.run(main())
