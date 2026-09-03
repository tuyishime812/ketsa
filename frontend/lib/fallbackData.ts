// Bundled fallback data mirroring the FastAPI backend seed.
// Used so the page renders even if the backend isn't running (dev convenience).

import type { HomeData, SiteSettings } from './types';

export const fallbackSettings: SiteSettings = {
  hero: {
    headline_1: 'Trade on ',
    headline_accent: 'what happens next.',
    description:
      'Ketsa is a real-time market for the outcomes that matter — politics, crypto, sport, and culture. Prices move with the crowd, not a bookmaker, and you can exit the instant the odds turn your way.',
    badge: '$97.4M traded this week',
  },
  cta: {
    title: 'Markets are opinions with a price.',
    description:
      'Put a number on what you believe. Ketsa turns your read on the world into a position you can trade.',
    button: 'Create an account',
  },
  steps: {
    kicker: 'Mechanics',
    title: 'Three steps, one price',
    description:
      'No order forms, no fine print. Shares trade between 1¢ and 99¢ based on what the market believes.',
    items: [
      {
        num: '01',
        title: 'Pick a market',
        body: 'Browse thousands of questions on politics, crypto, sport, and culture — each priced by real trading, not a bookmaker\u2019s line.',
      },
      {
        num: '02',
        title: 'Buy Yes or No',
        body: 'Shares cost between 1¢ and 99¢. If you\u2019re right, each share resolves to $1. If you\u2019re wrong, it resolves to zero.',
      },
      {
        num: '03',
        title: 'Cash out anytime',
        body: 'Sell your position the moment the odds move your way — you don\u2019t have to wait for the market to resolve.',
      },
    ],
  },
  footer: {
    tagline:
      "A real-time market for the questions everyone's arguing about. Trade the odds, not the opinions.",
    columns: [
      {
        title: 'Product',
        links: [
          { label: 'Markets', href: '#markets' },
          { label: 'Dashboard', href: '#dashboard' },
          { label: 'How it works', href: '#how' },
          { label: 'Pricing', href: '#top' },
        ],
      },
      {
        title: 'Company',
        links: [
          { label: 'About', href: '#top' },
          { label: 'Careers', href: '#top' },
          { label: 'Blog', href: '#top' },
          { label: 'Contact', href: '#top' },
        ],
      },
      {
        title: 'Resources',
        links: [
          { label: 'Docs', href: '#top' },
          { label: 'API', href: '#top' },
          { label: 'Status', href: '#top' },
          { label: 'Support', href: '#top' },
        ],
      },
    ],
    copyright: '© 2026 Ketsa. All rights reserved.',
    disclaimer: 'Trading involves risk. Markets resolve based on published rules.',
  },
  markets_section: {
    kicker: 'Order book',
    title: 'Markets moving right now',
    description:
      'Every price is a probability. Buy the side you believe, sell whenever the market catches up to you.',
  },
  dashboard_section: {
    kicker: 'Dashboard',
    title: 'Your positions, priced live',
    description:
      "Track performance across every market you're in, updated in real time as odds move.",
  },
};

export const fallbackHomeData: HomeData = {
  markets: {
    all: [
      { id: 'btc-120k', cat: 'crypto', tag: 'Crypto', q: 'Will BTC close above $120,000 before December 31?', yes: 41, no: 59, meta: ['$2.4M vol', '8.1K traders'], trend: 'up', pts: [10, 14, 12, 18, 16, 22, 20, 26, 24, 28] },
      { id: 'fed-cuts', cat: 'politics', tag: 'Politics', q: 'Will the Fed cut interest rates at the next meeting?', yes: 47, no: 53, meta: ['$5.1M vol', '14K traders'], trend: 'down', pts: [30, 28, 26, 27, 24, 22, 23, 20, 19, 18] },
      { id: 'nova-finals', cat: 'sports', tag: 'Sports', q: 'Will Team Nova win the Apex Championship Finals?', yes: 78, no: 22, meta: ['$1.2M vol', '5.4K traders'], trend: 'up', pts: [18, 20, 24, 26, 30, 32, 34, 36, 38, 40] },
      { id: 'best-picture', cat: 'culture', tag: 'Culture', q: 'Will the next Best Picture winner be an original screenplay?', yes: 55, no: 45, meta: ['$640K vol', '2.1K traders'], trend: 'up', pts: [16, 18, 17, 20, 22, 21, 24, 26, 25, 28] },
      { id: 'ai-10t', cat: 'tech', tag: 'Tech', q: 'Will a major lab ship a 10-trillion parameter model in 2026?', yes: 23, no: 77, meta: ['$980K vol', '3.3K traders'], trend: 'down', pts: [26, 24, 25, 22, 20, 18, 17, 15, 14, 12] },
      { id: 'hottest-year', cat: 'climate', tag: 'Climate', q: 'Will 2026 be recorded as the hottest year on record?', yes: 69, no: 31, meta: ['$1.8M vol', '6.7K traders'], trend: 'up', pts: [20, 22, 24, 23, 26, 28, 30, 32, 31, 34] },
      { id: 'eu-dma', cat: 'politics', tag: 'Politics', q: 'Will the EU pass the Digital Markets amendment by Q4?', yes: 62, no: 38, meta: ['$3.3M vol', '9.9K traders'], trend: 'up', pts: [14, 16, 15, 18, 20, 22, 24, 26, 28, 30] },
      { id: 'eth-gas', cat: 'crypto', tag: 'Crypto', q: 'Will Ethereum average gas fees drop below 1 gwei this month?', yes: 33, no: 67, meta: ['$710K vol', '2.8K traders'], trend: 'down', pts: [24, 22, 23, 20, 18, 19, 16, 15, 13, 12] },
      { id: 'riverside', cat: 'sports', tag: 'Sports', q: 'Will the Riverside Open see a first-time champion this year?', yes: 44, no: 56, meta: ['$540K vol', '1.9K traders'], trend: 'up', pts: [12, 14, 13, 16, 18, 17, 20, 22, 21, 24] },
    ],
    by_category: {
      politics: [
        { id: 'fed-cuts', cat: 'politics', tag: 'Politics', q: 'Will the Fed cut interest rates at the next meeting?', yes: 47, no: 53, meta: ['$5.1M vol', '14K traders'], trend: 'down', pts: [30, 28, 26, 27, 24, 22, 23, 20, 19, 18] },
        { id: 'eu-dma', cat: 'politics', tag: 'Politics', q: 'Will the EU pass the Digital Markets amendment by Q4?', yes: 62, no: 38, meta: ['$3.3M vol', '9.9K traders'], trend: 'up', pts: [14, 16, 15, 18, 20, 22, 24, 26, 28, 30] },
      ],
      crypto: [
        { id: 'btc-120k', cat: 'crypto', tag: 'Crypto', q: 'Will BTC close above $120,000 before December 31?', yes: 41, no: 59, meta: ['$2.4M vol', '8.1K traders'], trend: 'up', pts: [10, 14, 12, 18, 16, 22, 20, 26, 24, 28] },
        { id: 'eth-gas', cat: 'crypto', tag: 'Crypto', q: 'Will Ethereum average gas fees drop below 1 gwei this month?', yes: 33, no: 67, meta: ['$710K vol', '2.8K traders'], trend: 'down', pts: [24, 22, 23, 20, 18, 19, 16, 15, 13, 12] },
      ],
      sports: [
        { id: 'nova-finals', cat: 'sports', tag: 'Sports', q: 'Will Team Nova win the Apex Championship Finals?', yes: 78, no: 22, meta: ['$1.2M vol', '5.4K traders'], trend: 'up', pts: [18, 20, 24, 26, 30, 32, 34, 36, 38, 40] },
        { id: 'riverside', cat: 'sports', tag: 'Sports', q: 'Will the Riverside Open see a first-time champion this year?', yes: 44, no: 56, meta: ['$540K vol', '1.9K traders'], trend: 'up', pts: [12, 14, 13, 16, 18, 17, 20, 22, 21, 24] },
      ],
      culture: [
        { id: 'best-picture', cat: 'culture', tag: 'Culture', q: 'Will the next Best Picture winner be an original screenplay?', yes: 55, no: 45, meta: ['$640K vol', '2.1K traders'], trend: 'up', pts: [16, 18, 17, 20, 22, 21, 24, 26, 25, 28] },
      ],
      tech: [
        { id: 'ai-10t', cat: 'tech', tag: 'Tech', q: 'Will a major lab ship a 10-trillion parameter model in 2026?', yes: 23, no: 77, meta: ['$980K vol', '3.3K traders'], trend: 'down', pts: [26, 24, 25, 22, 20, 18, 17, 15, 14, 12] },
      ],
      climate: [
        { id: 'hottest-year', cat: 'climate', tag: 'Climate', q: 'Will 2026 be recorded as the hottest year on record?', yes: 69, no: 31, meta: ['$1.8M vol', '6.7K traders'], trend: 'up', pts: [20, 22, 24, 23, 26, 28, 30, 32, 31, 34] },
      ],
    },
  },
  watch: [
    { name: 'BTC > $120K', cat: 'crypto', price: 41, pts: [10, 14, 12, 18, 16, 22, 20, 26] },
    { name: 'Fed cuts rates', cat: 'politics', price: 47, pts: [30, 28, 26, 27, 24, 22, 23, 20] },
    { name: 'Nova wins finals', cat: 'sports', price: 78, pts: [18, 20, 24, 26, 30, 32, 34, 36] },
    { name: 'Hottest year on record', cat: 'climate', price: 69, pts: [20, 22, 24, 23, 26, 28, 30, 32] },
    { name: 'EU DMA amendment', cat: 'politics', price: 62, pts: [14, 16, 15, 18, 20, 22, 24, 26] },
  ],
  ticker: [
    { t: 'BTC > $120K', v: '41¢', d: 'up' },
    { t: 'FED CUTS RATES', v: '47¢', d: 'down' },
    { t: 'NOVA WINS FINALS', v: '78¢', d: 'up' },
    { t: 'HOTTEST YEAR', v: '69¢', d: 'up' },
    { t: 'AI 10T MODEL', v: '23¢', d: 'down' },
    { t: 'ETH GAS < 1GWEI', v: '33¢', d: 'down' },
    { t: 'EU DMA AMENDMENT', v: '62¢', d: 'up' },
    { t: 'BEST PICTURE ORIGINAL', v: '55¢', d: 'up' },
  ],
  dashboard: {
    ranges: {
      '1D': { pts: [16800, 17050, 16920, 17240, 17480, 17390, 17650, 17820, 17960, 18120, 18040, 18420], balance: 18420, change: 4.2 },
      '1W': { pts: [15200, 15800, 15600, 16400, 16100, 16900, 17300, 17100, 17600, 17980], balance: 17980, change: 8.6 },
      '1M': { pts: [12100, 12800, 12500, 13600, 13100, 14200, 13900, 15000, 15600, 16210], balance: 16210, change: 21.4 },
      '1Y': { pts: [4200, 5100, 4800, 6300, 7100, 6800, 8200, 7900, 9100, 9800], balance: 9800, change: 138.2 },
    },
    positions: [
      { name: 'BTC > $120K', avg: 34, cur: 41, pts: [10, 14, 12, 18, 16, 22, 20, 26] },
      { name: 'Fed cuts rates', avg: 52, cur: 47, pts: [30, 28, 26, 27, 24, 22, 23, 20] },
      { name: 'Nova wins finals', avg: 61, cur: 78, pts: [18, 20, 24, 26, 30, 32, 34, 36] },
      { name: 'Hottest year on record', avg: 58, cur: 69, pts: [20, 22, 24, 23, 26, 28, 30, 32] },
    ],
  },
  stats: { pnl: 3120, open_positions: 4, win_rate: 68 },
  proof: { traders_k: 412, live_markets: 1284, total_volume_m: 97.4 },
  settings: fallbackSettings,
};
