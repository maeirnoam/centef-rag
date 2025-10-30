# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY apps/ingest_av/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY apps/ingest_av /app/apps/ingest_av

ENV HOST=0.0.0.0 PORT=8080
CMD ["uvicorn", "apps.ingest_av.main:app", "--host", "0.0.0.0", "--port", "8080"]
