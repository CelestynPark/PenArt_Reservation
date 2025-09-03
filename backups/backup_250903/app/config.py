from __future__ import annotations
import os
from dotenv import load_dotenv

# .env 로드
load_dotenv()

class Config:
    # Flask
    SECRET_KEY: str = os.getenv("SECRET_KEY", "vpsdkxm!@#")
    ENV: str = os.getenv("FLASK_ENV", "production")
    JSON_SORT_KEYS: bool = False

    # Mongo
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/stms2")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "stms2")

    # Timezone
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Seoul")

    # CORS
    CORS_ALLOW_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
    ]

    