import json
from typing import Any

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
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
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        return [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp] for arr in trades.values() for t in arr]

    def compress_observations(self, observations: Observation) -> list[Any]:
        co = {}
        for p, o in observations.conversionObservations.items():
            co[p] = [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex]
        return [observations.plainValueObservations, co]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi, out = 0, min(len(value), max_length), ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


class Trader:
    PRODUCT = "VELVETFRUIT_EXTRACT"
    LIMIT = 200

    PRIOR = 5257.0
    ANCHOR_ALPHA = 0.001
    PRIOR_WEIGHT = 0.7

    ENTRY = 10
    CLIP = 30

    def __init__(self) -> None:
        self.traderData = "{}"

    def run(self, state: TradingState):
        orders = {p: [] for p in state.order_depths}
        depth = state.order_depths.get(self.PRODUCT)

        if depth is None or not depth.buy_orders or not depth.sell_orders:
            logger.flush(state, orders, 0, self.traderData)
            return orders, 0, self.traderData

        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            saved = {}

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        mid = (best_bid + best_ask) / 2.0
        pos = state.position.get(self.PRODUCT, 0)

        anchor = saved.get("anchor", mid)
        anchor = self.ANCHOR_ALPHA * mid + (1.0 - self.ANCHOR_ALPHA) * anchor
        saved["anchor"] = anchor

        fair = self.PRIOR_WEIGHT * self.PRIOR + (1.0 - self.PRIOR_WEIGHT) * anchor

        if best_ask <= fair - self.ENTRY:
            qty = min(self.CLIP, self.LIMIT - pos, -depth.sell_orders[best_ask])
            if qty > 0:
                orders[self.PRODUCT].append(Order(self.PRODUCT, best_ask, qty))

        if best_bid >= fair + self.ENTRY:
            qty = min(self.CLIP, self.LIMIT + pos, depth.buy_orders[best_bid])
            if qty > 0:
                orders[self.PRODUCT].append(Order(self.PRODUCT, best_bid, -qty))

        self.traderData = json.dumps(saved, separators=(",", ":"))
        logger.flush(state, orders, 0, self.traderData)
        return orders, 0, self.traderData
