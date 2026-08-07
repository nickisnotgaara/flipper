"""Быстрый осмотр старой parser_cian.db."""
import sqlite3

con = sqlite3.connect("C:/Users/User/Desktop/flipping/flipper/data/parser_cian.db.recovered")
cur = con.cursor()

print("=== Tables ===")
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(" ", row[0])
print()

for t in ("cian_active_ads", "cian_sold_ads", "cian_filters"):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]:,} rows")
    except Exception as e:
        print(f"  {t}: ERROR {e}")
print()

cur.execute("SELECT source, COUNT(*) FROM cian_active_ads GROUP BY source")
print("cian_active_ads by source:")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]:,}")
print()

cur.execute("SELECT is_parsed, COUNT(*) FROM cian_active_ads GROUP BY is_parsed")
print("cian_active_ads by is_parsed:")
for row in cur.fetchall():
    print(f"  is_parsed={row[0]}: {row[1]:,}")
print()

cur.execute("PRAGMA table_info(cian_active_ads)")
print("cian_active_ads columns:")
for c in cur.fetchall():
    print(f"  {c}")
print()

cur.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='cian_active_ads'"
)
print("cian_active_ads indexes:")
for row in cur.fetchall():
    print(" ", row[0])
print()

# Sample row
cur.execute("SELECT * FROM cian_active_ads LIMIT 1")
row = cur.fetchone()
cur.execute("PRAGMA table_info(cian_active_ads)")
cols = [c[1] for c in cur.fetchall()]
print("cian_active_ads columns:", cols)
print("Sample row:", dict(zip(cols, row)))
