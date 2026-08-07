"""Фикстуры для тестов scripts/.

Импортирует `repo` из packages/flipper_db/tests/conftest.py напрямую.
"""

import sys
from pathlib import Path

# Добавляем путь к packages/flipper_db/tests/ для прямого импорта
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "packages" / "flipper_db" / "tests"))

# Импортируем фикстуру напрямую
from conftest import repo  # type: ignore  # noqa: E402, F401
