"""services.parsers.domclick_sold - парсер проданных объявлений domclick.ru (v2).

Структура (после v2-рефакторинга, 2026-08-05):
    acquirer.py         - BFF-сборщик ссылок (только list), вызывается из main.py
    main.py             - оркестратор v2 (тонкий wrapper, --mode {list,pipeline,backfill,full})
    requirements.txt    - зависимости (asyncpg, httpx)
    Dockerfile          - python -m services.parsers.domclick_sold.main
    domclick_links.json - transient артефакт: id + published_dt + soldDate из BFF
    offer-page.html     - fixture для unit-тестов
    offers.bash         - bash-примеры curl (reference, не используется в проде)

Парсинг карточек — через v2-инфраструктуру (packages/flipper_db/pipeline.py + sources/domclick.py).
Все данные пишутся напрямую в PostgreSQL (houses + sold_ads), БЕЗ промежуточных JSON-файлов.
Google Sheets / .xlsx НЕ используются (отказались).

Entry point: python -m services.parsers.domclick_sold.main [--mode ...]
"""
