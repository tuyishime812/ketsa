"""wandePay mobile-money gateway integration (MWK — Airtel Money / TNM Mpamba).

This module is the thin server-to-server client for the wandePay API
(https://wandepay.site). Per wandePay's integration guide the API must only be
called from the backend — never from browser JavaScript — and every request
authenticates with ``KETSA_WANDE_TOKEN`` sent as a form field.

Endpoints used:
    POST {base}/deposits.php      create a deposit
    POST {base}/status.php        check deposit status by wandePay id
    POST {base}/with.php          create a withdrawal (payout to mobile number)
    POST {base}/withdrawST.php    check withdrawal status by payout id
    POST {base}/balance.php       merchant account balance

There is no webhook: success is determined by polling status until
``transaction_status == COMPLETED``. Callers persist order state and are
responsible for crediting/debiting wallets idempotently (see main.py).
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL_DEFAULT = "https://apiv1.wandepay.site/api/"
CORRESPONDENTS = ("AIRTEL_MWI", "TNM_MWI")
MIN_AMOUNT_MWK = 100.0


class WandeError(Exception):
    """Raised when the wandePay API reports an error or is unreachable."""


def _http_post(url: str, data: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    """POST url-encoded form data; returns the parsed JSON response."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
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
        raise WandeError(str(msg)) from e
    except urllib.error.URLError as e:
        raise WandeError(f"wandePay unreachable: {e.reason}") from e
    except (ValueError, OSError) as e:
        raise WandeError(f"wandePay response parse failed: {e}") from e


def configured() -> bool:
    return bool(os.getenv("KETSA_WANDE_TOKEN", "").strip())


def _endpoint(name: str, **fields: Any) -> dict[str, Any]:
    if not configured():
        raise WandeError("KETSA_WANDE_TOKEN is not configured")
    base = os.getenv("KETSA_WANDE_BASE_URL", BASE_URL_DEFAULT).rstrip("/")
    token = os.getenv("KETSA_WANDE_TOKEN", "").strip()
    return _http_post(f"{base}/{name}", {**fields, "token": token})


def _require_success(payload: dict[str, Any]) -> None:
    """Raise on wandePay error envelopes; success means status == 'success'."""
    if payload.get("status") != "success":
        msg = (
            payload.get("message")
            or (payload.get("data") or {}).get("message")
            or "wandePay request failed"
        )
        raise WandeError(str(msg))


def create_deposit(
    amount: float,
    number: str,
    correspondent: str,
    product_id: str | None = None,
) -> dict[str, Any]:
    """Start a deposit; returns the raw payload including the wandePay tx id."""
    fields: dict[str, Any] = {
        "amount": amount,
        "number": number.lstrip("0"),
        "correspondent": correspondent,
    }
    if product_id:
        fields["productID"] = product_id
    payload = _endpoint("deposits.php", **fields)
    _require_success(payload)
    return payload


def deposit_status(wande_id: str) -> dict[str, Any]:
    """Poll a deposit's status. e.g. ``{"transaction_status": "COMPLETED"}``."""
    return _endpoint("status.php", depositId=wande_id)


def create_withdrawal(
    amount: float,
    number: str,
    correspondent: str,
) -> dict[str, Any]:
    """Start a payout; returns the raw payload (payoutId in ``data``)."""
    fields: dict[str, Any] = {
        "amount": amount,
        "number": number.lstrip("0"),
        "correspondent": correspondent,
    }
    payload = _endpoint("with.php", **fields)
    _require_success(payload)
    return payload


def withdrawal_status(wande_id: str) -> dict[str, Any]:
    """Poll a withdrawal's status. e.g. ``{"withdrawal_status": "COMPLETED"}``."""
    return _endpoint("withdrawST.php", withdrawSTId=wande_id)


def check_balance() -> float:
    """Return the merchant's available wandePay balance in MWK."""
    payload = _endpoint("balance.php")
    if payload.get("success") is not True:
        raise WandeError(str(payload.get("message") or "Balance check failed"))
    return float(payload.get("total_balance") or 0.0)


def normalize_number(number: str) -> str:
    """Strip spaces, drop the leading 0, and validate a Malawian mobile number."""
    digits = "".join(number.split()).lstrip("0")
    if not digits.isdigit() or len(digits) < 9 or len(digits) > 10:
        raise WandeError("Phone number must be a valid 10-digit MW number")
    return digits