"""Tests for the shared auth-state store (authstate.py + storage backends).

Two layers are covered:

1. The ``authstate`` facade over the in-memory backend (the same object the
   dev server and the whole test suite run on): sessions, admin sessions,
   SSO tickets, OTPs and throttle buckets, plus the lazy sweep and the reset
   used as fixture teardown.

2. The Supabase path, driven through a fake PostgREST client (no live
   database). This is where the interesting guarantees live:

   * tickets and OTPs are consumed by conditional DELETEs, so two "workers"
     racing to redeem the same ticket or burn the same code cannot both win;
   * an OTP at its attempt cap is dead *even with the correct code* (matches
     auth.py's historical increment-then-compare semantics — CWE-307);
   * every row survives a "restart": a brand-new backend object pointed at
     the same database sees the same sessions, tickets and codes.
"""

import time

import pytest

from app import authstate
from app import storage
from app.storage import SupabaseBackend

AUTH = "ketsa_auth"


# --- fake PostgREST client ---------------------------------------------------
# Minimal in-memory stand-in for the postgrest-py builder chain used by
# SupabaseBackend.auth_*. It emulates filter semantics (eq/gt/lt/lte), column
# projection, exact counts, ordering, and delete/update "return=representation"
# (`.data` holds the affected rows), which is what the atomicity claims rely on.


class _Resp:
    def __init__(self, rows, count=None):
        self.data = [dict(r) for r in rows]
        self.count = count


def _fits(row: dict, filters: list) -> bool:
    for op, col, val in filters:
        got = row.get(col)
        if op == "eq":
            if got != val:
                return False
        elif op == "gt":
            if not (isinstance(got, (int, float)) and got > val):
                return False
        elif op == "gte":
            if not (isinstance(got, (int, float)) and got >= val):
                return False
        elif op == "lt":
            if not (isinstance(got, (int, float)) and got < val):
                return False
        elif op == "lte":
            if not (isinstance(got, (int, float)) and got <= val):
                return False
    return True


class _Query:
    def __init__(self, table, op, *, columns=None, count=None, fields=None):
        self._table = table
        self._op = op
        self._columns = columns if columns is not None else ("*",)
        self._count = count
        self._fields = fields
        self._filters = []
        self._limit = None
        self._order = None

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def lt(self, col, val):
        self._filters.append(("lt", col, val))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, col, *, desc=False, **kw):
        self._order = (col, desc)
        return self

    def execute(self):
        rows = list(self._table._rows.values())
        rows = [r for r in rows if _fits(r, self._filters)]
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r: (r.get(col), r.get("id")), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._op == "delete":
            for r in rows:
                self._table._rows.pop(r["id"], None)
            return _Resp(rows)
        if self._op == "update":
            for r in rows:
                r.update(dict(self._fields))
            return _Resp(rows)
        cols = self._columns
        if cols == ("*",):
            out = [dict(r) for r in rows]
        else:
            out = [{c: r.get(c) for c in cols} for r in rows]
        return _Resp(out, count=len(rows) if self._count == "exact" else None)


class _Table:
    def __init__(self, client, name):
        self._rows = client._tables.setdefault(name, {})

    def select(self, *cols, count=None, **kw):
        return _Query(self, "select", columns=cols, count=count)

    def delete(self, **kw):
        return _Query(self, "delete")

    def update(self, fields, **kw):
        return _Query(self, "update", fields=fields)

    def upsert(self, payload, **kw):
        for r in payload if isinstance(payload, list) else [payload]:
            self._rows[r["id"]] = dict(r)
        return _Query(self, "select")


class FakeClient:
    def __init__(self):
        self._tables = {}

    def table(self, name):
        return _Table(self, name)


def _fake_backend() -> SupabaseBackend:
    b = SupabaseBackend()
    b._client = FakeClient()
    return b


# --- authstate facade over the memory backend --------------------------------


@pytest.fixture(autouse=True)
def _clean_state():
    """Every test starts from (and ends on) an empty shared store."""
    authstate.reset()
    yield
    authstate.reset()


def test_sessions_round_trip_and_slide() -> None:
    authstate.put_session("digest-1", "user-7", issued=100.0, expires=1_000.0)
    assert authstate.get_session("digest-1") == (1_000.0, "user-7")
    assert authstate.get_session("missing") is None
    assert authstate.session_count() == 1

    authstate.touch_session("digest-1", 2_000.0)
    assert authstate.get_session("digest-1") == (2_000.0, "user-7")

    authstate.delete_sessions_for_user("user-7")
    assert authstate.session_count() == 0


def test_sessions_scoped_per_user() -> None:
    authstate.put_session("a", "u1", issued=1.0, expires=1_000.0)
    authstate.put_session("b", "u2", issued=1.0, expires=1_000.0)
    authstate.put_session("c", "u1", issued=1.0, expires=1_000.0)
    assert authstate.delete_sessions_for_user("u1") == 2
    assert authstate.session_count() == 1
    assert authstate.get_session("b") is not None


def test_admin_sessions() -> None:
    authstate.put_admin_session("digest", 1_000.0)
    assert authstate.get_admin_session("digest") == 1_000.0
    authstate.touch_admin_session("digest", 2_000.0)
    assert authstate.get_admin_session("digest") == 2_000.0
    authstate.delete_admin_session("digest")
    assert authstate.get_admin_session("digest") is None


def test_ticket_is_single_use_even_when_unexpired() -> None:
    now = time.time()
    authstate.put_ticket("t1", "user-7", issued=now, expires=now + 60)
    taken = authstate.take_ticket("t1")
    assert taken is not None and taken["user_id"] == "user-7"
    # Second redemption fails even though the ticket never expired.
    assert authstate.take_ticket("t1") is None
    assert authstate.ticket_count() == 0


def test_ticket_count_and_oldest() -> None:
    now = time.time()
    authstate.put_ticket("new", "u1", issued=now + 50, expires=now + 60)
    authstate.put_ticket("old", "u2", issued=now - 50, expires=now + 60)
    authstate.put_ticket("mid", "u3", issued=now, expires=now + 60)
    assert authstate.ticket_count() == 3
    assert authstate.oldest_tickets(2) == ["old", "mid"]


def test_expire_ticket_helper() -> None:
    now = time.time()
    authstate.put_ticket("t1", "u1", issued=now, expires=now + 60)
    authstate.expire_ticket("t1", now - 1)
    authstate.sweep()
    assert authstate.ticket_count() == 0


def test_otp_round_trip_and_atomic_consume() -> None:
    now = time.time()
    authstate.put_otp("signup:a@b.io", "hash-1", {"name": "Alice"}, issued=now, expires=now + 600)
    entry = authstate.get_otp("signup:a@b.io")
    assert entry is not None and entry["payload"] == {"name": "Alice"}

    # Wrong code: not burned; auth.py's flow bumps the failed-guess counter.
    assert authstate.consume_otp("signup:a@b.io", "wrong", max_attempts=5, now=now) is None
    authstate.bump_otp_attempts("signup:a@b.io", max_attempts=5, now=now)
    entry = authstate.get_otp("signup:a@b.io")
    assert entry is not None and entry["attempts"] == 1

    # Correct code: burned exactly once.
    assert authstate.consume_otp("signup:a@b.io", "hash-1", max_attempts=5, now=now) is not None
    assert authstate.get_otp("signup:a@b.io") is None


def test_otp_is_dead_at_attempt_cap_even_with_correct_code() -> None:
    """CWE-307: five wrong guesses kill the code; the sixth is rejected too."""
    now = time.time()
    authstate.put_otp("login:u1", "hash-1", None, issued=now, expires=now + 600)
    max5 = 5
    for _ in range(5):
        assert authstate.consume_otp("login:u1", "wrong", max_attempts=max5, now=now) is None
        authstate.bump_otp_attempts("login:u1", max_attempts=max5, now=now)
    entry = authstate.get_otp("login:u1")
    assert entry is not None and entry["attempts"] == 5
    # At the cap the atomic consume refuses even the right digest.
    assert authstate.consume_otp("login:u1", "hash-1", max_attempts=max5, now=now) is None
    # And bumping no longer pushes the counter past the cap.
    authstate.bump_otp_attempts("login:u1", max_attempts=max5, now=now)
    assert authstate.get_otp("login:u1")["attempts"] == 5


def test_otp_expired_via_helper_and_expire_all() -> None:
    now = time.time()
    authstate.put_otp("signup:a@b.io", "h1", None, issued=now, expires=now + 600)
    authstate.put_otp("login:u1", "h2", None, issued=now, expires=now + 600)
    authstate.expire_otp("signup:a@b.io", now - 1)
    authstate.expire_all_otps(now - 1)
    authstate.sweep()
    assert authstate.get_otp("signup:a@b.io") is None
    assert authstate.get_otp("login:u1") is None


def test_age_otp_rewinds_cooldown_stamp() -> None:
    now = time.time()
    authstate.put_otp("signup:a@b.io", "h1", None, issued=now, expires=now + 600)
    authstate.age_otp("signup:a@b.io", now - 9_999)
    assert authstate.get_otp("signup:a@b.io")["issued"] < now - 9_000


def test_throttle_buckets() -> None:
    authstate.throttle_set("throttle:login:alice", [1.0, 2.0], 900)
    assert authstate.throttle_get("throttle:login:alice") == [1.0, 2.0]
    authstate.throttle_clear("throttle:login:alice")
    assert authstate.throttle_get("throttle:login:alice") == []


def test_sweep_drops_expired_rows_across_namespaces() -> None:
    now = time.time()
    authstate.put_session("alive", "u1", issued=now, expires=now + 60)
    authstate.put_session("dead", "u2", issued=now, expires=now - 1)
    authstate.put_ticket("tdead", "u3", issued=now, expires=now - 1)
    authstate.put_otp("signup:a@b.io", "h1", None, issued=now, expires=now - 1)
    authstate.sweep()
    assert authstate.session_count() == 1
    assert authstate.ticket_count() == 0
    assert authstate.get_otp("signup:a@b.io") is None


def test_reset_clears_everything() -> None:
    now = time.time()
    authstate.put_session("s", "u1", issued=now, expires=now + 60)
    authstate.put_ticket("t", "u1", issued=now, expires=now + 60)
    authstate.put_otp("signup:a@b.io", "h1", None, issued=now, expires=now + 60)
    authstate.throttle_set("throttle:login:a", [now], 900)
    authstate.reset()
    assert authstate.session_count() == 0
    assert authstate.ticket_count() == 0
    assert authstate.get_otp("signup:a@b.io") is None
    assert authstate.throttle_get("throttle:login:a") == []


# --- SupabaseBackend through the fake PostgREST client -----------------------


def test_supabase_put_get_update_delete() -> None:
    b = _fake_backend()
    b.auth_put("session:d1", "session", user_id="u1", issued=1.0, expires=2.0)
    row = b.auth_get("session:d1")
    assert row is not None
    assert row["ns"] == "session"
    assert row["user_id"] == "u1"
    assert row["expires"] == 2.0

    b.auth_update("session:d1", {"expires": 9.0})
    assert b.auth_get("session:d1")["expires"] == 9.0

    b.auth_delete("session:d1")
    assert b.auth_get("session:d1") is None


def test_supabase_payload_round_trips_json_safely() -> None:
    b = _fake_backend()
    payload = {"stamps": [1.5, 2.5], "who": "alice@ketsa.io"}
    b.auth_put("throttle:x", "throttle", payload=payload, issued=1.0, expires=2.0)
    assert b.auth_get("throttle:x")["payload"] == payload


def test_supabase_take_is_single_use() -> None:
    b = _fake_backend()
    b.auth_put("ticket:t1", "ticket", user_id="u1", issued=1.0, expires=99.0)
    assert b.auth_take("ticket:t1")["user_id"] == "u1"
    assert b.auth_take("ticket:t1") is None


def test_supabase_two_workers_cannot_both_take_the_ticket() -> None:
    db = FakeClient()
    b1, b2 = SupabaseBackend(), SupabaseBackend()
    b1._client = db
    b2._client = db  # same "database", different processes
    b1.auth_put("ticket:t1", "ticket", user_id="u1", issued=1.0, expires=99.0)
    winners = [b.auth_take("ticket:t1") for b in (b1, b2)]
    assert sum(1 for w in winners if w is not None) == 1


def test_supabase_consume_otp_atomicity() -> None:
    db = FakeClient()
    b1, b2 = SupabaseBackend(), SupabaseBackend()
    b1._client = db
    b2._client = db
    b1.auth_put("otp:signup:a@b.io", "otp", secret_hash="abc", payload={"n": 1}, issued=1.0, expires=999.0)
    winners = [
        b.auth_consume_otp("otp:signup:a@b.io", secret_hash="abc", max_attempts=5, now=50.0)
        for b in (b1, b2)
    ]
    assert sum(1 for w in winners if w is not None) == 1


def test_supabase_consume_otp_rejects_wrong_code() -> None:
    b = _fake_backend()
    b.auth_put("otp:login:u1", "otp", secret_hash="abc", issued=1.0, expires=999.0)
    assert b.auth_consume_otp("otp:login:u1", secret_hash="xyz", max_attempts=5, now=50.0) is None
    assert b.auth_get("otp:login:u1") is not None  # entry kept for payload recovery


def test_supabase_consume_otp_rejects_expired() -> None:
    b = _fake_backend()
    b.auth_put("otp:login:u1", "otp", secret_hash="abc", issued=1.0, expires=100.0)
    assert b.auth_consume_otp("otp:login:u1", secret_hash="abc", max_attempts=5, now=101.0) is None


def test_supabase_consume_otp_dead_at_cap() -> None:
    """`attempts < max` in the DELETE: at the cap the code is unredeemable."""
    b = _fake_backend()
    b.auth_put("otp:login:u1", "otp", secret_hash="abc", attempts=5, issued=1.0, expires=999.0)
    assert b.auth_consume_otp("otp:login:u1", secret_hash="abc", max_attempts=5, now=50.0) is None
    b.auth_update("otp:login:u1", {"attempts": 4})
    assert b.auth_consume_otp("otp:login:u1", secret_hash="abc", max_attempts=5, now=50.0) is not None


def test_supabase_delete_for_user_is_ns_scoped() -> None:
    b = _fake_backend()
    b.auth_put("session:a", "session", user_id="u1", issued=1.0, expires=2.0)
    b.auth_put("session:b", "session", user_id="u2", issued=1.0, expires=2.0)
    b.auth_put("ticket:c", "ticket", user_id="u1", issued=1.0, expires=2.0)
    assert b.auth_delete_for_user("session", "u1") == 1
    assert b.auth_get("session:b") is not None
    assert b.auth_get("ticket:c") is not None  # different namespace untouched


def test_supabase_count_ids_and_oldest() -> None:
    b = _fake_backend()
    for i, stamp in ((1, 10.0), (2, 30.0), (3, 20.0)):
        b.auth_put(f"ticket:t{i}", "ticket", user_id="u1", issued=stamp, expires=99.0)
    b.auth_put("otp:x", "otp", secret_hash="h", issued=1.0, expires=99.0)
    assert b.auth_count("ticket") == 3
    assert b.auth_count("otp") == 1
    assert b.auth_ids("ticket") == ["ticket:t1", "ticket:t2", "ticket:t3"]
    # Oldest first by `issued`.
    assert b.auth_ids_oldest("ticket", 2) == ["ticket:t1", "ticket:t3"]


def test_supabase_sweep_and_clear() -> None:
    b = _fake_backend()
    b.auth_put("session:alive", "session", user_id="u1", issued=1.0, expires=100.0)
    b.auth_put("session:dead", "session", user_id="u1", issued=1.0, expires=50.0)
    b.auth_sweep(75.0)
    assert b.auth_get("session:alive") is not None
    assert b.auth_get("session:dead") is None
    b.auth_clear()
    assert b.auth_get("session:alive") is None


def test_state_survives_backend_restart(monkeypatch) -> None:
    """A redeploy (new backend object, same database) keeps auth state."""
    db = FakeClient()
    b1 = SupabaseBackend()
    b1._client = db
    monkeypatch.setattr(storage, "_backend", b1)

    now = time.time()
    authstate.put_session("session:d1", "u1", issued=now, expires=now + 60)
    authstate.put_ticket("ticket:t1", "u1", issued=now, expires=now + 60)
    authstate.put_otp("otp:signup:a@b.io", "hash-1", {"n": 1}, issued=now, expires=now + 600)
    authstate.put_admin_session("admin:ad1", now + 60)
    authstate.throttle_set("throttle:login:a@b.io", [now], 900)

    # "Restart": a brand-new backend against the same database.
    b2 = SupabaseBackend()
    b2._client = db
    monkeypatch.setattr(storage, "_backend", b2)

    assert authstate.get_session("session:d1") == (now + 60, "u1")
    assert authstate.take_ticket("ticket:t1")["user_id"] == "u1"
    assert authstate.get_otp("otp:signup:a@b.io")["payload"] == {"n": 1}
    assert authstate.get_admin_session("admin:ad1") == now + 60
    assert authstate.throttle_get("throttle:login:a@b.io") == [now]
    # The consume after restart still burns atomically.
    assert authstate.consume_otp("otp:signup:a@b.io", "hash-1", max_attempts=5, now=time.time()) is not None
    assert authstate.consume_otp("otp:signup:a@b.io", "hash-1", max_attempts=5, now=time.time()) is None