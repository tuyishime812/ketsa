"""Startup resilience tests.

The API used to call ``init_db()`` unguarded at import time. A transient
Supabase/DNS failure therefore crashed the process before it could answer even
``/api/health`` (and uvicorn's reloader turned that into a crash loop). These
tests pin the retry/degrade behaviour and the ``/health`` alias.
"""

import httpx
import pytest

from app import main


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Retries are about correctness here, not wall-clock time.
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: None)


def test_retries_transient_transport_errors(monkeypatch):
    calls = {"n": 0}

    def flaky_init():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("getaddrinfo failed")

    monkeypatch.setattr(main, "init_db", flaky_init)
    main._init_storage_with_retry(attempts=3)

    assert calls["n"] == 3


def test_degrades_after_exhausting_transient_retries(monkeypatch, caplog):
    calls = {"n": 0}

    def always_offline():
        calls["n"] += 1
        raise httpx.ConnectError("getaddrinfo failed")

    monkeypatch.setattr(main, "init_db", always_offline)
    with caplog.at_level("ERROR", logger="ketsa.main"):
        main._init_storage_with_retry(attempts=2)

    assert calls["n"] == 2
    assert "still unreachable" in caplog.text


def test_non_transient_errors_still_fail_fast(monkeypatch):
    calls = {"n": 0}

    def misconfigured():
        calls["n"] += 1
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    monkeypatch.setattr(main, "init_db", misconfigured)
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        main._init_storage_with_retry(attempts=3)

    assert calls["n"] == 1


def test_create_app_survives_a_transient_storage_outage(monkeypatch):
    monkeypatch.setattr(
        main, "init_db", lambda: (_ for _ in ()).throw(httpx.ConnectError("offline"))
    )

    app = main.create_app()

    assert app is not None


def test_health_has_short_alias(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


def test_read_retries_once_on_transient_transport_error():
    from app.storage import SupabaseBackend

    backend = SupabaseBackend()
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        is_first = calls["n"] == 1

        class Query:
            def execute(self):
                if is_first:
                    raise httpx.ReadError("connection reset")
                return type("Result", (), {"data": ["ok"]})()

        return Query()

    assert backend._read(build).data == ["ok"]
    assert calls["n"] == 2


def test_read_does_not_retry_non_transient_errors():
    from app.storage import SupabaseBackend

    backend = SupabaseBackend()
    calls = {"n": 0}

    def build():
        calls["n"] += 1

        class Query:
            def execute(self):
                raise ValueError("bad query")

        return Query()

    with pytest.raises(ValueError, match="bad query"):
        backend._read(build)
    assert calls["n"] == 1

