'use client';

// Subscribe to realtime `staff` events on the shared Ketsa WebSocket.
//
// The backend broadcasts every staff add/update/remove/upload/invite as a
// `{"type":"staff", ...}` frame (see backend/app/staff.py + the pump in
// main.py). This hook owns the socket lifecycle — open, capped-backoff
// reconnect, cleanup — and hands each event to `onEvent`. The caller decides
// how to apply it (the public page patches its list; the admin editor
// re-fetches the authoritative list).
//
// Mirrors the reconnect policy in MarketFeed.tsx so both consumers behave the
// same across a backend restart.

import { useEffect, useRef, useState } from 'react';
import { WS_URL } from './ws';
import type { StaffWsEvent } from './types';

export function useStaffStream(
  onEvent: (event: StaffWsEvent) => void,
): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onEvent);

  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let timer: number | null = null;
    let attempt = 0;

    const schedule = () => {
      if (stopped || timer !== null) return;
      // 1s, 2s, 4s … capped at 15s.
      const delay = Math.min(15000, 1000 * 2 ** attempt);
      attempt += 1;
      timer = window.setTimeout(() => {
        timer = null;
        open();
      }, delay);
    };

    const open = () => {
      if (stopped) return;
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      ws.onmessage = (ev) => {
        try {
          const payload = JSON.parse(String(ev.data)) as { type?: string };
          if (payload && payload.type === 'staff') {
            handlerRef.current(payload as StaffWsEvent);
          }
        } catch {
          /* skip malformed frame */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        schedule();
      };
      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          /* onclose schedules the retry */
        }
      };
    };

    open();

    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  }, []);

  return { connected };
}
