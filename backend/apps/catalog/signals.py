"""Django signals that record activity in one place instead of in every view.

Only login is done this way: it happens through `django.contrib.auth.login` (the admin's form, the web app's
panel hand-off, anything else we add later), so a signal sees all of it, while every other event is a deliberate
step in `panel.py` and is recorded there, next to the code that does it.
"""

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def _record_login(sender, request, user, **kwargs):
    from .activity import record
    from .models import Activity

    record(Activity.Kind.LOGIN, actor=user, note="ورود به پنل" if user.is_staff else "ورود")
