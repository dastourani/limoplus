"""
Sends a real test email using the active deployment EMAIL_* settings and prints SMTP configuration diagnostics.

    python manage.py send_test_email teacher@example.com
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = "Send a test email with the active SMTP settings to verify real inbox delivery."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, email, **options):
        target = (email or "").strip().lower()
        try:
            validate_email(target)
        except ValidationError as exc:
            raise CommandError("نشانی ایمیل واردشده معتبر نیست.") from exc

        self.stdout.write(f"EMAIL_BACKEND = {settings.EMAIL_BACKEND}")
        self.stdout.write(f"EMAIL_HOST = {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        self.stdout.write(f"EMAIL_USE_TLS = {settings.EMAIL_USE_TLS} | EMAIL_USE_SSL = {settings.EMAIL_USE_SSL}")
        self.stdout.write(f"DEFAULT_FROM_EMAIL = {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"SITE_URL = {settings.SITE_URL}")

        if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
            self.stdout.write(
                self.style.WARNING(
                    "بک‌اند روی console است؛ برای ارسال واقعی روی سرور، EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend را تنظیم کنید."
                )
            )

        msg = EmailMultiAlternatives(
            subject="آزمایش تحویل ایمیل لیموخوان",
            body=(
                "سلام،\n\n"
                "این یک پیام آزمایشی برای اطمینان از ارسال و تحویل ایمیل‌های میز تألیف لیموخوان است.\n\n"
                f"نشانی سایت: {settings.SITE_URL}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[target],
        )
        msg.attach_alternative(
            '<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;padding:16px;">'
            "<p>سلام،</p>"
            "<p>این یک پیام آزمایشی برای اطمینان از ارسال و تحویل ایمیل‌های میز تألیف لیموخوان است.</p>"
            "</div>",
            "text/html",
        )
        try:
            sent_count = msg.send(fail_silently=False)
        except Exception as exc:
            raise CommandError(f"ارسال ایمیل با خطا مواجه شد: {exc.__class__.__name__}: {exc}") from exc

        if sent_count:
            self.stdout.write(self.style.SUCCESS(f"سرور ایمیل پیام را برای {target} پذیرفت (sent={sent_count}). لطفاً صندوق ورودی و پوشه هرزنامه (Spam) را بررسی کنید."))
        else:
            self.stdout.write(self.style.WARNING("سرور ایمیل خطا نداد اما هیچ پیامی ارسال نشد (sent=0)."))
