'use client';

// Public team directory. Server-rendered with an initial list, then kept live
// over the shared WebSocket: staff add/update/remove events patch the list in
// place, and an `upload` (bulk) event triggers a re-fetch of the authoritative
// list. Reconnects re-sync too, so nothing is missed while the socket is down.

import { useCallback, useEffect, useState } from 'react';
import { fetchStaffSession } from '@/lib/api';
import { useStaffStream } from '@/lib/useStaffStream';
import type { StaffPublic, StaffWsEvent } from '@/lib/types';

const ROLE_ORDER = [
  'owner',
  'admin',
  'support',
  'finance',
  'marketing',
  'moderation',
];

const ROLE_LABELS: Record<string, string> = {
  owner: 'Owner',
  admin: 'Admin',
  support: 'Support',
  finance: 'Finance',
  marketing: 'Marketing',
  moderation: 'Moderation',
};

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role.charAt(0).toUpperCase() + role.slice(1);
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function orderTeam(a: StaffPublic, b: StaffPublic): number {
  const ra = ROLE_ORDER.indexOf(a.role);
  const rb = ROLE_ORDER.indexOf(b.role);
  const byRole = (ra === -1 ? 99 : ra) - (rb === -1 ? 99 : rb);
  if (byRole !== 0) return byRole;
  return a.name.localeCompare(b.name);
}

function LiveBadge({ connected }: { connected: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-paper px-3 py-1.5 font-mono text-[10.5px] font-bold uppercase tracking-[.14em] text-ink-2">
      <span
        className={`h-2 w-2 rounded-full ${
          connected ? 'animate-pulse-dot bg-pos' : 'bg-ink-3'
        }`}
      />
      {connected ? 'Live' : 'Reconnecting'}
    </span>
  );
}

export default function TeamDirectory({ initial }: { initial: StaffPublic[] }) {
  const [team, setTeam] = useState<StaffPublic[]>(initial);

  const resync = useCallback(async () => {
    try {
      setTeam(await fetchStaffSession());
    } catch {
      /* backend unreachable — keep the last known list */
    }
  }, []);

  const onEvent = useCallback(
    (ev: StaffWsEvent) => {
      if (ev.action === 'upload') {
        void resync();
        return;
      }
      if (ev.action === 'invite') return; // no public-visible change
      if (ev.action === 'remove') {
        if (ev.id) setTeam((prev) => prev.filter((p) => p.id !== ev.id));
        return;
      }
      const s = ev.staff;
      if (!s) return;
      if (s.active === false) {
        setTeam((prev) => prev.filter((p) => p.id !== s.id));
        return;
      }
      const entry: StaffPublic = { id: s.id, name: s.name, role: s.role };
      setTeam((prev) => {
        const idx = prev.findIndex((p) => p.id === s.id);
        const next =
          idx === -1
            ? [...prev, entry]
            : prev.map((p) => (p.id === s.id ? entry : p));
        return next.sort(orderTeam);
      });
    },
    [resync],
  );

  const { connected } = useStaffStream(onEvent);

  // Re-sync whenever the socket (re)connects, to catch anything missed offline.
  useEffect(() => {
    if (connected) void resync();
  }, [connected, resync]);

  const ordered = [...team].sort(orderTeam);

  return (
    <section className="section">
      <div className="wrap">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <div className="font-mono text-[11px] font-bold uppercase tracking-[.18em] text-brand">
              Company
            </div>
            <h1 className="mt-3 font-serif text-[38px] leading-[1.05] text-ink sm:text-[44px]">
              The people behind Ketsa
            </h1>
            <p className="mt-4 text-[15px] leading-[1.65] text-ink-2">
              Ketsa is built by a small, focused team across support, finance,
              operations and moderation. This directory updates live as the team
              changes.
            </p>
          </div>
          <LiveBadge connected={connected} />
        </div>

        {ordered.length === 0 ? (
          <p className="mt-14 text-ink-3">No team members to show yet.</p>
        ) : (
          <ul className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {ordered.map((p) => (
              <li
                key={p.id}
                className="rounded-l border border-line bg-paper p-6 shadow-[0_1px_2px_rgba(12,21,38,.04)] transition-all duration-200 ease-ketsa hover:-translate-y-[2px] hover:border-line-strong hover:shadow-[0_14px_30px_-18px_rgba(12,21,38,.45)]"
              >
                <div className="flex items-center gap-4">
                  <span
                    aria-hidden
                    className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-brand-tint font-mono text-[15px] font-bold text-brand"
                  >
                    {initials(p.name)}
                  </span>
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-ink">
                      {p.name}
                    </div>
                    <div className="mt-1 font-mono text-[10.5px] font-bold uppercase tracking-[.12em] text-ink-3">
                      {roleLabel(p.role)}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
