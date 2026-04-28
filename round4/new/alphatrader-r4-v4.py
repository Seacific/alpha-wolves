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
        self.max_log_length = 3750

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
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
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
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            encoded_candidate = json.dumps(candidate)
            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out

logger = Logger()

class Trader:
    def __init__(self):
        self.limits = {
            'HYDROGEL_PACK': 200,
            'VELVETFRUIT_EXTRACT': 200,
        }

        self.orders = {}
        self.conversions = 0
        self.traderData = "SAMPLE"

        self.hydrogel_position = 0
        self.hydrogel_buy_orders = 0
        self.hydrogel_sell_orders = 0

        self.vfe_position = 0
        self.vfe_buy_orders = 0
        self.vfe_sell_orders = 0


    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))
        if msg is not None:
            logger.print(msg)

    def get_ask(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            for ask, _ in order_depth.sell_orders.items():
                if ask > price:
                    return ask
        return None

    def get_bid(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            for bid, _ in order_depth.buy_orders.items():
                if bid < price:
                    return bid
        return None

    def trade_hydrogel(self, state: TradingState) -> None:
        product = 'HYDROGEL_PACK'
        LIMIT       = self.limits[product]
        QUOTE_SIZE  = 25
        SKEW_THRESH = 20
        SKEW_QTY    = 10


        order_book = state.order_depths.get(product)
        if order_book is None:
            return

        buy_orders  = order_book.buy_orders
        sell_orders = order_book.sell_orders
        no_bids = len(buy_orders) == 0
        no_asks = len(sell_orders) == 0

        if no_bids or no_asks:
            return

        best_bid = max(buy_orders)
        best_ask = min(sell_orders)
        bid_vol  = buy_orders[best_bid]
        ask_vol  = abs(sell_orders[best_ask])

        # Microprice: weighted mid skewed toward the heavier side
        fair = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        pos  = self.hydrogel_position

        # Take mispriced quotes
        if sell_orders:
            for ask, amount in sorted(sell_orders.items()):
                if ask >= fair:
                    break
                size = min(LIMIT - pos - self.hydrogel_buy_orders, -amount)
                if size <= 0:
                    continue
                self.hydrogel_buy_orders += size
                self.send_buy_order(product, ask, size, msg=f"HYDROGEL take buy {size} @ {ask}")

        if buy_orders:
            for bid, amount in sorted(buy_orders.items(), reverse=True):
                if bid <= fair:
                    break
                size = min(pos + LIMIT - self.hydrogel_sell_orders, amount)
                if size <= 0:
                    continue
                self.hydrogel_sell_orders += size
                self.send_sell_order(product, bid, -size, msg=f"HYDROGEL take sell {size} @ {bid}")

        # Inventory skew reduction: market-order to trim toward SKEW_THRESH
        if pos > SKEW_THRESH:
            best_bid = max(buy_orders) if buy_orders else None
            if best_bid is not None:
                qty = min(SKEW_QTY, pos - SKEW_THRESH, pos + LIMIT - self.hydrogel_sell_orders)
                if qty > 0:
                    self.hydrogel_sell_orders += qty
                    self.send_sell_order(product, best_bid, -qty, msg=f"HYDROGEL skew sell {qty} @ {best_bid}")
        elif pos < -SKEW_THRESH:
            best_ask = min(sell_orders) if sell_orders else None
            if best_ask is not None:
                qty = min(SKEW_QTY, -SKEW_THRESH - pos, LIMIT - pos - self.hydrogel_buy_orders)
                if qty > 0:
                    self.hydrogel_buy_orders += qty
                    self.send_buy_order(product, best_ask, qty, msg=f"HYDROGEL skew buy {qty} @ {best_ask}")

        # Passive quotes — asymmetric sizing based on inventory
        # Long position: reduce buy size, increase sell size (and vice versa)
        skew = pos / LIMIT  # -1 to +1
        buy_qty  = max(0, min(QUOTE_SIZE - int(skew * QUOTE_SIZE), LIMIT - pos - self.hydrogel_buy_orders))
        sell_qty = max(0, min(QUOTE_SIZE + int(skew * QUOTE_SIZE), pos + LIMIT - self.hydrogel_sell_orders))

        buy_spread  = 10 if no_bids else 4
        sell_spread = 10 if no_asks else 4
        buy_px  = math.floor(fair) - buy_spread
        sell_px = math.ceil(fair)  + sell_spread

        other_ask = self.get_ask(state, product, int(fair))
        other_bid = self.get_bid(state, product, int(fair))
        if other_ask is not None:
            sell_px = other_ask - 1
        if other_bid is not None:
            buy_px = other_bid + 1

        if buy_qty > 0 and not (pos > 0 and float(buy_px) == fair):
            self.send_buy_order(product, buy_px, buy_qty, msg=f"HYDROGEL MM buy {buy_qty} @ {buy_px}")
        if sell_qty > 0 and not (pos < 0 and float(sell_px) == fair):
            self.send_sell_order(product, sell_px, -sell_qty, msg=f"HYDROGEL MM sell {sell_qty} @ {sell_px}")

    def trade_vfe(self, state: TradingState) -> None:
        product = 'VELVETFRUIT_EXTRACT'
        LIMIT       = self.limits[product]
        SKEW_THRESH = 30
        SKEW_QTY    = 10
        FOLLOW_QTY  = 15   # Mark 67 follow size
        FADE_QTY    = 15   # Mark 22/49 fade size

        depth = state.order_depths.get(product)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            return

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        bid_vol  = depth.buy_orders[best_bid]
        ask_vol  = abs(depth.sell_orders[best_ask])
        pos      = self.vfe_position

        imb = (bid_vol - ask_vol) / (bid_vol + ask_vol)

        # Inventory skew reduction
        if pos > SKEW_THRESH:
            qty = min(SKEW_QTY, pos - SKEW_THRESH, pos + LIMIT - self.vfe_sell_orders)
            if qty > 0:
                self.vfe_sell_orders += qty
                self.send_sell_order(product, best_bid, -qty)
        elif pos < -SKEW_THRESH:
            qty = min(SKEW_QTY, -SKEW_THRESH - pos, LIMIT - pos - self.vfe_buy_orders)
            if qty > 0:
                self.vfe_buy_orders += qty
                self.send_buy_order(product, best_ask, qty)

        # Trader-following: parse market_trades for named trader signals
        # Mark 67: follow (83% win rate, +1.9 avg fwd return)
        # Mark 22, Mark 49: fade (14-22% win rate, negative avg fwd return)
        FOLLOW_TRADERS = {"Mark 67"}
        FADE_TRADERS   = {"Mark 22", "Mark 49"}

        recent_trades = state.market_trades.get(product, [])
        follow_signal = 0  # +1 buy, -1 sell
        fade_signal   = 0

        for trade in recent_trades:
            if trade.buyer in FOLLOW_TRADERS:
                follow_signal = 1
            elif trade.seller in FOLLOW_TRADERS:
                follow_signal = -1
            if trade.buyer in FADE_TRADERS:
                fade_signal = -1   # fade their buy → we sell
            elif trade.seller in FADE_TRADERS:
                fade_signal = 1    # fade their sell → we buy

        combined_signal = 0
        if follow_signal != 0:
            combined_signal = follow_signal
        elif fade_signal != 0:
            combined_signal = fade_signal

        if combined_signal == 1:
            qty = min(FOLLOW_QTY, LIMIT - pos - self.vfe_buy_orders)
            if qty > 0:
                self.vfe_buy_orders += qty
                self.send_buy_order(product, best_ask, qty, msg=f"VFE trader-follow BUY {qty} @ {best_ask}")
        elif combined_signal == -1:
            qty = min(FOLLOW_QTY, pos + LIMIT - self.vfe_sell_orders)
            if qty > 0:
                self.vfe_sell_orders += qty
                self.send_sell_order(product, best_bid, -qty, msg=f"VFE trader-follow SELL {qty} @ {best_bid}")

        # OI-skewed passive quotes: signal → post on favored side inside spread
        QUOTE_SIZE = 15
        skew = pos / LIMIT  # inventory skew -1 to +1

        oi_adj = imb  # -1 to +1
        buy_qty  = max(0, min(int(QUOTE_SIZE * (1 - skew) * (1 - max(oi_adj, 0))),
                              LIMIT - pos - self.vfe_buy_orders))
        sell_qty = max(0, min(int(QUOTE_SIZE * (1 + skew) * (1 + min(oi_adj, 0))),
                              pos + LIMIT - self.vfe_sell_orders))

        buy_px  = best_bid + 1
        sell_px = best_ask - 1

        if buy_qty > 0 and buy_px < best_ask:
            self.vfe_buy_orders += buy_qty
            self.send_buy_order(product, buy_px, buy_qty)
        if sell_qty > 0 and sell_px > best_bid:
            self.vfe_sell_orders += sell_qty
            self.send_sell_order(product, sell_px, -sell_qty)


    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0

        self.hydrogel_position = state.position.get('HYDROGEL_PACK', 0)
        self.hydrogel_buy_orders  = 0
        self.hydrogel_sell_orders = 0

        self.vfe_position = state.position.get('VELVETFRUIT_EXTRACT', 0)
        self.vfe_buy_orders  = 0
        self.vfe_sell_orders = 0

        for product in state.order_depths:
            self.orders[product] = []

    def run(self, state: TradingState):
        self.reset_orders(state)
        self.trade_hydrogel(state)
        self.trade_vfe(state)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData
