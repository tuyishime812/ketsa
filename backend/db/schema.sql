-- Ketsa storage schema for Supabase (Postgres).
--
-- Run this ONCE in the Supabase SQL editor (Dashboard -> SQL -> New query)
-- before pointing the backend at the project. All Ketsa content is stored as
-- JSONB rows so the app never needs migrations for content changes.
--
-- Three tables:
--   ketsa_kv       — markets + editable content (watch, ticker, dashboard,
--                    stats, proof, settings). The "kind" column lets the API
--                    scope queries; a content-reset only ever touches these.
--   ketsa_wallets  — persisted wallet balances. Real-money state: it is NEVER
--                    wiped by the admin "reset content" action.
--   ketsa_payments — the mobile-money (wandePay) payment ledger. Idempotency
--                    flags live here, so this is also never wiped by resets.

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

-- The service-role key operates server-side and bypasses RLS. If you enable
-- row-level security, allow the service role (permissions are set by default
-- when tables are created). For an extra lock-down you can grant/revoke:
--   alter table public.ketsa_kv enable row level security;
--   drop policy if exists "service_read" on public.ketsa_kv;
--   create policy "service_read" on public.ketsa_kv
--     for select using (true);
-- (the service role is exempt from RLS unless the table's owner opts in).