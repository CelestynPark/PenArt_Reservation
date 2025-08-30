from datetime import datetime
from werkzeug.security import generate_password_hash
from app import create_app
from app.utils.time import KST
from app.schedule.service import open_week_slots

def main():
    app = create_app()
    with app.app_context():
        db = app.config["MONGO_DB_HANDLE"]

        phone = "+821011112222"
        user = db.users.find_one({"phone": phone})
        if not user:
            uid = db.users.insert_one({
                "name": "관리자",
                "phone": phone,
                "email": "admin@example.com",
                "role": "admin",
                "password_hash": generate_password_hash("pass1234"),
                "created_at": datetime.utcnow()
            }).inserted_id
            print(f"[dev_seed] user created: {uid}")
        else:
            print(f"[dev_seed] user exists: {user['_id']}")

        phone = "+8210123456789"
        user = db.users.find_one({"phone": phone})
        if not user:
            uid = db.users.insert_one({
                "name": "최영준",
                "phone": phone,
                "email": "demo@example.com",
                "password_hash": generate_password_hash("pass1234"),
                "created_at": datetime.utcnow()
            }).inserted_id
            print(f"[dev_seed] user created: {uid}")
        else:
            print(f"[dev_seed] user exists: {user['_id']}")

        enroll = db.enrollments.find_one({"user_id": user["_id"], "course_type": "ADVANCED"})
        if not enroll:
            eid = db.enrollments.insert_one({
                "user_id": user["_id"],
                "course_type": "ADVANCED",
                "session_minutes": 120,
                "total_sessions": 4,
                "remaining_sessions": 4,
                "adjust_tokens": 1,
                "status": "ACTIVE",
                "created_at": datetime.utcnow()
            }).inserted_id
            print(f"[dev_seed] enrollment created: {eid}")
        else:
            print(f"[dev_seed] enrollment exists: {enroll['_id']}")

        base_date = datetime.now(tz=KST).date()
        result = open_week_slots(base_date)
        print(f"[dev_seed] open_week {base_date} -> {result}")

if __name__ == "__main__":
    main()