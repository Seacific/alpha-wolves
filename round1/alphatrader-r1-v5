from typing import List
import string
import numpy as np
import json
from typing import Any
import math

import json
from typing import Any
from datamodel import *
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3720

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append([
                    trade.symbol, trade.price, trade.quantity,
                    trade.buyer, trade.seller, trade.timestamp,
                ])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice, observation.askPrice, observation.transportFees,
                observation.exportTariff, observation.importTariff,
                observation.sugarPrice, observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return value[:max_length - 3] + "..."

logger = Logger()


class Trader:
    def __init__(self):
        self.limits = {
            'ASH_COATED_OSMIUM': 80,
            'INTARIAN_PEPPER_ROOT': 80,
        }

        self.orders = {}
        self.conversions = 0
        self.traderData = "SAMPLE"

        # osmium
        self.osmium_buy_orders = 0
        self.osmium_sell_orders = 0
        self.osmium_position = 0
        self.osmium_prev_fair_price = None

        # pepper
        self.pepper_position = 0
        self.pepper_buy_orders = 0
        self.pepper_sell_orders = 0
        self.pepper_slope = None
        self.pepper_intercept = None
        self.pepper_t0 = None
        self.pepper_prev_fair_price = None

    # ------------------------------------------------------------------
    # Order helpers
    # ------------------------------------------------------------------

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))
        if msg is not None:
            logger.print(msg)

    def get_product_pos(self, state, product):
        if product == 'ASH_COATED_OSMIUM':
            return state.position.get('ASH_COATED_OSMIUM', 0)
        elif product == 'INTARIAN_PEPPER_ROOT':
            return state.position.get('INTARIAN_PEPPER_ROOT', 0)
        else:
            raise ValueError(f"Unknown product: {product}")

    def search_buys(self, state, product, acceptable_price, depth=1):
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            orders = list(order_depth.sell_orders.items())
            for ask, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(ask) < acceptable_price or (abs(ask - acceptable_price) < 1 and (pos < 0 and abs(pos - amount) < abs(pos))):
                    if product == 'ASH_COATED_OSMIUM':
                        size = min(self.limits["ASH_COATED_OSMIUM"] - self.osmium_position - self.osmium_buy_orders, -amount)
                        self.osmium_buy_orders += size
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {size} x @ {ask}")
                    elif product == 'INTARIAN_PEPPER_ROOT':
                        size = min(self.limits["INTARIAN_PEPPER_ROOT"] - self.pepper_position - self.pepper_buy_orders, -amount)
                        self.pepper_buy_orders += size
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {size} x @ {ask}")

    def search_sells(self, state, product, acceptable_price, depth=1):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            for bid, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(bid) > acceptable_price or (abs(bid - acceptable_price) < 1 and (pos > 0 and abs(pos - amount) < abs(pos))):
                    if product == 'ASH_COATED_OSMIUM':
                        size = min(self.osmium_position + self.limits['ASH_COATED_OSMIUM'] - self.osmium_sell_orders, amount)
                        self.osmium_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {-size} x @ {bid}")
                    elif product == 'INTARIAN_PEPPER_ROOT':
                        size = min(self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders, amount)
                        self.pepper_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {-size} x @ {bid}")

    def get_bid(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            for bid, _ in list(order_depth.buy_orders.items()):
                if bid < price:
                    return bid
        return None

    def get_ask(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            for ask, _ in list(order_depth.sell_orders.items()):
                if ask > price:
                    return ask
        return None

    # ------------------------------------------------------------------
    # Rolling OLS — persisted through traderData
    # ------------------------------------------------------------------

    def _rolling_ols(self, history):
        """
        history: list of [timestamp, price] pairs (already trimmed to window)
        Returns (slope_per_ms, intercept, t0) where fair = intercept + slope*(ts - t0)
        Returns (0, last_price, last_ts) if not enough data.
        """
        if len(history) < 20:
            return 0.0, float(history[-1][1]), float(history[-1][0])

        xs = np.array([h[0] for h in history], dtype=float)
        ys = np.array([h[1] for h in history], dtype=float)
        xs_n = xs - xs[0]
        denom = float(np.dot(xs_n, xs_n) - len(xs_n) * xs_n.mean() ** 2)
        if abs(denom) > 1e-8:
            b = float(np.dot(xs_n, ys - ys.mean()) / denom)
        else:
            b = 0.0
        a = float(ys.mean() - b * xs_n.mean())
        return b, a, float(xs[0])

    # ------------------------------------------------------------------
    # PEPPER
    # ------------------------------------------------------------------

    def trade_pepper(self, state):
        # --- Load persisted history from traderData ---
        try:
            saved = json.loads(state.traderData) if state.traderData and state.traderData != "SAMPLE" else {}
        except Exception:
            saved = {}

        pepper_history = saved.get("pepper_history", [])

        order_depth = state.order_depths.get('INTARIAN_PEPPER_ROOT')
        if order_depth is None:
            return

        buy_orders = order_depth.buy_orders
        sell_orders = order_depth.sell_orders

        # --- Compute current mid from best bid/ask ---
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None

        if best_bid is not None and best_ask is not None:
            current_mid = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            current_mid = float(best_bid)
        elif best_ask is not None:
            current_mid = float(best_ask)
        else:
            return

        # Spike guard: reject ticks where mid jumps implausibly
        last_mid = pepper_history[-1][1] if pepper_history else None
        if last_mid is not None and abs(current_mid - last_mid) > 500:
            current_mid = last_mid  # carry forward, don't append
        else:
            pepper_history.append([state.timestamp, current_mid])
            if len(pepper_history) > 500:
                pepper_history = pepper_history[-500:]

        # --- Rolling OLS fair value ---
        slope, intercept, t0 = self._rolling_ols(pepper_history)
        fair = intercept + slope * (state.timestamp - t0)

        # Min slope to confirm trend: 0.0005/ms ≈ 500/day (safe margin below ~1000/day actual)
        TREND_MIN_SLOPE = 0.0005
        trend_up   = slope >  TREND_MIN_SLOPE
        trend_down = slope < -TREND_MIN_SLOPE

        ts = state.timestamp
        DAY_END = 999900
        OPEN_FRAC  = 0.20
        CLOSE_FRAC = 0.80

        logger.print(f"PEPPER ts={ts} mid={current_mid:.1f} fair={fair:.1f} slope={slope:.6f} trend_up={trend_up}")

        # ---- OPENING WINDOW: enter directional position aggressively ----
        if ts < DAY_END * OPEN_FRAC:
            if trend_up:
                # Actively take asks — don't wait for market to come to us
                for ask in sorted(sell_orders.keys()):
                    max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                    if max_buy <= 0:
                        break
                    # Take any ask that is at or below fair+10 (generous, we want to be filled)
                    if ask <= fair + 10:
                        size = min(max_buy, -sell_orders[ask])
                        if size > 0:
                            self.pepper_buy_orders += size
                            self.send_buy_order('INTARIAN_PEPPER_ROOT', ask, size,
                                msg=f"PEPPER OPEN LONG: BUY {size} @ {ask}")
                    else:
                        break
                # Also post a passive buy just below the ask to catch any dumps
                max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                if max_buy > 0 and best_ask is not None:
                    passive_buy = int(best_ask) - 1  # one tick below current ask
                    self.pepper_buy_orders += max_buy
                    self.send_buy_order('INTARIAN_PEPPER_ROOT', passive_buy, max_buy,
                        msg=f"PEPPER OPEN PASSIVE BUY {max_buy} @ {passive_buy}")

            elif trend_down:
                # Actively take bids to go short
                for bid in sorted(buy_orders.keys(), reverse=True):
                    max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                    if max_sell <= 0:
                        break
                    if bid >= fair - 10:
                        size = min(max_sell, buy_orders[bid])
                        if size > 0:
                            self.pepper_sell_orders += size
                            self.send_sell_order('INTARIAN_PEPPER_ROOT', bid, -size,
                                msg=f"PEPPER OPEN SHORT: SELL {size} @ {bid}")
                    else:
                        break
                max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                if max_sell > 0 and best_bid is not None:
                    passive_sell = int(best_bid) + 1
                    self.pepper_sell_orders += max_sell
                    self.send_sell_order('INTARIAN_PEPPER_ROOT', passive_sell, -max_sell,
                        msg=f"PEPPER OPEN PASSIVE SELL {max_sell} @ {passive_sell}")

            else:
                # No trend yet — standard market make
                self._pepper_market_make(state, order_depth, fair)

        # ---- CLOSING WINDOW: unwind position aggressively ----
        elif ts > DAY_END * CLOSE_FRAC:
            if trend_up:
                # We should be long — sell into bids
                for bid in sorted(buy_orders.keys(), reverse=True):
                    max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                    if max_sell <= 0:
                        break
                    if bid >= fair - 10:
                        size = min(max_sell, buy_orders[bid])
                        if size > 0:
                            self.pepper_sell_orders += size
                            self.send_sell_order('INTARIAN_PEPPER_ROOT', bid, -size,
                                msg=f"PEPPER CLOSE LONG: SELL {size} @ {bid}")
                    else:
                        break
                # Passive sell just above best bid
                max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                if max_sell > 0 and best_bid is not None:
                    passive_sell = int(best_bid) + 1
                    self.pepper_sell_orders += max_sell
                    self.send_sell_order('INTARIAN_PEPPER_ROOT', passive_sell, -max_sell,
                        msg=f"PEPPER CLOSE PASSIVE SELL {max_sell} @ {passive_sell}")

            elif trend_down:
                # We should be short — cover into asks
                for ask in sorted(sell_orders.keys()):
                    max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                    if max_buy <= 0:
                        break
                    if ask <= fair + 10:
                        size = min(max_buy, -sell_orders[ask])
                        if size > 0:
                            self.pepper_buy_orders += size
                            self.send_buy_order('INTARIAN_PEPPER_ROOT', ask, size,
                                msg=f"PEPPER CLOSE SHORT: BUY {size} @ {ask}")
                    else:
                        break
                max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                if max_buy > 0 and best_ask is not None:
                    passive_buy = int(best_ask) - 1
                    self.pepper_buy_orders += max_buy
                    self.send_buy_order('INTARIAN_PEPPER_ROOT', passive_buy, max_buy,
                        msg=f"PEPPER CLOSE PASSIVE BUY {max_buy} @ {passive_buy}")

            else:
                self._pepper_market_make(state, order_depth, fair)

        # ---- MIDDAY: market make around fair value ----
        else:
            self._pepper_market_make(state, order_depth, fair)

        # --- Save updated history ---
        saved["pepper_history"] = pepper_history
        return saved

    def _pepper_market_make(self, state, order_depth, fair):
        """Standard midday market making around OLS fair value."""
        buy_orders = order_depth.buy_orders
        sell_orders = order_depth.sell_orders

        # Take mispriced orders first
        self.search_buys(state, 'INTARIAN_PEPPER_ROOT', fair - 1, depth=5)
        self.search_sells(state, 'INTARIAN_PEPPER_ROOT', fair + 1, depth=5)

        # Post passive quotes — undercut other makers if present
        other_best_ask = self.get_ask(state, 'INTARIAN_PEPPER_ROOT', int(fair))
        other_best_bid = self.get_bid(state, 'INTARIAN_PEPPER_ROOT', int(fair))

        buy_price  = math.floor(fair) - 6
        sell_price = math.ceil(fair)  + 6

        if other_best_ask is not None:
            sell_price = other_best_ask - 1
        if other_best_bid is not None:
            buy_price = other_best_bid + 1

        max_buy  = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
        max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders

        if max_buy > 0:
            self.send_buy_order('INTARIAN_PEPPER_ROOT', buy_price, max_buy,
                msg=f"PEPPER MM BUY {max_buy} @ {buy_price} (fair={fair:.1f})")
        if max_sell > 0:
            self.send_sell_order('INTARIAN_PEPPER_ROOT', sell_price, -max_sell,
                msg=f"PEPPER MM SELL {max_sell} @ {sell_price} (fair={fair:.1f})")

    # ------------------------------------------------------------------
    # OSMIUM
    # ------------------------------------------------------------------

    def trade_osmium(self, state):
        # ash_coated_osmium market-making (previously trade_tomato)
        # position limits
        low = -self.limits["ASH_COATED_OSMIUM"]
        high = self.limits["ASH_COATED_OSMIUM"] 

        position = state.position.get("ASH_COATED_OSMIUM", 0)

        max_buy = high - position
        max_sell = position - low

        order_book = state.order_depths.get('ASH_COATED_OSMIUM')
        if order_book is None:
            return
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders
        no_bids = len(buy_orders) == 0
        no_asks = len(sell_orders) == 0

        # compute wall prices where available
        bid_wall_price, bid_wall_amount = None, 0
        ask_wall_price, ask_wall_amount = None, 0

        if len(buy_orders) != 0:
            try:
                bid_wall_price, bid_wall_amount = max(buy_orders.items(), key=lambda x: x[1])
            except Exception:
                bid_wall_price, bid_wall_amount = None, 0

        if len(sell_orders) != 0:
            try:
                ask_wall_price, ask_wall_amount = max(sell_orders.items(), key=lambda x: abs(x[1]))
            except Exception:
                ask_wall_price, ask_wall_amount = None, 0

        # fall back to the last-seen wall on whichever side is missing
        if bid_wall_price is None:
            if self.osmium_prev_bid_wall is None:
                return
            bid_wall_price = self.osmium_prev_bid_wall
            bid_wall_amount = 0
        if ask_wall_price is None:
            if self.osmium_prev_ask_wall is None:
                return
            ask_wall_price = self.osmium_prev_ask_wall
            ask_wall_amount = 0

        # compute fair price and remember walls for next time
        decimal_fair_price = (bid_wall_price + ask_wall_price) / 2
        fair_price = int(math.ceil(decimal_fair_price))
        self.osmium_prev_bid_wall = bid_wall_price
        self.osmium_prev_ask_wall = ask_wall_price

        logger.print(f"ASH_COATED_OSMIUM FAIR PRICE (walls): {decimal_fair_price} -- bid_wall={bid_wall_price}@{bid_wall_amount} ask_wall={ask_wall_price}@{ask_wall_amount}")
        # use wall-based fair price for search
        self.search_buys(state, 'ASH_COATED_OSMIUM', decimal_fair_price, depth=3)
        self.search_sells(state, 'ASH_COATED_OSMIUM', decimal_fair_price, depth=3)

        # Check if there's another market maker
        best_ask = self.get_ask(state, 'ASH_COATED_OSMIUM', fair_price)
        best_bid =  self.get_bid(state, 'ASH_COATED_OSMIUM', fair_price)

        ## our ordinary market — widen when that side has no competition
        buy_spread = 10 if no_bids else 4
        sell_spread = 10 if no_asks else 4
        buy_price = math.floor(decimal_fair_price) - buy_spread
        sell_price = math.ceil(decimal_fair_price) + sell_spread

        ## update market if someone else is better than us
        if best_ask is not None:
            sell_price = best_ask - 1
        if best_bid is not None:
            buy_price = best_bid + 1

        max_buy =  self.limits["ASH_COATED_OSMIUM"] - self.osmium_position - self.osmium_buy_orders # MAXIMUM SIZE OF MARKET ON BUY SIDE
        max_sell = self.osmium_position + self.limits["ASH_COATED_OSMIUM"] - self.osmium_sell_orders # MAXIMUM SIZE OF MARKET ON SELL SIDE

        pos = self.get_product_pos(state, 'ASH_COATED_OSMIUM')
        # if we are in long, and our best buy price IS the fair price, don't buy more 
        if not(pos > 0 and float(buy_price) == decimal_fair_price):
            self.send_buy_order('ASH_COATED_OSMIUM', buy_price, max_buy, msg=f"ASH_COATED_OSMIUM: MARKET MADE Buy {max_buy} @ {buy_price}")
        
        # if we are in short, and our best sell price IS the fair price, don't sell more
        if not(pos < 0 and float(sell_price) == decimal_fair_price):
            self.send_sell_order('ASH_COATED_OSMIUM', sell_price, -max_sell, msg=f"ASH_COATED_OSMIUM: MARKET MADE Sell {max_sell} @ {sell_price}")

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0

        self.osmium_position   = self.get_product_pos(state, 'ASH_COATED_OSMIUM')
        self.osmium_buy_orders  = 0
        self.osmium_sell_orders = 0

        self.pepper_position   = self.get_product_pos(state, 'INTARIAN_PEPPER_ROOT')
        self.pepper_buy_orders  = 0
        self.pepper_sell_orders = 0

        for product in state.order_depths:
            self.orders[product] = []

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self, state: TradingState):
        self.reset_orders(state)

        osmium_saved = self.trade_osmium(state)
        pepper_saved = self.trade_pepper(state)

        # Merge both products' persisted state into one JSON blob
        try:
            merged = json.loads(state.traderData) if state.traderData and state.traderData != "SAMPLE" else {}
        except Exception:
            merged = {}

        if osmium_saved:
            merged.update(osmium_saved)
        if pepper_saved:
            merged.update(pepper_saved)

        new_trader_data = json.dumps(merged)

        logger.flush(state, self.orders, self.conversions, new_trader_data)
        return self.orders, self.conversions, new_trader_data