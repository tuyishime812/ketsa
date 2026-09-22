-- Ketsa Supabase Realtime configuration.
--
-- Run this AFTER schema.sql in the Supabase SQL editor (Dashboard -> SQL ->
-- New query), signed in as the project owner, after the five tables exist.
-- It wires all five Ketsa tables into the supabase_realtime publication
-- so the backend can broadcast live market ticks, trades, resolutions and
-- wallet notifications over a single Realtime channel that survives
-- multiple backend replicas.
-- (Run it here in the editor — not from the backend and not via a plain
-- client connection. ALTER PUBLICATION requires owning the publication and
-- the tables. The editor's postgres role has that; the backend's
-- service_role key does not.)

-- Two Realtime patterns are used by Ketsa:
--   * Postgres Changes - auto-broadcast row INSERT/UPDATE/DELETE.
--     Used for ketsa_kv (content) + ketsa_notifications (wallet-scoped).
--   * realtime.send()  - manually broadcast arbitrary JSON payloads.
--     Used by the engine for high-frequency market ticks/trades that are
--     derived in-memory and don't map to a single row write.

-- 1. Add every Ketsa table to the supabase_realtime publication.
--    There is no realtime.add() helper — it does not exist, and calling it
--    fails with 42883 "function realtime.add(unknown) does not exist".
--    The supported way is ALTER PUBLICATION ... ADD TABLE. That statement
--    has no IF NOT EXISTS and errors if a table is already tracked, so each
--    ADD is guarded by a pg_publication_tables check. The whole script stays
--    idempotent: safe to re-run, it logs a NOTICE per table instead of
--    erroring.
do $$
declare
  t text;
begin
  foreach t in array array[
    'ketsa_kv',
    'ketsa_wallets',
    'ketsa_payments',
    'ketsa_users',
    'ketsa_notifications'
  ]
  loop
    if not exists (
      select 1
      from pg_publication_tables
      where pubname    = 'supabase_realtime'
        and schemaname = 'public'
        and tablename  = t
    ) then
      execute format('alter publication supabase_realtime add table %I.%I', 'public', t);
      raise notice 'realtime: added public.% to supabase_realtime', t;
    else
      raise notice 'realtime: public.% is already tracked by supabase_realtime (skipped)', t;
    end if;
  end loop;
end
$$;

-- 2. ketsa_kv: public content (markets, watchlist, ticker, dashboard, proof).
--    No wallet filtering needed - every connected client receives updates.
--    (RLS already blocks anon reads; Realtime respects RLS automatically.)

-- 3. ketsa_notifications: wallet-scoped delivery.
--    Set replica identity to FULL so DELETE events carry the full old row
--    (id plus the value JSONB that holds the wallet id). The default
--    (primary key only) would omit the value column, so Postgres Changes
--    could not filter deletes by wallet.
alter table public.ketsa_notifications replica identity full;

-- 4. OPTIONAL: Grant the anon / authenticated role SELECT on the three
--    sensitive tables IF you want clients to subscribe to their own wallet
--    notifications via Postgres Changes (requires the caller JWT to carry a
--    wallet_id claim). The backend uses the service_role key (RLS-exempt)
--    for all writes and forwards wallet-scoped events privately over /api/ws,
--    so granting anon SELECT is OPTIONAL. Uncomment only if you expose
--    notifications directly via Postgres Changes:
--
--  grant select on public.ketsa_notifications  to authenticated;
--  grant select on public.ketsa_wallets        to authenticated;
--  grant select on public.ketsa_payments       to authenticated;

-- 5. Verify the wiring (runs automatically and lists the tracked tables).
select schemaname, tablename
from pg_publication_tables
where pubname = 'supabase_realtime'
order by 1, 2;

-- Backend: after a trade, broadcast a market snapshot to all clients.
-- Current realtime.send() signature is (payload, event, topic, is_private):
--   payload    - the JSONB message body clients receive.
--   event      - event name clients filter on (.on('broadcast', { event: 'market' })).
--   topic      - channel clients subscribe to (supabase.channel('ketsa:live')).
--   is_private - true  = authenticated subscribers only.
--                false = public channel (anon clients can subscribe too).
-- select realtime.send(
--   jsonb_build_object('type', 'market', 'market', '<snapshot_json>'),
--   'market',
--   'ketsa:live',
--   true
-- );
