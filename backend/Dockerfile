FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends unixodbc \
    && rm -rf /var/lib/apt/lists/*

COPY platform-contracts /deps/platform-contracts
COPY platform-db /deps/platform-db
COPY backend /app/backend

RUN pip install --no-cache-dir /deps/platform-contracts /deps/platform-db \
    && pip install --no-cache-dir /app/backend

ENV API_HOST=0.0.0.0
ENV API_PORT=7812
ENV DATABASE_URL=postgresql+psycopg://constructor:constructor@postgres:5432/constructor
ENV USE_STUBS=true
ENV AUTH_STUB=true

EXPOSE 7812
CMD ["python", "-m", "app.main"]
