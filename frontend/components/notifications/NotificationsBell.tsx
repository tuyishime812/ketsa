'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { markNotificationsReadSession } from '@/lib/api';
import type { NotificationItem } from '@/lib/types';
import { useWallet } from '@/components/wallet/WalletProvider';
import { timeAgo } from '@/lib/utils';
import { fetchNotificationsSession } from '@/lib/api';
import { onPush, startPush, subscribeWallet } from '@/lib/push';
import { loadStoredSession } from '@/lib/wallet';

const TYPE_STYLES: Record<NotificationItem['type'], string> = {
  fill: 'bg-pos-tint text-pos',
  deposit: 'bg-brand-tint text-brand',
  withdraw: 'bg-brand-tint text-brand',
  system: 'bg-paper-alt text-ink-2',
};

export default function NotificationsBell() {
  const { wallet } = useWallet();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const loaded = useRef(false);

  const unread = items.filter((n) => !n.read).length;

  const refresh = useCallback(async () => {
    if (!wallet) return;
    try {
      setLoading(true);
      const notes = await fetchNotificationsSession(wallet.id, 25);
      setItems(notes);
    } catch {
      /* backend unreachable — keep last known list */
    } finally {
      setLoading(false);
    }
  }, [wallet]);

  useEffect(() => {
    if (!wallet) return;
    startPush();
    // The server authorizes a wallet subscription against the account token,
    // so an account wallet only subscribes with its bearer token. A guest
    // wallet has none and is allowed through on its unguessable id alone.
    subscribeWallet(wallet.id, loadStoredSession()?.token ?? null);
    const off = onPush((ev) => {
      if (ev.type !== 'notification') return;
      const notif = ev.notification as NotificationItem;
      if (!notif || notif.wallet_id !== wallet.id) return;
      setItems((prev) => {
        if (prev.some((n) => n.id === notif.id)) return prev;
        return [notif, ...prev].sort((a, b) => b.ts - a.ts).slice(0, 50);
      });
    });
    return () => {
      off();
      subscribeWallet(null);
    };
  }, [wallet]);

  useEffect(() => {
    if (!wallet || !open) return;
    if (!loaded.current) {
      loaded.current = true;
      void refresh();
    }
    const timer = window.setInterval(() => void refresh(), 20_000);
    return () => window.clearInterval(timer);
  }, [wallet, open, refresh]);

  if (!wallet) return null;

  async function markAllRead() {
    if (!wallet || unread === 0) return;
    try {
      await markNotificationsReadSession(wallet.id, []);
      setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="relative">
      <button
        aria-label={`Notifications (${unread} unread)`}
        aria-expanded={open}
        className="relative rounded-full border border-line-strong p-[8px] text-ink-3 transition-colors hover:border-ink hover:text-ink"
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path
            d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6ZM10 20a2 2 0 0 0 4 0"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-[5px] -top-[5px] flex h-[17px] min-w-[17px] items-center justify-center rounded-full bg-neg px-[4px] font-mono text-[9.5px] font-bold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <button
            aria-label="Close notifications"
            className="fixed inset-0 z-[110] cursor-default"
            tabIndex={-1}
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-[120] mt-[10px] w-[340px] overflow-hidden rounded-m border border-line bg-white shadow-[0_24px_60px_-24px_rgba(12,21,38,.3)]">
            <div className="flex items-center justify-between border-b border-line px-[14px] py-[11px]">
              <span className="font-mono text-[11px] font-semibold uppercase tracking-[.06em] text-ink-2">
                Notifications
              </span>
              <button
                className="text-[11.5px] font-medium text-brand transition-colors hover:text-brand-ink disabled:opacity-40"
                disabled={unread === 0}
                onClick={() => void markAllRead()}
              >
                Mark all read
              </button>
            </div>

            <div className="max-h-[320px] overflow-y-auto">
              {loading && items.length === 0 ? (
                <div className="flex items-center gap-[8px] px-4 py-6 text-[12.5px] text-ink-3">
                  <span className="h-2 w-2 animate-pulse-dot rounded-full bg-brand" />
                  Loading…
                </div>
              ) : items.length === 0 ? (
                <div className="px-4 py-6 text-center text-[12.5px] text-ink-3">
                  No notifications yet.
                </div>
              ) : (
                items.map((n) => (
                  <div
                    key={n.id}
                    className={`border-b border-line px-[14px] py-[11px] last:border-b-0 ${
                      n.read ? '' : 'bg-brand-tint/30'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span
                        className={`rounded-[4px] px-[7px] py-[2px] font-mono text-[9.5px] font-bold uppercase tracking-[.05em] ${TYPE_STYLES[n.type]}`}
                      >
                        {n.type}
                      </span>
                      <span className="font-mono text-[10.5px] text-ink-3">
                        {timeAgo(n.ts)}
                      </span>
                    </div>
                    <div className="mt-[6px] text-[13px] font-semibold leading-snug text-ink">
                      {n.title}
                    </div>
                    <div className="mt-[2px] text-[12px] leading-snug text-ink-2">
                      {n.message}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
