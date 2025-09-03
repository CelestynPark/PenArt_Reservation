# gunicorn.conf.py
import os
import multiprocessing
import time

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
wsgi_app = os.getenv('WSGI_APP', 'app:create_app()')
worker_class = os.getenv('WORKER_CLASS', 'gthread')
workers = int(os.getenv('WEB_CONCURRENCY', str(multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.getenv('THREADS', '4'))
preload_app = True

timeout = int(os.getenv('GUNICORN_TIMEOUT', '60'))
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))
keepalive = int(os.getenv('GUNICORN_KEEPALIVE', '5'))
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '0'))
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '0'))

errorlog = os.getenv('GUNICORN_ERRORLOG', '-')
accesslog = os.getenv('GUNICORN_ACCESSLOG', '-')
loglevel = os.getenv('GUNICORN_LOGLEVEL', 'info')
access_log_format = (
    '{"remote":"%(h)s","method":"%(m)s","path":"%(U)s","query":"%(q)s",'
    '"status":%(s)s,"length":%(B)s,"referer":"%(f)s","user_agent":"%(a)s",'
    '"request_time":%(L)s,"pid":"%(p)s"}'
)

forwarded_allow_ips = os.getenv('FORWARDED_ALLOW_IPS', '*')
secure_scheme_headers = {"X-Forwarded-Proto": "https"}

def on_starting(server):
    tz = os.getenv('TIMEZONE', 'Asia/Seoul')
    try:
        os.environ['TZ'] = tz
        time.tzset()
    except Exception:
        pass  # POSIX only

def worker_int(worker):
    worker.log.info("worker: received interrupt")

def worker_abort(worker):
    worker.log.warning("worker: aborted")