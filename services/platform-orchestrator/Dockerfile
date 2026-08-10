FROM python:3.12-slim

WORKDIR /app

COPY platform-contracts /deps/platform-contracts
COPY platform-db /deps/platform-db
COPY services/platform-orchestrator /app/service

RUN pip install --no-cache-dir /deps/platform-contracts /deps/platform-db \
    && pip install --no-cache-dir /app/service

ENV DATABASE_URL=postgresql+psycopg://constructor:constructor@postgres:5432/constructor
ENV CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
ENV API_PORT=7825
ENV USE_STUBS=true

EXPOSE 7825
CMD ["python", "-m", "platform_orchestrator.api_main"]
