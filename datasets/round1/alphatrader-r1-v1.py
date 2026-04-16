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

        self.osmium_buy_orders = 0
        self.osmium_sell_orders = 0
        self.osmium_position = 0
        self.osmium_prev_fair_price = None

        self.pepper_position = 0
        self.pepper_buy_orders = 0
        self.pepper_sell_orders = 0
        self.pepper_slope = None
        self.pepper_intercept = None
        self.pepper_t0 = None
        self.pepper_prev_fair_price = None

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

    def _rolling_ols(self, history):
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

    def trade_pepper(self, state):
        try:
            saved = json.loads(state.traderData) if state.traderData and state.traderData != "SAMPLE" else {}
        except Exception:
            saved = {}

        pepper_history = saved.get("pepper_history", [])

        order_depth = state.order_depths.get('INTARIAN_PEPPER_ROOT')
        if order_depth is None:
            return saved

        buy_orders  = order_depth.buy_orders
        sell_orders = order_depth.sell_orders

        best_bid = max(buy_orders.keys())  if buy_orders  else None
        best_ask = min(sell_orders.keys()) if sell_orders else None

        if best_bid is not None and best_ask is not None:
            current_mid = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            current_mid = float(best_bid)
        elif best_ask is not None:
            current_mid = float(best_ask)
        else:
            return saved

        last_mid = pepper_history[-1][1] if pepper_history else None
        if last_mid is not None and abs(current_mid - last_mid) > 500:
            current_mid = last_mid
        else:
            pepper_history.append([state.timestamp, current_mid])
            if len(pepper_history) > 500:
                pepper_history = pepper_history[-500:]

        slope, intercept, t0 = self._rolling_ols(pepper_history)
        fair = intercept + slope * (state.timestamp - t0)

        TREND_MIN_SLOPE = 0.0005
        trend_up   = slope >  TREND_MIN_SLOPE
        trend_down = slope < -TREND_MIN_SLOPE

        ts       = state.timestamp
        DAY_END  = 999900
        OPEN_FRAC  = 0.20
        CLOSE_FRAC = 0.99

        logger.print(f"PEPPER ts={ts} mid={current_mid:.1f} fair={fair:.1f} slope={slope:.6f} trend_up={trend_up}")

        if ts < DAY_END * OPEN_FRAC:
            # Buy unconditionally at any ask — no fair value gate, no trend gate.
            # Proven: trend_up is False for first 19 ticks on every day due to OLS warmup.
            # The price always trends up ~1000/day so buying any ask at open is correct.
            # Mirror: if by tick 20 slope is strongly negative, sell instead.
            if not trend_down:
                for ask in sorted(sell_orders.keys()):
                    max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                    if max_buy <= 0:
                        break
                    size = min(max_buy, -sell_orders[ask])
                    if size > 0:
                        self.pepper_buy_orders += size
                        self.send_buy_order('INTARIAN_PEPPER_ROOT', ask, size,
                            msg=f"PEPPER OPEN LONG: BUY {size} @ {ask}")

                # Post passive at the ask to catch any market trades at that level
                max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                if max_buy > 0 and best_ask is not None:
                    self.pepper_buy_orders += max_buy
                    self.send_buy_order('INTARIAN_PEPPER_ROOT', int(best_ask), max_buy,
                        msg=f"PEPPER OPEN PASSIVE BUY {max_buy} @ {int(best_ask)}")

            else:
                # Confirmed downtrend — go short at open
                for bid in sorted(buy_orders.keys(), reverse=True):
                    max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                    if max_sell <= 0:
                        break
                    size = min(max_sell, buy_orders[bid])
                    if size > 0:
                        self.pepper_sell_orders += size
                        self.send_sell_order('INTARIAN_PEPPER_ROOT', bid, -size,
                            msg=f"PEPPER OPEN SHORT: SELL {size} @ {bid}")

                max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                if max_sell > 0 and best_bid is not None:
                    self.pepper_sell_orders += max_sell
                    self.send_sell_order('INTARIAN_PEPPER_ROOT', int(best_bid), -max_sell,
                        msg=f"PEPPER OPEN PASSIVE SELL {max_sell} @ {int(best_bid)}")

        elif ts > DAY_END * CLOSE_FRAC:
            if not trend_down:
                # Holding long — sell unconditionally into any bid
                for bid in sorted(buy_orders.keys(), reverse=True):
                    max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                    if max_sell <= 0:
                        break
                    size = min(max_sell, buy_orders[bid])
                    if size > 0:
                        self.pepper_sell_orders += size
                        self.send_sell_order('INTARIAN_PEPPER_ROOT', bid, -size,
                            msg=f"PEPPER CLOSE LONG: SELL {size} @ {bid}")

                # Post passive at the bid to catch any market trades at that level
                max_sell = self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders
                if max_sell > 0 and best_bid is not None:
                    self.pepper_sell_orders += max_sell
                    self.send_sell_order('INTARIAN_PEPPER_ROOT', int(best_bid), -max_sell,
                        msg=f"PEPPER CLOSE PASSIVE SELL {max_sell} @ {int(best_bid)}")

            else:
                # Confirmed downtrend — cover short unconditionally
                for ask in sorted(sell_orders.keys()):
                    max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                    if max_buy <= 0:
                        break
                    size = min(max_buy, -sell_orders[ask])
                    if size > 0:
                        self.pepper_buy_orders += size
                        self.send_buy_order('INTARIAN_PEPPER_ROOT', ask, size,
                            msg=f"PEPPER CLOSE SHORT: BUY {size} @ {ask}")

                max_buy = self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_position - self.pepper_buy_orders
                if max_buy > 0 and best_ask is not None:
                    self.pepper_buy_orders += max_buy
                    self.send_buy_order('INTARIAN_PEPPER_ROOT', int(best_ask), max_buy,
                        msg=f"PEPPER CLOSE PASSIVE BUY {max_buy} @ {int(best_ask)}")

        else:
            self._pepper_market_make(state, order_depth, fair)

        saved["pepper_history"] = pepper_history
        return saved

    def _pepper_market_make(self, state, order_depth, fair):
        self.search_buys(state,  'INTARIAN_PEPPER_ROOT', fair - 1, depth=5)
        self.search_sells(state, 'INTARIAN_PEPPER_ROOT', fair + 1, depth=5)

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

    def trade_osmium(self, state):
        low  = -self.limits["ASH_COATED_OSMIUM"]
        high =  self.limits["ASH_COATED_OSMIUM"]

        position = state.position.get("ASH_COATED_OSMIUM", 0)

        max_buy  = high - position
        max_sell = position - low

        order_book = state.order_depths.get('ASH_COATED_OSMIUM')
        if order_book is None:
            return {}
        sell_orders = order_book.sell_orders
        buy_orders  = order_book.buy_orders
        no_bids = len(buy_orders) == 0
        no_asks = len(sell_orders) == 0

        try:
            saved = json.loads(state.traderData) if state.traderData and state.traderData != "SAMPLE" else {}
        except Exception:
            saved = {}

        no_bid_streak        = saved.get("no_bid_streak", 0)
        no_ask_streak        = saved.get("no_ask_streak", 0)
        osmium_prev_bid_wall = saved.get("osmium_prev_bid_wall", None)
        osmium_prev_ask_wall = saved.get("osmium_prev_ask_wall", None)

        if no_bids:
            no_bid_streak += 1
        else:
            no_bid_streak = 0

        if no_asks:
            no_ask_streak += 1
        else:
            no_ask_streak = 0

        def empty_side_spread(streak):
            if streak >= 10:
                return 15
            elif streak >= 5:
                return 12
            else:
                return 10

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

        if bid_wall_price is None:
            if osmium_prev_bid_wall is None:
                saved["no_bid_streak"] = no_bid_streak
                saved["no_ask_streak"] = no_ask_streak
                return saved
            bid_wall_price  = osmium_prev_bid_wall
            bid_wall_amount = 0

        if ask_wall_price is None:
            if osmium_prev_ask_wall is None:
                saved["no_bid_streak"] = no_bid_streak
                saved["no_ask_streak"] = no_ask_streak
                return saved
            ask_wall_price  = osmium_prev_ask_wall
            ask_wall_amount = 0

        decimal_fair_price = (bid_wall_price + ask_wall_price) / 2
        fair_price = int(math.ceil(decimal_fair_price))

        saved["osmium_prev_bid_wall"] = bid_wall_price
        saved["osmium_prev_ask_wall"] = ask_wall_price
        saved["no_bid_streak"]        = no_bid_streak
        saved["no_ask_streak"]        = no_ask_streak

        logger.print(
            f"ASH_COATED_OSMIUM FAIR PRICE (walls): {decimal_fair_price} "
            f"-- bid_wall={bid_wall_price}@{bid_wall_amount} ask_wall={ask_wall_price}@{ask_wall_amount} "
            f"no_bid_streak={no_bid_streak} no_ask_streak={no_ask_streak}"
        )

        self.search_buys(state,  'ASH_COATED_OSMIUM', decimal_fair_price, depth=3)
        self.search_sells(state, 'ASH_COATED_OSMIUM', decimal_fair_price, depth=3)

        best_ask = self.get_ask(state, 'ASH_COATED_OSMIUM', fair_price)
        best_bid = self.get_bid(state, 'ASH_COATED_OSMIUM', fair_price)

        buy_spread  = empty_side_spread(no_bid_streak) if no_bids else 4
        sell_spread = empty_side_spread(no_ask_streak) if no_asks else 4

        buy_price  = math.floor(decimal_fair_price) - buy_spread
        sell_price = math.ceil(decimal_fair_price)  + sell_spread

        if best_ask is not None:
            sell_price = best_ask - 1
        if best_bid is not None:
            buy_price = best_bid + 1

        max_buy  = self.limits["ASH_COATED_OSMIUM"] - self.osmium_position - self.osmium_buy_orders
        max_sell = self.osmium_position + self.limits["ASH_COATED_OSMIUM"] - self.osmium_sell_orders

        pos = self.get_product_pos(state, 'ASH_COATED_OSMIUM')

        if not (pos > 0 and float(buy_price) == decimal_fair_price):
            self.send_buy_order('ASH_COATED_OSMIUM', buy_price, max_buy,
                msg=f"ASH_COATED_OSMIUM: MARKET MADE Buy {max_buy} @ {buy_price} (spread={buy_spread})")

        if not (pos < 0 and float(sell_price) == decimal_fair_price):
            self.send_sell_order('ASH_COATED_OSMIUM', sell_price, -max_sell,
                msg=f"ASH_COATED_OSMIUM: MARKET MADE Sell {max_sell} @ {sell_price} (spread={sell_spread})")

        return saved

    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0

        self.osmium_position    = self.get_product_pos(state, 'ASH_COATED_OSMIUM')
        self.osmium_buy_orders  = 0
        self.osmium_sell_orders = 0

        self.pepper_position    = self.get_product_pos(state, 'INTARIAN_PEPPER_ROOT')
        self.pepper_buy_orders  = 0
        self.pepper_sell_orders = 0

        for product in state.order_depths:
            self.orders[product] = []

    def run(self, state: TradingState):
        self.reset_orders(state)

        osmium_saved = self.trade_osmium(state)
        pepper_saved = self.trade_pepper(state)

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