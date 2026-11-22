from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.commerce.wallet import release_pending_balances


class Command(BaseCommand):
    help = "آزادسازی خودکار سهم‌های فروش در انتظار گارانتی که دوره آن‌ها به پایان رسیده است."

    def handle(self, *args, **options):
        now = timezone.now()
        released_count = release_pending_balances(now=now)
        self.stdout.write(
            self.style.SUCCESS(
                f"عملیات آزادسازی سهم‌های در انتظار با موفقیت انجام شد: {released_count} سهم آزاد گردید."
            )
        )
