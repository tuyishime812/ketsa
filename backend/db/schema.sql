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
create index if not exists ketsa_users_auth0_sub_idx
  on public.ketsa_users ((value ->> 'auth0_sub'));

create table if not exists public.ketsa_notifications (
  id    text primary key,
  value jsonb not null default '{}'::jsonb
);

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