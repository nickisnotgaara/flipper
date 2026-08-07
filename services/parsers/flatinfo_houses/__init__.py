"""services.parsers.flatinfo_houses - парсер реестра домов flatinfo.ru.

Структура:
    houses.py             — фильтрация списка домов (утилита, не основной парсер)
    acquirer.py           — детальные страницы домов → house_pages_result.json
    houses_to_excel.py    — JSON → xlsx (утилита)
    exporter.py           — house_pages_result.json → xlsx
    importer.py           — маппинг house_pages_result.json → houses (только houses)
    main.py               — оркестратор
    requirements.txt
    Dockerfile
"""
