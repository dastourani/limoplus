"""
Sending SMS. The backend is chosen with SMS_BACKEND in backend/.env:

- console: writes the message to the server log (development, tests)
- raygan:  sends through RayganSMS (raygansms.com)
"""

import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)


class SMSError(Exception):
    pass


def send_sms(phone: str, text: str) -> None:
    """Raises SMSError when the message could not be handed to the provider."""
    backend = settings.SMS_BACKEND
    if backend == "console":
        log.warning("SMS (console) to %s: %s", phone, text)
        return
    if backend == "raygan":
        _send_raygan(phone, text)
        return
    raise SMSError(f"Unknown SMS_BACKEND: {backend}")


def _send_raygan(phone: str, text: str) -> None:
    if not (settings.RAYGAN_USERNAME and settings.RAYGAN_PASSWORD and settings.RAYGAN_SENDER_NUMBER):
        raise SMSError("RayganSMS credentials are missing in backend/.env")
    try:
        response = requests.post(
            "https://RayganSMS.com/SendMessageWithPost.ashx",
            data={
                "UserName": settings.RAYGAN_USERNAME,
                "Password": settings.RAYGAN_PASSWORD,
                "PhoneNumber": settings.RAYGAN_SENDER_NUMBER,
                "MessageBody": text,
                "RecNumber": phone,
                "Smsclass": "1",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise SMSError(f"RayganSMS unreachable: {exc}") from exc
    body = response.text.strip()
    # RayganSMS answers with a message id (a positive number) on success.
    if response.status_code != 200 or not body.lstrip("-").isdigit() or int(body) <= 0:
        log.error("RayganSMS rejected the message: HTTP %s, body %r", response.status_code, body[:200])
        raise SMSError(f"RayganSMS rejected the message (answer: {body[:60]})")
    log.warning("RayganSMS accepted the message to %s (id %s)", phone, body)
