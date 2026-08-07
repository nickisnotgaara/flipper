"""services.parsers.cian_active - парсер активных объявлений CIAN (через Firecrawl).

Структура:
    main.py          - оркестратор (запускает acquirer + пишет в БД)
    config.py        - настройки (Pydantic Settings, .env)
    acquirer/        - всё, что связано с самим парсингом:
        cards.py     - парсинг отдельных объявлений (Firecrawl, rawHtml, stats API)
        search.py    - парсинг поисковых страниц (через cianparser)
        queue.py     - параллельное выполнение с concurrency
        models.py    - Pydantic-модели (ParsedAdData, AddressInfo, ...)
        legacy_db/   - LEGACY DB layer (CianFilter/CianActiveAd/CianSoldAd);
                       в следующих итерациях заменяется на packages/flipper_db
    importer.py      - заглушка (см. PLAN.md — миграция в flipper_db)
    cianparser/      - встроенная библиотека парсинга страниц Cian
    Dockerfile
    requirements.txt
"""
