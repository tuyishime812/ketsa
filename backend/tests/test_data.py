"""Tests for the seed data layer and its internal consistency."""

from app.data import (
    CATEGORIES,
    DASHBOARD,
    MARKETS,
    PROOF,
    STATS,
    TICKER,
    WATCH,
    markets_by_category,
)


def test_market_ids_unique() -> None:
    ids = [m.id for m in MARKETS]
    assert len(ids) == len(set(ids)), "market ids must be unique"


def test_market_categories_valid() -> None:
    for m in MARKETS:
        assert m.cat in CATEGORIES


def test_yes_no_prices_in_range() -> None:
    for m in MARKETS:
        assert 1 <= m.yes <= 99
        assert 1 <= m.no <= 99
        # YES + NO should be 100 for a fair binary market.
        assert m.yes + m.no == 100


def test_every_market_has_points() -> None:
    for m in MARKETS:
        assert len(m.pts) >= 2


def test_by_category_partitions_all_markets() -> None:
    by = markets_by_category()
    grouped = []
    for cat in CATEGORIES:
        for m in getattr(by, cat):
            assert m.cat == cat
            grouped.append(m.id)
    assert sorted(grouped) == sorted(m.id for m in MARKETS)


def test_watch_price_range() -> None:
    for item in WATCH:
        assert 1 <= item.price <= 99


def test_ticker_directions_valid() -> None:
    for item in TICKER:
        assert item.d in ("up", "down")


def test_dashboard_ranges_consistent() -> None:
    for key, series in DASHBOARD.ranges.items():
        assert series.pts, f"range {key} has no points"
        # Balance should match the last recorded point in the series.
        assert series.balance == series.pts[-1]


def test_proof_stats_shape() -> None:
    assert PROOF.traders_k > 0
    assert PROOF.live_markets > 0
    assert PROOF.total_volume_m > 0
    assert STATS.pnl >= 0
    assert STATS.open_positions >= 0
    assert 0 <= STATS.win_rate <= 100
