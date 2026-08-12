@echo off
REM ============================================================
REM _run_parser.cmd — запуск парсера cian_active нативно на Windows.
REM
REM Используется в dev для прогона парсера. Переопределяет Docker-DNS
REM имена на localhost (cookie_manager, html_to_markdown, flippercrawl).
REM ============================================================
set PYTHONPATH=C:\Users\User\Desktop\flipping\flipper;C:\Users\User\Desktop\flipping\flipper\services\parsers\cian_active\cianparser
cd /d C:\Users\User\Desktop\flipping\flipper

REM Жёстко зашитые переменные для dev (override .env)
set DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
set POSTGRES_PASSWORD=flipper_secret

REM Flippercrawl — локально (не Docker)
set FLIPPERCRAWL_API_KEY=local
set FLIPPERCRAWL_BASE_URL=http://127.0.0.1:3002

REM Grist
set GRIST_API_KEY=flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978
set GRIST_BASE=http://localhost:8484
set GRIST_DOC=mDaHoGD6yahtxaqugwr5mK

REM Telegram
set TG_BOT_TOKEN=8612305452:AAEpWGzmlAeEY0q1LyxmzjEFmKr4-uQzmCo
set TG_CHAT_ID=6089511983

REM Parser infra
set COOKIE_MANAGER_URL=http://127.0.0.1:8000
set COOKIE_CHECK_INTERVAL=1800
set PARSER_CONCURRENCY=50
set HTML_TO_MARKDOWN_URL=http://127.0.0.1:8090

REM Аргументы: --mode [offers|avans] --skip-links | --only-links | --unparsed-only
REM По умолчанию: offers + --skip-links (парсим то, что в БД)
py -3.11 services\parsers\cian_active\main.py %*
