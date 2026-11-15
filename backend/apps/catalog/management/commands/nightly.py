import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.catalog.backups import _safe, run_due


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
        time.sleep(120)  # let the web server start first
        while True:
            try:
                close_old_connections()
                done = run_due()
                if done:
                    self.stdout.write("nightly: " + ", ".join(done))
            except Exception as exc:  # noqa: BLE001 — try again next hour
                self.stderr.write(f"nightly failed: {type(exc).__name__}: {_safe(exc)}")
            time.sleep(3600)
