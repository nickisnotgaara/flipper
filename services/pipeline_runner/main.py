"""services.pipeline_runner.main — ежедневный pipeline-runner.

Тонкая обёртка вокруг scripts/run_pipeline.py --fetch-missing, чтобы
scheduler мог его дёргать через `docker compose run --rm pipeline_runner`.
Сам по себе — просто запускает подпроцесс, логирует в data/logs/ и
записывает в таблицу pipeline_runs (для health-check).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

LOG_FILE = os.getenv("PIPELINE_LOG_FILE", "/app/data/logs/pipeline.log")
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
DB_URL = os.getenv("DATABASE_URL", "")


def _setup_logging() -> logging.Logger:
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"),
    ]
    logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format=fmt, handlers=handlers, force=True)
    return logging.getLogger("pipeline_runner")


def _record_run(started_at: datetime, finished_at: datetime, status: str, details: str) -> None:
    """Записать запись о прогоне в таблицу pipeline_runs (для health-check)."""
    if not DB_URL:
        return
    try:
        import asyncio
        import asyncpg

        async def _go():
            dsn = DB_URL.replace("postgresql+asyncpg://", "postgresql://", 1) if DB_URL.startswith("postgresql+asyncpg://") else DB_URL
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS pipeline_runs (
                        id           BIGSERIAL PRIMARY KEY,
                        source       TEXT NOT NULL,
                        started_at   TIMESTAMPTZ NOT NULL,
                        finished_at  TIMESTAMPTZ,
                        status       TEXT NOT NULL,
                        details      TEXT
                    )
                """)
                await conn.execute(
                    """
                    INSERT INTO pipeline_runs (source, started_at, finished_at, status, details)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    "cian_active", started_at, finished_at, status, details[:4000],
                )
            finally:
                await conn.close()
        asyncio.run(_go())
    except Exception as exc:
        log.warning("Не удалось записать pipeline_runs: %s", exc)


log = _setup_logging()


def main() -> int:
    started = datetime.now(timezone.utc)
    log.info("===== pipeline_runner START at %s =====", started.isoformat())
    # Запускаем реальный pipeline. По умолчанию — fetch-missing (полный прогон)
    # всех активных объявлений; опционально через env PIPELINE_MODE=recent N
    # или =ids FILE для ад--hoc прогонов.
    mode = os.getenv("PIPELINE_MODE", "fetch-missing")
    args = [sys.executable, "scripts/run_pipeline.py", "--source", "cian_active"]
    if mode == "fetch-missing":
        args.append("--fetch-missing")
    elif mode == "recent":
        n = int(os.getenv("PIPELINE_RECENT_N", "100"))
        args += ["--recent", str(n)]
    elif mode == "ids":
        ids_file = os.getenv("PIPELINE_IDS_FILE", "")
        if not ids_file:
            log.error("PIPELINE_MODE=ids но PIPELINE_IDS_FILE не задан")
            return 2
        args += ["--from-links", ids_file]
    else:
        log.error("Unknown PIPELINE_MODE=%s", mode)
        return 2

    log.info("CMD: %s", " ".join(args))
    t0 = time.monotonic()
    code = subprocess.call(args, cwd=str(ROOT))
    elapsed = time.monotonic() - t0
    status = "OK" if code == 0 else "FAILED"
    finished = datetime.now(timezone.utc)
    details = f"elapsed_s={elapsed:.1f}, mode={mode}, code={code}"
    _record_run(started, finished, status, details)
    log.info("===== pipeline_runner END at %s (%s, code=%d, %.1fs) =====",
             finished.isoformat(), status, code, elapsed)
    return code


if __name__ == "__main__":
    sys.exit(main())
