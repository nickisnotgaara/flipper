"""scripts/link_cian_active_to_houses - привязать cian_active объявления к домам (flatinfo).

В active_ads нет cian_house_id, поэтому матчим по адресу.

Адрес из cian: "Москва, ВАО, р-н Соколиная гора, ул. Ибрагимова, 5А"
Адрес из flatinfo: street="...", house_num="д.3"  -> собираем ключ

Стратегия:
  1. Нормализуем обе стороны: убираем префиксы (ул., пер., пр-т, б-р, д., корп., стр., к.),
     lower-case, убираем лишние пробелы.
  2. Точное совпадение по (street_norm, house_num_norm).
  3. Если несколько домов на ключ — НЕ линкуем (чтобы не было ложных срабатываний).
  4. Если один — линкуем.

Идемпотентен: UPDATE WHERE house_id IS NULL.
"""
import argparse
import asyncio
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from packages.flipper_db import init_engine, get_session_factory

logger = logging.getLogger("link_cian_active_to_houses")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Префиксы/суффиксы типов улиц: могут стоять И в начале, И в конце.
STREET_TYPE_LEAD = re.compile(
    r"^(ул\.?|улица|пр-т\.?|проспект|просп\.?|пер\.?|переулок|"
    r"б-р\.?|бульвар|ш\.?|шоссе|наб\.?|набережная|пл\.?|площадь|"
    r"аллея|проезд|тупик|кв-л\.?|квартал)\s+",
    re.IGNORECASE,
)
STREET_TYPE_TRAIL = re.compile(
    r"\s+(ул\.?|улица|пр-т\.?|проспект|просп\.?|пер\.?|переулок|"
    r"б-р\.?|бульвар|ш\.?|шоссе|наб\.?|набережная|пл\.?|площадь|"
    r"аллея|проезд|тупик|кв-л\.?|квартал)\.?$",
    re.IGNORECASE,
)
# Префикс района: "р-н Бибирево"
DISTRICT_RE = re.compile(r"^р-н\s+\S+", re.IGNORECASE)
# Префиксы номера дома: д., дом, корп., корпус, стр., строение, к., к.
HOUSE_PREFIX_RE = re.compile(
    r"^(д\.?|дом|корп\.?|корпус|стр\.?|строение|к\.?|к)\s*",
    re.IGNORECASE,
)
# Округа: ЦАО, САО, СВАО, ЗАО, ЮЗАО, ЮАО, ЮВАО, ВАО, СЗАО, ЗелАО, ТиНАО
# (2-5 букв рус. алфавита, заглавные, опционально с цифрами)
OKRUG_RE = re.compile(r"^[А-ЯЁA-Z]{2,5}$")
# "Москва" (city)
CITY_RE = re.compile(r"^москва$", re.IGNORECASE)


def norm_street(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    s = STREET_TYPE_LEAD.sub("", s)
    s = STREET_TYPE_TRAIL.sub("", s)
    return s.lower().strip()


def norm_house(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    # может быть "корпус 2" — вытащим в "к2"
    m = HOUSE_PREFIX_RE.match(s)
    if m:
        s = s[m.end():]
    return s.lower().strip()


def parse_cian_address(full: str) -> tuple[str | None, str | None]:
    """Распарсить cian-адрес в (street_norm, house_norm).

    Примеры:
      'Москва, ВАО, р-н Соколиная гора, ул. Ибрагимова, 5А'
        -> ('ибрагимова', '5а')
      'Москва, СВАО, р-н Бибирево, ул. Коненкова'  (без дома)
        -> ('коненкова', None)
      'Москва, Челобитьевское шоссе, дом 14, корпус 2'
        -> ('челобитьевское', '2')  # "дом 14" — это и есть ул., а корпус 2 — body
    """
    if not full:
        return None, None
    parts = [p.strip() for p in full.split(",") if p.strip()]

    # Отфильтровать служебные компоненты
    keep = []
    for p in parts:
        if CITY_RE.match(p):
            continue
        if OKRUG_RE.match(p):
            continue
        if DISTRICT_RE.match(p):
            continue
        keep.append(p)

    if not keep:
        return None, None

    # Спец-кейс: "Челобитьевское шоссе, дом 14, корпус 2"
    # Здесь "Челобитьевское шоссе" — это ул., "дом 14" — это 14,
    # "корпус 2" — корпус 2.
    # Если последняя часть — "корпус N" / "стр. N" / "к. N" и предпоследняя
    # — "дом N" / "д. N", то это сложный адрес: улица = keep[0], корпус = keep[-1].
    if len(keep) >= 3:
        last = keep[-1].lower()
        prev = keep[-2].lower()
        if re.match(r"^(корпус|корп\.?|стр\.?|строение|к\.?)\s*\d+", last):
            # корпус последним — берём его как house_num (если он непустой)
            house_raw = last
            street_raw = keep[0]
            # "дом 14" в середине игнорируем — мы не различаем "14" и "14 корпус 2",
            # ищем просто по корпусу.
            return norm_street(street_raw) or None, norm_house(house_raw) or None

    # Обычный случай: keep[-2] = улица, keep[-1] = дом
    if len(keep) < 2:
        # Только улица, без дома — не матчим
        return norm_street(keep[0]) if keep else None, None

    street_raw = keep[-2]
    house_raw = keep[-1]
    street = norm_street(street_raw)
    house = norm_house(house_raw)
    return street or None, house or None


async def main(dry_run: bool = False, apply: bool = True):
    init_engine("postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper")
    sf = get_session_factory()

    async with sf() as s:
        # 1. Все дома flatinfo с адресом -> (street_norm, house_norm) -> [(id, cian_house_id)]
        logger.info("Загружаем дома flatinfo ...")
        houses = (await s.execute(text("""
            SELECT id, cian_house_id, street, house_num
            FROM houses WHERE source='flatinfo';
        """))).all()
        logger.info(f"Домов flatinfo: {len(houses):,}")

        house_index: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for hid, hcian, street, hnum in houses:
            if not street or not hnum:
                continue
            street_n = norm_street(street)
            hnum_n = norm_house(hnum)
            if not street_n or not hnum_n:
                continue
            house_index[(street_n, hnum_n)].append((hid, hcian))
        logger.info(f"Уникальных ключей (street, house): {len(house_index):,}")
        collisions = sum(1 for v in house_index.values() if len(v) > 1)
        logger.info(f"  из них с >1 домом (collisions): {collisions:,}")

        # 2. Все unlinked cian_active с адресом
        ads = (await s.execute(text("""
            SELECT id, cian_id, raw_data->'address'->>'full' AS full_addr
            FROM active_ads
            WHERE source='cian_active'
              AND house_id IS NULL
              AND raw_data->'address'->>'full' IS NOT NULL;
        """))).all()
        logger.info(f"cian_active без привязки: {len(ads):,}")

        # 3. Матчинг
        updates = []  # [(ad_id, house_id, cian_house_id, cian_id, full_addr)]
        skipped_no_key = 0
        skipped_collision = 0
        for ad_id, cian_id, full_addr in ads:
            street_n, hnum_n = parse_cian_address(full_addr)
            if not street_n or not hnum_n:
                skipped_no_key += 1
                continue
            cands = house_index.get((street_n, hnum_n))
            if not cands:
                continue
            if len(cands) > 1:
                skipped_collision += 1
                continue
            hid, hcian = cands[0]
            updates.append((ad_id, hid, hcian, cian_id, full_addr))

        logger.info(f"Однозначных матчей: {len(updates):,}")
        logger.info(f"  без ключа (нет улицы/дома): {skipped_no_key:,}")
        logger.info(f"  с коллизией (>1 дома): {skipped_collision:,}")
        if updates:
            logger.info("Примеры матчей:")
            for _, _, _, cid, fa in updates[:5]:
                logger.info(f"  cian_id={cid} '{fa}'")
            if len(updates) > 5:
                logger.info(f"  ... +{len(updates) - 5} more")

        if not apply:
            logger.info("DRY RUN — обновления не применены")
            return

        # 4. UPDATE batch
        start = time.time()
        batch_size = 500
        n_updated = 0
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            values_sql = ",".join(
                f"({ad_id}, {hid}, {hcian})"
                for ad_id, hid, hcian, _, _ in batch
            )
            result = await s.execute(text(f"""
                UPDATE active_ads
                SET house_id = v.hid,
                    cian_house_id = v.hcian
                FROM (VALUES {values_sql}) AS v(aid, hid, hcian)
                WHERE active_ads.id = v.aid
                  AND active_ads.house_id IS NULL;
            """))
            await s.commit()
            n_updated += result.rowcount

        logger.info(f"UPDATE: {n_updated:,} строк за {time.time() - start:.1f}s")

        # 5. Финальная статистика
        row = (await s.execute(text("""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE house_id IS NOT NULL) AS linked
            FROM active_ads WHERE source='cian_active';
        """))).first()
        pct = 100 * row.linked / row.total if row.total else 0
        logger.info(f"=== Итог ===")
        logger.info(f"  всего: {row.total:,}")
        logger.info(f"  привязано: {row.linked:,} ({pct:.1f}%)")
        logger.info(f"  без привязки: {row.total - row.linked:,}")


def main_entry():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="только посчитать, не UPDATE")
    p.add_argument("--no-apply", action="store_true", help="алиас для --dry-run")
    args = p.parse_args()
    asyncio.run(main(dry_run=args.dry_run or args.no_apply, apply=not (args.dry_run or args.no_apply)))


if __name__ == "__main__":
    main_entry()
