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
    """The message may or may not have reached the provider (e.g. the answer timed out)."""


class SMSNotSent(SMSError):
    """The message certainly did not go out: nothing was handed over, or the provider refused it."""


def send_sms(phone: str, text: str) -> None:
    """Raises SMSError when the message could not be handed to the provider."""
    backend = settings.SMS_BACKEND
    if backend == "console":
        log.warning("SMS (console) to %s: %s", phone, text)
        return
    if backend == "raygan":
        _send_raygan(phone, text)
        return
    raise SMSNotSent(f"Unknown SMS_BACKEND: {backend}")


def _send_raygan(phone: str, text: str) -> None:
    if not (settings.RAYGAN_USERNAME and settings.RAYGAN_PASSWORD and settings.RAYGAN_SENDER_NUMBER):
        raise SMSNotSent("RayganSMS credentials are missing in backend/.env")
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
    except requests.ConnectionError as exc:  # never connected (includes ConnectTimeout): nothing was sent
        raise SMSNotSent(f"RayganSMS unreachable: {exc}") from exc
    except requests.RequestException as exc:  # e.g. the answer timed out: it may have been sent
        raise SMSError(f"RayganSMS did not answer: {exc}") from exc
    body = response.text.strip()
    # RayganSMS answers with a message id (a positive number) on success, an error code (zero or negative) otherwise.
    if response.status_code == 200 and body.lstrip("-").isdigit() and int(body) <= 0:
        log.error("RayganSMS rejected the message: code %s", body)
        raise SMSNotSent(f"RayganSMS rejected the message (code {body})")
    if response.status_code != 200 or not body.isdigit():
        log.error("RayganSMS gave an unclear answer: HTTP %s, body %r", response.status_code, body[:200])
        raise SMSError(f"RayganSMS gave an unclear answer (HTTP {response.status_code}: {body[:60]})")
    log.warning("RayganSMS accepted the message to %s (id %s)", phone, body)
