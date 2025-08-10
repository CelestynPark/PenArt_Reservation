from flask import Flask, jsonify
from .config import load_config
from .db import init_mongo, close_mongo

def create_app() -> Flask:
    app = Flask(__name__, template_folder='templates', static_folder='static')

    load_config(app)

    init_mongo(app)
    app.teardown_appcontext(close_mongo)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200
    
    @app.get("/ping")
    def ping():
        db = app.config["MONGO_DB_HANDLE"]
        collections = db.list_collection_names()
        return jsonify({"pong": True, "collection": collections})
    
    return app
