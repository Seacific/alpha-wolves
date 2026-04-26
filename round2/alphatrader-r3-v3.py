import json
from typing import Any
import math

from datamodel import *
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
        return [state.timestamp, trader_data, self.compress_listings(state.listings),
                self.compress_order_depths(state.order_depths), self.compress_trades(state.own_trades),
                self.compress_trades(state.market_trades), state.position, self.compress_observations(state.observations)]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        return [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                for arr in trades.values() for t in arr]

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
                out = candidate; lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()

MM_VOUCHER_STRIKES = [4500, 5000, 5100, 5200, 5300]
VOUCHER_LIMIT      = 200
TICKS_PER_DAY      = 10_000
TOTAL_TICKS        = 50_000   # 5 days to expiry from tick 0

# IV linear trend: iv(t) = slope * global_tick + intercept  (fitted from historical days 0-2)
IV_SLOPE = {
    4500: 5.2413880036e-09,
    5000: 1.3245300938e-09,
    5100: 9.9241503383e-10,
    5200: 1.3408141422e-09,
    5300: 1.5390054946e-09,
}
IV_INTERCEPT = {
    4500: 0.00026136,
    5000: 0.00015514,
    5100: 0.00015827,
    5200: 0.00015514,
    5300: 0.00015418,
}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call_fair(S: float, K: int, iv: float, T: float) -> float:
    """Black-Scholes European call, r=0. T in ticks."""
    if T <= 0 or iv <= 0 or S <= 0:
        return max(S - K, 0.0)
    sq = iv * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / sq
    d2 = d1 - sq
    return S * _norm_cdf(d1) - K * _norm_cdf(d2)


class Trader:
    # VFE wall-fair MR params
    VFE_ENTRY_STEP   = 2
    VFE_MIN_TARGET   = 5
    VFE_STEP_SIZE    = 1
    VFE_MAX_TAKE     = 30
    VFE_PASSIVE_EDGE = 0
    VFE_EMA_ALPHA    = 0.6
    VFE_SWING_LIMIT  = 200
    VFE_MM_QUOTE     = 15

    # VEV_4500 params
    V4500_ENTRY_STEP = 1; V4500_MIN_TARGET = 5; V4500_STEP_SIZE = 1
    V4500_MAX_TAKE = 30; V4500_PASSIVE_EDGE = 0; V4500_EMA_ALPHA = 0.8
    V4500_SWING_LIMIT = 200; V4500_MM_QUOTE = 15
    # VEV_5000 params
    V5000_ENTRY_STEP = 1; V5000_MIN_TARGET = 5; V5000_STEP_SIZE = 1
    V5000_MAX_TAKE = 30; V5000_PASSIVE_EDGE = 0; V5000_EMA_ALPHA = 0.8
    V5000_SWING_LIMIT = 200; V5000_MM_QUOTE = 15
    # VEV_5100 params
    V5100_ENTRY_STEP = 1; V5100_MIN_TARGET = 5; V5100_STEP_SIZE = 1
    V5100_MAX_TAKE = 30; V5100_PASSIVE_EDGE = 0; V5100_EMA_ALPHA = 0.8
    V5100_SWING_LIMIT = 50; V5100_MM_QUOTE = 15
    # VEV_5200 params
    V5200_ENTRY_STEP = 2; V5200_MIN_TARGET = 5; V5200_STEP_SIZE = 1
    V5200_MAX_TAKE = 30; V5200_PASSIVE_EDGE = 0; V5200_EMA_ALPHA = 0.8
    V5200_SWING_LIMIT = 200; V5200_MM_QUOTE = 15
    # VEV_5300 params
    V5300_ENTRY_STEP = 2; V5300_MIN_TARGET = 5; V5300_STEP_SIZE = 1
    V5300_MAX_TAKE = 30; V5300_PASSIVE_EDGE = 0; V5300_EMA_ALPHA = 0.8
    V5300_SWING_LIMIT = 200; V5300_MM_QUOTE = 15

    DAY_OFFSET = 0  # set to 4 before live submission

    def __init__(self):
        self.limits = {
            'HYDROGEL_PACK': 200,
            'VELVETFRUIT_EXTRACT': 200,
            **{f'VEV_{s}': VOUCHER_LIMIT for s in MM_VOUCHER_STRIKES},
        }
        self.orders: dict[str, list[Order]] = {}
        self.conversions = 0
        self.traderData = "{}"
        self.prev_walls: dict[str, tuple] = {}
        # per-product order accounting, reset each tick
        self._buy_sent:  dict[str, int] = {}
        self._sell_sent: dict[str, int] = {}

    def _buy_cap(self, product: str, pos: int) -> int:
        return max(0, self.limits[product] - pos - self._buy_sent.get(product, 0))

    def _sell_cap(self, product: str, pos: int) -> int:
        return max(0, pos + self.limits[product] - self._sell_sent.get(product, 0))

    def _take_buy(self, product: str, sell_orders: dict, pos: int, target: int, max_price: float, max_take: int) -> None:
        to_buy = min(target - pos - self._buy_sent.get(product, 0),
                     self._buy_cap(product, pos),
                     max_take)
        if to_buy <= 0:
            return
        for ask in sorted(sell_orders.keys()):
            if to_buy <= 0 or ask > max_price:
                break
            size = min(to_buy, -sell_orders[ask])
            if size <= 0:
                continue
            self._buy_sent[product] = self._buy_sent.get(product, 0) + size
            self.orders[product].append(Order(product, ask, size))
            to_buy -= size

    def _take_sell(self, product: str, buy_orders: dict, pos: int, target: int, min_price: float, max_take: int) -> None:
        to_sell = min(pos - target - self._sell_sent.get(product, 0),
                      self._sell_cap(product, pos),
                      max_take)
        if to_sell <= 0:
            return
        for bid in sorted(buy_orders.keys(), reverse=True):
            if to_sell <= 0 or bid < min_price:
                break
            size = min(to_sell, buy_orders[bid])
            if size <= 0:
                continue
            self._sell_sent[product] = self._sell_sent.get(product, 0) + size
            self.orders[product].append(Order(product, bid, -size))
            to_sell -= size

    def _passive_buy(self, product: str, buy_orders: dict, sell_orders: dict, pos: int, target: int, fair: float, passive_edge: int, max_take: int) -> None:
        to_buy = min(target - pos - self._buy_sent.get(product, 0),
                     self._buy_cap(product, pos),
                     max_take)
        if to_buy <= 0:
            return
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        px = math.floor(fair) - passive_edge
        if best_bid is not None:
            px = min(best_bid + 1, px)
        if best_ask is not None:
            px = min(px, best_ask - 1)
        self._buy_sent[product] = self._buy_sent.get(product, 0) + to_buy
        self.orders[product].append(Order(product, px, to_buy))

    def _passive_sell(self, product: str, buy_orders: dict, sell_orders: dict, pos: int, target: int, fair: float, passive_edge: int, max_take: int) -> None:
        to_sell = min(pos - target - self._sell_sent.get(product, 0),
                      self._sell_cap(product, pos),
                      max_take)
        if to_sell <= 0:
            return
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        px = math.ceil(fair) + passive_edge
        if best_ask is not None:
            px = max(best_ask - 1, px)
        if best_bid is not None:
            px = max(px, best_bid + 1)
        self._sell_sent[product] = self._sell_sent.get(product, 0) + to_sell
        self.orders[product].append(Order(product, px, -to_sell))

    def _market_make(self, product: str, buy_orders: dict, sell_orders: dict, pos: int, fair: float,
                     quote_size: int = None, take_quotes: bool = True) -> None:
        no_bids = len(buy_orders) == 0
        no_asks = len(sell_orders) == 0

        if take_quotes:
            for ask in sorted(sell_orders.keys()):
                if ask >= fair:
                    break
                size = min(self._buy_cap(product, pos), -sell_orders[ask])
                if size <= 0:
                    continue
                self._buy_sent[product] = self._buy_sent.get(product, 0) + size
                self.orders[product].append(Order(product, ask, size))

            for bid in sorted(buy_orders.keys(), reverse=True):
                if bid <= fair:
                    break
                size = min(self._sell_cap(product, pos), buy_orders[bid])
                if size <= 0:
                    continue
                self._sell_sent[product] = self._sell_sent.get(product, 0) + size
                self.orders[product].append(Order(product, bid, -size))

        best_ask_out = next((px for px in sorted(sell_orders.keys()) if px > math.ceil(fair)), None)
        best_bid_out = next((px for px in sorted(buy_orders.keys(), reverse=True) if px < math.floor(fair)), None)

        buy_spread  = 10 if no_bids else 4
        sell_spread = 10 if no_asks else 4
        buy_px  = math.floor(fair) - buy_spread
        sell_px = math.ceil(fair)  + sell_spread

        if best_ask_out is not None:
            sell_px = best_ask_out - 1
        if best_bid_out is not None:
            buy_px  = best_bid_out + 1

        max_buy  = self._buy_cap(product, pos)
        max_sell = self._sell_cap(product, pos)
        if quote_size is not None:
            max_buy  = min(max_buy,  quote_size)
            max_sell = min(max_sell, quote_size)

        if max_buy > 0:
            self._buy_sent[product] = self._buy_sent.get(product, 0) + max_buy
            self.orders[product].append(Order(product, buy_px, max_buy))
        if max_sell > 0:
            self._sell_sent[product] = self._sell_sent.get(product, 0) + max_sell
            self.orders[product].append(Order(product, sell_px, -max_sell))

    def _trade_mr(self, state: TradingState, product: str, saved: dict,
                  entry_step: int, min_target: int, step_size: int, max_take: int,
                  passive_edge: int, ema_alpha: float, swing_limit: int, mm_quote: int) -> dict:
        depth = state.order_depths.get(product)
        if depth is None:
            return saved

        buy_orders  = depth.buy_orders
        sell_orders = depth.sell_orders

        bid_wall = max(buy_orders.items(),  key=lambda x: x[1])[0] if buy_orders  else None
        ask_wall = max(sell_orders.items(), key=lambda x: abs(x[1]))[0] if sell_orders else None

        prev_bid, prev_ask = self.prev_walls.get(product, (None, None))
        if bid_wall is None: bid_wall = prev_bid
        if ask_wall is None: ask_wall = prev_ask
        self.prev_walls[product] = (bid_wall, ask_wall)

        if bid_wall is None or ask_wall is None:
            return saved

        raw_fair = (bid_wall + ask_wall) / 2.0
        ema_key  = f'ema_{product}'
        ema_fair = saved.get(ema_key, raw_fair)

        # scale alpha up with rolling vol: high vol → react faster to walls
        vol_key = f'vol_{product}'
        prev_fair = ema_fair
        vol = saved.get(vol_key, 0.0)
        vol = 0.1 * abs(raw_fair - prev_fair) + 0.9 * vol
        saved[vol_key] = vol
        base_vol = 15  # wall-fair moves more than mid; scale alpha only on big moves
        vol_scale = min(vol / base_vol, 2.0)  # cap at 2x
        dyn_alpha = min(ema_alpha * (1.0 + vol_scale), 1.0)

        ema_fair = dyn_alpha * raw_fair + (1 - dyn_alpha) * ema_fair
        saved[ema_key] = ema_fair
        fair = ema_fair

        pos = state.position.get(product, 0)
        self._buy_sent[product]  = 0
        self._sell_sent[product] = 0

        sl            = min(self.limits[product], swing_limit)
        mm_quote_size = min(mm_quote, max(0, self.limits[product] - sl))

        best_ask = min(sell_orders.keys()) if sell_orders else None
        best_bid = max(buy_orders.keys())  if buy_orders  else None

        if best_ask is not None and best_ask <= fair - entry_step:
            discount = fair - best_ask
            target = min(sl, min_target + int(discount // entry_step) * step_size)
            self._take_buy(product, sell_orders, pos, target, fair - entry_step, max_take)
            self._passive_buy(product, buy_orders, sell_orders, pos, target, fair, passive_edge, max_take)
            self._market_make(product, buy_orders, sell_orders, pos, fair,
                              quote_size=mm_quote_size, take_quotes=False)

        elif best_bid is not None and best_bid >= fair + entry_step:
            premium = best_bid - fair
            target = -min(sl, min_target + int(premium // entry_step) * step_size)
            self._take_sell(product, buy_orders, pos, target, fair + entry_step, max_take)
            self._passive_sell(product, buy_orders, sell_orders, pos, target, fair, passive_edge, max_take)
            self._market_make(product, buy_orders, sell_orders, pos, fair,
                              quote_size=mm_quote_size, take_quotes=False)

        else:
            self._market_make(product, buy_orders, sell_orders, pos, fair)

        return saved

    def trade_vfe(self, state: TradingState, saved: dict) -> dict:
        return self._trade_mr(state, 'VELVETFRUIT_EXTRACT', saved,
            self.VFE_ENTRY_STEP, self.VFE_MIN_TARGET, self.VFE_STEP_SIZE, self.VFE_MAX_TAKE,
            self.VFE_PASSIVE_EDGE, self.VFE_EMA_ALPHA, self.VFE_SWING_LIMIT, self.VFE_MM_QUOTE)

    def trade_vev4500(self, state, saved):
        return self._trade_mr(state, 'VEV_4500', saved,
            self.V4500_ENTRY_STEP, self.V4500_MIN_TARGET, self.V4500_STEP_SIZE, self.V4500_MAX_TAKE,
            self.V4500_PASSIVE_EDGE, self.V4500_EMA_ALPHA, self.V4500_SWING_LIMIT, self.V4500_MM_QUOTE)

    def trade_vev5000(self, state, saved):
        return self._trade_mr(state, 'VEV_5000', saved,
            self.V5000_ENTRY_STEP, self.V5000_MIN_TARGET, self.V5000_STEP_SIZE, self.V5000_MAX_TAKE,
            self.V5000_PASSIVE_EDGE, self.V5000_EMA_ALPHA, self.V5000_SWING_LIMIT, self.V5000_MM_QUOTE)

    def trade_vev5100(self, state, saved):
        return self._trade_mr(state, 'VEV_5100', saved,
            self.V5100_ENTRY_STEP, self.V5100_MIN_TARGET, self.V5100_STEP_SIZE, self.V5100_MAX_TAKE,
            self.V5100_PASSIVE_EDGE, self.V5100_EMA_ALPHA, self.V5100_SWING_LIMIT, self.V5100_MM_QUOTE)

    def trade_vev5200(self, state, saved):
        return self._trade_mr(state, 'VEV_5200', saved,
            self.V5200_ENTRY_STEP, self.V5200_MIN_TARGET, self.V5200_STEP_SIZE, self.V5200_MAX_TAKE,
            self.V5200_PASSIVE_EDGE, self.V5200_EMA_ALPHA, self.V5200_SWING_LIMIT, self.V5200_MM_QUOTE)

    def trade_vev5300(self, state, saved):
        return self._trade_mr(state, 'VEV_5300', saved,
            self.V5300_ENTRY_STEP, self.V5300_MIN_TARGET, self.V5300_STEP_SIZE, self.V5300_MAX_TAKE,
            self.V5300_PASSIVE_EDGE, self.V5300_EMA_ALPHA, self.V5300_SWING_LIMIT, self.V5300_MM_QUOTE)

    def run(self, state: TradingState):
        self.orders = {p: [] for p in state.order_depths}
        self.conversions = 0

        try:
            saved = json.loads(state.traderData) if state.traderData and state.traderData != "{}" else {}
        except Exception:
            saved = {}

        # track day number; DAY_OFFSET=0 for backtester, =4 for live
        prev_ts = saved.get('prev_ts', state.timestamp)
        if state.timestamp < prev_ts:
            saved['day'] = saved.get('day', self.DAY_OFFSET) + 1
        elif 'day' not in saved:
            saved['day'] = self.DAY_OFFSET
        saved['prev_ts'] = state.timestamp

        saved = self.trade_vfe(state, saved)
        saved = self.trade_vev4500(state, saved)
        saved = self.trade_vev5000(state, saved)
        saved = self.trade_vev5100(state, saved)
        saved = self.trade_vev5200(state, saved)
        saved = self.trade_vev5300(state, saved)

        self.traderData = json.dumps(saved)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData
