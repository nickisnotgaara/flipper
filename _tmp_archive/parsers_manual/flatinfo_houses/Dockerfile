FROM python:3.11-slim

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

COPY services/parsers/flatinfo_houses/requirements.txt ./services/parsers/flatinfo_houses/requirements.txt
RUN pip install --no-cache-dir -r services/parsers/flatinfo_houses/requirements.txt

COPY packages/ ./packages/
COPY services/parsers/ ./services/parsers/

ENV PYTHONPATH="/app:/app/services"

ENTRYPOINT ["python", "-m", "services.parsers.flatinfo_houses.main"]
