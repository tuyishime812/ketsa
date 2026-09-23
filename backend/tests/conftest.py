"""Shared pytest fixtures for the Ketsa backend test-suite.

The application factory reads configuration from the environment at
`create_app()` time, so each test can build an app with its own settings
without leaking state into other tests.
"""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Never let the test-suite talk to a real database.
#
# ``app.config`` loads ``backend/.env`` (gitignored) at import time, so a dev
# whose local .env points at Supabase (KETSA_DB_BACKEND=supabase) would
# otherwise run the whole suite — plus the import-time ``create_app()`` in
# ``app/main.py`` — against the live project: seeding content, creating real
# wallet/payment/user rows, and wiping markets on a reset test. Pin the
# in-process store here, *before* the app is imported, so both the import-time
# app and every test app are memory backed. CI has no backend/.env, so this is
# a no-op there. See tests/test_storage.py for the backend-selection tests,
# which still manipulate the env var explicitly (monkeypatch restores it).
# ---------------------------------------------------------------------------
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
os.environ["KETSA_DB_BACKEND"] = "memory"
# Pin the admin gate too — a dev .env's KETSA_ADMIN_PASSWORD would otherwise
# make every admin-login test 401 (config.py never overrides existing vars,
# so this assignment wins over backend/.env at import time).
os.environ["KETSA_ADMIN_PASSWORD"] = "ketsa-admin"

from app.engine import engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.storage import reset_backend  # noqa: E402


def make_client(rate_limit: int = 0, expose_docs: bool = True) -> TestClient:
    """Return a TestClient for an app built with the given env overrides."""
    reset_backend()  # fresh seeded store per test run
    engine.reset()   # fresh wallet/book runtime per test run
    with mock.patch.dict(
        os.environ,
        {
            "KETSA_RATE_LIMIT_PER_MIN": str(rate_limit),
            "KETSA_EXPOSE_DOCS": "1" if expose_docs else "0",
        },
        clear=False,
    ):
        return TestClient(create_app())


@pytest.fixture()
def client() -> TestClient:
    """A client with rate limiting disabled and docs enabled."""
    return make_client(rate_limit=0, expose_docs=True)


@pytest.fixture()
def limited_client() -> TestClient:
    """A client with a strict per-IP rate limit to exercise 429 handling."""
    return make_client(rate_limit=3, expose_docs=False)
