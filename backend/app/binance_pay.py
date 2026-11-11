"""Binance Pay merchant integration scaffold for crypto (USDT) deposits/payouts.

This module provides the integration points required by the app:
- create a deposit invoice per payment
- query/verify invoice status (for polling/reconciliation; webhooks must re-query)
- verify webhook authenticity
- (future) create payouts for withdrawals

IMPORTANT
--------
Real Binance Pay API calls require correct request signing and webhook
verification as specified by Binance's current merchant documentation. Signing
schemes, headers, endpoints, and payload shapes can change; this scaffold reads
configuration from environment variables and keeps provider calls isolated so
the exact API contract can be finalized with your Binance merchant credentials.

Do NOT credit deposits or finalize withdrawals solely on client input or an
unverified webhook payload. Always verify with the provider and keep operations
idempotent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class BinancePayError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    # Binance Pay merchant API base URL (sandbox/prod as configured).
    return (os.getenv("BINANCE_PAY_BASE_URL", "").strip() or "https://bpay.binanceapi.com").rstrip("/")


def _api_key() -> str:
    return os.getenv("BINANCE_PAY_API_KEY", "").strip()


def _secret_key() -> str:
    return os.getenv("BINANCE_PAY_SECRET_KEY", "").strip()


def configured() -> bool:
    return bool(_api_key() and _secret_key())


def webhook_configured() -> bool:
    # Webhook verification material depends on Binance's current mechanism
    # (e.g. certificate/public-key signature or shared secret). Configure via env.
    return bool(os.getenv("BINANCE_PAY_WEBHOOK_SECRET", "").strip() or os.getenv("BINANCE_PAY_WEBHOOK_PUBLIC_KEY", "").strip())


def crypto_settings() -> dict[str, Any]:
    # MWK wallet amounts are converted to USDT for invoicing using a configured
    # rate (MWK per 1 USDT). Set BINANCE_PAY_MWK_PER_USDT to a trusted/fixed rate
    # or update it from your pricing source.
    rate = float(os.getenv("BINANCE_PAY_MWK_PER_USDT", "1750") or 1750)
    if rate <= 0:
        rate = 1750.0
    expiry = int(os.getenv("BINANCE_PAY_INVOICE_EXPIRE_SECONDS", "1800") or 1800)
    if expiry < 300:
        expiry = 300
    return {
        "currency": (os.getenv("BINANCE_PAY_CRYPTO_CURRENCY", "USDT").strip() or "USDT").upper(),
        "network": (os.getenv("BINANCE_PAY_CRYPTO_NETWORK", "TRC20").strip() or "TRC20").upper(),
        "mwk_per_usdt": rate,
        "expire_seconds": expiry,
    }


def _mwk_to_crypto(amount_mwk: float) -> float:
    rate = crypto_settings()["mwk_per_usdt"]
    # Round to 2dp for stable invoicing; adjust if your asset/network needs more precision.
    return round(float(amount_mwk) / rate, 2)


def _http(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Signed HTTP request scaffold.

    TODO: Implement Binance Pay request signing exactly per your merchant API
    version (headers such as timestamp/nonce/signature/certificate SN and the
    canonical string to sign). Until finalized, this raises a clear error.
    """
    if not configured():
        raise BinancePayError("BINANCE_PAY_API_KEY / BINANCE_PAY_SECRET_KEY are not configured", status_code=503)
    raise BinancePayError(
        "Binance Pay API signing/call is not finalized. Configure credentials and implement request signing per Binance merchant docs.",
        status_code=501,
    )


def create_deposit_invoice(*, payment_id: str, amount_mwk: float, wallet_id: str) -> dict[str, Any]:
    """Create a Binance Pay deposit invoice/order for a payment.

    Returns a normalized invoice dict used by the app:
      {provider, provider_charge_id, invoice_id, invoice_url, qr_code,
       deposit_address, crypto_amount, crypto_currency, crypto_network,
       expires_at, message, raw}

    If live API calls are not finalized, returns a pending invoice placeholder so
    the app can present per-payment invoice details and wiring, while clearly
    indicating provider configuration is required.
    """
    settings = crypto_settings()
    crypto_amount = _mwk_to_crypto(amount_mwk)
    expires_at = time.time() + settings["expire_seconds"]
    merchant_order_id = payment_id

    # Attempt real provider call when fully implemented.
    try:
        raw = _http(
            "POST",
            "/binancepay/openapi/v3/order",  # verify exact endpoint for your account/version
            {
                "merchantTradeNo": merchant_order_id,
                "orderAmount": crypto_amount,
                "currency": settings["currency"],
                "goods": {
                    "goodsType": "02",
                    "goodsCategory": "Z000",
                    "referenceGoodsId": wallet_id,
                    "goodsName": "Ketsa wallet deposit",
                },
            },
        )
    except BinancePayError as e:
        if e.status_code == 501 or not configured():
            # Placeholder invoice: per-payment, unique, non-credited, awaiting
            # provider integration/confirmation.
            return {
                "provider": "binance_pay",
                "provider_charge_id": merchant_order_id,
                "invoice_id": merchant_order_id,
                "invoice_url": None,
                "qr_code": None,
                "deposit_address": None,
                "crypto_amount": crypto_amount,
                "crypto_currency": settings["currency"],
                "crypto_network": settings["network"],
                "expires_at": expires_at,
                "message": (
                    "Invoice created. Complete Binance Pay merchant API configuration to receive a payable QR/link; "
                    "deposits will be credited only after verified payment confirmation."
                ),
                "raw": {"placeholder": True},
            }
        raise

    data = raw.get("data") or {}
    return {
        "provider": "binance_pay",
        "provider_charge_id": str(data.get("prepayId") or data.get("merchantTradeNo") or merchant_order_id),
        "invoice_id": str(data.get("prepayId") or merchant_order_id),
        "invoice_url": data.get("universalUrl") or data.get("checkoutUrl") or data.get("deeplink"),
        "qr_code": data.get("qrcodeLink") or data.get("qrContent"),
        "deposit_address": None,
        "crypto_amount": crypto_amount,
        "crypto_currency": settings["currency"],
        "crypto_network": settings["network"],
        "expires_at": float(data.get("expireTime", expires_at * 1000)) / (1000.0 if float(data.get("expireTime", 0) or 0) > 10_000_000_000 else 1.0),
        "message": "Awaiting crypto payment confirmation.",
        "raw": raw,
    }


def query_deposit(invoice_or_order_id: str) -> dict[str, Any]:
    """Query invoice/order status from Binance Pay (for polling/reconciliation)."""
    return _http("POST", "/binancepay/openapi/v2/order/query", {"prepayId": invoice_or_order_id})


def verify_webhook(raw_body: bytes, headers: dict[str, str]) -> bool:
    """Verify Binance Pay webhook authenticity.

    TODO: Implement exact verification per Binance docs (e.g. verify signature
    using provided certificate/public key over timestamp+nonce+body). Current
    fallback supports HMAC-SHA512 over raw body with BINANCE_PAY_WEBHOOK_SECRET
    if you configure a compatible scheme; otherwise returns False (fail closed).
    """
    secret = os.getenv("BINANCE_PAY_WEBHOOK_SECRET", "").strip()
    signature = (headers.get("BinancePay-Signature") or headers.get("binancepay-signature") or headers.get("Signature") or "").strip()
    if not signature:
        return False
    if secret:
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest().upper()
        try:
            return hmac.compare_digest(expected, signature.upper())
        except Exception:
            return False
    # Public-key/certificate verification required but not configured/implemented.
    return False


def payment_state(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Map a Binance Pay status payload to (pending|completed|failed, message)."""
    if not isinstance(payload, dict):
        return "pending", None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(data.get("status") or payload.get("bizStatus") or "").upper()
    msg = data.get("msg") or data.get("message") or payload.get("bizStatusDesc")
    if status in {"PAID", "SUCCESS", "COMPLETED"}:
        return "completed", (str(msg) if msg else "Payment confirmed.")
    if status in {"EXPIRED", "CANCELED", "CANCELLED", "FAILED", "ERROR"}:
        return "failed", (str(msg) if msg else "Payment not completed.")
    return "pending", (str(msg) if msg else None)
