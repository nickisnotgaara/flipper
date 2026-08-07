"""packages.flipper_db.cian_state — Python-порт ``flippercrawl`` stateParser.

Извлекает встроенный JSON-стейт карточки Cian (SSR) из raw HTML.

Cian — SSR-приложение: внутри inline-скрипта лежит
    window._cianConfig['frontend-offer-card'] = (...).concat([{...}, ...]);
где один из элементов массива — ``{ key: "defaultState", value: {...} }``,
а ``value.offerData`` содержит полные данные объявления (offer, agent,
photos, priceChanges, bti, seoData, breadcrumbs, ...).

Назначение в архитектуре v2:
    Flippercrawl уже отдаёт ``data.json.rawOfferData`` при успешном static
    extract. Но при LLM-fallback ``rawOfferData`` не возвращается — там у
    нас остаётся только ``data.rawHtml``. Чтобы и в этом случае получить
    полный offerData (для ``active_ads.raw_data``), парсим ``rawHtml`` этим
    модулем. Результат структурно совпадает с тем, что отдаёт
    ``tryCianStaticExtract`` в ``result.rawOfferData``.

Прямой порт ``flippercrawl/apps/api/src/lib/cian/stateParser.ts``.
Алгоритм:
    1. ``rawHtml.indexOf(CONFIG_MARKER)`` — найти инжекшн-маркер.
    2. ``rawHtml.indexOf("concat(")`` — должен быть рядом (≤500 символов).
    3. Сканировать сбалансированный JSON-массив, начиная с позиции ``[``.
    4. ``JSON.parse`` → найти ``{ key: "defaultState", value: {...} }``.
    5. Вернуть ``value.offerData`` (или ``None`` если ничего нет).

Никаких зависимостей кроме stdlib. Безопасен для вызова в LLM-fallback
(никогда не raise, всегда возвращает ``dict | None``).
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

# Тот же маркер, что в flippercrawl stateParser.ts: window._cianConfig['frontend-offer-card']
_CONFIG_MARKER = "_cianConfig['frontend-offer-card']"


def _scan_balanced_array(html: str, open_bracket: int) -> Optional[str]:
    """Сканирует сбалансированный JSON-массив, начиная с символа ``[``
    на позиции ``open_bracket``.

    Возвращает текст массива включительно со скобками (для ``json.loads``)
    или ``None`` если баланс не сошёлся до конца строки.

    Корректно пропускает содержимое строк с эскейпами (\\" и прочее).
    Прямой порт ``scanBalancedArray()`` из ``stateParser.ts``.
    """
    if open_bracket >= len(html) or html[open_bracket] != "[":
        return None

    depth = 0
    in_string = False
    i = open_bracket
    while i < len(html):
        ch = html[i]
        if in_string:
            if ch == "\\":
                i += 2  # пропустить экранированный символ
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
        elif ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
            if depth == 0:
                return html[open_bracket : i + 1]
        i += 1
    return None


def extract_offer_data(raw_html: str) -> Optional[dict[str, Any]]:
    """Извлекает ``state.offerData`` из raw HTML карточки Cian.

    Возвращает ``dict`` (готовый для ``AdRecord.raw_data``) или ``None``,
    если маркер не найден / JSON невалидный / ``defaultState.offerData``
    отсутствует.

    Прямой порт ``parseCianOfferState()`` из ``stateParser.ts``.
    """
    if not raw_html:
        return None

    search_from = 0
    while True:
        marker_idx = raw_html.find(_CONFIG_MARKER, search_from)
        if marker_idx == -1:
            return None
        search_from = marker_idx + len(_CONFIG_MARKER)

        # После маркера должен идти ``concat(`` в пределах 500 символов
        concat_idx = raw_html.find("concat(", marker_idx)
        if concat_idx == -1 or concat_idx - marker_idx > 500:
            continue

        # Затем ``[`` в пределах 20 символов
        open_bracket = raw_html.find("[", concat_idx)
        if open_bracket == -1 or open_bracket - concat_idx > 20:
            continue

        array_text = _scan_balanced_array(raw_html, open_bracket)
        if not array_text:
            continue

        try:
            entries = json.loads(array_text)
        except (ValueError, TypeError):
            continue
        if not isinstance(entries, list):
            continue

        # Ищем элемент ``{ key: "defaultState", value: {…} }``
        default_state_value: Optional[dict[str, Any]] = None
        for entry in entries:
            if (
                isinstance(entry, dict)
                and entry.get("key") == "defaultState"
                and isinstance(entry.get("value"), dict)
            ):
                default_state_value = entry["value"]
                break
        if default_state_value is None:
            continue

        offer_data = default_state_value.get("offerData")
        if not isinstance(offer_data, dict):
            continue

        return offer_data

    # unreachable, но для type-checker
    # pragma: no cover


__all__ = ["extract_offer_data"]
