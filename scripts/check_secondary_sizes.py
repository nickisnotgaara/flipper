"""Быстрая проверка размеров secondary/."""
import json
from pathlib import Path

SECONDARY = Path("C:/Users/User/Desktop/flipping/secondary")

print("=== cian_sold ===")
jsonl = SECONDARY / "cian" / "data" / "result.jsonl"
with jsonl.open(encoding="utf-8") as f:
    n = sum(1 for _ in f)
print(f"  result.jsonl: {n:,} records ({jsonl.stat().st_size / 1024 / 1024:.1f} MB)")

print("\n=== winners ===")
for name in ("all_advs.json", "all_advs_vtorichka.json",
             "filtered_advs.json", "filtered_advs_vtorichka.json"):
    p = SECONDARY / "winners" / name
    if not p.exists():
        print(f"  {name}: NOT FOUND")
        continue
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {name}: {len(data):,} records ({p.stat().st_size / 1024 / 1024:.1f} MB)")

print("\n=== domclick ===")
p = SECONDARY / "domclick" / "domclick_result.json"
with p.open(encoding="utf-8") as f:
    data = json.load(f)
items = data.get("items") if isinstance(data, dict) else data
print(f"  domclick_result.json: {len(items):,} items ({p.stat().st_size / 1024 / 1024:.1f} MB)")

print("\n=== flatinfo ===")
p = SECONDARY / "flatinfo" / "house_pages_result.json"
with p.open(encoding="utf-8") as f:
    data = json.load(f)
print(f"  house_pages_result.json: {len(data):,} houses ({p.stat().st_size / 1024 / 1024:.1f} MB)")

print("\n=== ИТОГО ===")
total_mb = sum(
    f.stat().st_size for f in SECONDARY.rglob("*")
    if f.is_file() and f.suffix in (".json", ".jsonl") and "__pycache__" not in f.parts
)
print(f"  Всего JSON/JSONL (без кэша): {total_mb / 1024 / 1024:.1f} MB")
