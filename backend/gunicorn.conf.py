import os
import subprocess
import sys

wsgi_app = "config.wsgi:application"
bind = "0.0.0.0:8000"  # the port set for the app in the ParsPack panel
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
# Threads: a slow phone downloading the APK, or a large upload, does not hold up everyone else.
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "8"))
timeout = 120
accesslog = "-"
errorlog = "-"

HERE = os.path.dirname(os.path.abspath(__file__))
_jobs = None


def when_ready(server):
    """On the real server (NIGHTLY_JOBS=True): one separate process that does the hourly jobs
    (clean-up, nightly database backup, weekly media backup). Started once, by the master."""
    global _jobs
    if os.environ.get("NIGHTLY_JOBS", "").strip().lower() in ("1", "true", "yes"):
        _jobs = subprocess.Popen([sys.executable, "manage.py", "nightly", "--loop"], cwd=HERE)


def on_exit(server):
    if _jobs and _jobs.poll() is None:
        _jobs.terminate()
