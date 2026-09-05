"""Shared pytest fixtures for the Ketsa backend test-suite.

The application factory reads configuration from the environment at
`create_app()` time, so each test can build an app with its own settings
without leaking state into other tests.
"""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.engine import engine
from app.main import create_app
from app.storage import reset_backend


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
