from app import create_app
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from app.utils.time import KST
from app.schedule.service import open_week_slots

app = create_app()

def job_open_week():
    with app.app_context():
        base_date = datetime.now(tz=KST).date()
        result = open_week_slots(base_date)
        app.logger.info(f"[OPEN_WEEK] base={base_date} -> {result}")

scheduler = BackgroundScheduler(timezone="Asia/Seoul")

scheduler.add_job(job_open_week, CronTrigger(day_of_week="mon", hour=10, minute=0))
scheduler.start()


if __name__== "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
    