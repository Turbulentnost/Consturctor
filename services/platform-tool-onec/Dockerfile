FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg unixodbc unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
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
