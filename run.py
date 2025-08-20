from app import create_app
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from app.utils.time import KST
from app.schedule.service import open_week_slots
from app.attendance.service import sweep_no_show

app = create_app()

def job_open_week():
    with app.app_context():
        base_date = datetime.now(tz=KST).date()
        result = open_week_slots(base_date)
        app.logger.info(f"[OPEN_WEEK] base={base_date} -> {result}")

def job_authnoshow():
    with app.app_context():
        result = sweep_no_show(grace_minutes=10)
        app.logger.info(f"[AUTO_NOSHOW] {result}")

scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(job_open_week, CronTrigger(day_of_week="mon", hour=10, minute=0))
scheduler.add_job(job_authnoshow, IntervalTrigger(minutes=10))
scheduler.start()


if __name__== "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
    