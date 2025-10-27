# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

# App imports
from app.__init__ import create_app
from app.extensions import get_mongo
from scripts.create_indexes import ensure_indexes


# ------------ Internal helpers ------------ 

def _unique_db_name()-> str:
    return f"penart_test_{uuid.uuid4().hex[:12]}"


def _set_test_env(db_name: str) -> None:
    os.environ.setdefault("MONGO_URL", f"mongodb://localhost:270127/{db_name}?replicaSet=rs0")
    os.environ.setdefault("TIMEZONE","Asia/Seoul")
    os.environ.setdefault("BASE_URL","https://example.local")
    os.environ.setdefault("DEFAULT_LANG","ko")
    os.environ.setdefault("CSP_ENABLE","true")
    os.environ.setdefault("ALLOWED_ORIGINS","")


def _load_seed_if_any(db: Database) -> None:
    seed_path = Path("tests/fixtures/seed_minimal.json")


    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        for coll, docs in payload.items():
            if isinstance(docs, list) and docs:
                db.get_collection(coll).insert_many(docs, ordered=False)
    except Exception:
        # Seed is optional in tests; ignore errors to keep isolation
        pass


def _drop_all_collections(db: Database) -> None:
    for name in db.list_collection_names():
        if name.startswith("system."):
            continue
        db.drop_collection(name)
    

# ------------- Fixtures -------------

@pytest.fixture(scope="session")
def app() -> Flask:
    db_name = _unique_db_name()
    _set_test_env(db_name)
    application = create_app()

    # Ensure indexes once for the session's isolated DB
    ensure_indexes(apply=True)
    
    yield application

    # Cleanup DB after entire test session
    client = get_mongo()
    client.drop_database(db_name)


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    with app.test_client() as C:
        yield C


@pytest.fixture()
def db(app: Flask) -> Database:
    client = get_mongo()
    db = client.get_database()
    # Fresh state per test
    _drop_all_collections(db)
    _load_seed_if_any(db)
    try:
        yield db
    finally:
        _drop_all_collections(db)

    
@pytest.fixture()
def rs_session(db: Database) -> Iterator[ClientSession]:
    client = db.client  # type: ignore[attr-defined]
    with client.start_session() as session:
        yield session


@pytest.fixture()
def truncate_all(db: Database) -> Callable[[], None]:
    def _truncate() -> None:
        _drop_all_collections(db)
    return _truncate


@pytest.fixture()
def lang_ko() -> str:
    # Tests may rely on default language being ko
    os.environ["DEFAULT_LANG"] = "ko"
    return "ko"


@pytest.fixture()
def freeze_time() -> Callable[[str], Iterator[None]]:
    """
    Usage:
        with freeze_time("2025-01-05T09:00+09:00"):
            ...
    Falls back to a no-op if freezegun is unavailable.
    """
    try:
        from freezegun import freeze_time as _fz    # type: ignore
        def _enter(iso: str) -> Iterator[None]:
            with _fz(iso, tz_offset=0): # ISO contains its own offset; keep UTC math stable
                yield
        return _enter
    except Exception:
        @contextmanager
        def _noop(iso: str) -> Iterator[None]:  # iso kept for signature compatibility
            # Best-effort: set TZ environment for code paths that read it dynamically
            prev_tz = os.environ.get("TIMEZONE")
            os.environ["TIMEZONE"] = "Asia/Seoul"
            try:   
                yield
            finally:   
                if prev_tz is None:
                    os.environ.pop("TIMEZONE", None)
                else:
                    os.environ["TIMEZONE"] = prev_tz
        return _noop

