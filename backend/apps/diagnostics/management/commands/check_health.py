from django.core.management.base import BaseCommand

from apps.diagnostics.checks import run_all_health_checks


class Command(BaseCommand):
    help = "اجرای بررسی‌های دوره‌ای سلامت محصول (پرداخت و دسترسی، جلسه‌های مرور، خلاصهٔ آفلاین)."

    def handle(self, *args, **options):
        runs = run_all_health_checks()
        for r in runs:
            state = "OK" if r.completed else "FAILED"
            self.stdout.write(f"[{state}] {r.check_key}: {r.summary}")
