'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { fetchMarketsSession } from '@/lib/api';
import { WS_URL } from '@/lib/ws';
import type { Market, Trade } from '@/lib/types';

export interface MarketFeedValue {
  markets: Record<string, Market>;
  /** Replace a single market in the feed (e.g. right after a trade). */
  upsert: (m: Market) => void;
  connected: boolean;
  /**
   * Subscribe to live fills the engine broadcasts on the shared socket.
   * Returns an unsubscribe function. Fires for *every* market, so consumers
   * filter by `marketId`.
   */
  subscribeTrades: (fn: TradeListener) => () => void;
}

export type TradeListener = (trade: Trade, marketId: string) => void;

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

  const tradeListeners = useRef<Set<TradeListener>>(new Set());
  const subscribeTrades = useCallback((fn: TradeListener) => {
    tradeListeners.current.add(fn);
    return () => {
      tradeListeners.current.delete(fn);
    };
  }, []);

  // Live feed (WebSocket), with capped-backoff reconnects and a polling
  // fallback while the socket is down. The backend broadcasts market
  // snapshots, live fills and resolutions on one stream; snapshots are merged
  // here and fills are handed to trade subscribers (e.g. the tape).
  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let timer: number | null = null;
    let attempt = 0;

    const schedule = () => {
      if (stopped || timer !== null) return;
      // 1s, 2s, 4s … capped at 15s: a backend restart reconnects promptly
      // without hammering it while it is down.
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
          const payload = JSON.parse(String(ev.data)) as {
            type?: string;
            market?: Market;
            trade?: Trade;
            market_id?: string;
          };
          if (payload.type === 'market' && payload.market?.id) {
            upsert(payload.market);
          } else if (
            payload.type === 'trade' &&
            payload.trade &&
            payload.market_id
          ) {
            const trade = payload.trade;
            const marketId = payload.market_id;
            tradeListeners.current.forEach((fn) => fn(trade, marketId));
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
          /* ignore — onclose schedules the retry */
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
    <MarketFeedContext.Provider
      value={{ markets, upsert, connected, subscribeTrades }}
    >
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