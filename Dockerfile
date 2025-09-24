# Flask + Gunicorn runtime image with reproducible layers and non-root execution.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/app/.local/bin:${PATH}"

# System deps (ssl/zlib for pymongo+gunicorn), tini for signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libc6-dev libssl-dev libffi-dev zlib1g-dev \
    curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 10001 -s /bin/bash app

WORKDIR /app

# Leverage layer cache: install deps first
COPY requirements.txt /app/requirements.txt
RUN pip install --user -r /app/requirements.txt

# Copy app source (only what we need at runtime)
COPY app /app/app
COPY scripts /app/scripts
COPY openapi /app/openapi
COPY app/templates /app/app/templates

# Optional static (served by Nginx via volume; keep as fallback)
COPY static /app/static

# Entrypoint script
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    'umask 027' \
    '# Best-effort indexes init (Replica Set required). Non-fatal on error.' \
    'if [ -f /app/scripts/create_indexes.py ]; then' \
    '  python -m scripts.create_indexes || python /app/scripts/create_indexes.py || true' \
    'fi' \
    'exec /usr/bin/tini -- gunicorn -b 0.0.0.0:8000 \'app:create_app()\' \'--workers=${GUNICORN_WORKERS:-2}\' \'--threads=${GUNICORN_THREADS:-4}\' \'--timeout=${GUNICORN_TIMEOUT:-60}\' --access-logfile - --error-logfile -' \
    > /app/entrypoint.sh \
    && chmod +x /app/entrypoint.sh \
    && chown -R app:app /app

USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
