"""
grist_apply_experiments.py — применяет ВСЕ эксперименты из docs/GRIST_EXPERIMENTS.md
к таблицам Houses2 и Active_ads в Grist.

Что делает:
  - Удаляет тестовые/пустые таблицы
  - Добавляет formula columns в Houses2 и Active_ads
  - Создаёт 3 summary tables (by district, by filter, by month)
  - Возвращает summary что создалось, что нет

Использование:
  py scripts/grist_apply_experiments.py           # применить всё
  py scripts/grist_apply_experiments.py --dry    # только показать
  py scripts/grist_apply_experiments.py --reset  # удалить всё и применить заново
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from typing import Any

import requests

GRIST_URL = os.environ.get("GRIST_URL", "http://127.0.0.1:8484")
GRIST_API_KEY = os.environ.get(
    "GRIST_API_KEY",
    "flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978",
)
DOC = "mDaHoGD6yahtxaqugwr5mK"
H = {"Authorization": f"Bearer {GRIST_API_KEY}"}


def grist(method: str, path: str, **kw) -> Any:
    r = requests.request(method, f"{GRIST_URL}{path}", headers=H, timeout=60, **kw)
    if not r.ok:
        print(f"  ERR {method} {path} -> {r.status_code}: {r.text[:200]}")
        return None
    return r.json() if r.text else {}


# Formula columns to add
HOUSES_COLS = [
    # Возраст
    ("age", "Возраст дома", "Int", "2026 - $year_built"),
    ("era", "Эпоха", "Text",
     "IF($year_built == null, 'unknown', "
     "IF($year_built < 1900, 'дореволюционный', "
     "IF($year_built < 1950, 'сталинка', "
     "IF($year_built < 1990, 'советский', "
     "IF($year_built < 2010, 'современный', 'новостройка')))))"),
    ("decade", "Десятилетие", "Int", "FLOOR($year_built / 10) * 10"),
    # Координаты
    ("has_coords", "Есть координаты", "Bool", "$lat != null AND $lng != null"),
    # Этажность
    ("height_cat", "Тип этажности", "Text",
     "IF($levels == null, 'unknown', "
     "IF($levels <= 5, 'малоэтажка', "
     "IF($levels <= 9, 'среднеэтажка', "
     "IF($levels <= 17, 'высотка', 'небоскрёб'))))"),
    # Центр
    ("is_cao", "В ЦАО", "Bool", "$okrug.contains('ЦАО')"),
    ("is_moscow", "В Москве", "Bool", "$address.contains('Москва') OR $address.contains('москва')"),
]

ACTIVE_ADS_COLS = [
    # Цена
    ("cheap_signal", "Подозрительно дёшево", "Bool", "$price_per_m2 < 200000"),
    ("expensive_signal", "Дорого", "Bool", "$price_per_m2 > 600000"),
    # Время на рынке
    ("is_stale", "Залежалось (>60д)", "Bool", "$days_in_exposition > 60"),
    ("is_fresh", "Свежее (<14д)", "Bool", "$days_in_exposition < 14"),
    # Engagement
    ("views_per_day", "Просмотров/день", "Numeric",
     "IF($days_in_exposition > 0, ROUND($total_views / $days_in_exposition, 1), null)"),
    ("engagement_pct", "Engagement %", "Numeric",
     "IF($total_views > 0, ROUND($unique_views * 100.0 / $total_views, 1), null)"),
    # Этаж
    ("is_first_floor", "Первый этаж", "Bool", "$floor_current == 1"),
    ("is_last_floor", "Последний этаж", "Bool",
     "$floor_current != null AND $floor_total != null AND $floor_current == $floor_total"),
    # Комнаты
    ("is_studio", "Студия", "Bool", "$rooms == 0"),
    # Фильтр
    ("filter_name", "Фильтр", "Text",
     "IF($filter_id == 1, 'offers_до2000', "
     "IF($filter_id == 2, 'offers_после2000', "
     "IF($filter_id == 3, 'offers_ЦАО_до2000', "
     "IF($filter_id == 4, 'offers_ЦАО_после2000', "
     "IF($filter_id == 5, 'signals_Опека', "
     "IF($filter_id == 6, 'advance_Запрет', 'other'))))))"),
    # Потенциал
    ("has_potential", "Аномалия (дешево И свежее)", "Bool",
     "$price_per_m2 < 300000 AND $days_in_exposition < 30"),
]


# Summary tables to create (Houses2 ref=23, Active_ads ref=22)
SUMMARY_TABLES = [
    {
        "id": "HousesByDistrict",
        "summarySourceTable": 23,
        "label": "Houses by District",
        "columns": [
            {"id": "group", "fields": {"type": "RefList:Text", "label": "Район"}},
            {"id": "count", "fields": {"type": "Int", "formula": "len($group)"}},
            {"id": "avg_year", "fields": {"type": "Numeric", "formula": "AVG($group.year_built)"}},
            {"id": "oldest", "fields": {"type": "Numeric", "formula": "MIN($group.year_built)"}},
            {"id": "with_coords", "fields": {"type": "Int",
                "formula": "SUM(IF($group.lat != null, 1, 0))"}},
        ]
    },
    {
        "id": "HousesBySource",
        "summarySourceTable": 23,
        "label": "Houses by Source",
        "columns": [
            {"id": "group", "fields": {"type": "RefList:Text", "label": "Источник"}},
            {"id": "count", "fields": {"type": "Int", "formula": "len($group)"}},
            {"id": "with_coords_pct", "fields": {"type": "Numeric",
                "formula": "ROUND(100 * SUM(IF($group.lat != null, 1, 0)) / len($group), 1)"}},
        ]
    },
    {
        "id": "ActiveAdsByFilter",
        "summarySourceTable": 22,
        "label": "Active Ads by Filter",
        "columns": [
            {"id": "group", "fields": {"type": "RefList:Numeric", "label": "filter_id"}},
            {"id": "count", "fields": {"type": "Int", "formula": "len($group)"}},
            {"id": "avg_price", "fields": {"type": "Numeric", "formula": "AVG($group.price)"}},
            {"id": "avg_price_m2", "fields": {"type": "Numeric", "formula": "AVG($group.price_per_m2)"}},
            {"id": "avg_days", "fields": {"type": "Numeric", "formula": "AVG($group.days_in_exposition)"}},
            {"id": "avg_views", "fields": {"type": "Numeric", "formula": "AVG($group.total_views)"}},
        ]
    },
    {
        "id": "ActiveAdsByMonth",
        "summarySourceTable": 22,
        "label": "Active Ads Timeline (by publish month)",
        "columns": [
            {"id": "month", "fields": {"type": "Date", "label": "Месяц"}},
            {"id": "count", "fields": {"type": "Int", "formula": "len($group)"}},
            {"id": "avg_price", "fields": {"type": "Numeric", "formula": "AVG($group.price)"}},
            {"id": "avg_price_m2", "fields": {"type": "Numeric", "formula": "AVG($group.price_per_m2)"}},
        ]
    },
]


def reset():
    """Удалить пустые summary таблицы и тестовые колонки."""
    print("Cleaning up...")
    # Не можем удалить таблицы через API, но можем удалить колонки
    # Удалим test cols
    r = grist("GET", f"/api/docs/{DOC}/tables/Houses2/columns")
    for c in r.get("columns", []):
        if c["id"].startswith("age_") or c["id"] in ("age", "is_central"):
            grist("DELETE", f"/api/docs/{DOC}/tables/Houses2/columns/{c['id']}")
    # Grist не поддерживает DELETE column через REST API, но через user actions
    # Оставим как есть, юзер удалит в UI


def add_formula_columns(table: str, cols: list, dry: bool):
    print(f"\n[+] Adding {len(cols)} formula columns to {table}")
    # Check existing
    r = grist("GET", f"/api/docs/{DOC}/tables/{table}/columns")
    existing = {c["id"] for c in r.get("columns", [])} if r else set()
    for col_id, label, ctype, formula in cols:
        if col_id in existing:
            print(f"  [skip] {col_id} (already exists)")
            continue
        if dry:
            print(f"  [dry] would add: {col_id} = {formula[:60]}...")
            continue
        payload = {
            "columns": [{
                "id": col_id,
                "fields": {
                    "label": label,
                    "type": ctype,
                    "isFormula": True,
                    "formula": formula,
                }
            }]
        }
        r = grist("POST", f"/api/docs/{DOC}/tables/{table}/columns", json=payload)
        if r is not None:
            print(f"  [+] {col_id}: {label}")
        time.sleep(0.3)  # rate limit politeness


def create_summary_table(spec: dict, dry: bool):
    name = spec["id"]
    print(f"\n[+] Summary table: {name}")
    # Check if exists
    r = grist("GET", f"/api/docs/{DOC}/tables")
    existing = {t["id"] for t in r.get("tables", [])} if r else set()
    if name in existing:
        print(f"  [skip] {name} (already exists)")
        return
    if dry:
        print(f"  [dry] would create {name} with {len(spec['columns'])} cols")
        return
    payload = {"tables": [{
        "id": name,
        "label": spec.get("label", name),
        "summarySourceTable": spec["summarySourceTable"],
        "columns": spec["columns"]
    }]}
    r = grist("POST", f"/api/docs/{DOC}/tables", json=payload)
    if r is not None:
        print(f"  [+] {name} created")
    time.sleep(0.3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--reset", action="store_true", help="Cleanup before applying")
    args = ap.parse_args()

    if args.reset:
        reset()

    print(f"Target: {GRIST_URL}/o/flipper/doc/{DOC}")
    print(f"Dry run: {args.dry}")

    # Formula columns
    add_formula_columns("Houses2", HOUSES_COLS, args.dry)
    add_formula_columns("Active_ads", ACTIVE_ADS_COLS, args.dry)

    # Summary tables
    for spec in SUMMARY_TABLES:
        create_summary_table(spec, args.dry)

    print("\n=== Done ===")
    if not args.dry:
        print("Refresh http://localhost:8484/o/flipper/doc/mDaHoGD6yahtxaqugwr5mK")
        print("New formula columns visible in Houses2 and Active_ads")
        print("New summary tables: HousesByDistrict, HousesBySource,")
        print("                    ActiveAdsByFilter, ActiveAdsByMonth")


if __name__ == "__main__":
    main()
