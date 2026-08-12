"""services.parsers.cian_active.acquirer - парсер активных объявлений Cian.

Подмодули:
    cards.py     - парсинг отдельных объявлений через Flippercrawl (ранее parser.py)
    search.py    - парсинг поисковых страниц (ранее search_parser.py)
    queue.py     - параллельный запуск парсинга (ранее queue_manager.py)
    models.py    - Pydantic-модели (ParsedAdData и т.п.)
    legacy_db/   - legacy database layer (CianFilter/CianActiveAd/CianSoldAd) —
                   заменяется на packages/flipper_db в следующих итерациях
                   (см. PLAN.md).
"""
