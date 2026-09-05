import { fetchMarketsGroup } from '@/lib/api';
import { fallbackHomeData } from '@/lib/fallbackData';
import Nav from '@/components/Nav';
import { MarketFeedProvider } from '@/components/market/MarketFeed';
import MarketsExplorer from '@/components/market/MarketsExplorer';

export const dynamic = 'force-dynamic';

export default async function MarketsPage() {
  let markets = fallbackHomeData.markets.all;
  try {
    markets = (await fetchMarketsGroup()).all;
  } catch {
    // Backend offline — render the bundled seed markets.
  }

  return (
    <>
      <Nav />
      <main>
        <MarketFeedProvider initial={markets}>
          <MarketsExplorer initial={markets} />
        </MarketFeedProvider>
      </main>
    </>
  );
}