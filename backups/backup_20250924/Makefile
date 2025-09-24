# Makefile - Pen Art (deploy-grade, cross-OS)

# Usage: make help

# --- OS detection ---
ifeq ($(OS),Windows_NT)
  IS_WIN := 1
else
  IS_WIN := 0
endif

# --- shell ---
ifeq ($(IS_WIN),1)
  SHELL := bash
else
  SHELL := /bin/bash
endif

# --- vars (per OS) ---
APP_NAME := penart
PORT ?= 8000
WSGI_APP ?= app:create_app()
LOG_DIR := logs
ENVFILE := .env

ifeq ($(IS_WIN),1)
  PY := python
  PIP := pip
  VENV := .venv
  ACTIVATE := $(VENV)/Scripts/activate
  ACT := source $(ACTIVATE)
  RUN_SERVE = $(ACT); exec waitress-serve --listen=0.0.0.0:$${PORT:-$(PORT)} "$(WSGI_APP)"
else
  PY := python3
  PIP := pip
  VENV := .venv
  ACTIVATE := $(VENV)/bin/activate
  ACT := source $(ACTIVATE)
  # 서비스 커맨드: 리눅스/맥은 gunicorn
  RUN_SERVE = $(ACT); exec gunicorn "$(WSGI_APP)" \
    --worker-class $${WORKER_CLASS:-gthread} \
    --workers $${WEB_CONCURRENCY:-3} \
    --threads $${THREADS:-4} \
    --bind 0.0.0.0:$${PORT:-$(PORT)} \
    --timeout $${GUNICORN_TIMEOUT:-60} \
    --graceful-timeout $${GUNICORN_GRACEFUL_TIMEOUT:-30} \
    --keep-alive $${GUNICORN_KEEPALIVE:-5} \
    --max-requests $${GUNICORN_MAX_REQUESTS:-0} \
    --max-requests-jitter $${GUNICORN_MAX_REQUESTS_JITTER:-0} \
    --access-logfile $${GUNICORN_ACCESSLOG:--} \
    --error-logfile $${GUNICORN_ERRORLOG:--} \
    --log-level $${GUNICORN_LOGLEVEL:-info} \
    --forwarded-allow-ips $${FORWARDED_ALLOW_IPS:-*}
endif

# --- phony ---
.PHONY: help venv install setup clean distclean up down restart logs tail shell \
   serve dev test test-cov lint fmt check seed reindex manage health db-shell \
   docker-build docker-rebuild docker-pull docker-push docker-login

# --- helpers ---
define export-dotenv
   set -a; [ -f $(ENVFILE) ] && . $(ENVFILE); set +a;
endef

# --- help ---
help:
   @echo "Targets:"
   @echo "  setup        Create venv and install requirements"
   @echo "  serve        Run app (waitress on Windows, gunicorn on *nix)"
   @echo "  dev          Run Flask dev server"
   @echo "  test         Run pytest; test-cov for coverage"
   @echo "  lint, fmt    Ruff/Black; check = lint+test"
   @echo "  seed         Load fixtures & create admin"
   @echo "  reindex      Ensure DB indexes"
   @echo "  up/down      docker compose up/down"
   @echo "  logs/tail    App logs once / follow"
   @echo "  shell        App repl with env; db-shell = mongo shell"
   @echo "  manage       Run scripts/manage.py <cmd> ARGS=..."
   @echo "  health       Curl /healthz using BASE_URL or localhost"
   @echo "  docker-*     Build/rebuild/pull/push/login"

# --- venv & install ---
$(ACTIVATE):
   @test -d $(VENV) || $(PY) -m venv $(VENV)

venv: $(ACTIVATE)

install: venv
   @$(ACT); $(PIP) install --upgrade pip
   @$(ACT); if [ -f requirements.txt ]; then $(PIP) install -r requirements.txt; fi
   @$(ACT); if [ -f pyproject.toml ]; then $(PIP) install -e . 2>/dev/null || true; fi
   @# Windows에서는 waitress를 기본 설치
   @if [ "$(IS_WIN)" = "1" ]; then $(ACT); $(PIP) install waitress; fi

setup: install
   @mkdir -p $(LOG_DIR) uploads

clean:
   @rm -rf $(VENV) .pytest_cache .coverage dist build **/__pycache__ **/*.pyc

distclean: clean
   @rm -rf $(LOG_DIR)/* uploads/*

# --- run (local) ---
serve:
   @$(export-dotenv) \
   mkdir -p $(LOG_DIR); \
   $(RUN_SERVE)

dev:
   @$(export-dotenv) \
   $(ACT); \
   export FLASK_ENV=$${FLASK_ENV:-development}; \
   export FLASK_APP="$(WSGI_APP)"; \
   exec flask run --host=0.0.0.0 --port $${PORT:-$(PORT)}

shell:
   @$(export-dotenv) \
   $(ACT); \
   $(PY) - <<'PY' || true
from app import create_app
app = create_app()
ctx = app.app_context(); ctx.push()
print("App shell ready. 'app' is available.")
PY

# --- docker compose ---
COMPOSE := docker compose
PROJECT ?= penart
IMG ?= $(PROJECT):latest

up:
   @$(COMPOSE) up -d --remove-orphans

down:
   @$(COMPOSE) down --remove-orphans

restart:
   @$(COMPOSE) restart

logs:
   @$(COMPOSE) logs --no-color --tail=200

tail:
   @$(COMPOSE) logs -f

docker-build:
   @$(COMPOSE) build

docker-rebuild:
   @$(COMPOSE) build --no-cache

docker-pull:
   @$(COMPOSE) pull

docker-push:
   @docker push $(IMG)

docker-login:
   @docker login

# --- tests & quality ---
test:
   @$(export-dotenv) \
   $(ACT); PYTHONPATH=. pytest -q

test-cov:
   @$(export-dotenv) \
   $(ACT); PYTHONPATH=. pytest -q --cov=app --cov-report=term-missing

lint:
   @$(ACT); ruff check . || true
   @$(ACT); black --check . || true

fmt:
   @$(ACT); black .
   @$(ACT); ruff check . --fix

check: lint test

# --- data ops ---
seed:
   @$(export-dotenv) \
   $(ACT); PYTHONPATH=. $(PY) scripts/seed.py

reindex:
   @$(export-dotenv) \
   $(ACT); PYTHONPATH=. $(PY) scripts/create_indexes.py

manage:
   @$(export-dotenv) \
   $(ACT); PYTHONPATH=. $(PY) scripts/manage.py $(CMD) $(ARGS)

db-shell:
   @$(export-dotenv) \
   MURI=$${MONGO_URI:-mongodb://localhost:27017/penart}; \
   echo "Connecting to $$MURI"; \
   mongosh "$$MURI"

# --- ops ---
health:
   @$(export-dotenv) \
   URL=$${BASE_URL:-http://127.0.0.1:$(PORT)}; \
   echo "GET $$URL/healthz"; \
   curl -fsSL "$$URL/healthz" || (echo "health check failed" && exit 1)
