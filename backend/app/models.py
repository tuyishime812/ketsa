"""Pydantic response models for the Ketsa prediction-market API.

These models are the single source of truth for the wire format that the
Next.js frontend consumes. Keep field names/types in sync with
`frontend/lib/types.ts`.
"""

import math
import re
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

Category = Literal['politics', 'crypto', 'sports', 'culture', 'tech', 'climate']
Trend = Literal['up', 'down']
Outcome = Literal['yes', 'no']
Side = Literal['buy', 'sell']
MarketStatus = Literal['open', 'closed', 'resolved']


class Market(BaseModel):
    id: str
    cat: Category
    tag: str
    q: str
    yes: int  # YES price in cents / probability
    no: int
    meta: Tuple[str, str]
    trend: Trend
    pts: List[int]
    # Marketplace / detail fields (edited+served by the trading engine).
    description: str = ''
    end_date: Optional[str] = None  # ISO-8601 resolution time
    created: Optional[str] = None   # ISO-8601 market listing time
    volume: float = 0.0             # total traded notional, dollars
    liquidity: float = 0.0          # resting book value, dollars
    status: MarketStatus = 'open'
    last_price: Optional[int] = None  # most recent YES fill price in cents
    resolved_outcome: Optional[Outcome] = None  # winning outcome ('yes'/'no')
    resolved_price: Optional[int] = None        # final price of the winning outcome
    resolved_ts: Optional[float] = None         # unix time of resolution
    # Resolution bookkeeping: {"status": "in_progress"|"complete", "outcome",
    # "started_ts", ...}. Declared so it round-trips through admin edits instead
    # of being silently dropped, and so a content writer cannot inject it
    # (admin._SETTLEMENT_FIELDS rejects it on the write path).
    settlement: Optional[dict] = None


class MarketInput(Market):
    """Validated admin create/update payload for a market.

    `Market` is also the public read model, where stricter checks could reject
    historical rows. This subclass constrains what an admin may *write*: the id
    is a URL-safe slug, prices are cents that sum to 100, and the sparkline has
    enough finite points for the detail chart to render.
    """

    id: str = Field(min_length=1, max_length=80)
    tag: str = Field(min_length=1, max_length=40)
    q: str = Field(min_length=1, max_length=300)
    yes: int = Field(ge=0, le=100)
    no: int = Field(ge=0, le=100)
    pts: List[int] = Field(max_length=200)
    description: str = Field(default='', max_length=4000)
    volume: float = Field(default=0.0, ge=0)
    liquidity: float = Field(default=0.0, ge=0)

    @field_validator('id')
    @classmethod
    def _valid_slug(cls, value: str) -> str:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value):
            raise ValueError(
                'id must be a lowercase slug: letters, digits and single hyphens'
            )
        return value

    @field_validator('tag', 'q')
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('must not be empty')
        return value

    @field_validator('pts')
    @classmethod
    def _valid_points(cls, value: List[int]) -> List[int]:
        if len(value) < 2:
            raise ValueError('provide at least two sparkline points')
        if any(point < 0 or point > 100 for point in value):
            raise ValueError('sparkline points must be between 0 and 100')
        return value

    @model_validator(mode='after')
    def _prices_sum_to_100(self) -> 'MarketInput':
        if self.yes + self.no != 100:
            raise ValueError('yes + no must equal 100')
        return self


class ResolveMarketRequest(BaseModel):
    outcome: Outcome
    reason: Optional[str] = Field(default=None, max_length=500)


class OrderLevel(BaseModel):
    price: int
    size: float


class OrderBook(BaseModel):
    yes: int             # current YES price
    no: int
    bids: List[OrderLevel]      # YES bids (buy YES), descending
    asks: List[OrderLevel]      # YES asks (sell YES), ascending
    no_bids: List[OrderLevel]   # NO bids, descending
    no_asks: List[OrderLevel]   # NO asks, ascending
    spread: int
    last: Optional[int] = None


class Trade(BaseModel):
    ts: float
    market_id: str
    question: str = ''
    outcome: Outcome
    side: Side
    price: int   # cents for the traded outcome (YES or NO)
    qty: float   # shares of the traded outcome
    notional: float  # dollars
    kind: Literal['trade', 'resolution'] = 'trade'  # 'resolution' = payout entry


class PositionLot(BaseModel):
    """One individual buy, so a stacked position can be listed per bet."""
    id: str
    shares: float
    price: int      # cents paid for this lot
    notional: float  # dollars committed to this lot
    ts: float


class WalletPosition(BaseModel):
    market_id: str
    question: str
    outcome: Outcome
    shares: float
    avg_price: int
    current_price: int
    value: float
    pnl_value: float
    # Individual fills behind this position, oldest first. Empty for wallets
    # persisted before lots were tracked; the aggregate fields above remain
    # authoritative for cost basis and P&L.
    lots: List[PositionLot] = []


class Wallet(BaseModel):
    id: str
    name: str
    balance: float
    # Real money paid in via PayChangu â€” the ceiling on a withdrawal. Absent on
    # wallets persisted before the field existed, so default to 0.0 (a legacy
    # free seed stays play money and is never cashable).
    withdrawable: float = 0.0
    currency: str = "MWK"
    equity: float
    realized_pnl: float
    positions: List[WalletPosition]
    history: List[Trade]
    created: float


class WalletConnectRequest(BaseModel):
    id: Optional[str] = Field(default=None, max_length=128)
    name: str = Field(default="Trader", max_length=80)


class User(BaseModel):
    id: str
    email: str
    phone: Optional[str] = None
    name: str
    wallet_id: str
    referral_code: str = ""
    referred_by: Optional[str] = None
    referral_earnings: float = 0.0
    referral_count: int = 0
    created: float


class ChangePasswordRequest(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class AdminUserView(BaseModel):
    """A user record enriched with live wallet stats for the admin panel."""
    id: str
    email: str
    phone: Optional[str] = None
    name: str
    wallet_id: str
    created: float
    wallet_equity: Optional[float] = None
    wallet_balance: Optional[float] = None
    # Real money paid in through mobile money â€” the only cashable-out pool.
    wallet_withdrawable: Optional[float] = None
    wallet_currency: str = "MWK"
    positions: int = 0
    trades: int = 0
    # Wallet cash flow, from the (completed) PayChangu ledger, plus a count of
    # payments still in flight so an operator can spot a stuck withdrawal.
    deposits_total: float = 0.0
    withdrawals_total: float = 0.0
    pending_payments: int = 0
    last_seen: Optional[float] = None


# --- Staff directory --------------------------------------------------------
#
# A staff member is an operator of the platform (support, finance, â€¦), distinct
# from a trader account. Roles are an allowlist, not free text: the value is
# rendered in the admin UI and interpolated into the invite email, so an
# unbounded string would be a stored-injection vector.

STAFF_ROLES = ("owner", "admin", "support", "finance", "marketing", "moderation")


class StaffCreate(BaseModel):
    """Admin input for adding one staff member."""
    name: str
    email: str
    phone: Optional[str] = None
    role: str = "support"


class StaffUpdate(BaseModel):
    """Partial update (e.g. toggle `active`). Unset fields are left alone."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None


class StaffUpload(BaseModel):
    """Bulk add. Send a raw CSV/JSON *text* payload and/or pre-parsed rows."""
    text: Optional[str] = None
    rows: Optional[List[dict]] = None


class StaffMember(BaseModel):
    """Full staff record â€” the admin view, including contact details.

    Credential material (password hash, invite-token digest) is never part of
    this model; ``staff.admin_view`` projects it away and adds these status
    fields instead.
    """
    id: str
    name: str
    email: str
    phone: Optional[str] = None
    role: str
    active: bool = True
    created: float
    updated: float
    invited_ts: Optional[float] = None
    login_enabled: bool = False
    invite_pending: bool = False
    last_login_ts: Optional[float] = None


class StaffAcceptInvite(BaseModel):
    """Set-password payload for a single-use invite/reset link."""
    token: str = Field(max_length=128)
    password: str = Field(max_length=256)


class StaffForgotPassword(BaseModel):
    """Self-service reset request. Always answered generically."""
    email: str = Field(max_length=200)


class StaffChangePassword(BaseModel):
    """Password change for an already-authenticated staff session."""
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)



class StaffPublic(BaseModel):
    """Public view â€” deliberately WITHOUT email/phone (PII)."""
    id: str
    name: str
    role: str


class StaffUploadResult(BaseModel):
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = []


class StaffInviteResult(BaseModel):
    ok: bool
    delivered: bool
    detail: str


class LeaderboardEntry(BaseModel):
    rank: int
    wallet_id: str
    name: str
    equity: float
    realized_pnl: float
    positions: int
    currency: str = "MWK"


class Notification(BaseModel):
    id: str
    wallet_id: str
    type: str  # fill | deposit | withdraw | system
    title: str
    message: str
    ts: float
    read: bool = False


class MarkReadRequest(BaseModel):
    ids: list[str] = []


class TradeLeg(BaseModel):
    market_id: str
    outcome: Outcome
    side: Side = 'buy'
    amount: Optional[float] = None
    shares: Optional[float] = None

    @field_validator("amount", "shares")
    @classmethod
    def _finite_positive(cls, v: Optional[float], info) -> Optional[float]:
        if v is not None and (not math.isfinite(v) or v <= 0):
            raise ValueError(f"{info.field_name} must be a finite, positive number")
        return v


class TradeRequest(BaseModel):
    wallet_id: str
    market_id: Optional[str] = None
    outcome: Optional[Outcome] = None
    side: Side = 'buy'
    amount: Optional[float] = None  # dollars â€” required for buys
    shares: Optional[float] = None  # shares â€” required for sells
    legs: Optional[List[TradeLeg]] = None
    slip: Optional[List[TradeLeg]] = None
    bets: Optional[List[TradeLeg]] = None

    @field_validator("amount", "shares")
    @classmethod
    def _finite_positive(cls, v: Optional[float], info) -> Optional[float]:
        # JSON parsers accept NaN/Infinity literals; money math must never
        # receive them (false balance checks, poisoned ledgers).
        if v is not None and (not math.isfinite(v) or v <= 0):
            raise ValueError(f"{info.field_name} must be a finite, positive number")
        return v


class TradeResponse(BaseModel):
    wallet: Wallet
    market: Optional[Market] = None
    book: Optional[OrderBook] = None
    trade: Optional[Trade] = None
    trades: Optional[List[Trade]] = None
    results: Optional[List[dict]] = None


class WatchItem(BaseModel):
    name: str
    cat: Category
    price: int
    pts: List[int]


class TickerItem(BaseModel):
    t: str
    v: str
    d: Trend


class Position(BaseModel):
    name: str
    avg: int
    cur: int
    pts: List[int]


class DashboardSeries(BaseModel):
    pts: List[int]
    balance: int
    change: float


class DashboardData(BaseModel):
    ranges: dict[str, DashboardSeries]
    positions: List[Position]


class PortfolioStats(BaseModel):
    pnl: int
    open_positions: int
    win_rate: int


class MarketsByCategory(BaseModel):
    politics: List[Market]
    crypto: List[Market]
    sports: List[Market]
    culture: List[Market]
    tech: List[Market]
    climate: List[Market]


class MarketsGroup(BaseModel):
    all: List[Market]
    by_category: MarketsByCategory


class Proof(BaseModel):
    traders_k: int
    live_markets: int
    total_volume_m: float


class HomeData(BaseModel):
    markets: MarketsGroup
    watch: List[WatchItem]
    ticker: List[TickerItem]
    dashboard: DashboardData
    stats: PortfolioStats
    proof: Proof
    settings: dict[str, object] = {}  # editable site content (hero, cta, steps, footer, ...)


class DepositRequest(BaseModel):
    wallet_id: str
    amount: float
    number: str
    correspondent: str  # AIRTEL_MWI | TNM_MWI

    @field_validator("amount")
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("amount must be a finite, positive number")
        return v


class WithdrawalRequest(BaseModel):
    wallet_id: str
    amount: float
    number: str
    correspondent: str  # AIRTEL_MWI | TNM_MWI

    @field_validator("amount")
    @classmethod
    def _finite_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("amount must be a finite, positive number")
        return v


class Payment(BaseModel):
    id: str
    wallet_id: str
    kind: str  # deposit | withdraw
    amount: float
    number: str
    correspondent: str
    status: str  # pending | completed | failed
    credited: bool = False  # deposits only - idempotency guard
    rolled_back: bool = False  # withdrawals only - refund guard if the payout fails
    # The provider's charge id. We generate it ourselves (the payment id) so it
    # is stable across retries and webhooks can be matched idempotently.
    provider_charge_id: str | None = None
    # Legacy field name kept on the wire so older clients/records still parse.
    wande_id: str | None = None
    message: str | None = None
    provider: str | None = None  # e.g. paychangu, binance_pay
    invoice_id: str | None = None
    invoice_url: str | None = None
    qr_code: str | None = None
    deposit_address: str | None = None
    crypto_amount: float | None = None
    crypto_currency: str | None = None
    crypto_network: str | None = None
    expires_at: float | None = None
    created: float
    updated: float

    @model_validator(mode="before")
    @classmethod
    def _legacy_provider_id(cls, data):
        if isinstance(data, dict):
            provider = data.get("provider_charge_id") or data.get("wande_id")
            if provider:
                data = {**data, "provider_charge_id": provider, "wande_id": data.get("wande_id") or provider}
        return data
