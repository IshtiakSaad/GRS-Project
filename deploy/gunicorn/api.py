"""Gunicorn for the general API.

Sync workers: each request holds one worker, so capacity is predictable and Nginx buffering
protects workers from slow 3G clients. The 15 s timeout sits between the database statement
timeout (5 s) and Nginx (20 s), so a stuck request is cut in the right order.
"""

import os

bind = "0.0.0.0:8000"
worker_class = "sync"
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
timeout = 15
graceful_timeout = 30  # below Compose stop_grace_period (45 s): in-flight requests finish
keepalive = 5
# Recycle workers so slow memory growth never accumulates.
max_requests = 1000
max_requests_jitter = 100
accesslog = None  # Nginx logs every request once
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
forwarded_allow_ips = "*"  # only reachable from Nginx on the internal network
