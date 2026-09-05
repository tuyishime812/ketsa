import { fetchMarketsGroup } from '@/lib/api';
import { fallbackHomeData } from '@/lib/fallbackData';
import Nav from '@/components/Nav';
import { MarketFeedProvider } from '@/components/market/MarketFeed';
import Portfolio from '@/components/portfolio/Portfolio';

export const dynamic = 'force-dynamic';

export default async function PortfolioPage() {
  let markets = fallbackHomeData.markets.all;
  try {
    markets = (await fetchMarketsGroup()).all;
  } catch {
    // Backend offline — render with the bundled seed markets.
  }

  return (
    <>
      <Nav />
      <main>
        <MarketFeedProvider initial={markets}>
          <Portfolio initialMarkets={markets} />
        </MarketFeedProvider>
      </main>
    </>
  );
}