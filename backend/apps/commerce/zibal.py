"""Zibal payment gateway (https://help.zibal.ir/IPG/API/). Amounts sent to Zibal are in rials."""

import requests
from django.conf import settings

API = "https://gateway.zibal.ir/v1"
START_URL = "https://gateway.zibal.ir/start/{track_id}"


class GatewayError(Exception):
    pass


def _post(path: str, payload: dict) -> dict:
    try:
        response = requests.post(f"{API}/{path}", json={"merchant": settings.ZIBAL_MERCHANT, **payload}, timeout=15)
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise GatewayError(f"Zibal unreachable: {exc}") from exc


def request_payment(*, amount_rial: int, order_id: int, callback_url: str, mobile: str = "", description: str = "") -> str:
    """Returns Zibal's trackId."""
    data = _post(
        "request",
        {"amount": amount_rial, "callbackUrl": callback_url, "orderId": str(order_id), "mobile": mobile, "description": description[:200]},
    )
    if data.get("result") != 100 or not data.get("trackId"):
        raise GatewayError(f"Zibal request rejected: {data.get('result')} {data.get('message')}")
    return str(data["trackId"])


def verify(track_id: str) -> dict:
    """Zibal's verify answer. result 100 = verified now, 201 = already verified."""
    return _post("verify", {"trackId": int(track_id) if str(track_id).isdigit() else track_id})


def start_url(track_id: str) -> str:
    return START_URL.format(track_id=track_id)
