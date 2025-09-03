from __future__ import annotations
from typing import Any
from flask import current_app, g
from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database

def get_mongo_client() -> MongoClient:
    """Flask app context에서 재사용 가능한 MongoClient 반환."""
    client: MongoClient | None = getattr(g, "_mongo_client", None)
    if client is None:
        uri = current_app.config["MONGO_URI"]
        client = MongoClient(uri, appname="Pen-Art-Reservation")
        g._mongo_client = client
    return client

def get_db() -> Database:
    client = get_mongo_client()
    db_name = current_app.config["MONGO_DBNAME"]
    return client[db_name]

def get_collection(name: str) -> Collection:
    return get_db()[name]

def ensure_indexes() -> None:
    """
    어플리케이션 기동 시 보장해야 할 인덱스 정의.
    Mongo는 컬렉션이 없어도 create_index 호출 시 생성된다.
    """
    db = get_db()

    # users: 전화번호 유니크, 로그인/조회 최적화
    db.users.create_index([("phone", ASCENDING)], unique=True, name="uniq_phone")
    db.users.create_index([("created_at", ASCENDING)], name="users_created_at")

    # slots: (data, start) 유니크 -> 동일 일자/시간 슬롯 중복 생성을 방지
    db.slots.create_index([("date", ASCENDING), ("start", ASCENDING)], unique=True, name="uniq_date_start")
    db.slots.create_index([("is_open", ASCENDING)], name="slots_is_open")

    # reservations: 사용자/생성일, 상태, 슬롯 점유 조회
    db.reservations.create_index([("user_id", ("created_at", ASCENDING))], name="resv_user_created")
    db.reservations.create_index([("status", ASCENDING)], name="resv_status")
    db.reservations.create_index([("slot_ids", ASCENDING)], name="resv_slot_ids")

    