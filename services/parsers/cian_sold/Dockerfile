FROM python:3.11-slim

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Зависимости
COPY services/parsers/cian_sold/requirements.txt ./services/parsers/cian_sold/requirements.txt
RUN pip install --no-cache-dir -r services/parsers/cian_sold/requirements.txt

# Общие пакеты
COPY packages/ ./packages/

# Код парсера
COPY services/parsers/ ./services/parsers/

# Корень проекта + parsers в PYTHONPATH
ENV PYTHONPATH="/app:/app/services"

# ENTRYPOINT: docker compose run --rm cian_sold [-- ...]
ENTRYPOINT ["python", "-m", "services.parsers.cian_sold.main"]
