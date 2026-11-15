import os
import subprocess
import sys
import threading
import time

wsgi_app = "config.wsgi:application"
bind = "0.0.0.0:8000"  # the port set for the app in the ParsPack panel
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = 600  # large uploads (APK, backup restore) on slow connections
accesslog = "-"
errorlog = "-"

HERE = os.path.dirname(os.path.abspath(__file__))


def _hourly():
    """Every hour: `manage.py nightly` does whatever is due (clean-up, nightly database backup, weekly media backup)."""
    time.sleep(120)  # let the app start first
    while True:
        try:
            subprocess.run([sys.executable, "manage.py", "nightly"], cwd=HERE, timeout=3 * 3600, check=False)
        except Exception as exc:  # noqa: BLE001 — the web server must never stop because of this
            print(f"nightly job failed: {exc}", file=sys.stderr)
        time.sleep(3600)


def when_ready(server):
    # Only on the real server (NIGHTLY_JOBS=True), in the master process, so it runs once however many workers there are.
    if os.environ.get("NIGHTLY_JOBS", "").strip().lower() in ("1", "true", "yes"):
        threading.Thread(target=_hourly, name="nightly", daemon=True).start()
