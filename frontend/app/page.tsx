import { fetchHomeData } from '@/lib/api';
import Nav from '@/components/Nav';
import DataUnavailable from '@/components/DataUnavailable';
import Hero from '@/components/Hero';
import Ticker from '@/components/Ticker';
import Markets from '@/components/Markets';
import { MarketFeedProvider } from '@/components/market/MarketFeed';
import CtaBand from '@/components/CtaBand';
import Footer from '@/components/Footer';

export const dynamic = 'force-dynamic';

export default async function HomePage() {
  // Live data only. There is deliberately no bundled seed/demo fallback: every
  // figure on this page (prices, volume, trader counts, the hero badge) is shown
  // to the user as real, so serving placeholder numbers when the API is down
  // would be fabricated market data. Fail closed with an honest message
  // instead, and log the reason server-side (the browser never sees it).
  const data = await fetchHomeData().catch((err: unknown) => {
    console.error('GET /api/home failed:', err);
    return null;
  });

  // The API always returns settings (they back the admin content editor).
  if (!data?.settings) {
    console.error('home payload missing settings');
    return (
      <>
        <Nav />
        <main id="top">
          <DataUnavailable
            what="market data"
            devHint="The frontend cannot reach the Ketsa API. Start the backend (from the backend/ folder run: python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) and ensure KETSA_BACKEND_URL points to it, then retry."
          />
        </main>
      </>
    );
  }

  const settings = data.settings;

  return (
    <>
      <Nav />
      <main id="top">
        <Hero watch={data.watch} proof={data.proof} copy={settings.hero} />
        {data.ticker.length > 0 && <Ticker items={data.ticker} />}
        <MarketFeedProvider initial={data.markets.all}>
          <Markets markets={data.markets.all} copy={settings.markets_section} />
        </MarketFeedProvider>
        <CtaBand copy={settings.cta} />
      </main>
      <Footer copy={settings.footer} />
    </>
  );
}
