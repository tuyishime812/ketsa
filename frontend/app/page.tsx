import { fetchHomeData } from '@/lib/api';
import { fallbackHomeData } from '@/lib/fallbackData';
import Nav from '@/components/Nav';
import Hero from '@/components/Hero';
import Ticker from '@/components/Ticker';
import Markets from '@/components/Markets';
import Dashboard from '@/components/Dashboard';
import Steps from '@/components/Steps';
import CtaBand from '@/components/CtaBand';
import Footer from '@/components/Footer';

export const dynamic = 'force-dynamic';

export default async function HomePage() {
  let data = fallbackHomeData;
  let fromApi = false;

  try {
    data = await fetchHomeData();
    fromApi = true;
  } catch {
    // Backend not reachable (e.g. dev machine hasn't started FastAPI yet).
    // Fall back to the bundled seed data so the page still renders.
  }

  return (
    <>
      <Nav />
      <main id="top">
        <Hero watch={data.watch} proof={data.proof} />
        <Ticker items={data.ticker} />
        <Markets markets={data.markets.all} />
        <Dashboard data={data.dashboard} stats={data.stats} />
        <Steps />
        <CtaBand />
      </main>
      <Footer />
      {!fromApi && (
        <div className="fixed bottom-4 right-4 z-[200] rounded-full bg-brand px-4 py-2 font-mono text-xs text-white shadow-lg">
          Demo using bundled data — start the FastAPI backend to go live
        </div>
      )}
    </>
  );
}
