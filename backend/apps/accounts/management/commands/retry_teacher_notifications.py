"""
Retries unsent (pending/failed or stale sending) teacher notifications without creating duplicate rows.

    python manage.py retry_teacher_notifications
"""

from django.core.management.base import BaseCommand

from apps.accounts.notifications import retry_teacher_notifications, retryable_notifications_queryset


class Command(BaseCommand):
    help = "Retry pending, failed, or stale-sending teacher email notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-skipped",
            action="store_true",
            help="Also re-check notifications previously skipped due to missing/unverified email.",
        )

    def handle(self, include_skipped=False, **options):
        qs = retryable_notifications_queryset(include_skipped=include_skipped)
        stats = retry_teacher_notifications(qs)
        self.stdout.write(
            self.style.SUCCESS(
                f"Attempted={stats['attempted']} | Sent={stats['sent']} | "
                f"Failed={stats['failed']} | SkippedNoEmail={stats['skipped_no_email']} | "
                f"InProgress={stats['in_progress']}"
            )
        )
