import type { Metadata } from 'next';
import { WalletProvider } from '@/components/wallet/WalletProvider';
import { BetSlipProvider } from '@/components/betslip/BetSlipProvider';
import BetSlip from '@/components/betslip/BetSlip';
import './globals.css';

export const metadata: Metadata = {
  title: 'Ketsa — Trade on what happens next',
  description:
    'Ketsa is a real-time market for the outcomes that matter — politics, crypto, sport, and culture. Prices move with the crowd, not a bookmaker.',
  metadataBase: new URL(process.env.KETSA_SITE_URL || 'http://localhost:3000'),
  openGraph: {
    title: 'Ketsa — Trade on what happens next',
    description:
      'A real-time market for the outcomes that matter. Prices move with the crowd, not a bookmaker.',
    type: 'website',
    siteName: 'Ketsa',
  },
  twitter: {
    card: 'summary',
    title: 'Ketsa — Trade on what happens next',
    description:
      'A real-time market for the outcomes that matter. Prices move with the crowd, not a bookmaker.',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&family=Newsreader:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <WalletProvider>
          <BetSlipProvider>
            {children}
            <BetSlip />
          </BetSlipProvider>
        </WalletProvider>
      </body>
    </html>
  );
}
