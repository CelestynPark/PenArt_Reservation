from typing import Optional
from flask import current_app, g
from pymongo import MongoClient, ASCENDING

def _create_indexes(db):
    db.users.create_index([("phone", ASCENDING)], unique=True, name="uniq_phone")

    db.slots.create_index(
        [("date", ASCENDING), ("start", ASCENDING)],
        unique=True,
        name="uniq_date_start"
    )
    db.slots.create_index([("is_open", ASCENDING)], name="idx_is_open")
    db.slots.create_index([("date", ASCENDING)], name="idx_date")

    db.reservations.create_index([("user_id", ASCENDING)], name="idx_resv_user")
    db.reservations.create_index([("enrollment_id", ASCENDING)], name="idx_resv_slot_ids")

def init_mongo(app):
    uri = app.config["MONGO_URI"]
    db_name = app.config["MONGO_DB_NAME"]

    client = MongoClient(uri)
    db = client[db_name]

    app.config["MONGO_CLIENT"] = client
    app.config["MONGO_DB_HANDLE"] = db

    _create_indexes(db)

def get_db():
    if "mongo_db" not in g:
        g.mongo_db = current_app.config["MONGO_DB_HANDLE"]
    return g.mongo_db

def close_mongo(exception: Optional[BaseException] = None):
    g.pop("mongo_db", None)
