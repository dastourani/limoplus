import sys
import threading
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.catalog.backups import _safe, run_due

_thread_lock = threading.Lock()
_thread_started = False


def run_nightly_loop(
    *,
    initial_delay: float = 120,
    interval: float = 3600,
    stdout=None,
    stderr=None,
    stop_event: threading.Event | None = None,
) -> None:
    """Run due nightly tasks every `interval` seconds; shared by `manage.py nightly --loop` and single-worker Gunicorn."""
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    if initial_delay > 0:
        if stop_event is not None:
            if stop_event.wait(initial_delay):
                return
        else:
            time.sleep(initial_delay)
    while stop_event is None or not stop_event.is_set():
        try:
            close_old_connections()
            done = run_due()
            if done:
                out.write("nightly: " + ", ".join(done) + "\n")
                out.flush()
        except Exception as exc:  # noqa: BLE001 — try again next hour
            err.write(f"nightly failed: {type(exc).__name__}: {_safe(exc)}\n")
            err.flush()
        finally:
            close_old_connections()
        if stop_event is not None:
            if stop_event.wait(interval):
                return
        else:
            time.sleep(interval)


def start_nightly_thread(initial_delay: float = 120, interval: float = 3600) -> bool:
    """Start the hourly nightly loop once inside a single-worker server process (saves a separate Django process)."""
    global _thread_started
    with _thread_lock:
        if _thread_started:
            return False
        _thread_started = True
    thread = threading.Thread(
        target=run_nightly_loop,
        kwargs={"initial_delay": initial_delay, "interval": interval},
        name="limoplus-nightly",
        daemon=True,
    )
    thread.start()
    return True


class Command(BaseCommand):
    help = "کارهای شبانه‌ی سرور: پاک‌سازی، پشتیبان دیتابیس (هر شب) و پشتیبان عکس‌ها (هر هفته) — هر کدام که وقتش رسیده باشد."

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true", help="همه را همین حالا انجام بده")
        parser.add_argument("--loop", action="store_true", help="هر ساعت یک بار، تا وقتی سرور روشن است")

    def handle(self, *args, **options):
        if not options["loop"]:
            done = run_due(force=options["now"])
            self.stdout.write("انجام شد: " + (", ".join(done) or "هیچ‌کدام وقتش نبود"))
            return
        run_nightly_loop(stdout=self.stdout, stderr=self.stderr)
