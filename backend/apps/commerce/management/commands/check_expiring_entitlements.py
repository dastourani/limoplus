from datetime import timedelta
import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.accounts.sms import send_sms
from apps.catalog.backups import notify_bale
from apps.catalog.jalali import fa_digits, jalali_date
from apps.commerce.models import Entitlement

log = logging.getLogger(__name__)


def _has_extended_coverage(ent: Entitlement, three_days_later) -> bool:
    """
    True when the learner already has another non-archived entitlement covering the same scope that starts
    before or at `ent.ends_at` (active now or stacked seamlessly) and ends strictly after `ent.ends_at`
    (either a queued renewal or a broader/permanent entitlement).
    """
    base = Entitlement.objects.filter(user_id=ent.user_id, is_archived=False).exclude(pk=ent.pk)
    if ent.all_majors and ent.book_id is None:
        scope_q = Q(all_majors=True, book__isnull=True)
    elif ent.major_id and ent.book_id is None:
        scope_q = Q(all_majors=True, book__isnull=True) | Q(major_id=ent.major_id, book__isnull=True)
    elif ent.book_id:
        book_major_ids = list(ent.book.majors.values_list("id", flat=True))
        scope_q = Q(book_id=ent.book_id) | Q(all_majors=True, book__isnull=True)
        if book_major_ids:
            scope_q |= Q(major_id__in=book_major_ids, book__isnull=True)
    else:
        return False

    return (
        base.filter(scope_q, starts_at__lte=ent.ends_at)
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=ent.ends_at))
        .exists()
    )


def check_and_notify_expiring_entitlements(now=None, dry_run=False):
    """Checks active subscriptions ending within 3 days and sends reminder SMS and Bale report."""
    now = now or timezone.now()
    today_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)

    # Active paid or gift subscriptions ending in the next 3 days
    # Note: ends_at is not null, not archived, starts_at <= now, ends_at > now
    three_days_later = now + timedelta(days=3)
    expiring_qs = (
        Entitlement.objects.filter(
            is_archived=False,
            starts_at__lte=now,
            ends_at__gt=now,
            ends_at__lte=three_days_later,
        )
        .select_related("user", "book", "major", "order")
        .order_by("ends_at")
    )

    notified_users = []
    skipped_count = 0

    for ent in expiring_qs:
        # Prevent duplicate notifications sent today
        if ent.expiry_warning_sent_at and ent.expiry_warning_sent_at >= today_start:
            skipped_count += 1
            continue

        # Do not warn when the user already renewed or holds a longer/permanent covering entitlement.
        if _has_extended_coverage(ent, three_days_later):
            skipped_count += 1
            continue

        remaining_time = ent.ends_at - now
        days_left = remaining_time.days
        hours_left = int(remaining_time.total_seconds() // 3600)

        if days_left >= 1:
            time_str = f"{fa_digits(days_left)} روز دیگر"
        else:
            time_str = f"{fa_digits(max(1, hours_left))} ساعت دیگر"

        subscription_title = "اشتراک لیموخوان"
        if ent.major:
            subscription_title = f"اشتراک رشته {ent.major.name}"
        elif ent.book:
            subscription_title = f"دسترسی کتاب «{ent.book.title}»"

        phone = ent.user.phone
        sms_text = (
            f"کاربر گرامی لیمو،\n"
            f"{subscription_title} شما {time_str} ({jalali_date(ent.ends_at)}) به پایان می‌رسد.\n"
            f"برای ادامه مطالعه و استفاده بدون وقفه، هم‌اکنون می‌توانید اشتراک خود را تمدید فرمایید:\n"
            f"limookhan.ir"
        )

        if not dry_run:
            try:
                send_sms(phone, sms_text)
                ent.expiry_warning_sent_at = now
                ent.save(update_fields=["expiry_warning_sent_at"])
                notified_users.append((phone, subscription_title, time_str))
            except Exception as exc:
                log.error("Failed to send expiry SMS to %s: %s", phone, exc)
        else:
            notified_users.append((phone, subscription_title, time_str))

    # Send summary notification to Bale bot for admin oversight
    if notified_users:
        lines = [
            f"🔔 گزارش انقضای اشتراک لیموخوان‌ها ({jalali_date(now)}):",
            f"تعداد کاربران نیازمند یادآوری: {fa_digits(len(notified_users))}",
            "",
        ]
        for phone, title, time_left in notified_users[:15]:
            lines.append(f"• {phone} — {title} (مهلت: {time_left})")
        if len(notified_users) > 15:
            lines.append(f"• و {fa_digits(len(notified_users) - 15)} کاربر دیگر...")

        if not dry_run:
            notify_bale("\n".join(lines))

    return {
        "notified_count": len(notified_users),
        "skipped_count": skipped_count,
        "users": notified_users,
    }


class Command(BaseCommand):
    help = "بررسی اشتراک‌های در حال انقضای لیموخوان‌ها و ارسال پیامک یادآوری تمدید و گزارش بله"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="فقط نمایش اشتراک‌های مشمول بدون ارسال پیامک یا پیام بله",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        result = check_and_notify_expiring_entitlements(dry_run=dry_run)
        prefix = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(
            f"{prefix}تعداد هشدارهای ارسال‌شده: {result['notified_count']} (ردشده تکراری امروز: {result['skipped_count']})"
        )
        for phone, title, time_left in result["users"]:
            self.stdout.write(f"  - {phone}: {title} ({time_left})")
