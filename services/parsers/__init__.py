"""services.parsers - парсеры проекта Flipper.

Активные (автоматически по расписанию):
    cian_active/        — активные CIAN (через Flippercrawl). Scheduler: ежедневно 10:00, 18:00.
    domclick_sold/      — снятые domclick.ru. Scheduler: еженедельно Sun 07:00.

Заархивированные (только ручной запуск при необходимости):
    _tmp_archive/parsers_manual/cian_sold/ — снятые публикации CIAN (legacy, заменён на domclick_sold).
    flatinfo_houses/ и winners_sold/ — удалены в 6d75153 (deep cleanup),
        поднимаются из git: `git checkout 7dbbf4a -- _tmp_archive/parsers_manual/...`
    См. _tmp_archive/parsers_manual/README.md для инструкции по ручному запуску.

Общий код — в `services/parsers/_common.py`.
"""
