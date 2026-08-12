# parsers_manual — архив ручных парсеров

Здесь лежат **разовые** парсеры, которые больше не запускаются в проде автоматически,
но могут пригодиться для исторических выгрузок или одноразовых прогонов.

## Что здесь

| Парсер | Что делал | Заменён на |
|---|---|---|
| [`cian_sold/`](cian_sold/) | Снятые объявления CIAN (этапы 1+2: API + детальный парсинг HTML → Excel) | `services/parsers/domclick_sold/` (активный) |

`flatinfo_houses/` и `winners_sold/` тоже были тут, но окончательно удалены
в коммите `74fc57f` вместе со всем `_tmp_archive/` (см. deep cleanup `6d75153`).
Их можно поднять из git истории при необходимости:
```bash
git checkout 7dbbf4a -- _tmp_archive/parsers_manual/flatinfo_houses
git checkout 7dbbf4a -- _tmp_archive/parsers_manual/winners_sold
```

## Как запустить ручной парсер

`cian_sold` живёт в Docker-профиле **manual** (выключен по умолчанию).
Запуск:

```bash
# С Docker (рекомендуется)
docker compose --profile manual run --rm cian_active --mode offers

# Нативно (с vendored cianparser в PYTHONPATH)
_run_parser.cmd
py -3.11 -m services.parsers.cian_sold.main
```

## Зачем вообще оставили cian_sold

- Снятые объявления CIAN исторически были основным источником для аналитики.
- Сейчас эту роль играет **domclick_sold** (см. `services/parsers/domclick_sold/`).
- `cian_sold` остаётся здесь как fallback / для повторных выгрузок прошлых лет,
  когда API Cian был доступен без строгого cookie-челледжа.

## Что НЕ нужно делать

- **Не возвращать в прод-расписание.** Scheduler в `services/scheduler/main.py`
  настроен только на `cian_active` + `domclick_sold`.
- **Не добавлять в docker-compose как обычный сервис.** Это manual-профиль,
  поднимается через `docker compose --profile manual run`.
