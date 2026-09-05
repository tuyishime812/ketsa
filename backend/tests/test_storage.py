"""Tests for storage backend selection and the Supabase backend guards.

The Supabase backend is exercised only at the wiring level: selection by env,
clear error messages when the package or credentials are missing, and the
memory fallback used by the rest of the suite. No live Supabase calls happen.
"""

import os

import pytest

from app.storage import MemoryBackend, SupabaseBackend, select_backend


@pytest.fixture(autouse=True)
def _clear_db_env(monkeypatch):
    monkeypatch.delenv("KETSA_DB_BACKEND", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)


def test_default_backend_is_memory(monkeypatch):
    monkeypatch.delenv("KETSA_DB_BACKEND", raising=False)
    assert isinstance(select_backend(), MemoryBackend)


def test_memory_backend_selected_explicitly(monkeypatch):
    monkeypatch.setenv("KETSA_DB_BACKEND", "memory")
    assert isinstance(select_backend(), MemoryBackend)


@pytest.mark.parametrize("value", ["sqlite", ""])
def test_sqlite_and_empty_map_to_memory(monkeypatch, value):
    if value:
        monkeypatch.setenv("KETSA_DB_BACKEND", value)
    else:
        monkeypatch.delenv("KETSA_DB_BACKEND", raising=False)
    assert isinstance(select_backend(), MemoryBackend)


def test_supabase_backend_selected(monkeypatch):
    monkeypatch.setenv("KETSA_DB_BACKEND", "supabase")
    assert isinstance(select_backend(), SupabaseBackend)


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("KETSA_DB_BACKEND", "mysql")
    with pytest.raises(ValueError, match="Unknown KETSA_DB_BACKEND"):
        select_backend()


def test_supabase_requires_env_credentials(monkeypatch):
    monkeypatch.setenv("KETSA_DB_BACKEND", "supabase")
    backend = SupabaseBackend()
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        _ = backend.client


def test_supabase_partial_env_still_raises(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    backend = SupabaseBackend()
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY"):
        _ = backend.client


def test_reset_backend_swaps_the_active_backend(monkeypatch):
    """reset_backend() must hand out a fresh backend instance."""
    from app.storage import get_backend, reset_backend

    monkeypatch.setenv("KETSA_DB_BACKEND", "memory")
    reset_backend()
    first = get_backend()
    reset_backend()
    assert get_backend() is not first