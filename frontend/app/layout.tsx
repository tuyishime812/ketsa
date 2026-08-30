import type { Metadata } from 'next';
import { Newsreader, Inter, IBM_Plex_Mono } from 'next/font/google';
import './globals.css';

const newsreader = Newsreader({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  style: ['normal', 'italic'],
  variable: '--font-newsreader',
  display: 'swap',
});

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  weight: ['400', '500', '600', '700'],
  display: 'swap',
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  weight: ['400', '500', '600'],
  display: 'swap',
});

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
    <html
      lang="en"
      className={`${newsreader.variable} ${inter.variable} ${ibmPlexMono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
