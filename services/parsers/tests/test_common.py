"""Тесты общего кода парсеров."""

import logging

from services.parsers._common import (
    run_subprocess,
    safe_float,
    safe_int,
    safe_str,
    setup_logging,
)


# ============================================================ setup_logging

def test_setup_logging_returns_logger():
    log = setup_logging("test_parser")
    assert isinstance(log, logging.Logger)
    assert log.name == "test_parser"


def test_setup_logging_idempotent():
    """Повторный вызов не дублирует handlers."""
    log1 = setup_logging("test_parser_2")
    h1 = len(logging.getLogger().handlers)
    log2 = setup_logging("test_parser_2")
    h2 = len(logging.getLogger().handlers)
    assert h1 == h2, f"setup_logging добавил handlers при повторном вызове ({h1} → {h2})"


def test_setup_logging_creates_log_file(tmp_path, monkeypatch):
    """setup_logging создаёт файл лога (через монтированный volume)."""
    # Подменяем LOG_DIR на временную папку
    import services.parsers._common as common
    monkeypatch.setattr(common, "LOG_DIR", str(tmp_path))

    log = setup_logging("test_log_file_creation")

    log.info("hello test")

    # Проверяем что файл создан
    log_file = tmp_path / "test_log_file_creation.log"
    assert log_file.exists()


# ============================================================ run_subprocess

def test_run_subprocess_success():
    """Успешный процесс → rc=0."""
    code = run_subprocess(["-c", "print('hi')"])
    assert code == 0


def test_run_subprocess_failure():
    """Падающий процесс → rc != 0."""
    code = run_subprocess(["-c", "import sys; sys.exit(42)"])
    assert code == 42


def test_run_subprocess_with_cwd(tmp_path):
    """cwd применяется корректно."""
    code = run_subprocess(["-c", "import os; print(os.getcwd())"], cwd=tmp_path)
    assert code == 0


# ============================================================ safe_int

def test_safe_int():
    assert safe_int("123") == 123
    assert safe_int(456) == 456
    assert safe_int(None) is None
    assert safe_int("abc") is None
    assert safe_int(None, default=0) == 0
    assert safe_int("abc", default=-1) == -1


# ============================================================ safe_float

def test_safe_float():
    assert safe_float("1.5") == 1.5
    assert safe_float("1,5") == 1.5  # RU comma
    assert safe_float(2) == 2.0
    assert safe_float(None) is None
    assert safe_float("abc") is None
    assert safe_float("abc", default=0.0) == 0.0


# ============================================================ safe_str

def test_safe_str():
    assert safe_str("hello") == "hello"
    assert safe_str("  trim me  ") == "trim me"
    assert safe_str("") is None
    assert safe_str(None) is None
    assert safe_str(None, default="fb") == "fb"
    assert safe_str(123) == "123"
