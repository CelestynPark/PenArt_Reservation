from __future__ import annotations
import atexit
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from app import create_app
from app.config import Config

# Flask 앱 생성
app = create_app(Config)

#  ==== APScheduler 스텁 ====
# - 월요일 10:00 "주간 슬롯 오픈"
# - 5분마다 "NO_SHOW 스캔"

kst = timezone(app.config.get("TIMEZONE", "Asia/Seoul"))
scheduler = BackgroundScheduler(timezone=kst)
log = logging.getLogger('apscheduler')


def job_open_week_slots():
    with app.app_context():
        app.logger.info("[JOB] open_week_slots(): (스텁) 월요일 10시 오픈 작업 실행")

def job_scan_no_show():
    with app.app_context():
        app.logger.info("[JOB] scan_no_show(): (스텁) NO_SHOW 주기 스캔 작업 실행")

# 크론 등록
scheduler.add_job(job_open_week_slots, CronTrigger(day_of_week='mon', hour=10, minute=0))
scheduler.add_job(job_scan_no_show, "interval", minutes=5)

scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=(app.config["ENV"] == "development"))
    