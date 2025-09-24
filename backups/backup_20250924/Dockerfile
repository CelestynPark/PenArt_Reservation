# syntax=docker/dockerfile:1

##########
# Builder
##########
FROM python:3.11-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m pip install --upgrade pip wheel && \
    pip wheel --wheel-dir=/wheels -r requirements.txt

##########
# Runtime
##########
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Seoul \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DEFAULT_LANG=ko \
    ORDER_EXPIRE_HOURS=48 \
    INVENTORY_POLICY=hold
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata ca-certificates curl \
    libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*
RUN addgroup --system --gid 10001 penart && adduser --system --uid 10001 --ingroup penart penart
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

# App files (minimal, only what runtime needs)
COPY gunicorn.conf.py ./gunicorn.conf.py
COPY requirements.txt ./requirements.txt
COPY app ./app
COPY openapi ./openapi
COPY docs ./docs
COPY public ./public
COPY scripts ./scripts

# Folders for runtime writes (uploads/logs)
RUN mkdir -p /app/uploads /app/logs && chown -R penart:penart /app
USER penart

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]