FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends unixodbc unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY platform-contracts /deps/platform-contracts
COPY platform-db /deps/platform-db
COPY platform-service-common /deps/platform-service-common
COPY services/platform-tool-onec /app/service

RUN pip install --no-cache-dir /deps/platform-contracts /deps/platform-db /deps/platform-service-common \
    && pip install --no-cache-dir /app/service

ENV DATABASE_URL=postgresql+psycopg://constructor:constructor@postgres:5432/constructor
ENV API_PORT=7822
ENV USE_STUBS=true

EXPOSE 7822
CMD ["python", "-m", "platform_tool_onec.main"]
