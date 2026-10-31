"""Tests for the single-replica guard (app/replica.py)."""

import os
from unittest import mock

import pytest

from app import replica


def test_worker_count_single_when_unknown() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        # Default assumption: one process.
        assert replica.worker_count() == 1


def test_worker_count_takes_max_of_hints() -> None:
    with mock.patch.dict(
        os.environ, {"WEB_CONCURRENCY": "2", "UVICORN_WORKERS": "4"}, clear=True
    ):
        assert replica.worker_count() == 4


def test_check_passes_for_single() -> None:
    with mock.patch.dict(os.environ, {}, clear=True):
        replica.check_single_replica(locked=False)


def test_check_stands_down_when_locked() -> None:
    with mock.patch.dict(os.environ, {"WEB_CONCURRENCY": "3"}, clear=True):
        replica.check_single_replica(locked=True)


def test_check_allows_with_explicit_override() -> None:
    with mock.patch.dict(
        os.environ, {"WEB_CONCURRENCY": "2", "KETSA_ALLOW_MULTI_WORKER": "1"}, clear=True
    ):
        replica.check_single_replica(locked=False)


def test_check_raises_on_multi_without_lock_or_override() -> None:
    with mock.patch.dict(os.environ, {"UVICORN_WORKERS": "2"}, clear=True):
        with pytest.raises(replica.MultiWorkerError):
            replica.check_single_replica(locked=False)
