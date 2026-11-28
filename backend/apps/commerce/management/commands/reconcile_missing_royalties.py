from django.core.management.base import BaseCommand

from apps.commerce.royalty import reconcile_missing_royalties


class Command(BaseCommand):
    help = "جبران خودکار اسنپ‌شات‌های مالی و شارژ کیف پول اساتید که در زمان تسویه جا افتاده‌اند."

    def handle(self, *args, **options):
        res = reconcile_missing_royalties()
        self.stdout.write(
            f"اسنپ‌شات‌های جبران‌شده: {res['snapshots_created']} | تراکنش‌های کیف پول: {res['wallets_credited']} | خطاها: {res['errors']}"
        )
