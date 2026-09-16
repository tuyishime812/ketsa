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
from typing import Any

from . import store

CENTS_MIN = 1
CENTS_MAX = 99
MAX_PTS = 48
WALLET_START_BALANCE = 1000.0
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


class Marketplace:
    """Holds books, wallets and trades; executes market orders."""

    def __init__(self) -> None:
        self._books: dict[str, dict] = {}
        self._wallets: dict[str, dict] = {}
        self._trades: dict[str, list[dict]] = {}
        self._events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Event stream (pumped to WebSocket clients by main.py)
    # ------------------------------------------------------------------

    def flush_events(self) -> list[dict[str, Any]]:
        events, self._events = self._events, []
        return events

    def _emit(self, payload: dict[str, Any]) -> None:
        self._events.append(payload)

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

    def snapshot_market(self, market_id: str) -> dict | None:
        """Enriched market dict: stored content + live price/volume state."""
        market = store.get_market(market_id)
        if market is None:
            return None
        book = self._ensure(market_id)
        self._maybe_replenish(market_id)
        out = dict(market)
        if book is not None:
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

    def list_markets(self) -> list[dict]:
        snaps = []
        for market in store.list_markets():
            snap = self.snapshot_market(market["id"])
            if snap is not None:
                snaps.append(snap)
        return snaps

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
        else:
            wallet["balance"] += proceeds
            old_shares = entry["shares"]
            basis = min(old_shares, shares) * entry["avg"] / 100.0
            wallet["realized"] += proceeds - basis
            entry["shares"] = _round4(max(0.0, old_shares - shares))
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

    def place_trade(self, wallet_id: str, market_id: str, outcome: str, side: str,
                    amount: float | None = None, shares: float | None = None) -> dict:
        """Execute a market order and return wallet/market/book/trade payloads."""
        wallet = self._wallets.get(wallet_id)
        if wallet is None:
            raise ValueError("Unknown wallet")
        if outcome not in ("yes", "no"):
            raise ValueError("outcome must be 'yes' or 'no'")
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        book = self._ensure(market_id)
        if book is None:
            raise ValueError("Unknown market")
        market = store.get_market(market_id)
        question = market["q"] if market else market_id

        self._maybe_replenish(market_id)

        if side == "buy":
            budget = amount or 0.0
            if budget < 0.01:
                raise ValueError("Buy amount must be at least $0.01")
            if outcome == "yes":
                fills, avg_price, last_yes = self._fill_buy_yes(book, budget)
                new_price = avg_price
            else:
                fills, avg_price, last_yes = self._fill_buy_no(book, budget)
                new_price = avg_price
            spent = sum(f["notional"] for f in fills)
            if spent <= _EPS:
                raise ValueError("Not enough liquidity to place this order")
            if wallet["balance"] + _EPS < spent:
                raise ValueError("Insufficient balance for this order")
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
        wallet = self._wallets.get(wallet_id)
        if wallet is not None:
            store.upsert_wallet(copy.deepcopy(wallet))

    def notify(self, wallet_id: str, ntype: str, title: str, message: str) -> None:
        """Record an in-app notification for a wallet (fill / payment / system)."""
        self._wallets.get(wallet_id)  # ensure the wallet exists in memory
        store.upsert_notification(
            {
                "id": secrets.token_hex(16),
                "wallet_id": wallet_id,
                "type": ntype if ntype in ("fill", "deposit", "withdraw", "system") else "system",
                "title": title,
                "message": message,
                "ts": time.time(),
                "read": False,
            }
        )

    def connect_wallet(self, wallet_id: str | None = None, name: str = "Trader") -> dict:
        wallet_id = (wallet_id or "").strip() or ("0x" + secrets.token_hex(20))
        if wallet_id in self._wallets:
            return self.wallet_view(wallet_id)
        persisted = store.get_wallet(wallet_id)
        if persisted is not None:
            # Restore a funded wallet (e.g. after a backend restart).
            self._wallets[wallet_id] = persisted
            return self.wallet_view(wallet_id)
        self._wallets[wallet_id] = {
            "id": wallet_id,
            "name": (name or "Trader").strip() or "Trader",
            "balance": WALLET_START_BALANCE,
            "realized": 0.0,
            "positions": {},
            "history": [],
            "created": time.time(),
        }
        self._persist(wallet_id)
        return self.wallet_view(wallet_id)

    def credit_balance(self, wallet_id: str, amount: float) -> None:
        """Add funds to a wallet's available balance (e.g. a completed deposit).

        Callers are responsible for gating on idempotency (a payment record
        must only credit once).
        """
        wallet = self._wallets.get(wallet_id)
        if wallet is None:
            raise ValueError("Unknown wallet")
        wallet["balance"] = _round2(wallet["balance"] + amount)
        self._persist(wallet_id)

    def debit_balance(self, wallet_id: str, amount: float) -> None:
        """Reserve funds for a withdrawal; raises if the balance is short."""
        wallet = self._wallets.get(wallet_id)
        if wallet is None:
            raise ValueError("Unknown wallet")
        if wallet["balance"] + _EPS < amount:
            raise ValueError("Insufficient balance for this withdrawal")
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