"""PayChangu payment gateway integration (MWK — Airtel Money / TNM Mpamba).

Thin server-to-server client for the PayChangu API (https://api.paychangu.com).
The secret key is sent as a Bearer token.

The integration follows PayChangu's *Direct Charge → Mobile Money* flow:

* **Deposit** — ``POST /mobile-money/payments/initialize`` with a unique
  ``charge_id`` (we use the payment record id, which doubles as the
  idempotency key and the webhook correlation id).
* **Deposit status** — ``GET /mobile-money/payments/{chargeId}/verify``.
* **Withdrawal** — ``POST /mobile-money/payouts/initialize`` with the same
  ``charge_id`` contract.
* **Withdrawal status** — ``GET /mobile-money/payments/{chargeId}/details``.
* **Webhooks** — HMAC-SHA256 of the *raw* request body, keyed with
  ``PAYCHANGU_WEBHOOK_SECRET``. A webhook is only ever a hint: the caller
  re-queries the provider before crediting or refunding anything.

Environment:
  PAYCHANGU_SECRET_KEY       required for any payment call
  PAYCHANGU_WEBHOOK_SECRET   required to accept webhooks
  PAYCHANGU_BASE_URL         optional (sandbox/proxy override)
  PAYCHANGU_AIRTEL_REF       optional operator UUID override
  PAYCHANGU_TNM_REF          optional operator UUID override
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://api.paychangu.com"
MIN_AMOUNT_MWK = 100.0

# PayChangu identifies mobile-money operators by an opaque UUID (GET
# /mobile-money), not by the "AIRTEL"/"TNM" short code. These are the
# documented defaults; override via env if PayChangu rotates them.
_DEFAULT_OPERATOR_REFS = {
    "AIRTEL": "20be6c20-adeb-4b5b-a7ba-0769820df4fb",
    "TNM": "27494cb5-ba9e-437f-a114-4e7a7686bcca",
}

# Short codes accepted by the API, plus the legacy `_MWI` values the frontend
# has always sent. Everything is normalised to AIRTEL / TNM before use.
# USDT is supported as a crypto deposit rail (non-PayChangu).
_OPERATOR_ALIASES = {
    "AIRTEL": "AIRTEL",
    "AIRTEL_MWI": "AIRTEL",
    "TNM": "TNM",
    "TNM_MWI": "TNM",
    "USDT": "USDT",
    "CRYPTO": "USDT",
    "CRYPTO_USDT": "USDT",
}
CORRESPONDENTS = tuple(_OPERATOR_ALIASES)

# Provider statuses that mean "no money will ever move" (safe to refund).
_FAILED_STATES = {
    "failed",
    "failure",
    "declined",
    "cancelled",
    "canceled",
    "reversed",
    "error",
    "expired",
    "rejected",
}
_COMPLETED_STATES = {"success", "successful", "completed", "complete", "paid"}


class PayChanguError(Exception):
    """Raised when the PayChangu API reports an error or is unreachable.

    ``status_code`` is set when PayChangu answered with an HTTP status (a
    definitive rejection for 4xx). It stays ``None`` for transport/timeout
    failures, where the request may or may not have been accepted — callers
    must treat that as ambiguous and reconcile rather than refund.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    # Read lazily: `create_app()` loads backend/.env *after* this module is
    # imported, so a module-level constant would miss local configuration.
    return (os.getenv("PAYCHANGU_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")


def _secret() -> str:
    return os.getenv("PAYCHANGU_SECRET_KEY", "").strip()


def _http(method: str, path: str, data: Any = None, timeout: int = 30) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", f"Bearer {_secret()}")
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
        raise PayChanguError(str(msg), status_code=e.code) from e
    except urllib.error.URLError as e:
        raise PayChanguError(f"PayChangu unreachable: {e.reason}") from e
    except (ValueError, OSError) as e:
        raise PayChanguError(f"PayChangu response parse failed: {e}") from e


def configured() -> bool:
    return bool(_secret())


def webhook_configured() -> bool:
    return bool(os.getenv("PAYCHANGU_WEBHOOK_SECRET", "").strip())


def _require_configured() -> None:
    if not configured():
        raise PayChanguError("PAYCHANGU_SECRET_KEY is not configured")


# --- Operators / phone numbers -------------------------------------------------


def normalize_correspondent(value: str) -> str:
    """Map an operator alias to PayChangu's short code (``AIRTEL`` / ``TNM``)."""
    key = (value or "").strip().upper()
    canonical = _OPERATOR_ALIASES.get(key)
    if canonical is None:
        raise PayChanguError("Unknown mobile-money operator")
    return canonical


def operator_ref(correspondent: str) -> str:
    """Return the operator UUID PayChangu expects for an operator short code."""
    canonical = normalize_correspondent(correspondent)
    env_key = f"PAYCHANGU_{canonical}_REF"
    return os.getenv(env_key, "").strip() or _DEFAULT_OPERATOR_REFS[canonical]


def normalize_number(number: str) -> str:
    """Normalise a Malawian mobile number to E.164 (``+265991234567``).

    Accepts local (``0991 234 567``), country-code (``265991234567``) and
    already-E.164 input. PayChangu's examples use the ``+265`` form.
    """
    digits = re.sub(r"\D", "", number or "")
    if digits.startswith("265"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[89]\d{8}", digits):
        raise PayChanguError("Phone number must be a valid MW number")
    return f"+265{digits}"


def normalize_payment_contact(number: str, correspondent: str) -> str:
    """Return a normalized contact reference for the selected rail.

    Mobile money rails require a valid Malawian MSISDN. Crypto rails accept a
    wallet address / transaction reference string (kept opaque, length-bounded).
    """
    canonical = normalize_correspondent(correspondent)
    if canonical == "USDT":
        ref = (number or "").strip()
        if not ref:
            return "USDT"
        if len(ref) > 128:
            raise PayChanguError("Crypto reference is too long")
        return ref
    return normalize_number(number)


# --- Status parsing ------------------------------------------------------------


def charge_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Reduce a PayChangu verify/init payload to (state, message).

    ``state`` is one of ``pending`` / ``completed`` / ``failed``. PayChangu is
    inconsistent between endpoints (``status: "successful"`` at the top level
    vs ``data.status: "success"``), so both are inspected.
    """
    if not isinstance(payload, dict):
        return "pending", None
    data = payload.get("data")
    # `/mobile-money` returns a list here; charge endpoints return an object.
    # Anything else must degrade to "pending", never raise on the poll path.
    if not isinstance(data, dict):
        data = {}
    top = str(payload.get("status") or "").strip().lower()
    inner = str(data.get("status") or "").strip().lower()
    message = payload.get("message") or data.get("message")

    if top in _FAILED_STATES or inner in _FAILED_STATES:
        return "failed", (str(message) if message else None)
    # Completion must be asserted by the *transaction* status. PayChangu uses
    # "success" at the top level merely to mean "the request was accepted" (a
    # successful init is `status: success` with `data.status: pending`), so a
    # bare top-level success must never settle a payment: doing so would credit
    # a deposit before the money moved.
    if inner in _COMPLETED_STATES:
        return "completed", (str(message) if message else None)
    return "pending", (str(message) if message else None)


def provider_reference(payload: dict[str, Any]) -> str | None:
    """Extract PayChangu's charge id from an init response."""
    data = payload.get("data") or {}
    ref = data.get("charge_id") or data.get("chargeId")
    return str(ref) if ref else None


# --- Webhooks ------------------------------------------------------------------


def verify_webhook(raw_body: bytes, signature: str | None) -> bool:
    """Constant-time HMAC-SHA256 check of a PayChangu webhook signature.

    PayChangu sends the hex digest in the ``Signature`` header. Some proxies
    prefix it with ``sha256=``; both forms are accepted.
    """
    secret = os.getenv("PAYCHANGU_WEBHOOK_SECRET", "").strip()
    if not secret or not signature:
        return False
    supplied = signature.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, supplied)
    except TypeError:
        # compare_digest() rejects non-ASCII str input; a crafted header must
        # yield an authentication failure, never a 500.
        return False


# --- API calls -----------------------------------------------------------------


def create_deposit(
    amount: float,
    number: str,
    correspondent: str,
    charge_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Initialise a mobile-money direct charge.

    ``charge_id`` is generated by the caller (payment record id) so it is
    unique, stable across retries and echoed back by the webhook.
    """
    _require_configured()
    if not charge_id:
        raise PayChanguError("A charge_id is required for an idempotent deposit")
    api_mobile = re.sub(r"^\+265", "", number)
    payload = {
        "mobile": api_mobile or number,
        "mobile_money_operator_ref_id": operator_ref(correspondent),
        "amount": str(round(float(amount), 2)),
        "charge_id": charge_id,
    }
    return _http("POST", "/mobile-money/payments/initialize", payload)


def deposit_status(charge_id: str) -> dict[str, Any]:
    _require_configured()
    ref = urllib.parse.quote(str(charge_id), safe="")
    return _http("GET", f"/mobile-money/payments/{ref}/verify")


def create_withdrawal(
    amount: float,
    number: str,
    correspondent: str,
    charge_id: str | None = None,
) -> dict[str, Any]:
    _require_configured()
    if not charge_id:
        raise PayChanguError("A charge_id is required for an idempotent payout")
    api_mobile = re.sub(r"^\+265", "", number)
    payload = {
        "mobile": api_mobile or number,
        "mobile_money_operator_ref_id": operator_ref(correspondent),
        "amount": str(round(float(amount), 2)),
        "charge_id": charge_id,
    }
    return _http("POST", "/mobile-money/payouts/initialize", payload)


def withdrawal_status(charge_id: str) -> dict[str, Any]:
    _require_configured()
    ref = urllib.parse.quote(str(charge_id), safe="")
    return _http("GET", f"/mobile-money/payments/{ref}/details")


def check_balance(currency: str = "MWK") -> float:
    """Return the PayChangu merchant balance for ``currency`` (0.0 if unknown)."""
    _require_configured()
    payload = _http("GET", f"/wallet-balance?currency={urllib.parse.quote(currency)}")
    data = payload.get("data") or {}
    for key in ("main_balance", "available_balance", "balance", "total_balance"):
        try:
            if data.get(key) is not None:
                return float(data[key])
        except (TypeError, ValueError):
            continue
    return 0.0
