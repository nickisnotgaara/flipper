"""services.parsers.winners_sold - парсер baza-winner.ru (новостройки + вторичка).

Структура:
    acquirer.py    — основной скрипт парсинга (CLI: --category new|secondary)
    filters.py     — фильтр по круглой цене (опц., для Excel-выгрузки)
    exporter.py    — JSON → xlsx (опц.)
    importer.py    — маппинг JSON → houses + sold_ads (DB)
    main.py        — оркестратор
    requirements.txt
    Dockerfile
"""
