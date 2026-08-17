FROM python:3.12-slim

WORKDIR /app

COPY platform-contracts /deps/platform-contracts
COPY platform-db /deps/platform-db
COPY services/platform-kpi /app/service

RUN pip install --no-cache-dir /deps/platform-contracts /deps/platform-db \
    && pip install --no-cache-dir /app/service

ENV DATABASE_URL=postgresql+psycopg://constructor:constructor@postgres:5432/constructor
ENV API_PORT=7820

EXPOSE 7820
CMD ["python", "-m", "platform_kpi.main"]
