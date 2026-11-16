from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import DeviceSession


@receiver(post_save, sender=DeviceSession, dispatch_uid="guard-device-alert")
def device_signed_in(sender, instance, created, **kwargs):
    if created:
        from .alerts import after_login

        after_login(instance)
