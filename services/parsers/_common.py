"""services.parsers._common - общий код для всех парсеров.

Каждый парсер использует:
    from services.parsers._common import setup_logging, run_subprocess
    from packages.flipper_db import init_db, FlipperRepository, Source

Имя модуля начинается с `_` — Python-конвенция "private module в пакете".
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _default_log_dir() -> Path:
    """OS-aware log dir.

    Приоритет:
      1. $FLIPPER_LOG_DIR (явный override)
      2. /app/data/logs — если мы в Docker-контейнере (Linux, /app существует)
      3. data/logs — относительный путь для native dev (Windows/локальный Linux)
    """
    env = os.getenv("FLIPPER_LOG_DIR")
    if env:
        return Path(env)
    if sys.platform != "win32" and Path("/app").is_dir():
        return Path("/app/data/logs")
    return Path("data/logs")


LOG_DIR = str(_default_log_dir())


def setup_logging(name: str, level: str | None = None) -> logging.Logger:
    """Стандартное логирование: stdout + rotating file.

    Args:
        name: имя логгера (обычно = имя парсера, например 'cian_active').
        level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' (default из LOG_LEVEL env, fallback 'INFO').

    Returns:
        Настроенный logger.
    """
    # Windows-консоль часто CP1251/CP866 — эмодзи/✓ вызывают UnicodeEncodeError.
    # Делаем поток "непадающим": неподдерживаемые символы будут экранироваться.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")  # type: ignore[attr-defined]
        except Exception:
            pass

    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    level_int = getattr(logging, level_name, logging.INFO)

    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    log_path = f"{LOG_DIR}/{name}.log"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        ),
    ]
    logging.basicConfig(
        level=level_int, format=LOG_FORMAT, handlers=handlers, force=True
    )
    return logging.getLogger(name)


async def run_subprocess(
    args: list[str],
    cwd: Optional[Path | str] = None,
    logger: Optional[logging.Logger] = None,
) -> int:
    """Запустить шаг парсинга через async subprocess, прокинуть exit code.

    Асинхронная обёртка над asyncio.create_subprocess_exec — НЕ блокирует
    event loop (в отличие от subprocess.call). Стандартный вывод подпроцесса
    прокидывается в родительский stdout/stderr (наследуется).

    Args:
        args: список аргументов (например, ['-m', 'services.parsers.domclick_sold.acquirer', '--output', ...]).
        cwd: рабочая директория (если None — текущая).
        logger: куда логировать (если None — берётся logger по имени 'subprocess').

    Returns:
        Exit code. 0 = успех, !=0 = ошибка.
    """
    log = logger or logging.getLogger("subprocess")
    cmd_str = " ".join(str(a) for a in args)
    log.info("RUN: %s (cwd=%s)", cmd_str, cwd or os.getcwd())
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        log.error("FAIL: %s — файл не найден: %s", cmd_str, exc)
        return 2
    # Стрим stdout подпроцесса в наш лог (по строкам).
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        try:
            log.info("  | %s", line.decode("utf-8", errors="replace").rstrip())
        except Exception:
            pass
    rc = await proc.wait()
    log.info("EXIT: %s → rc=%s", cmd_str, rc)
    return rc


def safe_int(value, default: int | None = None) -> int | None:
    """Безопасно привести к int. None на ошибке или default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float | None = None) -> float | None:
    """Безопасно привести к float. None на ошибке или default."""
    if value is None:
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def safe_str(value, default: str | None = None) -> str | None:
    """Безопасно привести к str. None → None, иначе stripped str."""
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default