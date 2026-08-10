FROM python:3.12-slim

WORKDIR /app

COPY platform-contracts /deps/platform-contracts
COPY platform-db /deps/platform-db
COPY platform-service-common /deps/platform-service-common
COPY services/platform-tool-shell /app/service

RUN pip install --no-cache-dir /deps/platform-contracts /deps/platform-db /deps/platform-service-common \
    && pip install --no-cache-dir /app/service

ENV DATABASE_URL=postgresql+psycopg://constructor:constructor@postgres:5432/constructor
ENV API_PORT=7823
ENV USE_STUBS=true

EXPOSE 7823
CMD ["python", "-m", "platform_tool_shell.main"]
