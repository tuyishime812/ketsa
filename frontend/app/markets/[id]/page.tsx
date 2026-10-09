import { notFound } from 'next/navigation';
import {
  fetchMarketBook,
  fetchMarketsGroup,
  fetchMarketTrades,
} from '@/lib/api';
import type { OrderBook } from '@/lib/types';
import Nav from '@/components/Nav';
import DataUnavailable from '@/components/DataUnavailable';
import { MarketFeedProvider } from '@/components/market/MarketFeed';
import MarketDetail, {
  type MarketDetailInitial,
} from '@/components/market/MarketDetail';

export const dynamic = 'force-dynamic';

/**
 * A genuinely empty book — no resting orders, and NO synthetic price.
 *
 * The previous version of this file used a placeholder `{yes: 50, no: 50,
 * spread: 100}` when the book fetch failed. Nothing rendered those scalars
 * (the ladder only reads the level arrays), but an invented 50/50 quote is the
 * kind of value that must never exist in a trading UI: if it ever leaked into
 * a render it would be indistinguishable from a real market price.
 */
const EMPTY_BOOK: OrderBook = {
  yes: 0,
  no: 0,
  bids: [],
  asks: [],
  no_bids: [],
  no_asks: [],
  spread: 0,
  last: null,
};

export default async function MarketPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  // Resolve the market from live data only. No bundled seed lookup: an unknown
  // id must 404 rather than render a placeholder market.
  const market = await fetchMarketsGroup()
    .then((g) => g.all.find((m) => m.id === id) ?? null)
    .catch((err: unknown) => {
      console.error(`GET /api/markets failed (market ${id}):`, err);
      return undefined;
    });

  // `undefined` = the API is unreachable; `null` = the market does not exist.
  if (market === undefined) {
    return (
      <>
        <Nav />
        <main>
          <DataUnavailable what="market data" />
        </main>
      </>
    );
  }
  if (!market) notFound();

  const initial: MarketDetailInitial = {
    market,
    book: EMPTY_BOOK,
    trades: [],
  };

  // The book and the tape are live/ephemeral, so they degrade to empty rather
  // than taking the whole page down. MarketDetail re-polls both every 5s.
  try {
    const [book, trades] = await Promise.all([
      fetchMarketBook(id),
      fetchMarketTrades(id),
    ]);
    initial.book = book;
    initial.trades = trades;
  } catch {
    /* book/tape unavailable — render the market with an empty ladder */
  }

  return (
    <>
      <Nav />
      <main>
        <MarketFeedProvider initial={[market]}>
          <MarketDetail initial={initial} />
        </MarketFeedProvider>
      </main>
    </>
  );
}