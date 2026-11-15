from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "حساب‌ها"

    def ready(self):
        from django.contrib.auth.signals import user_login_failed

        def count_admin_failure(sender, credentials, request=None, **kwargs):
            # Only the admin login uses passwords; learners sign in with SMS codes.
            if request is None:
                return
            from . import ratelimit
            from .views import _client_ip

            ratelimit.hit(f"admin-fail-ip:{_client_ip(request)}")
            ratelimit.hit(f"admin-fail-phone:{(credentials.get('username') or '').strip()}")

        user_login_failed.connect(count_admin_failure, dispatch_uid="limoplus-admin-login-failed")
