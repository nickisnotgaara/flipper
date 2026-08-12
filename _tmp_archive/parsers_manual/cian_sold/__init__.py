"""services.parsers.cian_sold - парсер снятых публикаций CIAN (deactivated_offers).

Структура:
    acquirer/       — модули парсера: clients, config, runner, pipeline, ...
                     (запускается как `python -m services.parsers.cian_sold.acquirer`)
    main.py         — оркестратор: acquirer → importer.py → БД
    importer.py     — маппинг result.jsonl → houses + sold_ads (DB)
    requirements.txt
    Dockerfile
"""
