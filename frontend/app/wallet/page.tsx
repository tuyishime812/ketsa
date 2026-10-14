import Nav from '@/components/Nav';
import WalletDashboard from '@/components/wallet/WalletDashboard';

export const dynamic = 'force-dynamic';

export default function WalletPage() {
  return (
    <>
      <Nav />
      <main>
        <WalletDashboard />
      </main>
    </>
  );
}
