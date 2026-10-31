import { fetchMarketsGroup } from '@/lib/api';
import Nav from '@/components/Nav';
import DataUnavailable from '@/components/DataUnavailable';
import { MarketFeedProvider } from '@/components/market/MarketFeed';
import MarketsExplorer from '@/components/market/MarketsExplorer';

export const dynamic = 'force-dynamic';

export default async function MarketsPage() {
  // No bundled seed fallback — an empty or invented market list would read as
  // real. On failure we render an explicit unavailable state; the reason is
  // logged server-side only.
  const markets = await fetchMarketsGroup()
    .then((g) => g.all)
    .catch((err: unknown) => {
      console.error('GET /api/markets failed:', err);
      return null;
    });

  if (!markets) {
    return (
      <>
        <Nav />
        <main>
          <DataUnavailable what="markets" />
        </main>
      </>
    );
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
