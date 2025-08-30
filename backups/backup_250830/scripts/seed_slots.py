import sys
from datetime import datetime
from app import create_app
from app.utils.time import KST
from app.schedule.service import open_week_slots

def main():
    app = create_app()
    with app.app_context():
        if len(sys.argv) > 1:
            base_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        else:
            base_date = datetime.now(tz=KST).date()
        result = open_week_slots(base_date)
        print(f"[seed_slots] base={base_date} -> {result}")

if __name__ == "__main__":
    main()