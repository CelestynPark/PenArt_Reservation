from typing import Optional
from flask import current_app, g
from pymongo import MongoClient

def init_mongo(app):
    uri = app.config["MONGO_URI"]
    db_name = app.config["MONGO_DB_NAME"]

    client = MongoClient(uri)
    db = client[db_name]

    app.config["MONGO_CLIENT"] = client
    app.config["MONGO_DB_HANDLE"] = db

def get_db():
    if "mongo_db" not in g:
        g.mongo_db = current_app.config["MONGO_DB_HANDLE"]
    return g.mongo_db

def close_mongo(exception: Optional[BaseException] = None):
    g.pop("mongo_db", None)

