import json
from typing import Any
import math
from math import log, sqrt, exp
from statistics import NormalDist

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
                compressed.append([trade.symbol, trade.price, trade.quantity, trade.buyer, trade.seller, trade.timestamp])
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

_norm = NormalDist()

def bs_call(S: float, K: float, T: float, sigma: float) -> float:
    """Black-Scholes call price. T in years, r=0."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    return S * _norm.cdf(d1) - K * _norm.cdf(d2)

def implied_vol(market_price: float, S: float, K: float, T: float) -> float:
    """Bisection IV solve. Returns NaN if no solution."""
    if T <= 0:
        return float("nan")
    intrinsic = max(S - K, 0.0)
    if market_price <= intrinsic:
        return float("nan")
    lo, hi = 1e-6, 20.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if bs_call(S, K, T, mid) > market_price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-6:
            break
    return (lo + hi) / 2


class Trader:
    def __init__(self):
        self.limits = {
            'HYDROGEL_PACK': 200,
            'VELVETFRUIT_EXTRACT': 200,
            'VEV_4000': 300,
            'VEV_4500': 300,
            'VEV_5000': 300,
            'VEV_5100': 300,
            'VEV_5200': 300,
            'VEV_5300': 300,
            'VEV_5400': 300,
            'VEV_5500': 300,
            'VEV_6000': 300,
            'VEV_6500': 300,
        }

        self.orders = {}
        self.conversions = 0
        self.traderData = "{}"

        self.hydrogel_position = 0
        self.hydrogel_buy_orders = 0
        self.hydrogel_sell_orders = 0
        self.hydrogel_prev_bid_wall = None
        self.hydrogel_prev_ask_wall = None

        self.vfe_position = 0
        self.vfe_buy_orders = 0
        self.vfe_sell_orders = 0
        self.vfe_prev_bid_wall = None
        self.vfe_prev_ask_wall = None

        # Voucher IV tracking
        # Round starts at competition day 1 with 5 days to expiry.
        # Expiry is at timestamp 5_000_000 from the start of this round.
        self.EXPIRY_TICKS = 5_000_000
        self.TICKS_PER_YEAR = 1_000_000 * 252  # 1M ticks/day * 252 days/year
        self.ANCHOR_STRIKE = 5200
        self.RECALC_EVERY = 50
        # Quadratic smile fit: iv = a*lm^2 + b*lm + c  where lm = ln(S/K)
        # Fitted from historical round 3 data across all strikes (4000-6500)
        self.smile_coeffs = (7.44170806, 0.02165787, 0.21284070)
        self.ewm_iv = float("nan")  # kept for logging/fallback
        self._tick_count = 0
        self.prev_vfe_mid = float("nan")
        self.vfe_trend = float("nan")   # EWM of (wall_fair - ema_fair): positive=uptrend, negative=downtrend

        self.ALL_VOUCHER_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
        self.MAKER_STRIKE = 5200  # post passively at best bid/ask, earn the spread
        self.voucher_buy_orders: dict[int, int] = {}
        self.voucher_sell_orders: dict[int, int] = {}

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))
        if msg is not None:
            logger.print(msg)

    def get_product_pos(self, state, product):
        return state.position.get(product, 0)

    def search_buys(self, state, product, acceptable_price, depth=1):
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            orders = list(order_depth.sell_orders.items())
            for ask, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(ask) < acceptable_price or (abs(ask - acceptable_price) < 1 and (pos < 0 and abs(pos - amount) < abs(pos))):
                    if product == 'HYDROGEL_PACK':
                        size = min(self.limits['HYDROGEL_PACK'] - self.hydrogel_position - self.hydrogel_buy_orders, -amount)
                        self.hydrogel_buy_orders += size
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {str(size)} x @ {ask}")

    def search_sells(self, state, product, acceptable_price, depth=1):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            for bid, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(bid) > acceptable_price or (abs(bid - acceptable_price) < 1 and (pos > 0 and abs(pos - amount) < abs(pos))):
                    if product == 'HYDROGEL_PACK':
                        size = min(self.hydrogel_position + self.limits['HYDROGEL_PACK'] - self.hydrogel_sell_orders, amount)
                        self.hydrogel_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {str(-size)} x @ {bid}")

    def get_bid(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            for bid, _ in order_depth.buy_orders.items():
                if bid < price:
                    return bid
        return None

    def get_ask(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            for ask, _ in order_depth.sell_orders.items():
                if ask > price:
                    return ask
        return None

    def trade_hydrogel(self, state):
        low = -self.limits['HYDROGEL_PACK']
        high = self.limits['HYDROGEL_PACK']

        position = state.position.get('HYDROGEL_PACK', 0)
        max_buy = high - position
        max_sell = position - low

        order_book = state.order_depths.get('HYDROGEL_PACK')
        if order_book is None:
            return

        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders
        no_bids = len(buy_orders) == 0
        no_asks = len(sell_orders) == 0

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
            if self.hydrogel_prev_bid_wall is None:
                return
            bid_wall_price = self.hydrogel_prev_bid_wall
            bid_wall_amount = 0
        if ask_wall_price is None:
            if self.hydrogel_prev_ask_wall is None:
                return
            ask_wall_price = self.hydrogel_prev_ask_wall
            ask_wall_amount = 0

        decimal_fair_price = (bid_wall_price + ask_wall_price) / 2
        fair_p = int(math.ceil(decimal_fair_price))
        self.hydrogel_prev_bid_wall = bid_wall_price
        self.hydrogel_prev_ask_wall = ask_wall_price

        logger.print(f"HYDROGEL_PACK FAIR PRICE (walls): {decimal_fair_price} -- bid_wall={bid_wall_price}@{bid_wall_amount} ask_wall={ask_wall_price}@{ask_wall_amount}")

        self.search_buys(state, 'HYDROGEL_PACK', decimal_fair_price, depth=3)
        self.search_sells(state, 'HYDROGEL_PACK', decimal_fair_price, depth=3)

        best_ask = self.get_ask(state, 'HYDROGEL_PACK', fair_p)
        best_bid = self.get_bid(state, 'HYDROGEL_PACK', fair_p)

        buy_spread = 10 if no_bids else 4
        sell_spread = 10 if no_asks else 4
        buy_price = math.floor(decimal_fair_price) - buy_spread
        sell_price = math.ceil(decimal_fair_price) + sell_spread

        if best_ask is not None:
            sell_price = best_ask - 1
        if best_bid is not None:
            buy_price = best_bid + 1

        max_buy = self.limits['HYDROGEL_PACK'] - self.hydrogel_position - self.hydrogel_buy_orders
        max_sell = self.hydrogel_position + self.limits['HYDROGEL_PACK'] - self.hydrogel_sell_orders

        pos = self.get_product_pos(state, 'HYDROGEL_PACK')
        if not (pos > 0 and float(buy_price) == decimal_fair_price):
            self.send_buy_order('HYDROGEL_PACK', buy_price, max_buy, msg=f"HYDROGEL_PACK: MARKET MADE Buy {max_buy} @ {buy_price}")
        if not (pos < 0 and float(sell_price) == decimal_fair_price):
            self.send_sell_order('HYDROGEL_PACK', sell_price, -max_sell, msg=f"HYDROGEL_PACK: MARKET MADE Sell {max_sell} @ {sell_price}")

    def _vfe_wall_fair(self, buy_orders, sell_orders):
        bid_wall = max(buy_orders.items(), key=lambda x: x[1])[0] if buy_orders else None
        ask_wall = max(sell_orders.items(), key=lambda x: abs(x[1]))[0] if sell_orders else None
        if bid_wall is None:
            bid_wall = self.vfe_prev_bid_wall
        if ask_wall is None:
            ask_wall = self.vfe_prev_ask_wall
        if bid_wall is not None:
            self.vfe_prev_bid_wall = bid_wall
        if ask_wall is not None:
            self.vfe_prev_ask_wall = ask_wall
        if bid_wall is None or ask_wall is None:
            return None
        return (bid_wall + ask_wall) / 2.0

    def _vfe_passive_buy_to(self, buy_orders, sell_orders, pos, target, fair, edge=1, max_clip=20):
        limit = self.limits['VELVETFRUIT_EXTRACT']
        to_buy = min(target - pos - self.vfe_buy_orders, limit - pos - self.vfe_buy_orders, max_clip)
        if to_buy <= 0:
            return
        px = math.floor(fair) - edge
        if buy_orders:
            px = min(max(buy_orders.keys()) + 1, px)
        if sell_orders:
            px = min(px, min(sell_orders.keys()) - 1)
        self.vfe_buy_orders += to_buy
        self.send_buy_order('VELVETFRUIT_EXTRACT', px, to_buy, msg=f"VFE MR PASSIVE BUY {to_buy}@{px}")

    def _vfe_passive_sell_to(self, buy_orders, sell_orders, pos, target, fair, edge=1, max_clip=20):
        limit = self.limits['VELVETFRUIT_EXTRACT']
        to_sell = min(pos - target - self.vfe_sell_orders, pos + limit - self.vfe_sell_orders, max_clip)
        if to_sell <= 0:
            return
        px = math.ceil(fair) + edge
        if sell_orders:
            px = max(min(sell_orders.keys()) - 1, px)
        if buy_orders:
            px = max(px, max(buy_orders.keys()) + 1)
        self.vfe_sell_orders += to_sell
        self.send_sell_order('VELVETFRUIT_EXTRACT', px, -to_sell, msg=f"VFE MR PASSIVE SELL {to_sell}@{px}")

    def _vfe_take_buy_to(self, sell_orders, pos, target, acceptable, max_clip=30):
        limit = self.limits['VELVETFRUIT_EXTRACT']
        to_buy = min(target - pos - self.vfe_buy_orders, limit - pos - self.vfe_buy_orders, max_clip)
        if to_buy <= 0:
            return
        for ask in sorted(sell_orders.keys()):
            if to_buy <= 0 or ask > acceptable:
                break
            size = min(to_buy, -sell_orders[ask])
            if size <= 0:
                continue
            self.vfe_buy_orders += size
            self.send_buy_order('VELVETFRUIT_EXTRACT', ask, size, msg=f"VFE MR TAKE BUY {size}@{ask}")
            to_buy -= size

    def _vfe_take_sell_to(self, buy_orders, pos, target, acceptable, max_clip=30):
        limit = self.limits['VELVETFRUIT_EXTRACT']
        to_sell = min(pos - target - self.vfe_sell_orders, pos + limit - self.vfe_sell_orders, max_clip)
        if to_sell <= 0:
            return
        for bid in sorted(buy_orders.keys(), reverse=True):
            if to_sell <= 0 or bid < acceptable:
                break
            size = min(to_sell, buy_orders[bid])
            if size <= 0:
                continue
            self.vfe_sell_orders += size
            self.send_sell_order('VELVETFRUIT_EXTRACT', bid, -size, msg=f"VFE MR TAKE SELL {size}@{bid}")
            to_sell -= size

    def _vfe_market_make(self, buy_orders, sell_orders, pos, fair):
        limit = self.limits['VELVETFRUIT_EXTRACT']
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        buy_px = math.floor(fair) - 1
        sell_px = math.ceil(fair) + 1
        if best_bid is not None:
            buy_px = min(best_bid + 1, buy_px)
        if best_ask is not None:
            sell_px = max(best_ask - 1, sell_px)
        max_buy  = limit - pos - self.vfe_buy_orders
        max_sell = pos + limit - self.vfe_sell_orders
        if max_buy > 0:
            self.vfe_buy_orders += max_buy
            self.send_buy_order('VELVETFRUIT_EXTRACT', buy_px, max_buy, msg=f"VFE MM BUY {max_buy}@{buy_px}")
        if max_sell > 0:
            self.vfe_sell_orders += max_sell
            self.send_sell_order('VELVETFRUIT_EXTRACT', sell_px, -max_sell, msg=f"VFE MM SELL {max_sell}@{sell_px}")

    def _bs_delta(self, S: float, K: float, T: float, sigma: float) -> float:
        """BS call delta = N(d1)."""
        if T <= 0 or sigma <= 0 or S <= 0:
            return 1.0 if S > K else 0.0
        d1 = (log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt(T))
        return _norm.cdf(d1)

    def _voucher_mr_trade(self, state: TradingState, signal: int, vfe_signal_size: float) -> None:
        """Trade all vouchers on a strong VFE MR signal, delta-weighted and spread-gated.
        signal: +1 = buy vouchers (VFE cheap), -1 = sell vouchers (VFE rich).
        vfe_signal_size: magnitude of VFE discount/premium in ticks."""
        if self.vfe_prev_bid_wall is None or self.vfe_prev_ask_wall is None:
            return
        S = (self.vfe_prev_bid_wall + self.vfe_prev_ask_wall) / 2
        T = self._time_to_expiry(state.timestamp)

        STRIKES = [4000, 4500, 5000, 5200, 5300]  # 5100 handled independently by trade_vouchers

        for K in STRIKES:
            sym = f"VEV_{K}"
            depth = state.order_depths.get(sym)
            if depth is None:
                continue
            if signal > 0 and not depth.sell_orders:
                continue
            if signal < 0 and not depth.buy_orders:
                continue

            # spread gate: only trade if delta × vfe_signal > half_spread
            best_ask = min(depth.sell_orders) if depth.sell_orders else None
            best_bid = max(depth.buy_orders)  if depth.buy_orders  else None
            spread = (best_ask - best_bid) if (best_ask and best_bid) else 999
            half_spread = spread / 2
            smile_iv = self._smile_iv(S, K)
            if math.isnan(smile_iv):
                continue
            delta = self._bs_delta(S, K, T, smile_iv)
            expected_move = delta * vfe_signal_size
            if expected_move <= half_spread:
                continue

            # delta-weighted size relative to VFE base size of 30
            base_qty = max(1, round(30 * delta))
            pos = state.position.get(sym, 0)
            limit = self.limits[sym]

            if signal > 0:
                bought = self.voucher_buy_orders.get(K, 0)
                to_buy = min(limit - pos - bought, base_qty)
                for ask in sorted(depth.sell_orders.keys()):
                    if to_buy <= 0:
                        break
                    qty = min(to_buy, -depth.sell_orders[ask])
                    self.orders[sym].append(Order(sym, ask, qty))
                    self.voucher_buy_orders[K] = self.voucher_buy_orders.get(K, 0) + qty
                    to_buy -= qty
                    logger.print(f"{sym} MR BUY {qty}@{ask} delta={delta:.2f} exp={expected_move:.1f} hs={half_spread:.1f}")
            else:
                sold = self.voucher_sell_orders.get(K, 0)
                to_sell = min(pos + limit - sold, base_qty)
                for bid in sorted(depth.buy_orders.keys(), reverse=True):
                    if to_sell <= 0:
                        break
                    qty = min(to_sell, depth.buy_orders[bid])
                    self.orders[sym].append(Order(sym, bid, -qty))
                    self.voucher_sell_orders[K] = self.voucher_sell_orders.get(K, 0) + qty
                    to_sell -= qty
                    logger.print(f"{sym} MR SELL {qty}@{bid} delta={delta:.2f} exp={expected_move:.1f} hs={half_spread:.1f}")

    def trade_vfe(self, state: TradingState, saved: dict) -> None:
        ENTRY_STEP = 2
        MIN_TARGET = 20
        STEP_SIZE  = 10
        MAX_TAKE   = 30
        EMA_ALPHA  = 0.24

        order_book = state.order_depths.get('VELVETFRUIT_EXTRACT')
        if order_book is None:
            return

        buy_orders  = order_book.buy_orders
        sell_orders = order_book.sell_orders

        wall_fair = self._vfe_wall_fair(buy_orders, sell_orders)
        if wall_fair is None:
            return

        ema_fair = saved.get('vfe_ema_fair', wall_fair)
        ema_fair = EMA_ALPHA * wall_fair + (1 - EMA_ALPHA) * ema_fair
        saved['vfe_ema_fair'] = ema_fair
        fair = ema_fair

        # Trend filter: EWM of (wall_fair - ema_fair). Positive = price above fair = uptrend.
        TREND_ALPHA = 2 / (500 + 1)
        TREND_THRESHOLD = 1.0  # suppress counter-trend trades beyond this
        raw_trend = wall_fair - ema_fair
        self.vfe_trend = raw_trend if math.isnan(self.vfe_trend) else \
            TREND_ALPHA * raw_trend + (1 - TREND_ALPHA) * self.vfe_trend
        trend = self.vfe_trend
        trending_up   = trend >  TREND_THRESHOLD
        trending_down = trend < -TREND_THRESHOLD

        pos   = self.get_product_pos(state, 'VELVETFRUIT_EXTRACT')
        limit = self.limits['VELVETFRUIT_EXTRACT']

        best_ask = min(sell_orders.keys()) if sell_orders else None
        best_bid = max(buy_orders.keys())  if buy_orders  else None

        logger.print(f"VFE fair={fair:.2f} trend={trend:.2f} best_bid={best_bid} best_ask={best_ask} pos={pos}")

        if best_ask is not None and best_ask <= fair - ENTRY_STEP and not trending_down:
            discount = fair - best_ask
            target = min(limit, MIN_TARGET + int(discount // ENTRY_STEP) * STEP_SIZE)
            self._vfe_take_buy_to(sell_orders, pos, target, fair - ENTRY_STEP, max_clip=MAX_TAKE)
            self._vfe_passive_buy_to(buy_orders, sell_orders, pos, target, fair)
            self._voucher_mr_trade(state, signal=+1, vfe_signal_size=discount)
        elif best_bid is not None and best_bid >= fair + ENTRY_STEP and not trending_up:
            premium = best_bid - fair
            target = -min(limit, MIN_TARGET + int(premium // ENTRY_STEP) * STEP_SIZE)
            self._vfe_take_sell_to(buy_orders, pos, target, fair + ENTRY_STEP, max_clip=MAX_TAKE)
            self._vfe_passive_sell_to(buy_orders, sell_orders, pos, target, fair)
            self._voucher_mr_trade(state, signal=-1, vfe_signal_size=premium)
        else:
            self._vfe_market_make(buy_orders, sell_orders, pos, fair)

    def _time_to_expiry(self, timestamp: int) -> float:
        """Returns T in years."""
        remaining = self.EXPIRY_TICKS - timestamp
        return max(remaining / self.TICKS_PER_YEAR, 0.0)

    def _fit_smile(self, lms: list, ivs: list) -> tuple:
        """Fit quadratic a*m^2 + b*m + c to (log-moneyness, IV) pairs. Returns (a,b,c) or None."""
        n = len(lms)
        if n < 3:
            return None
        # Normal equations for least-squares quadratic fit (no numpy needed)
        s0 = n
        s1 = sum(lms)
        s2 = sum(x**2 for x in lms)
        s3 = sum(x**3 for x in lms)
        s4 = sum(x**4 for x in lms)
        t0 = sum(ivs)
        t1 = sum(lms[i]*ivs[i] for i in range(n))
        t2 = sum(lms[i]**2*ivs[i] for i in range(n))
        # Solve 3x3 system [[s4,s3,s2],[s3,s2,s1],[s2,s1,s0]] * [a,b,c] = [t2,t1,t0]
        A = [[s4,s3,s2],[s3,s2,s1],[s2,s1,s0]]
        b = [t2, t1, t0]
        # Gaussian elimination
        for col in range(3):
            pivot = A[col][col]
            if abs(pivot) < 1e-12:
                return None
            for row in range(col+1, 3):
                factor = A[row][col] / pivot
                for k in range(3):
                    A[row][k] -= factor * A[col][k]
                b[row] -= factor * b[col]
        c_val = b[2] / A[2][2]
        b_val = (b[1] - A[1][2]*c_val) / A[1][1]
        a_val = (b[0] - A[0][1]*b_val - A[0][2]*c_val) / A[0][0]
        return (a_val, b_val, c_val)

    def _update_iv(self, state: TradingState) -> None:
        """Solve IV from VEV_5200 mid-price every RECALC_EVERY ticks, update EWM.
        Runs every tick until the first valid IV is bootstrapped."""
        if not math.isnan(self.ewm_iv) and self._tick_count % self.RECALC_EVERY != 0:
            return
        anchor = f"VEV_{self.ANCHOR_STRIKE}"
        if anchor not in state.order_depths:
            return
        depth = state.order_depths[anchor]
        if not depth.buy_orders or not depth.sell_orders:
            return
        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        mid = (best_bid + best_ask) / 2

        vfe_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if vfe_depth is None or not vfe_depth.buy_orders or not vfe_depth.sell_orders:
            return
        S = (max(vfe_depth.buy_orders) + min(vfe_depth.sell_orders)) / 2

        T = self._time_to_expiry(state.timestamp)
        iv = implied_vol(mid, S, self.ANCHOR_STRIKE, T)
        if math.isnan(iv):
            return

        alpha = 2 / (10 + 1)
        self.ewm_iv = iv if math.isnan(self.ewm_iv) else alpha * iv + (1 - alpha) * self.ewm_iv
        logger.print(f"IV update: anchor_mid={mid:.1f} S={S:.1f} T={T:.6f} iv={iv:.4f} ewm_iv={self.ewm_iv:.4f}")

    def _smile_iv(self, S: float, K: float) -> float:
        """IV estimate: flat constant for near-ATM (|lm|<0.06), quadratic smile for far strikes."""
        lm = log(S / K)
        if abs(lm) < 0.06:
            return 0.219  # near-ATM mean IV across all days/strikes
        a, b, c = self.smile_coeffs
        iv = a * lm**2 + b * lm + c
        return iv if iv > 0.01 else float("nan")

    def trade_vouchers(self, state: TradingState) -> None:
        vfe_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if vfe_depth is None or not vfe_depth.buy_orders or not vfe_depth.sell_orders:
            return
        S = (max(vfe_depth.buy_orders) + min(vfe_depth.sell_orders)) / 2
        T = self._time_to_expiry(state.timestamp)

        vfe_move = 0.0 if math.isnan(self.prev_vfe_mid) else S - self.prev_vfe_mid
        self.prev_vfe_mid = S
        MIN_EDGE = 0.5 if abs(vfe_move) >= 2.0 else 1.5

        for K in self.ALL_VOUCHER_STRIKES:
            symbol = f"VEV_{K}"
            depth = state.order_depths.get(symbol)
            if depth is None or not depth.buy_orders or not depth.sell_orders:
                continue

            smile_iv = self._smile_iv(S, K)
            if math.isnan(smile_iv):
                continue
            fair = bs_call(S, K, T, smile_iv)
            delta = self._bs_delta(S, K, T, smile_iv)

            pos = state.position.get(symbol, 0)
            limit = self.limits[symbol]
            bought = self.voucher_buy_orders.get(K, 0)
            sold = self.voucher_sell_orders.get(K, 0)
            max_buy = limit - pos - bought
            max_sell = pos + limit - sold

            if K == self.MAKER_STRIKE:
                # 5200: passive maker — post at best bid/ask, gated by fair
                best_bid = max(depth.buy_orders)
                best_ask = min(depth.sell_orders)
                if max_buy > 0 and best_bid < fair:
                    self.voucher_buy_orders[K] = bought + max_buy
                    self.orders[symbol].append(Order(symbol, best_bid, max_buy))
                    logger.print(f"{symbol} MAKE BUY {max_buy}@{best_bid} fair={fair:.2f}")
                if max_sell > 0 and best_ask > fair:
                    self.voucher_sell_orders[K] = sold + max_sell
                    self.orders[symbol].append(Order(symbol, best_ask, -max_sell))
                    logger.print(f"{symbol} MAKE SELL {max_sell}@{best_ask} fair={fair:.2f}")
            else:
                # All other strikes: taker — cross when edge > MIN_EDGE, size scales with edge
                # Base qty peaks at ATM (delta~0.5) and shrinks for deep ITM/OTM
                base_qty = max(1, round(200 * delta * (1 - delta)))

                for ask_price in sorted(depth.sell_orders.keys()):
                    edge = fair - ask_price
                    if edge < MIN_EDGE or max_buy <= 0:
                        break
                    qty = min(max_buy, -depth.sell_orders[ask_price],
                              max(1, round(base_qty * edge / MIN_EDGE)))
                    self.orders[symbol].append(Order(symbol, ask_price, qty))
                    self.voucher_buy_orders[K] = self.voucher_buy_orders.get(K, 0) + qty
                    bought += qty; max_buy -= qty
                    logger.print(f"{symbol} TAKE BUY {qty}@{ask_price} fair={fair:.2f} edge={edge:.2f}")

                for bid_price in sorted(depth.buy_orders.keys(), reverse=True):
                    edge = bid_price - fair
                    if edge < MIN_EDGE or max_sell <= 0:
                        break
                    qty = min(max_sell, depth.buy_orders[bid_price],
                              max(1, round(base_qty * edge / MIN_EDGE)))
                    self.orders[symbol].append(Order(symbol, bid_price, -qty))
                    self.voucher_sell_orders[K] = self.voucher_sell_orders.get(K, 0) + qty
                    sold += qty; max_sell -= qty
                    logger.print(f"{symbol} TAKE SELL {qty}@{bid_price} fair={fair:.2f} edge={edge:.2f}")

    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0

        self.hydrogel_position = self.get_product_pos(state, 'HYDROGEL_PACK')
        self.hydrogel_buy_orders = 0
        self.hydrogel_sell_orders = 0
        self.vfe_position = self.get_product_pos(state, 'VELVETFRUIT_EXTRACT')
        self.vfe_buy_orders = 0
        self.vfe_sell_orders = 0
        self.voucher_buy_orders = {}
        self.voucher_sell_orders = {}

        for product in state.order_depths:
            self.orders[product] = []

    def run(self, state: TradingState):
        self.reset_orders(state)
        try:
            saved = json.loads(state.traderData) if state.traderData and state.traderData != "{}" else {}
        except Exception:
            saved = {}

        self._update_iv(state)
        self.trade_hydrogel(state)
        self.trade_vfe(state, saved)
        self.trade_vouchers(state)
        self._tick_count += 1
        self.traderData = json.dumps(saved)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData
