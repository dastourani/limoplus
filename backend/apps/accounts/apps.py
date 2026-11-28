from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "حساب‌ها"

    def ready(self):
        from django.contrib.auth.signals import user_login_failed

        def count_admin_failure(sender, credentials, request=None, **kwargs):
            # Only the superuser's break-glass admin login uses a password; staff normally use SMS codes.
            if request is None:
                return
            from . import ratelimit
            from .phone import InvalidPhone, normalize_phone
            from .views import _client_ip

            raw_phone = (credentials.get("username") or "").strip()
            try:
                phone = normalize_phone(raw_phone)
            except InvalidPhone:
                phone = raw_phone
            phone = phone[:100]  # Keep the key within RateBucket.key's 120-character column.
            ratelimit.hit(f"admin-fail-ip:{_client_ip(request)}")
            ratelimit.hit(f"admin-fail-phone:{phone}")

        user_login_failed.connect(count_admin_failure, dispatch_uid="limoplus-admin-login-failed")
