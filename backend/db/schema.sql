-- Ketsa storage schema for Supabase (Postgres).
--
-- Run this ONCE in the Supabase SQL editor (Dashboard -> SQL -> New query)
-- before pointing the backend at the project. All Ketsa content is stored as
-- JSONB rows so the app never needs migrations for content changes.
--
-- Seven tables:
--   ketsa_kv           — markets + editable content (watch, ticker, dashboard,
--                        stats, proof, settings). The "kind" column lets the
--                        API scope queries; a content-reset only ever touches
--                        these.
--   ketsa_wallets      — persisted wallet balances. Real-money state: it is
--                        NEVER wiped by the admin "reset content" action.
--   ketsa_payments     — the mobile-money (wandePay) payment ledger.
--                        Idempotency flags live here, so this is also never
--                        wiped by resets.
--   ketsa_users        — accounts (password + Auth0/Google sign-ins).
--   ketsa_notifications — per-wallet in-app notification feed.
--   ketsa_staff        — the platform team directory (admin-managed). Not
--                        wiped by "reset content".
--   ketsa_auth         — ephemeral auth state: bearer sessions, pending OTPs,
--                        Auth0 SSO tickets and the login/code-request throttles.
--                        Kept OUT of ketsa_kv so a content reset never logs
--                        everyone out, and shared so it (a) survives a restart
--                        or redeploy and (b) is the same across every backend
--                        worker. Never wiped by the admin "reset content".

create table if not exists public.ketsa_kv (
  id    text primary key,
  kind  text not null default 'content',
  value jsonb not null default '{}'::jsonb
);

create index if not exists ketsa_kv_kind_idx on public.ketsa_kv (kind);

create table if not exists public.ketsa_wallets (
  id    text primary key,
  value jsonb not null default '{}'::jsonb
);

create table if not exists public.ketsa_payments (
  id    text primary key,
  value jsonb not null default '{}'::jsonb
);

create table if not exists public.ketsa_users (
  id    text primary key,
  value jsonb not null default '{}'::jsonb
);

-- Auth0 social login: users created via "Continue with Google" carry their
-- Auth0 subject ("auth0_sub") inside the JSONB value. Index the lookup the
-- backend performs when a Google user returns (find-or-create by subject).
--
-- These three lookups are UNIQUE, not just indexed: the backend resolves an
-- account by each of these keys, so two rows sharing a value would make
-- "log in as this phone number" ambiguous (a takeover waiting to happen).
-- Uniqueness was previously only enforced in application code, which a
-- concurrent-registration race could slip past. A plain index could not
-- express the constraint, so it was cosmetic. Safe to re-run.
--
-- `null` values (accounts that don't use that identifier) are exempt, which
-- is what we want: most accounts have no auth0_sub, and most have no phone.
create unique index if not exists ketsa_users_auth0_sub_idx
  on public.ketsa_users ((value ->> 'auth0_sub'))
  where value ->> 'auth0_sub' is not null;

create unique index if not exists ketsa_users_phone_idx
  on public.ketsa_users ((value ->> 'phone'))
  where value ->> 'phone' is not null;

-- Wallet ownership: EVERY authenticated request resolves the caller's account
-- by wallet id (the ownership gate on wallet reads, trades and notifications).
-- This index is what keeps that check O(log n) instead of a full table scan.
create unique index if not exists ketsa_users_wallet_id_idx
  on public.ketsa_users ((value ->> 'wallet_id'))
  where value ->> 'wallet_id' is not null;

create table if not exists public.ketsa_notifications (
  id    text primary key,
  value jsonb not null default '{}'::jsonb
);

-- Both per-wallet feeds are read newest-first for a single wallet on every
-- page load / poll, so index the (wallet, time) pair rather than filtering
-- the whole table in the API.
create index if not exists ketsa_notifications_wallet_idx
  on public.ketsa_notifications ((value ->> 'wallet_id'), (value ->> 'ts') desc);

create index if not exists ketsa_payments_wallet_idx
  on public.ketsa_payments ((value ->> 'wallet_id'), (value ->> 'created') desc);

-- Staff directory (platform team). `email` and `phone` are the dedupe keys the
-- bulk-upload path upserts against, so they are UNIQUE where present — the same
-- reasoning as ketsa_users: two rows sharing an email would make "invite this
-- person" ambiguous. `null` (no phone) stays exempt. Safe to re-run.
create table if not exists public.ketsa_staff (
  id    text primary key,
  value jsonb not null default '{}'::jsonb
);

create unique index if not exists ketsa_staff_email_idx
  on public.ketsa_staff ((lower(value ->> 'email')))
  where value ->> 'email' is not null;

create unique index if not exists ketsa_staff_phone_idx
  on public.ketsa_staff ((value ->> 'phone'))
  where value ->> 'phone' is not null;

-- Auth state store (sessions, OTPs, SSO tickets, throttles).
--
-- One table serves every ephemeral auth purpose. `id` is namespaced by kind
-- ("session:<digest>", "otp:reset:<user_id>", "ticket:<t>", "throttle:<bucket>")
-- so one sweep covers all of them. `secret_hash` holds a SHA-256 digest (never
-- a plaintext code or token); `user_id` carries ownership for session/ticket
-- rows so "revoke every session for this account" is one indexed delete;
-- `attempts` is the OTP wrong-code counter that caps guessing; `payload`
-- carries the pending-signup data or a throttle's timestamps.
--
-- `expires`/`issued` are Unix epoch seconds as double precision, not
-- timestamptz: the application compares raw numbers, and a float both indexes
-- for the sweep and round-trips without timezone parsing.
--
-- Deliberately separate from ketsa_kv so a content reset never logs everyone
-- out. Safe to re-run.
create table if not exists public.ketsa_auth (
  id          text primary key,
  ns          text not null,
  secret_hash text,
  user_id     text,
  attempts    integer not null default 0,
  payload     jsonb,
  issued      double precision not null default 0,
  expires     double precision not null
);

-- The sweep deletes by expiry; counts and the ticket cap filter by namespace
-- (the composite also covers a bare `ns =`).
create index if not exists ketsa_auth_expires_idx on public.ketsa_auth (expires);
create index if not exists ketsa_auth_ns_user_idx on public.ketsa_auth (ns, user_id);

-- Append-only audit log. Every privileged or money-moving action (admin login,
-- password change, market resolution, user password reset/deletion, payment-cap
-- and deposit/withdrawal setting changes, staff and broadcast operations, ...)
-- appends one row here with the actor, client IP, target and a short JSON
-- metadata blob. See backend/app/audit.py.
--
-- Stored as JSONB in `value` (like the other content tables) plus a `ts`
-- column so the table can be ordered and (optionally) pruned by time. Rows are
-- only ever INSERTed: no application code path updates or deletes them, so the
-- log is the system of record during a dispute or abuse investigation.
--
-- Never wiped by the admin "reset content" action, and RLS with no policies
-- denies the public anon role all access (only the backend's service role,
-- which bypasses RLS, may read or write).
create table if not exists public.ketsa_audit (
  id    text primary key,
  ts    double precision not null default 0,
  value jsonb not null default '{}'::jsonb
);

-- Newest-first reads and optional action filters.
create index if not exists ketsa_audit_ts_idx on public.ketsa_audit (ts desc);
create index if not exists ketsa_audit_action_idx on public.ketsa_audit ((value->>'action'));

-- Row Level Security. The anon/publishable key is PUBLIC (it ships in the
-- browser bundle), so without RLS anyone holding it could read every wallet
-- balance, payment record, user account and password hash. Enabling RLS with NO
-- policies denies every non-service role by default, while the backend's
-- service-role key is exempt from RLS and keeps full access. This is safe to
-- run on an existing project: it is idempotent and changes no data.
alter table public.ketsa_kv            enable row level security;
alter table public.ketsa_wallets       enable row level security;
alter table public.ketsa_payments      enable row level security;
alter table public.ketsa_users         enable row level security;
alter table public.ketsa_notifications enable row level security;
-- Staff carries contact details (email/phone): same treatment as above.
alter table public.ketsa_staff         enable row level security;
-- Auth state carries live session digests and pending signups: same treatment.
alter table public.ketsa_auth          enable row level security;
-- Audit log records privileged actions: keep it away from the public anon key.
alter table public.ketsa_audit         enable row level security;