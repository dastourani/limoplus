from django.core.management.base import BaseCommand

from apps.catalog.maintenance import run_all


class Command(BaseCommand):
    help = "پاک‌سازی شبانه: داده‌های موقت، نسخه‌های قدیمی فصل‌ها و عکس‌های بی‌استفاده (داده‌ی کاربران دست نمی‌خورد)."

    def handle(self, *args, **options):
        summary = run_all()
        self.stdout.write(", ".join(f"{k}: {v}" for k, v in summary.items()))
