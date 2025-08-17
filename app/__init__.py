from flask import Flask, jsonify
from .config import load_config
from .db import init_mongo, close_mongo
from .schedule.routes import bp as schedule_bp
from .auth.routes import bp as auth_bp
from .reservations.routes import bp as resv_bp
from .attendance.routes import bp as attendacne_bp

def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

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
        return jsonify({"pong": True, "collections": collections})
    
    app.register_blueprint(schedule_bp, url_prefix="/schedule")

    app.register_blueprint(auth_bp, url_prefix="/auth")

    app.register_blueprint(resv_bp, url_prefix="/reservations")

    app.register_blueprint(attendacne_bp, url_prefix="/attendance")
    
    return app