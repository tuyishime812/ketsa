import { fetchMarketsGroup } from '@/lib/api';
import Nav from '@/components/Nav';
import DataUnavailable from '@/components/DataUnavailable';
import { MarketFeedProvider } from '@/components/market/MarketFeed';
import DashboardShell from '@/components/dashboard/DashboardShell';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  // Live markets only — no bundled seed fallback.
  const markets = await fetchMarketsGroup()
    .then((g) => g.all)
    .catch((err: unknown) => {
      console.error('GET /api/markets failed (dashboard):', err);
      return null;
    });

  if (!markets) {
    return (
      <>
        <Nav />
        <main>
          <DataUnavailable what="market data" />
        </main>
      </>
    );
  }

  return (
    <>
      <Nav />
      <main>
        <MarketFeedProvider initial={markets}>
          <DashboardShell initialMarkets={markets} />
        </MarketFeedProvider>
      </main>
    </>
  );
}
