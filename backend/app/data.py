"""Seed data for the Ketsa market, moved out of the HTML into the backend.

Derived from the original single-file build so the visuals stay faithful,
but now served as JSON over the API rather than hard-coded in JS.
"""

from .models import (
    DashboardData,
    DashboardSeries,
    Market,
    MarketsByCategory,
    PortfolioStats,
    Position,
    Proof,
    TickerItem,
    WatchItem,
)

MARKETS: list[Market] = [
    Market(id='btc-120k', cat='crypto', tag='Crypto', q='Will BTC close above $120,000 before December 31?', yes=41, no=59, meta=('$2.4M vol', '8.1K traders'), trend='up', pts=[10, 14, 12, 18, 16, 22, 20, 26, 24, 28], volume=2_400_000, liquidity=310_000,
           description='Bitcoin has spent most of the year consolidating below all-time highs. Resolves to YES if BTC closes a daily session above $120,000 before 2027 UTC.',
           end_date='2026-12-31T23:59:59Z', created='2026-06-02T12:00:00Z'),
    Market(id='fed-cuts', cat='politics', tag='Politics', q='Will the Fed cut interest rates at the next meeting?', yes=47, no=53, meta=('$5.1M vol', '14K traders'), trend='down', pts=[30, 28, 26, 27, 24, 22, 23, 20, 19, 18], volume=5_100_000, liquidity=420_000,
           description='Trades on whether the FOMC lowers the federal funds target range at its next scheduled meeting. Resolution follows the official statement, not market commentary.',
           end_date='2026-09-16T19:00:00Z', created='2026-07-21T09:00:00Z'),
    Market(id='nova-finals', cat='sports', tag='Sports', q='Will Team Nova win the Apex Championship Finals?', yes=78, no=22, meta=('$1.2M vol', '5.4K traders'), trend='up', pts=[18, 20, 24, 26, 30, 32, 34, 36, 38, 40], volume=1_200_000, liquidity=95_000,
           description='Resolves to YES if Team Nova wins the best-of-seven Apex Championship Finals Series, regardless of map count or individual game scores.',
           end_date='2026-11-22T22:00:00Z', created='2026-08-14T15:00:00Z'),
    Market(id='best-picture', cat='culture', tag='Culture', q='Will the next Best Picture winner be an original screenplay?', yes=55, no=45, meta=('$640K vol', '2.1K traders'), trend='up', pts=[16, 18, 17, 20, 22, 21, 24, 26, 25, 28], volume=640_000, liquidity=58_000,
           description='Resolves to YES if the film awarded Best Picture at the next Academy Awards ceremony is based on an original, non-adapted screenplay.',
           end_date='2027-03-12T02:00:00Z', created='2026-08-30T10:00:00Z'),
    Market(id='ai-10t', cat='tech', tag='Tech', q='Will a major lab ship a 10-trillion parameter model in 2026?', yes=23, no=77, meta=('$980K vol', '3.3K traders'), trend='down', pts=[26, 24, 25, 22, 20, 18, 17, 15, 14, 12], volume=980_000, liquidity=120_000,
           description='Resolves to YES if a model with 10T+ parameters is released to production or research access (API, weights, or on-prem) by a major lab before 2027.',
           end_date='2026-12-31T23:59:59Z', created='2026-05-15T14:00:00Z'),
    Market(id='hottest-year', cat='climate', tag='Climate', q='Will 2026 be recorded as the hottest year on record?', yes=69, no=31, meta=('$1.8M vol', '6.7K traders'), trend='up', pts=[20, 22, 24, 23, 26, 28, 30, 32, 31, 34], volume=1_800_000, liquidity=230_000,
           description='Resolves to YES if the NASA GISTEMP or NOAA global annual temperature anomaly ranks 2026 as the warmest year in the instrumental record.',
           end_date='2027-01-10T00:00:00Z', created='2026-01-08T08:00:00Z'),
    Market(id='eu-dma', cat='politics', tag='Politics', q='Will the EU pass the Digital Markets amendment by Q4?', yes=62, no=38, meta=('$3.3M vol', '9.9K traders'), trend='up', pts=[14, 16, 15, 18, 20, 22, 24, 26, 28, 30], volume=3_300_000, liquidity=280_000,
           description='Resolves to YES if the European Parliament and Council formally adopt the Digital Markets Act amendment before the end of Q4 2026.',
           end_date='2026-12-31T23:59:59Z', created='2026-04-22T11:00:00Z'),
    Market(id='eth-gas', cat='crypto', tag='Crypto', q='Will Ethereum average gas fees drop below 1 gwei this month?', yes=33, no=67, meta=('$710K vol', '2.8K traders'), trend='down', pts=[24, 22, 23, 20, 18, 19, 16, 15, 13, 12], volume=710_000, liquidity=88_000,
           description='Resolves to YES if the 30-day median base fee on the Ethereum L1 falls below 1 gwei during the current calendar month.',
           end_date='2026-09-30T23:59:59Z', created='2026-09-01T09:00:00Z'),
    Market(id='riverside', cat='sports', tag='Sports', q='Will the Riverside Open see a first-time champion this year?', yes=44, no=56, meta=('$540K vol', '1.9K traders'), trend='up', pts=[12, 14, 13, 16, 18, 17, 20, 22, 21, 24], volume=540_000, liquidity=64_000,
           description='Resolves to YES if the winner of the Riverside Open golf tournament has never won the event in a prior year.',
           end_date='2026-10-18T23:59:59Z', created='2026-07-30T13:00:00Z'),
    Market(id='mci-ful-win', cat='sports', tag='Sports', q='Will Manchester City win vs Fulham (2:30)?', yes=82, no=18, meta=('$0 vol', '0 traders'), trend='up', pts=[74, 76, 78, 79, 80, 80, 81, 81, 82, 82], volume=0.0, liquidity=0.0,
           description='Resolves to YES if Manchester City win the match against Fulham in regular time (90 minutes plus stoppage time). Draws and Fulham wins resolve to NO.',
           end_date='2026-11-21T14:30:00Z', created='2026-11-20T00:00:00Z'),
    Market(id='mci-ful-over-3', cat='sports', tag='Sports', q='Will there be over 3 total goals in Manchester City vs Fulham?', yes=40, no=60, meta=('$0 vol', '0 traders'), trend='down', pts=[46, 45, 44, 44, 43, 42, 42, 41, 40, 40], volume=0.0, liquidity=0.0,
           description='Resolves to YES if the match finishes with 4 or more total goals scored by both teams combined in regular time (90 minutes plus stoppage time). 3 or fewer total goals resolves to NO.',
           end_date='2026-11-21T14:30:00Z', created='2026-11-20T00:00:00Z'),
    Market(id='tot-ips-win', cat='sports', tag='Sports', q='Will Tottenham Hotspur win vs Ipswich Town?', yes=76, no=24, meta=('$0 vol', '0 traders'), trend='up', pts=[68, 70, 71, 72, 73, 74, 74, 75, 75, 76], volume=0.0, liquidity=0.0,
           description='Resolves to YES if Tottenham Hotspur win the match against Ipswich Town in regular time (90 minutes plus stoppage time). Draws and Ipswich wins resolve to NO.',
           end_date='2026-11-21T15:00:00Z', created='2026-11-20T00:00:00Z'),
    Market(id='che-lee-win', cat='sports', tag='Sports', q='Will Chelsea win vs Leeds United?', yes=67, no=33, meta=('$0 vol', '0 traders'), trend='up', pts=[60, 61, 62, 63, 64, 64, 65, 66, 66, 67], volume=0.0, liquidity=0.0,
           description='Resolves to YES if Chelsea win the match against Leeds United in regular time (90 minutes plus stoppage time). Draws and Leeds wins resolve to NO.',
           end_date='2026-11-21T15:00:00Z', created='2026-11-20T00:00:00Z'),
    Market(id='che-lee-over-3', cat='sports', tag='Sports', q='Will there be over 3 total goals in Chelsea vs Leeds United?', yes=31, no=69, meta=('$0 vol', '0 traders'), trend='down', pts=[38, 37, 36, 35, 34, 34, 33, 32, 32, 31], volume=0.0, liquidity=0.0,
           description='Resolves to YES if the match finishes with 4 or more total goals scored by both teams combined in regular time (90 minutes plus stoppage time). 3 or fewer total goals resolves to NO.',
           end_date='2026-11-21T15:00:00Z', created='2026-11-20T00:00:00Z'),
    Market(id='zeze-fill-civo', cat='culture', tag='Culture', q='Will Zeze Kingston fill Civo Stadium?', yes=74, no=26, meta=('$0 vol', '0 traders'), trend='up', pts=[66, 67, 68, 69, 70, 71, 72, 72, 73, 74], volume=0.0, liquidity=0.0,
           description='Resolves to YES if Zeze Kingston\'s concert at Civo Stadium is officially declared sold out / at full capacity by the event organizers or venue. Otherwise resolves to NO.',
           end_date='2026-12-31T20:00:00Z', created='2026-11-20T00:00:00Z'),
    Market(id='zeze-over-10k-tickets', cat='culture', tag='Culture', q='Will Zeze Kingston sell over 10,000 tickets?', yes=63, no=37, meta=('$0 vol', '0 traders'), trend='up', pts=[55, 56, 57, 58, 59, 60, 60, 61, 62, 63], volume=0.0, liquidity=0.0,
           description='Resolves to YES if more than 10,000 tickets are sold for the specified Zeze Kingston event, based on official ticketing or organizer figures. 10,000 or fewer tickets sold resolves to NO.',
           end_date='2026-12-31T20:00:00Z', created='2026-11-20T00:00:00Z'),
    Market(id='lil-kellz-fill-mangochi', cat='culture', tag='Culture', q='Will Lil Kellz fill Mangochi Stadium?', yes=40, no=60, meta=('$0 vol', '0 traders'), trend='down', pts=[46, 45, 44, 44, 43, 42, 42, 41, 41, 40], volume=0.0, liquidity=0.0,
           description='Resolves to YES if Lil Kellz\'s concert at Mangochi Stadium is officially declared sold out / at full capacity by the event organizers or venue. Otherwise resolves to NO.',
           end_date='2026-12-31T20:00:00Z', created='2026-11-20T00:00:00Z'),
]

CATEGORIES = ['politics', 'crypto', 'sports', 'culture', 'tech', 'climate']


def markets_by_category() -> MarketsByCategory:
    by = {c: [m for m in MARKETS if m.cat == c] for c in CATEGORIES}
    return MarketsByCategory(**by)


WATCH: list[WatchItem] = [
    WatchItem(name='BTC > $120K', cat='crypto', price=41, pts=[10, 14, 12, 18, 16, 22, 20, 26]),
    WatchItem(name='Fed cuts rates', cat='politics', price=47, pts=[30, 28, 26, 27, 24, 22, 23, 20]),
    WatchItem(name='Nova wins finals', cat='sports', price=78, pts=[18, 20, 24, 26, 30, 32, 34, 36]),
    WatchItem(name='Hottest year on record', cat='climate', price=69, pts=[20, 22, 24, 23, 26, 28, 30, 32]),
    WatchItem(name='EU DMA amendment', cat='politics', price=62, pts=[14, 16, 15, 18, 20, 22, 24, 26]),
]

TICKER: list[TickerItem] = [
    TickerItem(t='BTC > $120K', v='41¢', d='up'),
    TickerItem(t='FED CUTS RATES', v='47¢', d='down'),
    TickerItem(t='NOVA WINS FINALS', v='78¢', d='up'),
    TickerItem(t='HOTTEST YEAR', v='69¢', d='up'),
    TickerItem(t='AI 10T MODEL', v='23¢', d='down'),
    TickerItem(t='ETH GAS < 1GWEI', v='33¢', d='down'),
    TickerItem(t='EU DMA AMENDMENT', v='62¢', d='up'),
    TickerItem(t='BEST PICTURE ORIGINAL', v='55¢', d='up'),
]

DASHBOARD = DashboardData(
    ranges={
        '1D': DashboardSeries(pts=[16800, 17050, 16920, 17240, 17480, 17390, 17650, 17820, 17960, 18120, 18040, 18420], balance=18420, change=4.2),
        '1W': DashboardSeries(pts=[15200, 15800, 15600, 16400, 16100, 16900, 17300, 17100, 17600, 17980], balance=17980, change=8.6),
        '1M': DashboardSeries(pts=[12100, 12800, 12500, 13600, 13100, 14200, 13900, 15000, 15600, 16210], balance=16210, change=21.4),
        '1Y': DashboardSeries(pts=[4200, 5100, 4800, 6300, 7100, 6800, 8200, 7900, 9100, 9800], balance=9800, change=138.2),
    },
    positions=[
        Position(name='BTC > $120K', avg=34, cur=41, pts=[10, 14, 12, 18, 16, 22, 20, 26]),
        Position(name='Fed cuts rates', avg=52, cur=47, pts=[30, 28, 26, 27, 24, 22, 23, 20]),
        Position(name='Nova wins finals', avg=61, cur=78, pts=[18, 20, 24, 26, 30, 32, 34, 36]),
        Position(name='Hottest year on record', avg=58, cur=69, pts=[20, 22, 24, 23, 26, 28, 30, 32]),
    ],
)

STATS = PortfolioStats(pnl=3120, open_positions=4, win_rate=68)

PROOF = Proof(traders_k=412, live_markets=1284, total_volume_m=97.4)
