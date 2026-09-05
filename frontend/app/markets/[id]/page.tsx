import { notFound } from 'next/navigation';
import {
  fetchMarketBook,
  fetchMarketsGroup,
  fetchMarketTrades,
} from '@/lib/api';
import { fallbackHomeData } from '@/lib/fallbackData';
import Nav from '@/components/Nav';
import { MarketFeedProvider } from '@/components/market/MarketFeed';
import MarketDetail, {
  type MarketDetailInitial,
} from '@/components/market/MarketDetail';

export const dynamic = 'force-dynamic';

const EMPTY_BOOK = {
  yes: 50,
  no: 50,
  bids: [],
  asks: [],
  no_bids: [],
  no_asks: [],
  spread: 100,
  last: null,
};

export default async function MarketPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let market =
    fallbackHomeData.markets.all.find((m) => m.id === id) ?? null;

  // Prefer live values from the backend when it's reachable.
  try {
    const found = (await fetchMarketsGroup()).all.find((gm) => gm.id === id);
    if (found) market = found;
  } catch {
    /* keep bundled seed market */
  }

  if (!market) notFound();

  const initial: MarketDetailInitial = {
    market,
    book: EMPTY_BOOK,
    trades: [],
  };

  try {
    const [book, trades] = await Promise.all([
      fetchMarketBook(id),
      fetchMarketTrades(id),
    ]);
    initial.book = book;
    initial.trades = trades;
  } catch {
    /* backend offline — render without live book */
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