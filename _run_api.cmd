@echo off
REM ============================================================
REM _run_api.cmd — запуск FastAPI бэкенда нативно на Windows.
REM
REM Используется в dev. Для prod — Docker (см. DEPLOY.md).
REM Загружает .env (через Python ниже), затем поднимает uvicorn.
REM ============================================================
set PYTHONPATH=C:\Users\User\Desktop\flipping\flipper
cd /d C:\Users\User\Desktop\flipping\flipper

REM Жёстко зашитые переменные для dev (override .env)
set DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
set POSTGRES_PASSWORD=flipper_secret
set CORS_ORIGINS=*

REM Flippercrawl — если поднят локально (не Docker)
set FLIPPERCRAWL_API_KEY=local
set FLIPPERCRAWL_BASE_URL=http://127.0.0.1:3002

REM Grist (replaces Google Sheets). Doc `Parcing` с 10 таблицами.
set GRIST_API_KEY=flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978
set GRIST_BASE=http://localhost:8484
set GRIST_DOC=mDaHoGD6yahtxaqugwr5mK

REM Telegram (уведомления парсера)
set TG_BOT_TOKEN=8663326200:AAFgTdFRQhWZV58XGnrCZKb4MFzvqSxNdV4
set TG_CHAT_ID=6089511983

REM Parser infra (опционально, только если поднят Docker)
set COOKIE_MANAGER_URL=http://127.0.0.1:8000
set COOKIE_CHECK_INTERVAL=1800
set PARSER_CONCURRENCY=50
set HTML_TO_MARKDOWN_URL=http://127.0.0.1:8090

py -3.11 -m uvicorn web.server:app --host 127.0.0.1 --port 8001 --log-level info > C:\Users\User\Desktop\flipping\flipper\_tmp_api.log 2>&1
