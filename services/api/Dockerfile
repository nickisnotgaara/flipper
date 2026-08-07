# Production Dockerfile for the FastAPI backend (web/server.py).
#
# Раньше api жил в `docker compose --profile dev up` с uvicorn --reload.
# Теперь api — always-on сервис: gunicorn + uvicorn workers, без --reload.
# Dev-вариант (с --reload и volume-монтированием) переехал в Dockerfile.dev
# и поднимается через `docker compose --profile dev up -d api-dev`.
#
# Build context — корень flipper/ (как у остальных сервисов).
FROM python:3.11-slim

ENV TZ=Europe/Moscow
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app"
ENV WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"
ENV GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-60}"
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Системные зависимости (curl нужен для healthcheck в compose)
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Python deps — отдельным слоем для кеша
COPY services/api/requirements.txt ./services/api/requirements.txt
RUN pip install --no-cache-dir -r services/api/requirements.txt \
 && pip install --no-cache-dir "gunicorn>=21.2"

# Код — копируется в образ, монтирования на проде не нужны
COPY packages/ ./packages/
COPY web/ ./web/
COPY services/ ./services/

EXPOSE 8000

# gunicorn с uvicorn-классами: WEB_CONCURRENCY воркеров, --timeout для
# долгих /api/clusters запросов. --access-logfile - пишет в stdout,
# чтобы docker logs нормально работал.
CMD ["sh", "-c", "gunicorn web.server:app \
  --bind 0.0.0.0:8000 \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers ${WEB_CONCURRENCY} \
  --timeout ${GUNICORN_TIMEOUT} \
  --access-logfile - \
  --error-logfile -"]
