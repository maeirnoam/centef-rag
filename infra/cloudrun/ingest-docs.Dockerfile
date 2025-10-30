# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# PyMuPDF dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY apps/ingest_docs/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY apps/ingest_docs /app/apps/ingest_docs

ENV HOST=0.0.0.0 PORT=8080
CMD ["uvicorn", "apps.ingest_docs.main:app", "--host", "0.0.0.0", "--port", "8080"]
