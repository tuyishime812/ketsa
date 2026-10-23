"""Tests for trusted-proxy client-IP resolution.

The resolver decides which address the rate limiters, admin lockout and OTP
throttles key on, so these cases encode the security contract:

* with no proxy configured / an untrusted peer, X-Forwarded-For is ignored;
* with a trusted peer, the rightmost untrusted hop wins (a prepended spoof is
  discarded);
* the signed proxy header is accepted only with a valid HMAC + fresh timestamp;
* anything malformed falls back to the transport peer rather than guessing.
"""

import hashlib
import hmac

import pytest
from starlette.requests import Request

from app import netutil


def _request(peer: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/health",
        "raw_path": b"/api/health",
        "query_string": b"",
        "headers": raw_headers,
        "client": (peer, 50000),
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("KETSA_TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("KETSA_PROXY_SECRET", raising=False)
    # The trusted-network parse is cached by raw value; a fresh value clears it.
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "")
    yield


def test_no_proxy_config_uses_direct_peer() -> None:
    request = _request("198.51.100.7", {"x-forwarded-for": "203.0.113.9"})
    assert netutil.client_ip(request) == "198.51.100.7"


def test_non_ip_peer_is_preserved_verbatim() -> None:
    # e.g. Starlette's TestClient peer ("testclient") or a unix socket. It must
    # not collapse into "unknown", which would merge independent buckets.
    request = _request("testclient", {"x-forwarded-for": "203.0.113.9"})
    assert netutil.client_ip(request) == "testclient"


def test_untrusted_peer_cannot_spoof_forwarded_for(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "10.0.0.0/8")
    request = _request("198.51.100.7", {"x-forwarded-for": "203.0.113.9"})
    assert netutil.client_ip(request) == "198.51.100.7"


def test_trusted_peer_uses_forwarded_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "10.0.0.0/8")
    request = _request(
        "10.1.2.3",
        {"x-forwarded-for": "203.0.113.9, 10.1.2.3"},
    )
    assert netutil.client_ip(request) == "203.0.113.9"


def test_prepended_spoof_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "10.0.0.0/8")
    # A caller sends "1.2.3.4, <real client>"; the trusted proxy appends itself.
    request = _request(
        "10.1.2.3",
        {"x-forwarded-for": "1.2.3.4, 203.0.113.9, 10.1.2.3"},
    )
    assert netutil.client_ip(request) == "203.0.113.9"


def test_malformed_forwarded_for_falls_back_to_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "10.0.0.0/8")
    request = _request("10.1.2.3", {"x-forwarded-for": "not-an-ip, 203.0.113.9"})
    assert netutil.client_ip(request) == "10.1.2.3"


def test_all_hops_trusted_returns_leftmost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "10.0.0.0/8")
    request = _request("10.1.2.3", {"x-forwarded-for": "10.9.9.9, 10.1.2.3"})
    assert netutil.client_ip(request) == "10.9.9.9"


def test_ipv6_and_ports_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "::1/128")
    request = _request("::1", {"x-forwarded-for": "[2001:db8::5]:443"})
    assert netutil.client_ip(request) == "2001:db8::5"


def test_empty_forwarded_for_uses_trusted_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_TRUSTED_PROXIES", "10.0.0.0/8")
    request = _request("10.1.2.3")
    assert netutil.client_ip(request) == "10.1.2.3"


def _sign(secret: str, ip: str, ts: int) -> dict[str, str]:
    message = f"{ip}\n{ts}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "x-ketsa-client-ip": ip,
        "x-ketsa-client-timestamp": str(ts),
        "x-ketsa-client-signature": digest,
    }


def test_signed_proxy_header_is_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_PROXY_SECRET", "shared-secret")
    headers = _sign("shared-secret", "203.0.113.9", 1_700_000_000)
    resolved = netutil.resolve_client_ip(
        "10.0.0.1",
        None,
        now=1_700_000_000,
        proxy_secret="shared-secret",
        signed_ip="203.0.113.9",
        signed_ts="1700000000",
        signed_sig=headers["x-ketsa-client-signature"],
    )
    assert resolved == "203.0.113.9"


def test_forged_signed_header_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KETSA_PROXY_SECRET", "shared-secret")
    headers = _sign("wrong-secret", "203.0.113.9", 1_700_000_000)
    resolved = netutil.resolve_client_ip(
        "198.51.100.7",
        None,
        now=1_700_000_000,
        proxy_secret="shared-secret",
        signed_ip=headers["x-ketsa-client-ip"],
        signed_ts=headers["x-ketsa-client-timestamp"],
        signed_sig=headers["x-ketsa-client-signature"],
    )
    assert resolved == "198.51.100.7"


def test_expired_signed_header_is_ignored() -> None:
    headers = _sign("shared-secret", "203.0.113.9", 1_700_000_000)
    resolved = netutil.resolve_client_ip(
        "198.51.100.7",
        None,
        now=1_700_000_000 + netutil.SIGNATURE_WINDOW_SECONDS + 1,
        proxy_secret="shared-secret",
        signed_ip=headers["x-ketsa-client-ip"],
        signed_ts=headers["x-ketsa-client-timestamp"],
        signed_sig=headers["x-ketsa-client-signature"],
    )
    assert resolved == "198.51.100.7"


def test_signed_header_works_even_behind_untrusted_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    # Serverless proxies have dynamic egress IPs, so the signature (not the
    # peer address) is what establishes trust.
    monkeypatch.setenv("KETSA_PROXY_SECRET", "shared-secret")
    headers = _sign("shared-secret", "203.0.113.9", 1_700_000_000)
    resolved = netutil.resolve_client_ip(
        "198.51.100.7",
        "1.2.3.4",
        now=1_700_000_000,
        proxy_secret="shared-secret",
        signed_ip=headers["x-ketsa-client-ip"],
        signed_ts=headers["x-ketsa-client-timestamp"],
        signed_sig=headers["x-ketsa-client-signature"],
    )
    assert resolved == "203.0.113.9"
