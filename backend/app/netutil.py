"""Trustworthy client-IP resolution for rate limits and login throttles.

Why this module exists
----------------------
Security controls key on the caller's IP: the global/write rate limiters, the
admin brute-force lockout, and the per-IP OTP / sign-in-code throttle. Reading
``request.client.host`` directly is only correct when the backend is the public
edge. Behind a reverse proxy (Caddy/Nginx, Docker, Vercel's runtime proxy) every
request appears to come from the proxy, which collapses all callers into one
bucket:

* one visitor can exhaust the shared write budget and deny service to everyone;
* anyone can trip the admin lockout with a handful of failed logins, locking the
  site owner out of ``/admin`` (which settles real money);
* per-IP OTP throttles become one global counter.

Conversely, blindly trusting ``X-Forwarded-For`` lets a caller spoof any address
and evade every one of those limits.

Trust model
-----------
1. **Signed proxy header (preferred).** The Next.js runtime proxy shares
   ``KETSA_PROXY_SECRET`` with the backend and sends
   ``X-Ketsa-Client-IP``/``-Timestamp``/``-Signature`` where the signature is
   ``HMAC-SHA256(secret, "<ip>\\n<unix-ts>")``. The backend verifies the HMAC and
   a short timestamp window before trusting the address. This works even when
   the proxy's own egress IP is dynamic (serverless), and cannot be forged by a
   direct caller because they do not know the secret.
2. **Trusted-proxy CIDRs.** If ``KETSA_TRUSTED_PROXIES`` is set (comma-separated
   IPs/CIDRs), ``X-Forwarded-For`` is honoured *only* when the direct peer is in
   that list. The rightmost untrusted hop is the client, so a caller-prepended
   spoof is discarded.
3. **Direct connection.** With neither configured the direct peer is used,
   which is the correct (and safest) default for a locally exposed backend.

Malformed or partially-valid input falls back to the direct peer rather than
guessing, so a hostile header can never widen trust.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
from typing import Iterable, Optional

from fastapi import Request

logger = logging.getLogger("ketsa.netutil")

# How far the signed-proxy timestamp may drift, in seconds.
SIGNATURE_WINDOW_SECONDS = 300
# Cap how many X-Forwarded-For hops we will parse (CPU/memory guard).
MAX_FORWARDED_HOPS = 32

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network

_TRUSTED_CACHE: tuple[str, tuple[Network, ...]] | None = None


def _trusted_networks() -> tuple[Network, ...]:
    """Parse ``KETSA_TRUSTED_PROXIES`` (cached by raw value)."""
    global _TRUSTED_CACHE
    raw = os.getenv("KETSA_TRUSTED_PROXIES", "")
    if _TRUSTED_CACHE is not None and _TRUSTED_CACHE[0] == raw:
        return _TRUSTED_CACHE[1]

    networks: list[Network] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid KETSA_TRUSTED_PROXIES entry %r", part)
    parsed = tuple(networks)
    _TRUSTED_CACHE = (raw, parsed)
    return parsed


def _parse_ip(raw: str | None) -> Optional[IPAddress]:
    """Parse an address that may carry a port or IPv6 brackets."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    # [2001:db8::1]:443
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        value = value[1:end]
    # 203.0.113.5:443 (a bare IPv6 address has more than one colon)
    elif value.count(":") == 1:
        host, _, port = value.rpartition(":")
        if port.isdigit():
            value = host
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_trusted(ip: IPAddress, networks: Iterable[Network]) -> bool:
    return any(ip in network for network in networks)


def _expected_signature(secret: str, ip: str, timestamp: str) -> str:
    message = f"{ip}\n{timestamp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _verify_signed_ip(
    *,
    secret: str,
    ip_header: str | None,
    ts_header: str | None,
    sig_header: str | None,
    now: float,
) -> Optional[IPAddress]:
    """Return the verified address, or None when anything is off."""
    if not (ip_header and ts_header and sig_header):
        return None
    ip = _parse_ip(ip_header)
    if ip is None:
        return None
    try:
        ts = int(ts_header)
    except ValueError:
        return None
    if abs(now - ts) > SIGNATURE_WINDOW_SECONDS:
        return None
    expected = _expected_signature(secret, str(ip), ts_header)
    if not hmac.compare_digest(expected, sig_header.strip()):
        return None
    return ip


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    *,
    now: float | None = None,
    proxy_secret: str | None = None,
    signed_ip: str | None = None,
    signed_ts: str | None = None,
    signed_sig: str | None = None,
) -> str:
    """Resolve the caller address from the peer + proxy metadata.

    Pure function (no Request/env access) so it can be unit-tested directly.
    """
    import time

    current = time.time() if now is None else now
    peer_ip = _parse_ip(peer)

    if proxy_secret:
        verified = _verify_signed_ip(
            secret=proxy_secret,
            ip_header=signed_ip,
            ts_header=signed_ts,
            sig_header=signed_sig,
            now=current,
        )
        if verified is not None:
            return str(verified)

    networks = _trusted_networks()
    if peer_ip is None:
        # Non-IP peer (unix socket, test client): use the transport value
        # verbatim. X-Forwarded-For cannot be trusted because there is no way
        # to check whether the peer is a proxy.
        return peer or "unknown"
    if not networks or not _is_trusted(peer_ip, networks):
        # Not behind a trusted proxy: the transport peer is authoritative, and
        # any X-Forwarded-For value is caller-controlled noise.
        return str(peer_ip)

    if not forwarded_for:
        return str(peer_ip)

    hops = [h for h in forwarded_for.split(",")][:MAX_FORWARDED_HOPS]
    parsed: list[IPAddress] = []
    for hop in hops:
        address = _parse_ip(hop)
        if address is None:
            # A malformed chain is not trustworthy: fall back to the peer.
            return str(peer_ip)
        parsed.append(address)

    # Walk right-to-left (closest proxy first) and return the first hop the
    # proxy chain did not itself add.
    for address in reversed(parsed):
        if not _is_trusted(address, networks):
            return str(address)

    # Every hop is trusted (e.g. an internal service chain): the leftmost entry
    # is the originating client.
    return str(parsed[0]) if parsed else str(peer_ip)


def client_ip(request: Request) -> str:
    """Resolve the security-relevant client IP for a FastAPI request."""
    headers = request.headers
    return resolve_client_ip(
        request.client.host if request.client else None,
        headers.get("x-forwarded-for"),
        proxy_secret=os.getenv("KETSA_PROXY_SECRET") or None,
        signed_ip=headers.get("x-ketsa-client-ip"),
        signed_ts=headers.get("x-ketsa-client-timestamp"),
        signed_sig=headers.get("x-ketsa-client-signature"),
    )
