from django.core.management.base import BaseCommand

from apps.catalog.backups import run_due


class Command(BaseCommand):
    help = "کارهای شبانه‌ی سرور: پاک‌سازی، پشتیبان دیتابیس (هر شب) و پشتیبان عکس‌ها (هر هفته) — هر کدام که وقتش رسیده باشد."

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true", help="همه را همین حالا انجام بده")

    def handle(self, *args, **options):
        done = run_due(force=options["now"])
        self.stdout.write("انجام شد: " + (", ".join(done) or "هیچ‌کدام وقتش نبود"))
