# `_tmp_archive/` — legacy-код, выведенный из активной разработки

> **Назначение:** хранить старый код, который больше не используется в проде,
> но может понадобиться для справки или отката. **Не импортируется.**
> Удалять не нужно — это живая документация прошлых решений.

## Что здесь

| Папка / файл              | Что внутри                                       | Почему в архиве                       |
|----------------------------|--------------------------------------------------|----------------------------------------|
| `parser_cian_legacy/`      | `services/parser_cian/` (13 файлов)              | Заменён на `services/parsers/cian_active/` (2026-07). Активный парсер — на Flippercrawl, не на прямом HTML. |
| `sheets_py_legacy.py`      | `packages/flipper_core/sheets.py` (39 KB)        | Заменён на `grist.py` (2026-08). Google Sheets заменён на Grist. |
| `filters_page/`            | `web/next/app/(dashboard)/filters/page.tsx`      | Удалён из Next.js — функциональность переехала в Grist (таблица `FILTERS`). |
| `pipeline_page/`          | `web/next/app/(dashboard)/pipeline/page.tsx`      | Удалён — не используется.            |
| `settings_page/`           | `web/next/app/(dashboard)/settings/page.tsx`     | Удалён — настройки живут в `.env`.    |
| `test_parser_cian_legacy/` | `tests/parser_cian/`                             | Удалён — относился к старому парсеру. |

## Правила

- **Не импортируй** файлы отсюда в production-коде. `pyproject.toml`
  `tool.ruff.exclude` включает `_tmp_archive/`.
- **Не редактируй** — это snapshot. Если нужно обновить, лучше переписать в
  основном коде.
- **Можно удалить** целиком когда станет ясно что legacy-код больше не нужен.
  Ориентир: полгода без обращений к git history для отката = кандидат на удаление.
- **Если решил восстановить** — `cp -r _tmp_archive/parser_cian_legacy/ services/parser_cian/`
  и адаптируй импорты под текущий `packages/flipper_db/`.

## История

- **2026-07-30** — выделен `parser_cian_legacy/` при переходе на Flippercrawl.
- **2026-08-09** — добавлены `filters/pipeline/settings` pages (Sidebar → Grist).
- **2026-08-11** — добавлен `sheets_py_legacy.py` (Google Sheets → Grist миграция).
- **2026-08-11** — добавлен этот README.
