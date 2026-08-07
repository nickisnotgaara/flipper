"""Check if cian_house_id is in parsed_data of cian_active_ads."""
import sqlite3
import json
import re

path = r"C:\Users\User\Desktop\flipping\flipper\data\parser_cian.db.recovered"
con = sqlite3.connect(path)
cur = con.cursor()

# sample first 5 records
cur.execute("SELECT id, url, source, parsed_data FROM cian_active_ads ORDER BY id LIMIT 5")
rows = cur.fetchall()
for r in rows:
    print(f"\n=== id={r[0]} url={r[1]} source={r[2]} ===")
    d = json.loads(r[3])
    print(f"  parsed_data keys: {list(d.keys())[:30]}")
    # search for cian_house_id-like fields
    s = r[3]
    for kw in ['cian_house_id', 'houseId', 'house_id', 'building_id', 'buildingId', 'cianHouseId']:
        if kw in s:
            for m in re.finditer(rf'"{kw}"\s*:\s*"?(\d+)"?', s):
                print(f"  found {kw}={m.group(1)}")
    # look for 'address' or 'geo' structure
    if 'address' in s:
        m = re.search(r'"address"\s*:\s*[\[\{](.+?)[\]\}]', s, re.DOTALL)
        if m:
            print(f"  address snippet: {m.group(0)[:200]}")
    if 'geo' in s:
        m = re.search(r'"geo"\s*:\s*\{(.+?)\}', s, re.DOTALL)
        if m:
            print(f"  geo snippet: {m.group(0)[:200]}")

# look for cian_house_id count
print("\n=== search across all 3,454 rows ===")
cur.execute("SELECT parsed_data FROM cian_active_ads")
hits_house_id = 0
hits_geo = 0
sample_with_house_id = []
for r in cur.fetchall():
    s = r[0]
    if '"cian_house_id"' in s or '"houseId"' in s or '"buildingId"' in s:
        hits_house_id += 1
        if len(sample_with_house_id) < 3:
            for kw in ['cian_house_id', 'houseId', 'buildingId']:
                m = re.search(rf'"{kw}"\s*:\s*"?(\d+)"?', s)
                if m:
                    sample_with_house_id.append((kw, m.group(1), s[max(0, m.start()-100):m.end()+50]))
    if '"geo"' in s:
        hits_geo += 1

print(f"  rows with cian_house_id-like field: {hits_house_id}/3454")
print(f"  rows with 'geo' field: {hits_geo}/3454")
print(f"  samples:")
for s in sample_with_house_id:
    print(f"    {s[0]}={s[1]} ctx: ...{s[2]}...")
