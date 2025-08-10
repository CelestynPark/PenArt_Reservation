import os
from dotenv import load_dotenv

DEFAULT_TZ = "Asia/Seoul"

def load_config(app):
    load_dotenv()

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "unniewebsiteqlalfkey1!")
    app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    app.config["MONGO_DB_NAME"] = os.getenv("MONGO_DB_NAME", "stms")
    app.config["TIMEZONE"] = os.getenv("TIMEZONE", DEFAULT_TZ)

