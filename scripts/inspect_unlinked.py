"""Look at unlinked cian_active ads to see address patterns."""
import asyncio
import asyncpg
import json
from collections import Counter


async def main():
    con = await asyncpg.connect(
        "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"
    )
    rows = await con.fetch("""
        SELECT id, cian_id,
               raw_data->'address'->>'full' as full_addr,
               raw_data->'address'->'street'->>'name' as street_name,
               raw_data->'address'->>'house_name' as house_name
        FROM active_ads
        WHERE source='cian_active' AND house_id IS NULL
        ORDER BY id
    """)
    print(f"unlinked total: {len(rows)}")
    print()
    # bucket by pattern
    no_house_num = 0
    with_house_num = 0
    digit_in_street = 0
    samples = {"no_house": [], "with_house": [], "digit_street": []}
    for r in rows:
        addr = r['full_addr'] or ""
        sn = r['street_name'] or ""
        hn = r['house_name'] or ""
        if not hn and not any(ch.isdigit() for ch in addr.split(",")[-1].strip()):
            no_house_num += 1
            if len(samples["no_house"]) < 8:
                samples["no_house"].append((r['cian_id'], addr[:100]))
        else:
            with_house_num += 1
            if len(samples["with_house"]) < 5:
                samples["with_house"].append((r['cian_id'], addr[:100]))
        # digit in street name like "15-я Парковая"
        if sn and any(w for w in sn.split() if w[0].isdigit() if w):
            digit_in_street += 1
            if len(samples["digit_street"]) < 5:
                samples["digit_street"].append((r['cian_id'], sn))

    print(f"no house num:    {no_house_num}")
    print(f"with house num:  {with_house_num}")
    print(f"digit in street: {digit_in_street}")
    print()
    print("--- samples (no house) ---")
    for cid, a in samples["no_house"]:
        print(f"  {cid}: {a}")
    print()
    print("--- samples (with house) ---")
    for cid, a in samples["with_house"]:
        print(f"  {cid}: {a}")
    print()
    print("--- samples (digit street) ---")
    for cid, sn in samples["digit_street"]:
        print(f"  {cid}: street={sn}")
    await con.close()


asyncio.run(main())
