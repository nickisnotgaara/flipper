FROM python:3.11-slim

# Set timezone to Moscow
ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Устанавливаем рабочую директорию как корень проекта
WORKDIR /app

# Копируем и устанавливаем зависимости
COPY services/parsers/cian_active/requirements.txt ./services/parsers/cian_active/requirements.txt
RUN pip install --no-cache-dir -r services/parsers/cian_active/requirements.txt

# Копируем общие пакеты (ядро, БД) в корень контейнера
COPY packages/ ./packages/

# Копируем код парсера
COPY services/parsers/cian_active/ ./services/parsers/cian_active/

# Корень проекта + parsers + cianparser (встроенный) в пути поиска Python
ENV PYTHONPATH="/app:/app/services:/app/services/parsers/cian_active/cianparser"

# ENTRYPOINT: `docker compose run --rm cian_active --mode offers` прокидывает аргументы дальше
ENTRYPOINT ["python", "-m", "services.parsers.cian_active.main"]
