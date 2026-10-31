// Shared domain types for the Ketsa prediction-market frontend.
// These mirror the models exposed by the Ketsa API.

export type Category =
  | 'politics'
  | 'crypto'
  | 'sports'
  | 'culture'
  | 'tech'
  | 'climate';

export type Trend = 'up' | 'down';

export type Outcome = 'yes' | 'no';
export type Side = 'buy' | 'sell';

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
  description?: string;
  end_date?: string | null; // ISO-8601 resolution time
  created?: string | null; // ISO-8601 listing time
  volume?: number; // traded notional, dollars
  liquidity?: number; // resting book value, dollars
  status?: 'open' | 'closed' | 'resolved';
  last_price?: number | null; // most recent YES fill price in cents
  resolved_outcome?: Outcome | null; // winning outcome once resolved
  resolved_price?: number | null; // final price of the YES side (100 or 0)
  resolved_ts?: number | null; // unix time of resolution
}

export interface OrderLevel {
  price: number; // cents
  size: number; // shares
}

export interface OrderBook {
  yes: number;
  no: number;
  bids: OrderLevel[]; // YES bids, descending
  asks: OrderLevel[]; // YES asks, ascending
  no_bids: OrderLevel[]; // NO bids, descending
  no_asks: OrderLevel[]; // NO asks, ascending
  spread: number;
  last?: number | null;
}

export interface Trade {
  ts: number;
  market_id: string;
  question?: string;
  outcome: Outcome;
  side: Side;
  price: number; // cents for the traded outcome
  qty: number; // shares
  notional: number; // dollars
  kind?: 'trade' | 'resolution'; // 'resolution' = payout entry at settlement
}

/** One individual buy. Repeat buys on the same market+outcome stay separate
 *  lots so each bet is listed, while the parent position keeps the averaged
 *  cost basis used for P&L. */
export interface PositionLot {
  id: string;
  shares: number;
  price: number; // cents paid for this lot
  notional: number; // dollars committed
  ts: number;
}

export interface WalletPosition {
  market_id: string;
  question: string;
  outcome: Outcome;
  shares: number;
  avg_price: number;
  current_price: number;
  value: number;
  pnl_value: number;
  /** Individual fills behind this position, oldest first. Empty for wallets
   *  persisted before lots were tracked. */
  lots?: PositionLot[];
}

export interface Wallet {
  id: string;
  name: string;
  balance: number;
  /** Real money paid in via mobile money — the ceiling on a withdrawal. */
  withdrawable: number;
  currency: string; // e.g. MWK
  equity: number;
  realized_pnl: number;
  positions: WalletPosition[];
  history: Trade[];
  created: number;
}

export interface User {
  id: string;
  email: string;
  phone?: string | null;
  name: string;
  wallet_id: string;
  created: number;
}

export interface AuthSession {
  token: string;
  user: User;
  wallet: Wallet;
}

/** 202 returned by /register for email signups awaiting OTP verification. */
export interface PendingVerification {
  ok: boolean;
  pending: true;
  email: string;
  /** Local-dev only (log email delivery + explicit opt-in); never in prod. */
  dev_otp?: string | null;
}

export type RegisterResult = AuthSession | PendingVerification;

export interface AuthCredentials {
  identifier: string; // email address OR Malawian phone number
  password: string;
}

export interface RegisterCredentials {
  name: string;
  identifier: string; // email address OR Malawian phone number
  password: string;
}

export interface LeaderboardEntry {
  rank: number;
  wallet_id: string;
  name: string;
  equity: number;
  realized_pnl: number;
  positions: number;
  currency: string;
}

export type NotificationType = 'fill' | 'deposit' | 'withdraw' | 'system';

export interface NotificationItem {
  id: string;
  wallet_id: string;
  type: NotificationType;
  title: string;
  message: string;
  ts: number;
  read: boolean;
}

/** User record enriched with live wallet stats, exposed to the admin panel. */
export interface AdminUserView {
  id: string;
  email: string;
  phone?: string | null;
  name: string;
  wallet_id: string;
  created: number;
  wallet_equity?: number | null;
  wallet_balance?: number | null;
  /** Real money paid in via mobile money — the only cashable-out pool. */
  wallet_withdrawable?: number | null;
  wallet_currency?: string;
  positions: number;
  trades: number;
  /** Completed PayChangu cash flow, in the wallet's currency. */
  deposits_total: number;
  withdrawals_total: number;
  /** Payments still pending (e.g. a withdrawal waiting on payout). */
  pending_payments: number;
  last_seen?: number | null;
}

export type PaymentKind = 'deposit' | 'withdraw';
export type PaymentStatus = 'pending' | 'completed' | 'failed';

export interface Payment {
  id: string;
  wallet_id: string;
  kind: PaymentKind;
  amount: number;
  number: string;
  correspondent: string; // AIRTEL_MWI | TNM_MWI
  status: PaymentStatus;
  credited: boolean;
  rolled_back: boolean;
  wande_id: string | null;
  message: string | null;
  created: number;
  updated: number;
}

export type Correspondent = 'AIRTEL_MWI' | 'TNM_MWI';

export interface TradeLeg {
  market_id: string;
  outcome: Outcome;
  side?: Side;
  amount?: number; // dollars — for buys
  shares?: number; // shares — for sells
}

export interface TradeRequest {
  wallet_id: string;
  market_id?: string;
  outcome?: Outcome;
  side?: Side;
  amount?: number; // dollars — for buys
  shares?: number; // shares — for sells
  legs?: TradeLeg[];
  slip?: TradeLeg[];
  bets?: TradeLeg[];
}

export interface TradeResponse {
  wallet: Wallet;
  market?: Market;
  book?: OrderBook;
  trade?: Trade;
  trades?: Trade[];
  results?: unknown[];
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

// --- Staff directory --------------------------------------------------------

export type StaffRole =
  | 'owner'
  | 'admin'
  | 'support'
  | 'finance'
  | 'marketing'
  | 'moderation';

export const STAFF_ROLES: StaffRole[] = [
  'owner',
  'admin',
  'support',
  'finance',
  'marketing',
  'moderation',
];

/** Public team directory entry — no contact details (PII). */
export interface StaffPublic {
  id: string;
  name: string;
  role: string;
}

/** Full staff record (admin view) — includes contact details. */
export interface StaffMember {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  role: string;
  active: boolean;
  created: number;
  updated: number;
  invited_ts?: number | null;
}

export interface StaffUploadResult {
  added: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export interface StaffInviteResult {
  ok: boolean;
  delivered: boolean;
  detail: string;
}

/**
 * A realtime `staff` event broadcast on the shared WebSocket. `staff` is the
 * public (PII-free) projection; `upload`/`invite` carry `staff: null` and ask
 * clients to re-fetch the authoritative list.
 */
export interface StaffWsEvent {
  type: 'staff';
  action: 'add' | 'update' | 'remove' | 'upload' | 'invite';
  id?: string;
  staff: (StaffPublic & { active: boolean }) | null;
}

// --- Admin config (Settings tab) --------------------------------------------
// Operational controls read/written via GET/PUT /api/admin/config[/{section}].

export interface PaymentsConfig {
  deposits_enabled: boolean;
  withdrawals_enabled: boolean;
  max_deposit_mwk: number;
  max_withdrawal_mwk: number;
  daily_withdrawal_limit_mwk: number;
}

export interface SecurityConfig {
  admin_max_failures: number;
  admin_lockout_seconds: number;
}

export interface StaffRolesConfig {
  roles: string[];
}

export interface ResolutionConfig {
  resolution_enabled: boolean;
  require_end_date: boolean;
}

export interface AdminConfig {
  payments: PaymentsConfig;
  security: SecurityConfig;
  staff_roles: StaffRolesConfig;
  resolution: ResolutionConfig;
}

