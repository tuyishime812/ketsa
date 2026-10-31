"""PayChangu payment gateway integration (MWK — Airtel Money / TNM Mpamba).

Thin server-to-server client for the PayChangu API (https://api.paychangu.com).
The secret key is sent as a Bearer token; the public key is used for
hosted/inline checkout. Mobile-money direct charge is used for deposits.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://api.paychangu.com"
CORRESPONDENTS = ("AIRTEL", "TNM")
MIN_AMOUNT_MWK = 100.0


class PayChanguError(Exception):
    """Raised when the PayChangu API reports an error or is unreachable."""


def _http(method: str, path: str, data: Any = None, timeout: int = 30) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", f"Bearer {os.getenv('PAYCHANGU_SECRET_KEY', '').strip()}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            detail = {}
        msg = detail.get("message") or detail.get("error") or f"HTTP {e.code}"
        raise PayChanguError(str(msg)) from e
    except urllib.error.URLError as e:
        raise PayChanguError(f"PayChangu unreachable: {e.reason}") from e
    except (ValueError, OSError) as e:
        raise PayChanguError(f"PayChangu response parse failed: {e}") from e


def configured() -> bool:
    return bool(os.getenv("PAYCHANGU_SECRET_KEY", "").strip())


def _require_configured() -> None:
    if not configured():
        raise PayChanguError("PAYCHANGU_SECRET_KEY is not configured")


def create_deposit(amount: float, number: str, correspondent: str, **_: Any) -> dict[str, Any]:
    _require_configured()
    payload = {
        "payment_method": "mobile_money",
        "amount": str(amount),
        "currency": "MWK",
        "charge_id": None,
        "mobile": number,
        "mobile_money_operator_ref_id": correspondent,
    }
    return _http("POST", "/direct-charge/payments/initialize", payload)


def deposit_status(charge_id: str) -> dict[str, Any]:
    _require_configured()
    return _http("GET", f"/mobile-money/payments/{charge_id}/verify")


def create_withdrawal(amount: float, number: str, correspondent: str) -> dict[str, Any]:
    _require_configured()
    payload = {
        "mobile_money_operator_ref_id": correspondent,
        "mobile": number,
        "amount": str(amount),
        "charge_id": None,
    }
    return _http("POST", "/mobile-money/payouts/initialize", payload)


def withdrawal_status(charge_id: str) -> dict[str, Any]:
    _require_configured()
    return _http("GET", f"/mobile-money/payments/{charge_id}/verify")


def check_balance() -> float:
    return 0.0


def normalize_number(number: str) -> str:
    digits = "".join(number.split()).lstrip("0")
    if not digits.isdigit() or len(digits) < 9 or len(digits) > 10:
        raise PayChanguError("Phone number must be a valid MW number")
    return digits