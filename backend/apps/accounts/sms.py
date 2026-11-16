"""
Sending SMS. The backend is chosen with SMS_BACKEND in backend/.env:

- console: writes the message to the server log (development, tests)
- raygan:  sends through RayganSMS (raygansms.com). Login codes go through RayganSMS's approved pattern
           (RAYGAN_ACCESS_HASH + RAYGAN_OTP_PATTERN_ID) when both are set: sent from the provider's service line, so they
           are delivered without a promotional permit and to numbers that refused advertising. Other messages (e.g. the
           waitlist «منتشر شد») use the sender line (RAYGAN_USERNAME/PASSWORD/SENDER_NUMBER).
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


def pattern_ready() -> bool:
    return settings.SMS_BACKEND == "raygan" and bool(settings.RAYGAN_ACCESS_HASH and settings.RAYGAN_OTP_PATTERN_ID)


def send_login_code(phone: str, code: str, text: str) -> None:
    """A login code: through the approved pattern when it is set up (its text lives in RayganSMS's panel; the code is
    token1), otherwise as the ordinary message `text`. Raises SMSError like send_sms."""
    if pattern_ready():
        _send_raygan_pattern(phone, code)
    else:
        send_sms(phone, text)


# The pattern service answers with a number: one of these codes means it refused (1xxx-3xxx: nothing was sent;
# 5xxx: its own error, so it is unclear), another number above 2000 is the id of the sent message.
_PATTERN_ERRORS = {1001, 1002, 1003, 1004, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009,
                   3001, 3002, 3003, 3004, 5001, 5002, 5003, 5004}
_PATTERN_URL = "https://smspanel.trez.ir/SendPatternCodeWithUrl.ashx"


def _send_raygan_pattern(phone: str, code: str) -> None:
    try:
        response = requests.post(
            _PATTERN_URL,
            data={"AccessHash": settings.RAYGAN_ACCESS_HASH, "PatternId": settings.RAYGAN_OTP_PATTERN_ID,
                  "Mobile": phone, "token1": code},
            timeout=10,
        )
    except requests.ConnectionError as exc:
        raise SMSNotSent(f"RayganSMS pattern service unreachable: {exc}") from exc
    except requests.RequestException as exc:
        raise SMSError(f"RayganSMS pattern service did not answer: {exc}") from exc
    body = response.text.strip()
    number = int(body) if response.status_code == 200 and body.lstrip("-").isdigit() else None
    if number in _PATTERN_ERRORS:
        log.error("RayganSMS pattern refused the message: code %s", number)
        error = SMSError if number >= 5000 else SMSNotSent
        raise error(f"RayganSMS pattern refused the message (code {number})")
    if number is None or number <= 2000:
        log.error("RayganSMS pattern gave an unclear answer: HTTP %s, body %r", response.status_code, body[:200])
        raise SMSError(f"RayganSMS pattern gave an unclear answer (HTTP {response.status_code}: {body[:60]})")
    log.warning("RayganSMS pattern accepted the code to %s (id %s)", phone, number)


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
