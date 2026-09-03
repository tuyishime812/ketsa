// Shared domain types for the Ketsa prediction-market frontend.
// These mirror the Pydantic models exposed by the FastAPI backend.

export type Category =
  | 'politics'
  | 'crypto'
  | 'sports'
  | 'culture'
  | 'tech'
  | 'climate';

export type Trend = 'up' | 'down';

export interface Market {
  id: string;
  cat: Category;
  tag: string;
  q: string;
  yes: number; // YES price in cents (same as probability %)
  no: number; // NO price in cents
  meta: [string, string];
  trend: Trend;
  pts: number[]; // sparkline points
}

export interface WatchItem {
  name: string;
  cat: string;
  price: number; // cents
  pts: number[];
}

export interface TickerItem {
  t: string;
  v: string; // e.g. "41¢"
  d: Trend;
}

export interface Position {
  name: string;
  avg: number;
  cur: number;
  pts: number[];
}

export interface DashboardSeries {
  pts: number[];
  balance: number;
  change: number;
}

export interface DashboardData {
  ranges: Record<string, DashboardSeries>;
  positions: Position[];
}

export interface PortfolioStats {
  pnl: number;
  open_positions: number;
  win_rate: number;
}

export interface Proof {
  traders_k: number;
  live_markets: number;
  total_volume_m: number;
}

export interface HomeData {
  markets: {
    all: Market[];
    by_category: Record<Category, Market[]>;
  };
  watch: WatchItem[];
  ticker: TickerItem[];
  dashboard: DashboardData;
  stats: PortfolioStats;
  proof: Proof;
  settings?: SiteSettings;
}

// ---------------------------------------------------------------------------
// Admin + editable content types
// ---------------------------------------------------------------------------

export interface HeroContent {
  headline_1: string;
  headline_accent: string;
  description: string;
  badge: string;
}

export interface CtaContent {
  title: string;
  description: string;
  button: string;
}

export interface StepItem {
  num: string;
  title: string;
  body: string;
}

export interface StepsContent {
  kicker: string;
  title: string;
  description: string;
  items: StepItem[];
}

export interface FooterLink {
  label: string;
  href: string;
}

export interface FooterColumn {
  title: string;
  links: FooterLink[];
}

export interface FooterContent {
  tagline: string;
  columns: FooterColumn[];
  copyright: string;
  disclaimer: string;
}

export interface SectionCopy {
  kicker: string;
  title: string;
  description: string;
}

export interface SiteSettings {
  hero: HeroContent;
  cta: CtaContent;
  steps: StepsContent;
  footer: FooterContent;
  markets_section: SectionCopy;
  dashboard_section: SectionCopy;
}

