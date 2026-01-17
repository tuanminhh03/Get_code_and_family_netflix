import os

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

database_url = os.getenv("DATABASE_URL", "")
default_workers = 1 if database_url.startswith("sqlite") else 2
workers = int(os.getenv("GUNICORN_WORKERS", str(default_workers)))
if database_url.startswith("sqlite") and workers > 1:
    workers = 1

threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))

accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
