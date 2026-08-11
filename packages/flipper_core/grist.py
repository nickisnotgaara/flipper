"""
packages.flipper_core.grist — Grist API client (replaces SheetsManager).

Используется парсером вместо Google Sheets:
- чтение FILTERS (фильтры парсинга)
- чтение Signals_Parser (URL объявлений)
- запись Offers_Parser / Signals_Parser / Аванс / Аванс_Продано / Продано
- запись Balans (category counter)

API Grist:
- POST /api/docs/{docId}/apply   — список action-массивов (AddRecord, UpdateRecord, RemoveRecord, ...)
- GET  /api/docs/{docId}/sql?q=…  — SQL запросы
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.parse import quote
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# Позиции элементов в row (из parse_to_sheets_row) → имена колонок Grist.
# 0..22 → url, publish_date, ..., parsed_at, A (legacy "Reason" W из Sheets).
PARSER_COLUMNS: List[str] = [
    "url",
    "publish_date",
    "price",
    "title",
    "address",
    "description",
    "price_per_m2",
    "area",
    "construction_year",
    "days_in_exposition",
    "district",
    "floor_info",
    "housing_type",
    "metro_station",
    "metro_walk_time",
    "okrug",
    "renovation",
    "rooms",
    "total_views",
    "unique_views",
    "cian_id",
    "parsed_at",
    "A",
]

NUMERIC_PARSER_COLS = {
    "price",
    "price_per_m2",
    "area",
    "construction_year",
    "metro_walk_time",
    "rooms",
    "total_views",
    "unique_views",
    "cian_id",
}


class GristError(RuntimeError):
    """Ошибка Grist API."""


class GristClient:
    """
    Grist REST-клиент. Минимальный API для парсера.

    Методы:
      - sql(query) → list[dict {id, fields}]
      - apply(actions) → dict (actionNum, actionHash, retValues)
      - get_filters_table() → {"headers": [...], "rows": [...]}
      - get_urls(table) → list[str]
      - upsert_row(table, row_list, cian_id=None) → bool
      - delete_by_cian_id(table, cian_id) → bool
      - find_by_cian_id(table, cian_id) → {"id"} | None
      - sync_offers_and_signals(row, cian_id, offers_match, signals_match, deactivated) → dict
      - add_balans_row(...) → bool
    """

    DEFAULT_BASE = "http://localhost:8484"
    DEFAULT_DOC = "mDaHoGD6yahtxaqugwr5mK"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        doc_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("GRIST_API_KEY", "")
        self.base_url = (base_url or os.getenv("GRIST_BASE", self.DEFAULT_BASE)).rstrip("/")
        self.doc_id = doc_id or os.getenv("GRIST_DOC", self.DEFAULT_DOC)

        if not self.api_key:
            raise ValueError(
                "GRIST_API_KEY must be provided or set in env (export GRIST_API_KEY=...)"
            )

        self._last_call_mono: float = 0.0
        self._spacing_sec: float = float(os.getenv("GRIST_READ_SPACING_SEC", "0.05"))

        logger.info(
            "GristClient initialized: doc=%s base=%s key=%s…",
            self.doc_id,
            self.base_url,
            (self.api_key[:8] + "…") if self.api_key else "(empty)",
        )

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        gap = self._spacing_sec
        now = time.monotonic()
        wait = gap - (now - self._last_call_mono)
        if wait > 0:
            time.sleep(wait)
        self._last_call_mono = time.monotonic()

    def _request(
        self, method: str, path: str, body: Any = None, max_retries: int = 5
    ) -> Any:
        self._throttle()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data: Optional[bytes] = None
        if body is not None:
            # Grist /apply принимает body как raw JSON-массив (НЕ обёртку),
            # остальные эндпоинты — обёртку {key: ...}.
            if path.endswith("/apply") and isinstance(body, list):
                data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            else:
                data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        req = urlrequest.Request(url, data=data, headers=headers, method=method)

        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                with urlrequest.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    if not raw:
                        return {}
                    return json.loads(raw)
            except HTTPError as e:
                last_err = e
                status = e.code
                body_text = e.read().decode("utf-8", "replace")
                if status in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    sleep_s = min(30, 1.5 * (attempt + 1))
                    logger.warning(
                        "Grist %s %s → %s (retry %s/%s after %.1fs): %s",
                        method, path, status, attempt + 1, max_retries, sleep_s, body_text[:200],
                    )
                    time.sleep(sleep_s)
                    continue
                logger.error("Grist %s %s → %s: %s", method, path, status, body_text[:300])
                raise GristError(f"Grist {method} {path} → {status}: {body_text[:300]}")
        raise GristError(f"Grist {method} {path} failed: {last_err}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sql(self, query: str) -> List[dict]:
        """SELECT через /api/docs/{docId}/sql. Возвращает [{id, fields}, ...]."""
        result = self._request("GET", f"/api/docs/{self.doc_id}/sql?q={quote(query)}")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("records", []) or []
        return []

    def apply(self, actions: list) -> dict:
        """Применить список action-массивов (AddRecord, UpdateRecord, RemoveRecord, ...)."""
        if not isinstance(actions, list):
            raise ValueError("actions must be a list of action arrays")
        if not actions:
            return {}
        return self._request("POST", f"/api/docs/{self.doc_id}/apply", actions)

    # --- FILTERS --------------------------------------------------------

    def get_filters_table(self, table: str = "FILTERS") -> dict:
        """
        Возвращает {"headers": [...], "rows": [{row_index, url, a_display, cells}, ...]}.

        Совместимо по форме с SheetsManager.get_filters_table() — используется
        в services/parsers/cian_active/main.py без изменений consumer-кода.
        """
        records = self.sql(f'SELECT * FROM "{table}" ORDER BY manualSort, id')
        # Хедер: первый ряд Grist — это уже данные (id=1). Хедер берём из схемы.
        headers = ["Фильтры", "Год", "Районы"]
        rows: List[dict] = []
        for i, r in enumerate(records):
            f = r.get("fields", {}) or {}
            url = (f.get("A") or "").strip()
            if not url:
                continue
            rows.append(
                {
                    "row_index": i + 2,  # 1-based, +1 под мнимый хедер
                    "url": url,
                    "a_display": url,  # в Grist нет "отображаемой" версии
                    "cells": [
                        url,
                        f.get("B", "") or "",
                        f.get("C", "") or "",
                    ],
                }
            )
        return {"headers": headers, "rows": rows}

    # --- URL lists ------------------------------------------------------

    def get_urls(self, table: str) -> List[str]:
        """Вернуть список URL из колонки 'url' указанной таблицы."""
        records = self.sql(
            f"SELECT url FROM \"{table}\" WHERE url IS NOT NULL AND url != ''"
        )
        out: List[str] = []
        for r in records:
            f = r.get("fields", {}) or {}
            u = (f.get("url") or "").strip()
            if u:
                out.append(u)
        return out

    # --- Row I/O --------------------------------------------------------

    @staticmethod
    def _row_to_dict(row_list: list) -> dict:
        """list[23] (от parse_to_sheets_row) → dict {col_name: value} для Grist.

        Пустые/None значения отбрасываются (Grist сам оставит их NULL).
        """
        d: Dict[str, Any] = {}
        for i, val in enumerate(row_list):
            if i >= len(PARSER_COLUMNS):
                break
            col = PARSER_COLUMNS[i]
            if val is None:
                continue
            if isinstance(val, str):
                sval = val.strip()
                if not sval:
                    continue
            else:
                sval = val
            if col in NUMERIC_PARSER_COLS:
                if isinstance(sval, (int, float)):
                    d[col] = sval
                else:
                    try:
                        d[col] = float(sval) if "." in str(sval) else int(sval)
                    except (ValueError, TypeError):
                        # Не пишем невалидное число — оставим NULL.
                        continue
            else:
                d[col] = sval
        return d

    def find_by_cian_id(self, table: str, cian_id: Any) -> Optional[dict]:
        """Найти запись по cian_id. Возвращает {'id': <rowId>} или None.

        В Grist SQL результат — список {fields: {...}}, поэтому rowId берём
        из records[0].fields.id.
        """
        try:
            cid = int(cian_id)
        except (ValueError, TypeError):
            return None
        records = self.sql(
            f'SELECT id FROM "{table}" WHERE cian_id = {cid} LIMIT 1'
        )
        if records and records[0].get("fields", {}).get("id") is not None:
            return {"id": records[0]["fields"]["id"]}
        return None

    def upsert_row(
        self, table: str, row_list: list, cian_id: Any = None
    ) -> bool:
        """Upsert по cian_id. cian_id берётся из row_list[20] если не передан.

        AddRecord / UpdateRecord в Grist: namedtuple(table_id, row_id, columns).
        row_id = None (или 0) для новой записи.
        """
        row_dict = self._row_to_dict(row_list)
        return self._upsert_dict(table, row_dict, cian_id)

    def upsert_dict(
        self, table: str, row_dict: dict, cian_id: Any = None
    ) -> bool:
        """Upsert по cian_id, передавая сразу dict (вместо 23-элементного list).

        Используется для Снятые (Sold_Ads) и Архив_Продано (Arhiv_Prodano) — туда
        надо дописать status/house_id,
        которых нет в стандартном row_list. Также для sync из Postgres, когда
        row_dict собирается из SQL-запроса.
        """
        if cian_id is not None:
            row_dict = {**row_dict, "cian_id": int(cian_id)}
        return self._upsert_dict(table, row_dict, cian_id)

    def _upsert_dict(
        self, table: str, row_dict: dict, cian_id: Any = None
    ) -> bool:
        """Internal: общая логика upsert через cian_id."""
        if not row_dict:
            logger.warning("upsert(%s): пустой row_dict", table)
            return False
        if cian_id is None:
            cian_id = row_dict.get("cian_id")
        if cian_id is None:
            logger.warning("upsert(%s): нет cian_id, пропуск", table)
            return False

        existing = self.find_by_cian_id(table, cian_id)
        if existing:
            actions: list = [["UpdateRecord", table, existing["id"], row_dict]]
        else:
            actions = [["AddRecord", table, None, row_dict]]
        self.apply(actions)
        return True

    def delete_by_cian_id(self, table: str, cian_id: Any) -> bool:
        """Удалить запись по cian_id. False если не найдена."""
        existing = self.find_by_cian_id(table, cian_id)
        if not existing:
            return False
        actions = [["RemoveRecord", table, existing["id"]]]
        self.apply(actions)
        return True

    # --- sync_offers_and_signals ---------------------------------------

    def sync_offers_and_signals(
        self,
        row: list,
        cian_id: str,
        offers_match: bool = True,
        signals_match: bool = False,
        deactivated: bool = False,
        status: Optional[str] = None,
    ) -> dict:
        """
        Полный аналог SheetsManager.sync_offers_and_signals().

        Offers_Parser обновляется/вставляется всегда (offers_match=True)
        или удаляется (offers_match=False).

        Signals_Parser:
        - deactivated=True: если строка есть — обновляем, иначе при signals_match — вставляем
        - deactivated=False: при signals_match — вставляем/обновляем;
          без signals_match при существующей — удаляем

        status: если передан — пишется в колонку status (active|hot|signal) для
        условного форматирования. По умолчанию "active".
        """
        return self.sync_offers_and_signals_with_status(
            row, cian_id,
            offers_match=offers_match, signals_match=signals_match,
            deactivated=deactivated, status=status,
        )

    def sync_offers_and_signals_with_status(
        self,
        row: list,
        cian_id: str,
        offers_match: bool = True,
        signals_match: bool = False,
        deactivated: bool = False,
        status: Optional[str] = None,
    ) -> dict:
        result = {
            "offers_ok": False,
            "signal_added": False,
            "signal_removed": False,
        }

        status_value = status or "active"

        # Offers_Parser
        if offers_match:
            # upsert_dict чтобы добавить status (Offers_Parser колонка не входит
            # в стандартный row_list).
            row_dict = self._row_to_dict(row)
            row_dict["status"] = status_value
            result["offers_ok"] = self.upsert_dict("Offers_Parser", row_dict, cian_id)
        else:
            result["offers_ok"] = self.delete_by_cian_id("Offers_Parser", cian_id)

        # Signals_Parser
        signals_exists = self.find_by_cian_id("Signals_Parser", cian_id) is not None
        if deactivated:
            if signals_exists:
                self.upsert_row("Signals_Parser", row, cian_id)
            elif signals_match:
                self.upsert_row("Signals_Parser", row, cian_id)
                result["signal_added"] = True
        else:
            if signals_match and not signals_exists:
                row_sig = self._row_to_dict(row)
                row_sig["status"] = "signal"
                self.upsert_dict("Signals_Parser", row_sig, cian_id)
                result["signal_added"] = True
            elif signals_match and signals_exists:
                row_sig = self._row_to_dict(row)
                row_sig["status"] = "signal"
                self.upsert_dict("Signals_Parser", row_sig, cian_id)
            elif not signals_match and signals_exists:
                self.delete_by_cian_id("Signals_Parser", cian_id)
                result["signal_removed"] = True

        return result

    # --- Balans ---------------------------------------------------------

    def add_balans_row(
        self,
        vtorichka_msk: int,
        pervichka_msk: int,
        pervichka_mo: int,
        vtorichka_mo: int,
        equilibrium: int = 150000,
    ) -> bool:
        """
        Записать строку баланса: дата MSK + 4 категории.
        Колонка F (Всего) считается как сумма — раньше была формулой в Sheets.
        """
        msb_total = (
            int(vtorichka_msk or 0)
            + int(pervichka_msk or 0)
            + int(pervichka_mo or 0)
            + int(vtorichka_mo or 0)
        )
        now_msk = datetime.now(ZoneInfo("Europe/Moscow")).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        row_dict = {
            "A": now_msk,
            "B": int(vtorichka_msk or 0),
            "C": int(pervichka_msk or 0),
            "D": int(pervichka_mo or 0),
            "E": int(vtorichka_mo or 0),
            "F": int(msb_total),
            "G": int(equilibrium),
        }
        actions = [["AddRecord", "Balans", None, row_dict]]
        self.apply(actions)
        return True
