"""Tests for the security posture of the Ketsa API.

Covers transport-independent defences: browser security headers, CORS
allowlist behaviour, OpenAPI doc gating, and rate limiting.
"""

import pytest
from fastapi.testclient import TestClient

from conftest import make_client


def _get(client: TestClient, path: str = "/api/home") -> dict[str, str]:
    return client.get(path).headers


def test_security_headers_present(client: TestClient) -> None:
    h = _get(client)
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert "default-src 'none'" in h["content-security-policy"]
    assert h["cross-origin-opener-policy"] == "same-origin"
    assert h["cross-origin-resource-policy"] == "same-origin"
    assert h["x-permitted-cross-domain-policies"] == "none"
    assert "geolocation=()" in h["permissions-policy"]


def test_cors_allows_configured_origin(client: TestClient) -> None:
    res = client.options(
        "/api/markets",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    res = client.options(
        "/api/markets",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # No explicit allow-origin is echoed back for disallowed origins.
    assert res.headers.get("access-control-allow-origin") is None


def test_cors_does_not_allow_credentials(client: TestClient) -> None:
    res = client.options(
        "/api/markets",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.headers.get("access-control-allow-credentials") != "true"


def test_docs_exposed_when_enabled() -> None:
    client = make_client(rate_limit=0, expose_docs=True)
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_hidden_when_disabled() -> None:
    client = make_client(rate_limit=0, expose_docs=False)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_rate_limit_returns_429(limited_client: TestClient) -> None:
    statuses = [limited_client.get("/api/health").status_code for _ in range(5)]
    # With limit=3 the 4th request onward is rejected with 429.
    assert statuses == [200, 200, 200, 429, 429]
    assert limited_client.get("/api/health").status_code == 429
