FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY tools ./tools

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]
