"""
Sends two test messages to a phone, one in the login format with the app hash line and one without, and prints what
the SMS provider answered. Helps find out why login codes do not arrive.

    python manage.py send_test_sms 09121234567
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.phone import InvalidPhone, normalize_phone
from apps.accounts.sms import SMSError, _send_raygan_pattern, pattern_ready, send_sms
from apps.accounts.views import _otp_message

SAMPLE_HASH = "AbCdEfGhIjK"


class Command(BaseCommand):
    help = "Send two test SMS (with and without the app hash line) and show the provider's answer."

    def add_arguments(self, parser):
        parser.add_argument("phone")

    def handle(self, phone, **options):
        try:
            phone = normalize_phone(phone)
        except InvalidPhone as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"SMS_BACKEND = {settings.SMS_BACKEND}")
        if settings.SMS_BACKEND != "raygan":
            self.stdout.write(self.style.WARNING("پیامک واقعی فرستاده نمی‌شود؛ در .env بنویسید SMS_BACKEND=raygan و سرور را دوباره اجرا کنید."))
        if pattern_ready():
            try:
                _send_raygan_pattern(phone, "123456")
                self.stdout.write(self.style.SUCCESS("کد ورود با الگو (کد ۱۲۳۴۵۶): رایگان اس‌ام‌اس پذیرفت. کد ورود اپ از همین راه می‌رود."))
            except SMSError as exc:
                self.stdout.write(self.style.ERROR(f"کد ورود با الگو: ارسال نشد — {exc}"))
        else:
            self.stdout.write(self.style.WARNING("الگوی کد ورود تنظیم نشده (RAYGAN_ACCESS_HASH و RAYGAN_OTP_PATTERN_ID)؛ کدها با خط عادی می‌روند."))
        tests = [
            ("۱ (بدون خط آخر)", "لیموخوان\nکد ورود: 111111\nاین کد را به کسی ندهید"),
            ("۲ (با خط کد اپ)", "لیموخوان\nکد ورود: 222222\nاین کد را به کسی ندهید\n" + SAMPLE_HASH),
        ]
        for name, text in tests:
            try:
                send_sms(phone, text)
                self.stdout.write(self.style.SUCCESS(f"پیامک {name}: رایگان اس‌ام‌اس پذیرفت."))
            except SMSError as exc:
                self.stdout.write(self.style.ERROR(f"پیامک {name}: ارسال نشد — {exc}"))
        self.stdout.write("اگر فقط پیامک ۱ رسید، در .env بنویسید OTP_SMS_APP_HASH=False (کد را دستی وارد می‌کنید).")
        self.stdout.write("Login message format: " + repr(_otp_message("123456", SAMPLE_HASH)))
