"""
Retries unsent (pending/failed) teacher notifications without creating duplicate rows.

    python manage.py retry_teacher_notifications
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import TeacherNotification
from apps.accounts.notifications import retry_teacher_notifications


class Command(BaseCommand):
    help = "Retry pending or failed teacher email notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-skipped",
            action="store_true",
            help="Also re-check notifications previously skipped due to missing/unverified email.",
        )

    def handle(self, include_skipped=False, **options):
        statuses = [
            TeacherNotification.Status.PENDING,
            TeacherNotification.Status.FAILED,
        ]
        if include_skipped:
            statuses.append(TeacherNotification.Status.SKIPPED_NO_EMAIL)

        qs = TeacherNotification.objects.filter(status__in=statuses).order_by("created_at", "pk")
        stats = retry_teacher_notifications(qs)
        self.stdout.write(
            self.style.SUCCESS(
                f"Attempted={stats['attempted']} | Sent={stats['sent']} | "
                f"Failed={stats['failed']} | SkippedNoEmail={stats['skipped_no_email']}"
            )
        )
