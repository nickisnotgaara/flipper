"""Check if raw_data for an unlinked ad contains cian_house_id or similar house info."""
import asyncio
import asyncpg
import json


async def main():
    con = await asyncpg.connect(
        "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"
    )
    rows = await con.fetch("""
        SELECT id, cian_id, raw_data
        FROM active_ads
        WHERE source='cian_active' AND house_id IS NULL
        LIMIT 3
    """)
    for r in rows:
        d = json.loads(r['raw_data']) if isinstance(r['raw_data'], str) else r['raw_data']
        print(f"\n=== ad id={r['id']}, cian_id={r['cian_id']} ===")
        # Search for keys containing 'house', 'building', 'complex', 'jk', 'address'
        interesting = {}
        for k, v in d.items():
            kl = k.lower()
            if any(t in kl for t in ['house', 'building', 'complex', 'jk', 'address', 'geo', 'location', 'street', 'flat']):
                interesting[k] = v
        print(json.dumps(interesting, ensure_ascii=False, default=str)[:1500])
    await con.close()


asyncio.run(main())
