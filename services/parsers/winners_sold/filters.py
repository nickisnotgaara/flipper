"""
Фильтрация all_advs.json по "круглой" цене.

Логика:
- Оставляем только объявления с price_rub, кратным 10 000 ₽.
- Примеры:
    60 139 829  ❌  (не кратно 10 000 — мусор/бот)
    60 130 000  ✅
    60 100 000  ✅
    60 450 000  ✅
- Порядок объявлений сохраняется (такой же, как в исходном файле).
- По умолчанию читает all_advs.json и пишет filtered_advs.json рядом.

Использование:
    python filter_advs.py
    python filter_advs.py --input all_advs.json --output filtered_advs.json
    python filter_advs.py --step 10000          # шаг округления, по умолчанию 10 000
"""

import argparse
import json
from collections import Counter
from pathlib import Path


DEFAULT_INPUT = Path(__file__).parent / "all_advs.json"
DEFAULT_OUTPUT = Path(__file__).parent / "filtered_advs.json"
DEFAULT_STEP = 10_000


def is_round_price(price, step: int) -> bool:
    """True, если price — положительное число, кратное step."""
    if price is None:
        return False
    try:
        value = float(price)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if value != int(value):
        return False
    return int(value) % step == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Фильтр объявлений по круглой цене (кратной N ₽).",
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help=f"Входной JSON (по умолчанию: {DEFAULT_INPUT.name})",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Выходной JSON (по умолчанию: {DEFAULT_OUTPUT.name})",
    )
    parser.add_argument(
        "--step", type=int, default=DEFAULT_STEP,
        help=f"Шаг округления в рублях (по умолчанию: {DEFAULT_STEP})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Читаю {args.input}...")
    with args.input.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    if not isinstance(data, list):
        raise ValueError(
            f"Ожидался JSON-массив на верхнем уровне, получен {type(data).__name__}"
        )

    total = len(data)
    print(f"Всего объявлений: {total}")
    print(f"Условие: price_rub кратно {args.step:,} ₽".replace(",", " "))

    kept: list[dict] = []
    reasons = Counter()

    for item in data:
        price = item.get("price_rub") if isinstance(item, dict) else None
        if price is None:
            reasons["без price_rub"] += 1
            continue
        if is_round_price(price, args.step):
            kept.append(item)
        else:
            reasons["некруглая цена"] += 1

    print("\n=== Итоги фильтрации ===")
    print(f"  Оставлено:   {len(kept):>7} ({len(kept) / total:.1%})")
    print(f"  Отброшено:   {total - len(kept):>7} ({(total - len(kept)) / total:.1%})")
    for reason, count in reasons.most_common():
        print(f"    - {reason}: {count}")

    print(f"\nСохраняю в {args.output}...")
    with args.output.open("w", encoding="utf-8") as fp:
        json.dump(kept, fp, ensure_ascii=False, indent=2)

    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Готово! Размер файла: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
