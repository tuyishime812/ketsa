"""In-memory marketplace engine for Ketsa trading.

This adds Polymarket-style trading to the content served by the storage
backends. It is deliberately decoupled from `storage.py`:

* The storage backends remain the source of truth for *market content*
  (question, category, description, …) as edited through the admin panel.
* The engine holds the *live runtime* state: resting order books, price
  ticks, user wallets/positions and a per-market trade tape. This state is
  kept in memory (per app instance) so no extra infrastructure is required for
  the simulated-wallet experience. Persisting the ledger would need a
  multi-tenant database and is out of scope for a play-market.

Prices are integer cents (1–99). YES and NO are complementary (YES + NO = 100).
Trading always takes place against the YES-side book; a NO buy/sell is a YES
book level on the opposite side, so every order rests or fills in the same
central limit order book — the same synthetic market-maker structure Polymarket
itself uses for NO tokens.
"""

from __future__ import annotations

import copy
import random
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable

from . import dblock, store

CENTS_MIN = 1
CENTS_MAX = 99
MAX_PTS = 48
WALLET_START_BALANCE = 0.0  # no free money: real funds come from deposits only
WALLET_CURRENCY = "MWK"
BOOK_DEPTH = 5
MIN_LIQUIDITY = 200.0
REPLENISH_INTERVAL = 10.0
LEVEL_WEIGHTS = [0.32, 0.26, 0.20, 0.14, 0.08]
_EPS = 1e-6


def _clamp(value: int, lo: int = CENTS_MIN, hi: int = CENTS_MAX) -> int:
    return max(lo, min(hi, value))


def _round2(x: float) -> float:
    return round(x, 2)


def _round4(x: float) -> float:
    return round(x, 4)


def _trading_block_reason(market: dict | None) -> str | None:
    """Return why a market cannot accept new orders, or ``None`` if it can.

    Trading is settled against real money, so a market must stop accepting
    orders the moment its published end date passes — not only when an operator
    later marks it resolved. Unparseable/missing dates are treated as open (a
    content bug must not silently freeze every market).
    """
    if not market:
        return None
    if market.get("status") == "resolved":
        return "This market has resolved — trading is closed"
    if market.get("status") == "closed":
        return "This market is closed — trading has stopped"
    end_date = market.get("end_date")
    if not end_date:
        return None
    try:
        due = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
    except ValueError:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= due:
        return "This market has reached its end date — trading is closed"
    return None


class Marketplace:
    """Holds books, wallets and trades; executes market orders."""

    def __init__(self) -> None:
        self._books: dict[str, dict] = {}
        self._wallets: dict[str, dict] = {}
        self._trades: dict[str, list[dict]] = {}
        self._events: list[dict[str, Any]] = []
        # Set by main.py at startup. Fired after every event is queued so the
        # WS pump task wakes immediately instead of waiting for the next poll
        # tick. This is what makes admin-side changes (e.g. staff uploads) push
        # to connected clients in real time. None in tests / bare imports.
        self._emit_hook: Callable[[], None] | None = None
        # Multi-leg execution is atomic: while a slip runs, notifications and
        # stream events are queued (and wallet writes deferred) so a failure in
        # leg N cannot leak fills/events from legs 1..N-1. See `place_trade`.
        self._deferred_notifications: list[dict[str, Any]] | None = None
        self._deferred_events: list[dict[str, Any]] | None = None
        self._deferred_persist = False

    # ------------------------------------------------------------------
    # Event stream (pumped to WebSocket clients by main.py)
    # ------------------------------------------------------------------

    def flush_events(self) -> list[dict[str, Any]]:
        events, self._events = self._events, []
        return events

    def set_emit_hook(self, hook: Callable[[], None] | None) -> None:
        """Register a callback fired after every queued event.

        main.py points this at an ``asyncio.Event.set`` hop so its pump task
        broadcasts within a loop iteration (real time) rather than on the 12s
        poll tick. Wrapped by ``_emit`` so a misbehaving hook can never break
        trading: emit is on the hot path of every fill.
        """
        self._emit_hook = hook

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._deferred_events is not None:
            self._deferred_events.append(payload)
            return
        self._events.append(payload)
        hook = self._emit_hook
        if hook is not None:
            try:
                hook()
            except Exception:  # pragma: no cover - defensive: never break a fill
                pass

    def _emit_market(self, market_id: str) -> None:
        snap = self.snapshot_market(market_id)
        if snap is not None:
            self._emit({"type": "market", "market": snap})

    # ------------------------------------------------------------------
    # Market book lifecycle
    # ------------------------------------------------------------------

    def _target_size(self, price: int, weight: float, liquidity: float) -> float:
        # A price level worth `weight` of the liquidity pool, held in shares.
        return (liquidity * weight) / (price / 100.0)

    def _build_levels(self, book: dict) -> None:
        bids: list[dict] = []
        asks: list[dict] = []
        yes = book["yes"]
        liquidity = book["liquidity"]
        for i, weight in enumerate(LEVEL_WEIGHTS, start=1):
            ask_price = yes + i
            if ask_price <= CENTS_MAX:
                asks.append(
                    {"price": ask_price, "size": _round4(self._target_size(ask_price, weight, liquidity))}
                )
            bid_price = yes - i
            if bid_price >= CENTS_MIN:
                bids.append(
                    {"price": bid_price, "size": _round4(self._target_size(bid_price, weight, liquidity))}
                )
        # Asks ascending (best first), bids descending (best first).
        book["asks"] = sorted(asks, key=lambda lv: lv["price"])
        book["bids"] = sorted(bids, key=lambda lv: lv["price"], reverse=True)

    def _make_book(self, market: dict) -> dict:
        if market.get("status") == "resolved":
            # Resolved markets hold their final answer instead of a live book.
            yes_price = int(market.get("resolved_price") or 0)
            yes_price = 100 if yes_price > 50 else 0
            book = {
                "yes": yes_price,
                "no": 100 - yes_price,
                "last": yes_price,
                "volume": float(market.get("volume", 0.0)),
                "liquidity": float(market.get("liquidity", 0.0)),
                "base_liquidity": float(market.get("liquidity", 0.0)),
                "pts": [int(p) for p in market.get("pts", [])] or [yes_price],
                "trend": "up",
                "updated": 0.0,
                "bids": [],
                "asks": [],
                "resolved": True,
            }
            # Cache it like an open book. Without this, every read of a resolved
            # market (list, detail, tape) re-queried storage because `_ensure`
            # found nothing in `_books` and fetched the market again.
            self._books[market["id"]] = book
            self._trades.setdefault(market["id"], [])
            return book
        yes = _clamp(int(market.get("yes", 50)))
        base_liquidity = max(float(market.get("liquidity", 0.0)) or 2000.0, MIN_LIQUIDITY)
        book = {
            "yes": yes,
            "no": 100 - yes,
            "last": int(market.get("yes", yes)),
            "volume": float(market.get("volume", 0.0)),
            "liquidity": base_liquidity,
            "base_liquidity": base_liquidity,
            "pts": [int(p) for p in market.get("pts", [])] or [yes],
            "trend": market.get("trend", "up"),
            "updated": 0.0,
        }
        self._build_levels(book)
        self._books[market["id"]] = book
        self._trades.setdefault(market["id"], [])
        return book

    def _ensure(self, market_id: str) -> dict | None:
        """Return the live book for a market, building it lazily if needed."""
        book = self._books.get(market_id)
        if book is not None:
            return book
        market = store.get_market(market_id)
        if market is None:
            return None
        return self._make_book(market)

    def _maybe_replenish(self, market_id: str) -> None:
        """Gradually restore resting depth, like market makers re-pricing."""
        book = self._books.get(market_id)
        if book is None:
            return
        now = time.time()
        if now - book["updated"] < REPLENISH_INTERVAL:
            return
        book["updated"] = now
        base = book["base_liquidity"]
        for side in ("bids", "asks"):
            for i, lvl in enumerate(book[side]):
                target = self._target_size(lvl["price"], LEVEL_WEIGHTS[i], base)
                current = lvl["size"]
                if target > current:
                    lvl["size"] = _round4(current + (target - current) * 0.25)
                elif current > target * 1.6:
                    lvl["size"] = _round4(target * 1.4)
        # Pool slowly rebuilds to full depth; trader orders bleed it down.
        book["liquidity"] = min(base, book["liquidity"] + base * 0.015)

    def _enrich(self, market: dict) -> dict:
        """Overlay live book state on a market dict already read from storage.

        Takes the stored market as an argument (instead of re-fetching it by id)
        so callers that already hold the record do not cause a second storage
        read. With the Supabase backend each read is an HTTP round-trip, so the
        old per-market `store.get_market()` in `list_markets()` turned every
        listing into an N+1 query storm (10 round-trips for 9 markets) and made
        a single transient disconnect fail the whole page.
        """
        market_id = market["id"]
        book = self._books.get(market_id)
        if book is None:
            book = self._make_book(market)
        self._maybe_replenish(market_id)
        out = dict(market)
        out["yes"] = book["yes"]
        out["no"] = book["no"]
        out["trend"] = book["trend"]
        out["pts"] = [int(p) for p in book["pts"]]
        out["volume"] = _round2(book["volume"])
        out["liquidity"] = _round2(book["liquidity"])
        out["last_price"] = book["last"]
        out.setdefault("description", "")
        out.setdefault("end_date", None)
        out.setdefault("created", None)
        out.setdefault("status", "open")
        out.setdefault("volume", 0.0)
        out.setdefault("liquidity", 0.0)
        return out

    def snapshot_market(self, market_id: str) -> dict | None:
        """Enriched market dict: stored content + live price/volume state."""
        market = store.get_market(market_id)
        if market is None:
            return None
        return self._enrich(market)

    def list_markets(self) -> list[dict]:
        """All markets with live state, using a single storage read.

        The stored list already contains every field `_enrich` needs, so build
        the books from those records rather than calling `snapshot_market()`
        (which would re-read each market one by one).
        """
        markets = store.list_markets()
        reps = {m["id"]: m for m in markets}
        # Drop books for markets that no longer exist (deleted in the admin UI)
        # so a stale in-memory book cannot keep a ghost market alive.
        for market_id in list(self._books):
            if market_id not in reps:
                self._books.pop(market_id, None)
        return [self._enrich(m) for m in markets]

    def book_view(self, market_id: str) -> dict | None:
        """YES-side order book plus the derived NO-side quotes."""
        book = self._ensure(market_id)
        if book is None:
            return None
        self._maybe_replenish(market_id)
        asks = [{"price": lv["price"], "size": _round4(lv["size"])} for lv in book["asks"] if lv["size"] > _EPS]
        bids_sorted = [{"price": lv["price"], "size": _round4(lv["size"])} for lv in book["bids"] if lv["size"] > _EPS]
        # NO side is the mirror image of the YES book.
        no_asks = [{"price": 100 - lv["price"], "size": lv["size"]} for lv in bids_sorted]
        no_bids = [{"price": 100 - lv["price"], "size": lv["size"]} for lv in asks]
        return {
            "yes": book["yes"],
            "no": book["no"],
            "bids": bids_sorted,
            "asks": asks,
            "no_bids": no_bids,
            "no_asks": no_asks,
            "spread": book["asks"][0]["price"] - book["bids"][0]["price"] if book["asks"] and book["bids"] else 0,
            "last": book["last"],
        }

    def recent_trades(self, market_id: str, limit: int = 20) -> list[dict]:
        self._ensure(market_id)
        return list(self._trades.get(market_id, [])[:limit])

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _book_move(self, market_id: str, side: str, levels: list[dict], fills: list[dict],
                   avg_yes: int, last_yes: int) -> None:
        book = self._books[market_id]
        book["yes"] = _clamp(avg_yes)
        book["no"] = 100 - book["yes"]
        book["last"] = last_yes
        traded = sum(f["notional"] for f in fills)
        book["volume"] += traded
        book["liquidity"] = max(MIN_LIQUIDITY * 0.3, book["liquidity"] - traded)
        pts = book["pts"] + [book["yes"]]
        book["pts"] = pts[-MAX_PTS:]
        book["trend"] = "up" if (
            len(book["pts"]) < 2 or book["pts"][-1] >= book["pts"][-2]
        ) else "down"
        self._maybe_replenish(market_id)

    def _apply_wallet(self, wallet_id: str, market_id: str, q: str, outcome: str, side: str,
                      shares: float, avg_outcome: int, proceeds: float) -> None:
        wallet = self._wallets[wallet_id]
        sides = wallet["positions"].setdefault(market_id, {})
        entry = sides.setdefault(outcome, {"shares": 0.0, "avg": 0})
        if shares <= _EPS:
            return
        if side == "buy":
            wallet["balance"] -= proceeds
            old_shares = entry["shares"]
            total = old_shares + shares
            entry["shares"] = _round4(total)
            entry["avg"] = (
                avg_outcome
                if old_shares <= _EPS
                else round((old_shares * entry["avg"] + shares * avg_outcome) / total)
            )
            # Record this fill as its own lot so the UI can list every bet
            # separately. The aggregate `entry` above remains authoritative for
            # cost basis, so P&L is unaffected by this bookkeeping.
            lots = wallet.setdefault("lots", {})
            lot_id = secrets.token_hex(8)
            lots[lot_id] = {
                "id": lot_id,
                "market_id": market_id,
                "question": q,
                "outcome": outcome,
                "shares": _round4(shares),
                "price": avg_outcome,
                "notional": _round2(proceeds),
                "ts": time.time(),
            }
        else:
            wallet["balance"] += proceeds
            old_shares = entry["shares"]
            basis = min(old_shares, shares) * entry["avg"] / 100.0
            wallet["realized"] += proceeds - basis
            entry["shares"] = _round4(max(0.0, old_shares - shares))
            self._consume_lots(wallet, market_id, outcome, shares)
        ts = time.time()
        wallet["history"].append(
            {
                "ts": ts,
                "market_id": market_id,
                "question": q,
                "outcome": outcome,
                "side": side,
                "price": avg_outcome,
                "qty": _round4(shares),
                "notional": _round2(proceeds),
            }
        )
        self._trades.setdefault(market_id, []).insert(0, wallet["history"][-1])
        self._trades[market_id][:] = self._trades[market_id][:60]

    def place_trade(self, wallet_id: str, market_id: str = None, outcome: str = None, side: str = None,
                    amount: float | None = None, shares: float | None = None, legs=None, **kwargs) -> dict:
        """Execute a market order and return wallet/market/book/trade payloads."""
        wallet = self._wallets.get(wallet_id)
        if wallet is None:
            raise ValueError("Unknown wallet")

        # Support multi-bet / parlay on a single slip
        multi_legs = legs or kwargs.get('slip') or kwargs.get('bets') or kwargs.get('selections') or kwargs.get('multibet')
        if multi_legs and isinstance(multi_legs, (list, tuple)) and len(multi_legs) > 0:
            # Normalize legs
            norm_legs = []
            for i, leg in enumerate(multi_legs):
                if isinstance(leg, dict):
                    l_mid = leg.get('market_id') or leg.get('market') or leg.get('id')
                    l_outcome = leg.get('outcome')
                    l_side = leg.get('side') or 'buy'
                    l_amount = leg.get('amount')
                    l_shares = leg.get('shares')
                else:
                    l_mid = getattr(leg, 'market_id', None)
                    l_outcome = getattr(leg, 'outcome', None)
                    l_side = getattr(leg, 'side', 'buy')
                    l_amount = getattr(leg, 'amount', None)
                    l_shares = getattr(leg, 'shares', None)
                norm_legs.append({
                    'market_id': l_mid,
                    'outcome': l_outcome,
                    'side': l_side,
                    'amount': l_amount,
                    'shares': l_shares,
                    'idx': i + 1,
                })

            # Dry-run validation pass (atomicity - fail fast before executing anything)
            for leg in norm_legs:
                if leg['outcome'] not in ("yes", "no"):
                    raise ValueError(f"Leg {leg['idx']}: outcome must be 'yes' or 'no'")
                if leg['side'] not in ("buy", "sell"):
                    raise ValueError(f"Leg {leg['idx']}: side must be 'buy' or 'sell'")
                if not leg['market_id']:
                    raise ValueError(f"Leg {leg['idx']}: market_id required")
                book = self._ensure(leg['market_id'])
                if book is None:
                    raise ValueError(f"Leg {leg['idx']}: Unknown market {leg['market_id']}")
                market = store.get_market(leg['market_id'])
                block = _trading_block_reason(market)
                if block:
                    raise ValueError(f"Leg {leg['idx']}: {block}")
                # Basic balance check for buys
                if leg['side'] == 'buy':
                    budget = leg['amount'] or 0.0
                    if budget < 0.01:
                        raise ValueError(f"Leg {leg['idx']}: Buy amount must be at least $0.01")
                    if wallet["balance"] + _EPS < budget:  # rough check, actual may differ slightly due to fills
                        pass  # will be caught properly in execution
                elif leg['side'] == 'sell':
                    qty = leg['shares'] or 0.0
                    if qty < 0.001:
                        raise ValueError(f"Leg {leg['idx']}: Sell size must be at least 1 share")
                    held_entry = wallet["positions"].get(leg['market_id'], {}).get(leg['outcome'])
                    held = held_entry.get("shares", 0.0) if held_entry else 0.0
                    if held < _EPS:
                        raise ValueError(f"Leg {leg['idx']}: You don't hold any shares of this outcome to sell")

            results = []
            trades = []
            # Execute all legs atomically. A slip that touches several markets
            # must either fill every leg or leave the wallet/books/tape exactly
            # as they were; otherwise a late failure (illiquidity, balance) can
            # strand earlier fills and emit phantom "Order filled" events.
            affected = {leg["market_id"] for leg in norm_legs}
            wallet_snapshot = copy.deepcopy(wallet)
            book_snapshots = {
                mid: copy.deepcopy(self._books[mid]) for mid in affected
            }
            trade_snapshots = {
                mid: copy.deepcopy(self._trades.get(mid, [])) for mid in affected
            }
            previous_notifications = self._deferred_notifications
            previous_events = self._deferred_events
            previous_persist = self._deferred_persist
            self._deferred_notifications = []
            self._deferred_events = []
            self._deferred_persist = True
            try:
                # Execute all legs in order on the same wallet.
                for leg in norm_legs:
                    try:
                        res = self.place_trade(wallet_id, leg['market_id'], leg['outcome'], leg['side'], amount=leg['amount'], shares=leg['shares'])
                        results.append(res)
                        if res.get('trade'):
                            trades.append(res['trade'])
                    except ValueError as e:
                        raise ValueError(f"Leg {leg['idx']} ({leg['market_id']}) failed: {str(e)}")
            except BaseException:
                # Roll back every leg's wallet, book and tape mutations, then
                # discard the notifications/events they queued.
                self._wallets[wallet_id] = wallet_snapshot
                for mid, snapshot in book_snapshots.items():
                    self._books[mid] = snapshot
                for mid, snapshot in trade_snapshots.items():
                    self._trades[mid] = snapshot
                self._deferred_notifications = previous_notifications
                self._deferred_events = previous_events
                self._deferred_persist = previous_persist
                self._persist(wallet_id)
                raise
            queued_notifications = self._deferred_notifications or []
            queued_events = self._deferred_events or []
            self._deferred_notifications = previous_notifications
            self._deferred_events = previous_events
            self._deferred_persist = previous_persist
            # One durable write for the whole slip, then deliver its effects.
            self._persist(wallet_id)
            for item in queued_notifications:
                store.upsert_notification(item)
            for payload in queued_events:
                self._emit(payload)
            # Return aggregated result
            return {
                "wallet": self.wallet_view(wallet_id),
                "results": results,
                "trades": trades,
            }

        if outcome not in ("yes", "no"):
            raise ValueError("outcome must be 'yes' or 'no'")
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if not market_id:
            raise ValueError("market_id required")
        book = self._ensure(market_id)
        if book is None:
            raise ValueError("Unknown market")
        market = store.get_market(market_id)
        question = market["q"] if market else market_id
        block = _trading_block_reason(market)
        if block:
            raise ValueError(block)

        self._maybe_replenish(market_id)

        if side == "buy":
            budget = amount or 0.0
            if budget < 0.01:
                raise ValueError("Buy amount must be at least $0.01")
            fill = self._fill_buy_yes if outcome == "yes" else self._fill_buy_no
            # Probe the fill on a clone first: the fill helpers consume book
            # levels as they walk them, so checking affordability *after* a
            # real fill would permanently drain liquidity on every rejected
            # (insufficient-balance) order.
            probe_fills, _, _ = fill(copy.deepcopy(book), budget)
            probe_spent = sum(f["notional"] for f in probe_fills)
            if probe_spent <= _EPS:
                raise ValueError("Not enough liquidity to place this order")
            if wallet["balance"] + _EPS < probe_spent:
                raise ValueError("Insufficient balance for this order")
            fills, avg_price, last_yes = fill(book, budget)
            new_price = avg_price
            spent = sum(f["notional"] for f in fills)
            if spent <= _EPS:
                raise ValueError("Not enough liquidity to place this order")
            bought_shares = sum(f["qty"] for f in fills)
            self._apply_wallet(wallet_id, market_id, question, outcome, "buy",
                               bought_shares, new_price, spent)
        else:
            qty = shares or 0.0
            if qty < 0.001:
                raise ValueError("Sell size must be at least 1 share")
            held_entry = wallet["positions"].get(market_id, {}).get(outcome)
            held = held_entry.get("shares", 0.0) if held_entry else 0.0
            if held < _EPS:
                raise ValueError("You don't hold any shares of this outcome to sell")
            qty = min(qty, held)
            if outcome == "yes":
                fills, avg_price, last_yes = self._fill_sell_yes(book, qty)
                new_price = avg_price
            else:
                fills, avg_price, last_yes = self._fill_sell_no(book, qty)
                new_price = avg_price
            proceeds = sum(f["notional"] for f in fills)
            if fills and fills[-1].get("partial") and proceeds <= _EPS:
                raise ValueError("Not enough liquidity to sell")
            if not fills:
                raise ValueError("No position or liquidity to sell")
            sold_shares = sum(f["qty"] for f in fills)
            # Sells are capped by what the book offers; surface that to the caller.
            self._apply_wallet(wallet_id, market_id, question, outcome, "sell",
                               sold_shares, new_price, proceeds)

        self._book_move(market_id, side, book["asks"] if outcome == "yes" else book["bids"],
                        fills, last_yes, last_yes)

        trade = wallet["history"][-1]
        self._persist(wallet_id)
        verb = "Bought" if trade["side"] == "buy" else "Sold"
        self.notify(
            wallet_id,
            "fill",
            "Order filled",
            (
                f"{verb} {_round4(trade['qty'])} {trade['outcome'].upper()} @ "
                f"{trade['price']}¢ for {_round2(trade['notional'])} — {question}"
            ),
        )
        self._emit_market(market_id)
        self._emit({"type": "trade", "trade": trade, "market_id": market_id})
        return {
            "wallet": self.wallet_view(wallet_id),
            "market": self.snapshot_market(market_id),
            "book": self.book_view(market_id),
            "trade": trade,
        }

    def _consume_lots(self, wallet: dict, market_id: str, outcome: str, shares: float) -> None:
        """Reduce open lots by ``shares``, oldest first (FIFO).

        A sell is capped by the aggregate position elsewhere, so walking the
        lots in time order cannot over-consume. Lots that fall to zero are
        dropped so the UI never lists an empty row.
        """
        lots = wallet.get("lots") or {}
        remaining = shares
        # Sort by timestamp so FIFO order is stable regardless of dict order.
        ordered = sorted(
            (l for l in lots.values()
             if l["market_id"] == market_id and l["outcome"] == outcome and l["shares"] > _EPS),
            key=lambda l: l["ts"],
        )
        for lot in ordered:
            if remaining <= _EPS:
                break
            take = min(lot["shares"], remaining)
            lot["shares"] = _round4(lot["shares"] - take)
            remaining -= take
        for lot_id in [k for k, l in lots.items() if l["shares"] <= _EPS]:
            del lots[lot_id]

    def _fill_buy_yes(self, book: dict, budget: float) -> tuple[list[dict], int, int]:
        remaining = budget
        fills: list[dict] = []
        for lvl in book["asks"]:
            if lvl["size"] <= _EPS or remaining < 0.005:
                continue
            price = lvl["price"]
            cost_all = lvl["size"] * price / 100.0
            if cost_all <= remaining:
                qty = lvl["size"]
                cost = cost_all
                lvl["size"] = 0.0
                remaining -= cost
            else:
                qty = remaining / (price / 100.0)
                cost = qty * price / 100.0
                lvl["size"] = _round4(lvl["size"] - qty)
                fills.append({"price": price, "qty": _round4(qty), "notional": _round2(cost)})
                remaining = 0.0
                break
            fills.append({"price": price, "qty": _round4(qty), "notional": _round2(cost)})
            if remaining < 0.005:
                break
        total_qty = sum(f["qty"] for f in fills)
        total_cost = sum(f["notional"] for f in fills)
        avg = int(round(total_cost / total_qty * 100)) if total_qty > 0 else book["yes"]
        last = fills[-1]["price"] if fills else book["last"]
        return fills, _clamp(avg), last

    def _fill_buy_no(self, book: dict, budget: float) -> tuple[list[dict], int, int]:
        remaining = budget
        fills: list[dict] = []
        for lvl in book["bids"]:
            if lvl["size"] <= _EPS or remaining < 0.005:
                continue
            bid = lvl["price"]
            price = 100 - bid
            cost_all = lvl["size"] * price / 100.0
            if cost_all <= remaining:
                qty = lvl["size"]
                cost = cost_all
                lvl["size"] = 0.0
                remaining -= cost
            else:
                qty = remaining / (price / 100.0)
                cost = qty * price / 100.0
                lvl["size"] = _round4(lvl["size"] - qty)
                fills.append({"price": price, "qty": _round4(qty), "notional": _round2(cost)})
                remaining = 0.0
                break
            fills.append({"price": price, "qty": _round4(qty), "notional": _round2(cost)})
            if remaining < 0.005:
                break
        total_qty = sum(f["qty"] for f in fills)
        total_cost = sum(f["notional"] for f in fills)
        avg_no = int(round(total_cost / total_qty * 100)) if total_qty > 0 else (100 - book["yes"])
        last_yes = 100 - fills[-1]["price"] if fills else book["last"]
        return fills, _clamp(avg_no), last_yes

    def _fill_sell_yes(self, book: dict, shares: float) -> tuple[list[dict], int, int]:
        remaining = shares
        fills: list[dict] = []
        for lvl in book["bids"]:
            if lvl["size"] <= _EPS or remaining < _EPS:
                continue
            bid = lvl["price"]
            qty = min(remaining, lvl["size"])
            lvl["size"] = _round4(lvl["size"] - qty)
            remaining -= qty
            fills.append({"price": bid, "qty": _round4(qty), "notional": _round2(qty * bid / 100.0)})
            if remaining < _EPS:
                break
        total_qty = sum(f["qty"] for f in fills)
        total_proceeds = sum(f["notional"] for f in fills)
        avg = int(round(total_proceeds / total_qty * 100)) if total_qty > 0 else book["yes"]
        last = fills[-1]["price"] if fills else book["last"]
        return fills, _clamp(avg), last

    def _fill_sell_no(self, book: dict, shares: float) -> tuple[list[dict], int, int]:
        remaining = shares
        fills: list[dict] = []
        for lvl in book["asks"]:
            if lvl["size"] <= _EPS or remaining < _EPS:
                continue
            ask = lvl["price"]
            price = 100 - ask
            qty = min(remaining, lvl["size"])
            lvl["size"] = _round4(lvl["size"] - qty)
            remaining -= qty
            fills.append({"price": price, "qty": _round4(qty), "notional": _round2(qty * price / 100.0)})
            if remaining < _EPS:
                break
        total_qty = sum(f["qty"] for f in fills)
        total_proceeds = sum(f["notional"] for f in fills)
        avg_no = int(round(total_proceeds / total_qty * 100)) if total_qty > 0 else (100 - book["yes"])
        last_yes = 100 - fills[-1]["price"] if fills else book["last"]
        return fills, _clamp(avg_no), last_yes

    # ------------------------------------------------------------------
    # Wallets
    # ------------------------------------------------------------------

    def _persist(self, wallet_id: str) -> None:
        """Persist a wallet snapshot so real funds survive restarts."""
        if self._deferred_persist:
            return
        wallet = self._wallets.get(wallet_id)
        if wallet is not None:
            store.upsert_wallet(copy.deepcopy(wallet))

    def notify(self, wallet_id: str, ntype: str, title: str, message: str) -> None:
        """Record an in-app notification for a wallet (fill / payment / system).

        Also pushes a ``notification`` event onto the stream so the WS layer can
        deliver it live to that wallet's subscribed sockets.
        """
        self._wallets.get(wallet_id)  # ensure the wallet exists in memory
        item = {
            "id": secrets.token_hex(16),
            "wallet_id": wallet_id,
            "type": ntype if ntype in ("fill", "deposit", "withdraw", "system") else "system",
            "title": title,
            "message": message,
            "ts": time.time(),
            "read": False,
        }
        if self._deferred_notifications is not None:
            self._deferred_notifications.append(item)
            return
        store.upsert_notification(item)
        self._emit({"type": "notification", "notification": item})

    def emit(self, payload: dict[str, Any]) -> None:
        """Publish an arbitrary event to the WS stream (callers: main.py)."""
        self._emit(payload)

    def connect_wallet(self, wallet_id: str | None = None, name: str = "Trader") -> dict:
        """Get-or-create a wallet; ids are always server-minted.

        A caller-supplied ``wallet_id`` is honored *only* as a restore key for
        a wallet that already exists (server-minted in the past, e.g. surviving
        a backend restart). If no such wallet exists the id is ignored and a
        fresh, unguessable id is minted — a client can never choose the id of a
        wallet, so squatting/forging another user's wallet is impossible.
        """
        request_id = (wallet_id or "").strip()
        if request_id:
            existing = self._wallets.get(request_id)
            if existing is not None:
                return self.wallet_view(request_id)
            persisted = store.get_wallet(request_id)
            if persisted is not None:
                # Restore a persisting wallet (e.g. after a backend restart).
                self._wallets[request_id] = persisted
                return self.wallet_view(request_id)
        # Mint a fresh wallet at a server-chosen id (no client influence).
        fresh_id = "0x" + secrets.token_hex(20)
        self._wallets[fresh_id] = {
            "id": fresh_id,
            "name": (name or "Trader").strip() or "Trader",
            "balance": WALLET_START_BALANCE,
            # Real money actually paid in (deposits + refunds). Withdrawals may
            # only draw on this, never on play balance. Absent on wallets
            # persisted before this field existed -> read as 0.0.
            "deposited": 0.0,
            "realized": 0.0,
            "positions": {},
            # Per-fill lot ledger, keyed by lot id. The aggregate position stays
            # the source of truth for cost basis and P&L; lots exist so the UI
            # can show each individual bet instead of one averaged row.
            "lots": {},
            "history": [],
            "created": time.time(),
        }
        self._persist(fresh_id)
        return self.wallet_view(fresh_id)

    def credit_balance(self, wallet_id: str, amount: float) -> None:
        """Add real funds to a wallet's balance (a completed deposit, or a refund).

        Every caller passes money that genuinely arrived via PayChangu, so this
        raises the withdrawable pool as well as the spendable balance. Callers
        are responsible for gating on idempotency (a payment record must only
        credit once).

        When ``KETSA_DB_URL`` is set the mutation runs inside a Postgres
        transaction with ``SELECT ... FOR UPDATE`` (cross-process safe). In the
        in-memory/single-process case the original asyncio.Lock in main.py plus
        the per-process wallet dict is sufficient.
        """
        if dblock.configured():
            with dblock.wallet_txn(wallet_id) as wallet:
                wallet["balance"] = _round2(wallet.get("balance", 0.0) + amount)
                wallet["deposited"] = _round2(wallet.get("deposited", 0.0) + amount)
            # Keep the in-process view in sync if we have it (read-only cache).
            if wallet_id in self._wallets:
                live = self._wallets[wallet_id]
                live["balance"] = _round2(live.get("balance", 0.0) + amount)
                live["deposited"] = _round2(live.get("deposited", 0.0) + amount)
            return
        wallet = self._wallets.get(wallet_id)
        if wallet is None:
            raise ValueError("Unknown wallet")
        wallet["balance"] = _round2(wallet["balance"] + amount)
        wallet["deposited"] = _round2(wallet.get("deposited", 0.0) + amount)
        self._persist(wallet_id)

    def debit_balance(self, wallet_id: str, amount: float) -> None:
        """Reserve funds for a withdrawal; raises if real funds are short.

        Withdrawals draw on ``deposited`` only — the money that actually
        arrived through PayChangu. Play balance (a legacy free seed, or trading
        winnings) is spendable on markets but is never cashable out, so the
        zero-balance change can't be sidestepped by withdrawing money the
        house never received.

        When ``KETSA_DB_URL`` is set the mutation runs inside a Postgres
        transaction with ``SELECT ... FOR UPDATE`` (cross-process safe).
        """
        if dblock.configured():
            with dblock.wallet_txn(wallet_id) as wallet:
                deposited = float(wallet.get("deposited", 0.0))
                if deposited + _EPS < amount:
                    raise ValueError(
                        "Insufficient deposited balance for this withdrawal. "
                        "Only real money paid in through mobile money can be cashed out."
                    )
                if float(wallet.get("balance", 0.0)) + _EPS < amount:
                    raise ValueError("Insufficient balance for this withdrawal")
                wallet["deposited"] = _round2(deposited - amount)
                wallet["balance"] = _round2(float(wallet.get("balance", 0.0)) - amount)
            if wallet_id in self._wallets:
                live = self._wallets[wallet_id]
                live["deposited"] = _round2(float(live.get("deposited", 0.0)) - amount)
                live["balance"] = _round2(float(live.get("balance", 0.0)) - amount)
            return
        wallet = self._wallets.get(wallet_id)
        if wallet is None:
            raise ValueError("Unknown wallet")
        deposited = wallet.get("deposited", 0.0)
        if deposited + _EPS < amount:
            raise ValueError(
                "Insufficient deposited balance for this withdrawal. "
                "Only real money paid in through mobile money can be cashed out."
            )
        if wallet["balance"] + _EPS < amount:
            raise ValueError("Insufficient balance for this withdrawal")
        wallet["deposited"] = _round2(deposited - amount)
        wallet["balance"] = _round2(wallet["balance"] - amount)
        self._persist(wallet_id)

    def wallet_view(self, wallet_id: str) -> dict | None:
        wallet = self._wallets.get(wallet_id)
        if wallet is None:
            return None
        positions: list[dict] = []
        position_value = 0.0
        for market_id, sides in wallet["positions"].items():
            market = store.get_market(market_id)
            question = market["q"] if market else market_id
            book = self._books.get(market_id)
            yes = book["yes"] if book else None
            for outcome in ("yes", "no"):
                entry = sides.get(outcome)
                if not entry:
                    continue
                shares = entry.get("shares", 0.0)
                avg = entry.get("avg", 0)
                if shares <= _EPS:
                    continue
                if outcome == "yes":
                    cur = yes if yes is not None else avg
                else:
                    cur = (100 - yes) if yes is not None else avg
                cur = max(1, min(99, int(cur)))
                value = shares * cur / 100.0
                pnl = value - shares * avg / 100.0
                position_value += value
                # The individual fills behind this averaged position, oldest
                # first, so the UI can list every bet separately. Lots whose
                # shares were sold off are already removed on trade.
                lots = [
                    {
                        "id": l["id"],
                        "shares": _round4(l["shares"]),
                        "price": l["price"],
                        "notional": _round2(l["notional"]),
                        "ts": l["ts"],
                    }
                    for l in sorted(
                        (
                            l
                            for l in (wallet.get("lots") or {}).values()
                            if l["market_id"] == market_id
                            and l["outcome"] == outcome
                            and l["shares"] > _EPS
                        ),
                        key=lambda l: l["ts"],
                    )
                ]
                positions.append(
                    {
                        "market_id": market_id,
                        "question": question,
                        "outcome": outcome,
                        "shares": _round4(shares),
                        "avg_price": avg,
                        "current_price": cur,
                        "value": _round2(value),
                        "pnl_value": _round2(pnl),
                        "lots": lots,
                    }
                )
        history = []
        for t in wallet["history"]:
            history.append({k: (t[k] if k != "qty" else _round4(t[k])) for k in t})
        equity = wallet["balance"] + position_value
        return {
            "id": wallet["id"],
            "name": wallet["name"],
            "balance": _round2(wallet["balance"]),
            # Cashable-out real money. `balance` is what can be traded with;
            # this is the ceiling on a withdrawal.
            "withdrawable": _round2(wallet.get("deposited", 0.0)),
            "currency": WALLET_CURRENCY,
            "equity": _round2(equity),
            "realized_pnl": _round2(wallet["realized"]),
            "positions": positions,
            "history": history,
            "created": wallet["created"],
        }

    # ------------------------------------------------------------------
    # Administrative hooks
    # ------------------------------------------------------------------

    def _settle_wallet(self, wallet: dict, market_id: str, winning_outcome: str,
                       question: str) -> float:
        """Pay out a wallet's winning shares for a resolved market.

        Winners get $1 per share credited to cash (all of it realized profit);
        loser positions simply expire to zero. Returns the payout credited.
        """
        sides = wallet.get("positions") or {}
        market_pos = sides.pop(market_id, None)
        if not market_pos:
            return 0.0
        payout = 0.0
        ts = time.time()
        for outcome in ("yes", "no"):
            entry = market_pos.get(outcome)
            if not entry or entry.get("shares", 0.0) <= _EPS:
                continue
            shares = entry["shares"]
            avg = int(entry.get("avg") or 0)
            wins = outcome == winning_outcome
            if wins:
                proceeds = shares
                wallet["balance"] = _round2(wallet["balance"] + proceeds)
                wallet["realized"] = _round2(wallet["realized"] + proceeds - shares * avg / 100.0)
                payout += proceeds
                final_price = 100
            else:
                final_price = 0
            wallet.setdefault("history", []).append(
                {
                    "ts": ts,
                    "market_id": market_id,
                    "question": question,
                    "outcome": outcome,
                    "side": "sell",
                    "price": final_price,
                    "qty": _round4(shares),
                    "notional": _round2(shares * final_price / 100.0),
                    "kind": "resolution",
                }
            )
            self.notify(
                wallet["id"],
                "system",
                "Market resolved",
                (
                    f"{question} — your {outcome.upper()} position "
                    + ("resolved to $1.00 per share. Funds added to balance." if wins
                       else "resolved to $0.00.")
                ),
            )
        if not sides:
            wallet["positions"] = {}
        return payout

    def resolve_market(self, market_id: str, outcome: str) -> dict:
        """Resolve a market to YES/NO, settle every holder, and lock trading.

        Winning shares pay $1 each (realizing the entire payout as profit);
        losing shares expire to zero. The resolved outcome + price are persisted
        on the market so the state survives restarts and shows everywhere.
        """
        if outcome not in ("yes", "no"):
            raise ValueError("outcome must be 'yes' or 'no'")
        market = store.get_market(market_id)
        if market is None:
            raise ValueError("Unknown market")
        if market.get("status") == "resolved":
            raise ValueError("Market is already resolved")
        question = market["q"] or market_id

        winning_price = 100 if outcome == "yes" else 0

        # Freeze the live book at the final answer.
        book = self._ensure(market_id)
        if book is not None:
            book["yes"] = winning_price
            book["no"] = 100 - winning_price
            book["last"] = winning_price
            book["bids"] = []
            book["asks"] = []
            pts = book["pts"] + [winning_price]
            book["pts"] = pts[-MAX_PTS:]
            book["trend"] = "up"
            book["resolved"] = True

        # Settle every wallet that holds a position in this market — both the
        # live in-memory wallets and any persisted-only copies, without double
        # paying wallets that exist in both places.
        settled = 0
        total_payout = 0.0
        wallet_ids = set(self._wallets) | {w["id"] for w in store.list_wallets()}
        for wallet_id in sorted(wallet_ids):
            wallet = self._wallets.get(wallet_id)
            if wallet is None:
                persisted = store.get_wallet(wallet_id)
                if persisted is None:
                    continue
                wallet = persisted
            is_live = wallet_id in self._wallets
            if (wallet.get("positions") or {}).get(market_id) is None:
                continue
            payout = self._settle_wallet(wallet, market_id, outcome, question)
            total_payout += payout
            settled += 1
            if is_live:
                self._persist(wallet_id)
            else:
                store.upsert_wallet(wallet)

        stored = dict(market)
        stored["status"] = "resolved"
        stored["resolved_outcome"] = outcome
        stored["resolved_price"] = winning_price
        stored["resolved_ts"] = time.time()
        store.upsert_market(stored)

        self._emit_market(market_id)
        self._emit({"type": "resolution", "market_id": market_id, "outcome": outcome,
                    "resolved_price": winning_price, "wallets_settled": settled,
                    "total_payout": _round2(total_payout)})
        self._emit({"type": "leaderboard"})
        return {
            "market_id": market_id,
            "outcome": outcome,
            "resolved_price": winning_price,
            "wallets_settled": settled,
            "total_payout": _round2(total_payout),
        }

    def reseed_market(self, market_id: str) -> None:
        """Rebuild a market's live state from its stored content (after admin edit)."""
        self._books.pop(market_id, None)
        self._trades.pop(market_id, None)
        self._ensure(market_id)

    def remove_market(self, market_id: str) -> None:
        self._books.pop(market_id, None)
        self._trades.pop(market_id, None)

    def reset(self) -> None:
        """Drop all runtime state (markets re-lazy-load; wallets reset)."""
        self._books.clear()
        self._wallets.clear()
        self._trades.clear()
        self._events.clear()

    def random_tick(self) -> None:
        """Nudge a couple of markets to simulate live liquidity re-pricing."""
        markets = store.list_markets()
        if not markets:
            return
        picks = random.sample(markets, k=min(2, len(markets)))
        for market in picks:
            book = self._ensure(market["id"])
            if book is None or market.get("status") == "resolved":
                continue
            delta = random.choice((-3, -2, -1, 0, 1, 1, 2))
            new_yes = _clamp(book["yes"] + delta, 5, 95)
            if new_yes == book["yes"]:
                new_yes = _clamp(book["yes"] + random.choice((-1, 1)), 5, 95)
            book["yes"] = new_yes
            book["no"] = 100 - new_yes
            book["last"] = new_yes
            pts = book["pts"] + [new_yes]
            book["pts"] = pts[-MAX_PTS:]
            book["trend"] = "up" if book["pts"][-1] >= book["pts"][-2] else "down"
            self._emit_market(market["id"])


engine = Marketplace()