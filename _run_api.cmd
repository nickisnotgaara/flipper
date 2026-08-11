@echo off
set PYTHONPATH=C:\Users\User\Desktop\flipping\flipper
cd /d C:\Users\User\Desktop\flipping\flipper
set DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
set POSTGRES_PASSWORD=flipper_secret
set CORS_ORIGINS=*
set FIRECRAWL_API_KEY=local
set FIRECRAWL_BASE_URL=http://flippercrawl-api-1:3002
set SPREADSHEET_ID=1ngL69G7WqYcQxeLKQrmVrNoYF-juo4bAkvz81fO7NB0
set TG_BOT_TOKEN=8663326200:AAFgTdFRQhWZV58XGnrCZKb4MFzvqSxNdV4
set TG_CHAT_ID=6089511983
set COOKIE_MANAGER_URL=http://cookie_manager:8000
set COOKIE_CHECK_INTERVAL=1800
set PARSER_CONCURRENCY=50
set HTML_TO_MARKDOWN_URL=http://html_to_markdown:8080
py -3.11 -m uvicorn web.server:app --host 127.0.0.1 --port 8001 --log-level info > C:\Users\User\Desktop\flipping\flipper\_tmp_api.log 2>&1
