"""services.parsers - парсеры проекта Flipper.

Активные (автоматически по расписанию):
    cian_active/        — активные CIAN (через Flippercrawl). Scheduler: ежедневно 10:00, 18:00.
    domclick_sold/      — снятые domclick.ru. Scheduler: еженедельно Sun 07:00.

Заархивированные (запускаются вручную при необходимости):
    flatinfo_houses/    — реестр домов flatinfo.ru     → _tmp_archive/parsers_manual/
    winners_sold/       — снятые baza-winner.ru          → _tmp_archive/parsers_manual/
    cian_sold/          — снятые публикации CIAN         → _tmp_archive/parsers_manual/
    См. _tmp_archive/parsers_manual/README.md для инструкции по ручному запуску.

Общий код — в `services/parsers/_common.py`.
"""
