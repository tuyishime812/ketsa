-- Ketsa storage schema for Supabase (Postgres).
--
-- Run this ONCE in the Supabase SQL editor (Dashboard -> SQL -> New query)
-- before pointing the backend at the project. All Ketsa content is stored as
-- JSONB rows so the app never needs migrations for content changes.
--
-- Five tables:
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