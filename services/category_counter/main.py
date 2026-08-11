"""Main entry point for category counter service."""

import os
import sys
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from packages.flipper_core.grist import GristClient
from services.category_counter.parser import CategoryCounterParser

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def main():
    """Run category counter parser."""
    load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

    for key in ("DECODO_AUTH_TOKEN", "DECODO_SCRAPER_URL", "DECODO_MAX_RETRIES"):
        os.environ.pop(key, None)

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    rel = (os.environ.get("CIAN_PROXIES_FILE") or "data/proxies.txt").strip()
    proxy_path = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(root, rel))

    from packages.flipper_core.proxy_loader import load_proxy_urls

    proxy_urls = load_proxy_urls(proxy_path) if os.path.isfile(proxy_path) else []
    http_single = (os.environ.get("HTTP_PROXY") or "").strip() or None

    logger.info(
        "Starting category counter (file %s → %s прокси; HTTP_PROXY=%s)",
        proxy_path,
        len(proxy_urls),
        "да" if http_single else "нет",
    )
    parser = CategoryCounterParser(
        http_proxy=http_single if not proxy_urls else None,
        proxy_urls=proxy_urls if proxy_urls else None,
    )

    # Parse all categories
    logger.info("Parsing all categories...")
    results = parser.parse_all_categories()

    if not results:
        logger.error("Failed to parse categories")
        sys.exit(1)

    logger.info(f"Successfully parsed {len(results)} categories")

    # Initialize Grist client
    logger.info("Initializing Grist client...")
    grist = GristClient()

    # Write to Grist Balans
    logger.info("Writing results to Grist 'Balans' table...")
    success = write_to_grist(grist, results)

    if success:
        logger.info("✓ Successfully wrote results to Grist")
    else:
        logger.error("Failed to write results to Grist")
        sys.exit(1)


def write_to_grist(grist: GristClient, results: list) -> bool:
    """Write category counter results to Grist Balans table.

    Один раз в день (MSK): проверяем, есть ли уже строка за сегодня.
    Если есть — пропускаем (только актуальные данные, без дублей).
    """
    EQUILIBRIUM_VALUE = 150000

    try:
        msk_tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(msk_tz)
        datetime_str = now.strftime("%d.%m.%Y %H:%M:%S")
        today_prefix = now.strftime("%d.%m.%Y")  # DD.MM.YYYY — для матча

        logger.info(f"Current MSK time: {datetime_str}")

        # Дедуп: проверим, есть ли уже запись за сегодня (DD.MM.YYYY).
        # В Grist столбец A = DateTime:UTC. Достаём строки за последние 36 часов
        # и фильтруем Python-стороной.
        today_rows = grist.sql(
            "SELECT id, A FROM Balans "
            "WHERE A >= (now() - interval '36 hours')"
        )
        for r in today_rows:
            f = r.get("fields", {})
            a = f.get("A")
            if not a:
                continue
            # Grist возвращает DateTime:UTC как Unix-секунды. Конвертим обратно.
            try:
                ts = int(a)
                row_dt = datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(msk_tz)
                if row_dt.strftime("%d.%m.%Y") == today_prefix:
                    logger.info(
                        f"  Сегодня ({today_prefix}) уже записано: row_id={r.get('id')}. "
                        f"Пропускаем — только актуальные данные."
                    )
                    return True
            except (ValueError, TypeError, OSError):
                continue

        results_dict = {r["name"]: r["count"] for r in results}

        vtorichka_msk = int(results_dict.get("Вторичка Москва", 0) or 0)
        pervichka_msk = int(results_dict.get("Первичка Москва", 0) or 0)
        pervichka_mo = int(results_dict.get("Первичка МО", 0) or 0)
        vtorichka_mo = int(results_dict.get("Вторичка МО", 0) or 0)

        success = grist.add_balans_row(
            vtorichka_msk=vtorichka_msk,
            pervichka_msk=pervichka_msk,
            pervichka_mo=pervichka_mo,
            vtorichka_mo=vtorichka_mo,
            equilibrium=EQUILIBRIUM_VALUE,
        )

        if success:
            logger.info(f"  Дата:           {datetime_str}")
            logger.info(f"  Вторичка Мск:   {vtorichka_msk:,}")
            logger.info(f"  Первичка Мск:   {pervichka_msk:,}")
            logger.info(f"  Первичка МО:    {pervichka_mo:,}")
            logger.info(f"  Вторичка МО:    {vtorichka_mo:,}")
            total = vtorichka_msk + pervichka_msk + pervichka_mo + vtorichka_mo
            logger.info(f"  Всего:          {total:,}")

        return success

    except Exception as e:
        logger.error(f"Error writing to Grist: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    main()
