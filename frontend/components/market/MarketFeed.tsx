'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { fetchMarketsSession } from '@/lib/api';
import type { Market } from '@/lib/types';

// Browser only ever connects to the backend directly for the WebSocket feed
// (the Next /api proxy does not proxy upgrades). Prefer an explicit
// NEXT_PUBLIC_KETSA_BACKEND_URL in production.
const WS_URL =
  (process.env.NEXT_PUBLIC_KETSA_BACKEND_URL || 'http://127.0.0.1:8000').replace(
    /^http/,
    'ws',
  ) + '/api/ws';

export interface MarketFeedValue {
  markets: Record<string, Market>;
  /** Replace a single market in the feed (e.g. right after a trade). */
  upsert: (m: Market) => void;
  connected: boolean;
}

const MarketFeedContext = createContext<MarketFeedValue | null>(null);

function sameMarket(a?: Market, b?: Market): boolean {
  if (!a || !b) return a === b;
  return (
    a.yes === b.yes &&
    a.no === b.no &&
    a.last_price === b.last_price &&
    a.volume === b.volume &&
    a.liquidity === b.liquidity &&
    (a.pts?.length ?? 0) === (b.pts?.length ?? 0)
  );
}

export function MarketFeedProvider({
  initial,
  children,
}: {
  initial: Market[];
  children: ReactNode;
}) {
  const initialMap = () =>
    Object.fromEntries(initial.map((m) => [m.id, m])) as Record<string, Market>;
  const [markets, setMarkets] = useState<Record<string, Market>>(initialMap);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setMarkets(initialMap());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const merge = useCallback((incoming: Market[]) => {
    setMarkets((prev) => {
      let changed = false;
      const next: Record<string, Market> = { ...prev };
      for (const m of incoming) {
        if (!sameMarket(next[m.id], m)) {
          next[m.id] = m;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  const upsert = useCallback(
    (m: Market) => merge([m]),
    [merge],
  );

  // Live feed (WebSocket), with a polling fallback when it's unavailable.
  useEffect(() => {
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(WS_URL);
    } catch {
      /* fall back to polling */
    }
    if (!ws) {
      setConnected(false);
      return;
    }
    ws.onopen = () => setConnected(true);
    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(String(ev.data)) as {
          type?: string;
          market?: Market;
        };
        if (payload.type === 'market' && payload.market?.id) {
          upsert(payload.market);
        }
      } catch {
        /* skip malformed frame */
      }
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => {
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
    return () => {
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  }, [upsert]);

  useEffect(() => {
    if (connected) return;
    const tick = async () => {
      try {
        const group = await fetchMarketsSession();
        merge(group.all);
      } catch {
        /* backend unreachable — keep last known data */
      }
    };
    void tick();
    const t = window.setInterval(tick, 5000);
    return () => window.clearInterval(t);
  }, [connected, merge]);

  return (
    <MarketFeedContext.Provider value={{ markets, upsert, connected }}>
      {children}
    </MarketFeedContext.Provider>
  );
}

export function useMarketFeed(): MarketFeedValue {
  const ctx = useContext(MarketFeedContext);
  if (!ctx) {
    throw new Error('useMarketFeed must be used within a <MarketFeedProvider>');
  }
  return ctx;
}

/** Resolve a market's live values (falls back to the passed-in snapshot). */
export function liveOf(m: Market, feed: Record<string, Market>): Market {
  return feed[m.id] ?? m;
}

export const marketFeedUrl = WS_URL;