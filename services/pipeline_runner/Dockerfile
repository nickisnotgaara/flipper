FROM python:3.11-slim

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Сначала requirements (для кеша слоёв Docker)
COPY services/pipeline_runner/requirements.txt ./services/pipeline_runner/requirements.txt
RUN pip install --no-cache-dir -r services/pipeline_runner/requirements.txt

# Копируем нужные пакеты
COPY packages/ ./packages/
COPY services/pipeline_runner/ ./services/pipeline_runner/
# scripts/run_pipeline.py зависит от services.parsers.* — копируем всю services/
COPY services/ ./services/

# PYTHONPATH — чтобы `scripts/run_pipeline.py` находил packages и services
ENV PYTHONPATH="/app:/app/services:/app/services/parsers"

ENTRYPOINT ["python", "-m", "services.pipeline_runner.main"]
