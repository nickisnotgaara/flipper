"""
scripts.grist_apply_conditional_formatting — Условное форматирование в Grist.

Применяет cell-style правила на колонке `status` в парсер-таблицах:
  status="deactivated" → серый фон
  status="hot"         → зелёный фон
  status="signal"      → жёлтый фон
  status="deposited"   → жёлтый фон

Подсвечивается ячейка в колонке `status`, что достаточно для быстрого
визуального сканирования — пользователь видит «серая/зелёная/жёлтая» строка
и сразу понимает статус.

Grist устроен так: условное форматирование = helper formula-колонка
(`gristHelper_ConditionalRule*`) с предикатом + `widgetOptions` с цветом,
которая через поле `rules` колонки автоматически применяется в обоих view
секциях таблицы (primary и raw).

Скрипт идемпотентен: переприменяется без дублей — если правило с такой
формулой уже есть, оно обновляется; если нет — создаётся.

Использование:
    py -3.11 scripts/grist_apply_conditional_formatting.py
    py -3.11 scripts/grist_apply_conditional_formatting.py --dry-run
    py -3.11 scripts/grist_apply_conditional_formatting.py --tables Sold_Ads,Offers_Parser

Зависит от env: GRIST_API_KEY, GRIST_BASE, GRIST_DOC (см. .env / flipper_core.grist).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, parse, request

# ---- IO -------------------------------------------------------------------

GRIST_BASE = os.getenv("GRIST_BASE", "http://127.0.0.1:8484")
DOC = os.getenv("GRIST_DOC", "mDaHoGD6yahtxaqugwr5mK")
API_KEY = os.getenv("GRIST_API_KEY", "")
if not API_KEY:
    raise SystemExit("GRIST_API_KEY env var is required (see .env).")

HEAD = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def _request(method: str, path: str, body=None, timeout: int = 60):
    url = f"{GRIST_BASE}{path}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers=HEAD, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except error.HTTPError as e:
        raise RuntimeError(
            f"Grist {method} {path} → {e.code}: {e.read().decode('utf-8','replace')[:400]}"
        )


def sql(query: str):
    return _request("GET", f"/api/docs/{DOC}/sql?q={parse.quote(query)}").get("records", [])


def apply(actions: list):
    return _request("POST", f"/api/docs/{DOC}/apply", actions)


# ---- Lookup helpers --------------------------------------------------------


def table_ref_by_id(table_id: str) -> int | None:
    recs = sql(f"SELECT id FROM _grist_Tables WHERE tableId = '{table_id}'")
    if recs:
        return recs[0]["fields"].get("id")
    return None


def col_ref_by_id(parent_id: int, col_id: str) -> int | None:
    recs = sql(
        f"SELECT id FROM _grist_Tables_column "
        f"WHERE parentId = {parent_id} AND colId = '{col_id}'"
    )
    if recs:
        return recs[0]["fields"].get("id")
    return None


def existing_cell_rules(col_ref: int) -> list[dict]:
    """Cell-style rules, привязанные к колонке (status).
    У колонки `rules` = JSON-массив ref-ов на helper-колонки `gristHelper_ConditionalRule*`.
    """
    recs = sql(
        f"SELECT rules FROM _grist_Tables_column WHERE id = {col_ref}"
    )
    if not recs:
        return []
    rules_str = recs[0]["fields"].get("rules") or "[]"
    rule_refs = json.loads(rules_str) if rules_str else []
    if not rule_refs:
        return []
    refs_csv = ",".join(str(r) for r in rule_refs)
    recs = sql(
        f"SELECT id, formula, widgetOptions FROM _grist_Tables_column "
        f"WHERE id IN ({refs_csv})"
    )
    return [r["fields"] for r in recs]


# ---- Mutators --------------------------------------------------------------


def upsert_cell_rule(
    *,
    table_id: str,
    status_col_ref: int,
    formula: str,
    fill_color: str,
    text_color: str = "#1f2937",
) -> tuple[str, int | None]:
    """Создаёт или обновляет cell-style условное правило на колонке status.

    Returns: (status, rule_col_ref) где status in {"created","updated","unchanged"}.
    """
    existing = existing_cell_rules(status_col_ref)
    target_idx = None
    for i, r in enumerate(existing):
        if (r.get("formula") or "").strip() == formula.strip():
            target_idx = i
            break

    new_widget_options = json.dumps(
        {"rulesOptions": [{"fillColor": fill_color, "textColor": text_color}]},
        ensure_ascii=False,
    )

    if target_idx is not None:
        # Rule already exists — update its color if changed.
        rule = existing[target_idx]
        rule_id = rule["id"]
        current_options = rule.get("widgetOptions") or ""
        if current_options == new_widget_options:
            return ("unchanged", rule_id)
        apply([
            ["UpdateRecord", "_grist_Tables_column", rule_id, {"widgetOptions": new_widget_options}],
        ])
        return ("updated", rule_id)

    # Create new cell-style rule on the status column.
    # AddEmptyRule(table_id, field_ref=0, col_ref=status_col_ref) → cell style.
    resp = apply([["AddEmptyRule", table_id, 0, status_col_ref]])
    ret = (resp.get("retValues") or [{}])[0] if resp.get("retValues") else {}
    new_rule_id = ret.get("colRef")
    if not new_rule_id:
        raise RuntimeError(f"AddEmptyRule did not return colRef for {table_id}")

    apply([
        ["UpdateRecord", "_grist_Tables_column", new_rule_id, {"formula": formula}],
        ["UpdateRecord", "_grist_Tables_column", new_rule_id, {"widgetOptions": new_widget_options}],
    ])
    return ("created", new_rule_id)


# ---- Color palette ---------------------------------------------------------

# Soft, low-saturation pastels so the table stays readable. text_color is a
# dark neutral for legibility.
COLORS = {
    "deactivated": {"fill": "#E5E7EB", "text": "#374151"},  # gray-200 / gray-700
    "hot":         {"fill": "#D1FAE5", "text": "#065F46"},  # emerald-100 / emerald-800
    "signal":      {"fill": "#FEF3C7", "text": "#92400E"},  # amber-100 / amber-800
    "deposited":   {"fill": "#FEF3C7", "text": "#92400E"},  # same as signal
}


# ---- Spec: which rules to apply per table ---------------------------------

# Each entry: tableId → list of (status_value, formula). If a status value is
# not in this list, it stays uncolored.

RULES_SPEC: dict[str, list[tuple[str, str]]] = {
    "Sold_Ads": [
        ("deactivated", "$status == 'deactivated'"),
    ],
    "Offers_Parser": [
        ("deactivated", "$status == 'deactivated'"),
        ("hot",         "$status == 'hot'"),
    ],
    "Signals_Parser": [
        ("signal", "$status == 'signal'"),
    ],
    "Table2": [  # Аванс
        ("deactivated", "$status == 'deactivated'"),
        ("deposited",   "$status == 'deposited'"),
    ],
    "Table3": [  # Аванс_Продано
        ("deactivated", "$status == 'deactivated'"),
        ("deposited",   "$status == 'deposited'"),
    ],
    "Arhiv_Prodano": [
        ("deactivated", "$status == 'deactivated'"),
    ],
}


# ---- Main ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply Grist conditional formatting (cell style on `status`)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be done, make no changes")
    ap.add_argument("--tables", type=str, default="", help="Comma-separated list of tableIds to limit (default: all in RULES_SPEC)")
    args = ap.parse_args(argv)

    targets = list(RULES_SPEC.keys())
    if args.tables:
        wanted = {t.strip() for t in args.tables.split(",") if t.strip()}
        targets = [t for t in targets if t in wanted]
        if not targets:
            print(f"ERROR: none of {sorted(wanted)} are in spec; known: {sorted(RULES_SPEC)}")
            return 1

    print(f"== Grist conditional formatting ({'DRY-RUN' if args.dry_run else 'APPLY'}) ==")
    print(f"Base: {GRIST_BASE}  Doc: {DOC}")
    print(f"Tables: {targets}\n")

    summary = []  # (table, status_value, action, rule_id)

    for table_id in targets:
        table_ref = table_ref_by_id(table_id)
        if not table_ref:
            print(f"  ✗ {table_id}: not found in _grist_Tables, skipping")
            continue
        status_col_ref = col_ref_by_id(table_ref, "status")
        if not status_col_ref:
            print(f"  ✗ {table_id}: no `status` column, skipping")
            continue
        print(f"  ▸ {table_id} (tableRef={table_ref}, status colRef={status_col_ref})")
        for status_value, formula in RULES_SPEC[table_id]:
            colors = COLORS[status_value]
            if args.dry_run:
                print(f"    · would upsert rule: {formula}  →  fill={colors['fill']}  text={colors['text']}")
                summary.append((table_id, status_value, "dry-run", None))
                continue
            try:
                action, rule_id = upsert_cell_rule(
                    table_id=table_id,
                    status_col_ref=status_col_ref,
                    formula=formula,
                    fill_color=colors["fill"],
                    text_color=colors["text"],
                )
                print(f"    · {action:9s} rule: {formula}  →  fill={colors['fill']}  (id={rule_id})")
                summary.append((table_id, status_value, action, rule_id))
            except Exception as e:
                print(f"    ✗ FAILED: {formula}: {e}")
                summary.append((table_id, status_value, f"error: {e}", None))

    print("\n== Summary ==")
    by_action: dict[str, int] = {}
    for _, _, action, _ in summary:
        by_action[action] = by_action.get(action, 0) + 1
    for k, v in sorted(by_action.items()):
        print(f"  {k}: {v}")
    print("\nDone. Refresh the Grist doc (Ctrl+R) to see colors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
