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


LIQUID_STRIKES = [5000, 5100, 5200, 5300]


class Trader:
    # VFE — r3-gamma signal: blended prior + slow EMA anchor
    VFE_PRIOR        = 5257.0   # in-sample mean; 70% weight
    VFE_PRIOR_WEIGHT = 0.7
    VFE_ANCHOR_ALPHA = 0.001    # slow EMA of mid (~700 tick half-life)
    VFE_ENTRY        = 10       # ticks from fair to trigger first buy
    VFE_INIT_QTY     = 100      # units to buy on first signal
    VFE_ADD_STEP     = 10       # additional ticks required to add more
    VFE_ADD_QTY      = 80       # units per additional ladder rung
    VFE_LIMIT        = 200

    # Voucher BS-fair params (liquid strikes 5000-5300)
    VEV_ENTRY        = 1        # ticks from BS fair to trigger first buy
    VEV_INIT_QTY     = 5        # units on first signal
    VEV_ADD_STEP     = 3        # additional ticks below last buy to add more
    VEV_ADD_QTY      = 3        # extra units per rung deeper
    VEV_LIMIT        = {5000: 200, 5100: 200, 5200: 75, 5300: 50}

    # Hydrogel Pack params — pure MM, wide spread, tight position cap
    HG_EDGE          = 4     # ticks inside best bid/ask to post
    HG_QUOTE_SIZE    = 10    # units per side
    HG_POS_CAP       = 30    # max absolute position before skewing quotes off

    DAY_OFFSET = 0  # set to 4 before live submission

    def __init__(self):
        self.limits = {
            'HYDROGEL_PACK': 200,
            'VELVETFRUIT_EXTRACT': self.VFE_LIMIT,
            **{f'VEV_{K}': self.VEV_LIMIT[K] for K in LIQUID_STRIKES},
        }
        self.orders: dict[str, list[Order]] = {}
        self.conversions = 0
        self.traderData = "{}"
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

        # safety: never cross the market
        best_ask_any = min(sell_orders.keys()) if sell_orders else None
        best_bid_any = max(buy_orders.keys())  if buy_orders  else None
        if best_ask_any is not None:
            buy_px  = min(buy_px,  best_ask_any - 1)
        if best_bid_any is not None:
            sell_px = max(sell_px, best_bid_any + 1)

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

        prev_key = f'_wall_{product}'
        prev_bid, prev_ask = saved.get(prev_key, (bid_wall, ask_wall)) or (bid_wall, ask_wall)
        if bid_wall is None: bid_wall = prev_bid
        if ask_wall is None: ask_wall = prev_ask
        saved[prev_key] = (bid_wall, ask_wall)

        if bid_wall is None or ask_wall is None:
            return saved

        # Skip products with negligible price — no edge, MM just donates
        best_bid = max(buy_orders.keys())  if buy_orders  else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        if best_bid is not None and best_ask is not None:
            mid_px = (best_bid + best_ask) / 2.0
            if mid_px < 5:
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
        base_vol = 15
        vol_scale = min(vol / base_vol, 2.0)
        dyn_alpha = min(ema_alpha * (1.0 + vol_scale), 1.0)

        ema_fair = dyn_alpha * raw_fair + (1 - dyn_alpha) * ema_fair
        saved[ema_key] = ema_fair

        pos = state.position.get(product, 0)
        limit = self.limits[product]

        fair = ema_fair
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
            # no directional signal — unwind inventory toward 0, then market make
            if pos > 0 and best_bid is not None and best_bid >= fair:
                qty = min(pos, max_take, self._sell_cap(product, pos))
                if qty > 0:
                    self._sell_sent[product] = self._sell_sent.get(product, 0) + qty
                    self.orders[product].append(Order(product, best_bid, -qty))
            elif pos < 0 and best_ask is not None and best_ask <= fair:
                qty = min(-pos, max_take, self._buy_cap(product, pos))
                if qty > 0:
                    self._buy_sent[product] = self._buy_sent.get(product, 0) + qty
                    self.orders[product].append(Order(product, best_ask, qty))
            self._market_make(product, buy_orders, sell_orders, pos, fair)

        return saved

    def trade_vfe(self, state: TradingState, saved: dict) -> dict:
        """r3-gamma signal: fair = PRIOR_WEIGHT*PRIOR + (1-PRIOR_WEIGHT)*slow_EMA(mid)."""
        product = 'VELVETFRUIT_EXTRACT'
        depth = state.order_depths.get(product)
        if depth is None:
            return saved
        if not depth.buy_orders or not depth.sell_orders:
            return saved

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        mid = (best_bid + best_ask) / 2.0
        pos = state.position.get(product, 0)

        anchor = saved.get('vfe_anchor', mid)
        anchor = self.VFE_ANCHOR_ALPHA * mid + (1.0 - self.VFE_ANCHOR_ALPHA) * anchor
        saved['vfe_anchor'] = anchor

        fair = self.VFE_PRIOR_WEIGHT * self.VFE_PRIOR + (1.0 - self.VFE_PRIOR_WEIGHT) * anchor
        saved['vfe_fair'] = fair  # share with voucher logic

        last_buy_px  = saved.get('vfe_last_buy_px',  None)
        last_sell_px = saved.get('vfe_last_sell_px', None)

        if best_ask <= fair - self.VFE_ENTRY:
            # Only buy if we have no position yet, or price is strictly below last buy
            if pos <= 0 or last_buy_px is None or best_ask < last_buy_px:
                discount = fair - best_ask
                rungs = int((discount - self.VFE_ENTRY) // self.VFE_ADD_STEP)
                target = min(self.VFE_LIMIT, self.VFE_INIT_QTY + rungs * self.VFE_ADD_QTY)
                qty = min(target - pos, -depth.sell_orders[best_ask])
                if qty > 0:
                    self.orders[product].append(Order(product, best_ask, qty))
                    saved['vfe_last_buy_px'] = best_ask

        if best_bid >= fair + self.VFE_ENTRY:
            # Only sell if we have no short yet, or price is strictly above last sell
            if pos >= 0 or last_sell_px is None or best_bid > last_sell_px:
                premium = best_bid - fair
                rungs = int((premium - self.VFE_ENTRY) // self.VFE_ADD_STEP)
                target = -min(self.VFE_LIMIT, self.VFE_INIT_QTY + rungs * self.VFE_ADD_QTY)
                qty = min(pos + self.VFE_LIMIT, depth.buy_orders[best_bid])
                qty = min(qty, pos - target)
                if qty > 0:
                    self.orders[product].append(Order(product, best_bid, -qty))
                    saved['vfe_last_sell_px'] = best_bid

        # Reset last price trackers when position is flat
        if pos == 0:
            saved.pop('vfe_last_buy_px',  None)
            saved.pop('vfe_last_sell_px', None)

        return saved

    def trade_vouchers(self, state: TradingState, saved: dict) -> dict:
        """Trade liquid options (5000-5300) using BS fair with same VFE anchor as S."""
        day      = saved.get('day', self.DAY_OFFSET)
        local_t  = state.timestamp // 100
        global_t = day * TICKS_PER_DAY + local_t
        T        = max(TOTAL_TICKS - global_t, 1)

        # Use the VFE fair computed this tick as the option underlying
        S = saved.get('vfe_fair', self.VFE_PRIOR)

        for K in LIQUID_STRIKES:
            product = f'VEV_{K}'
            depth   = state.order_depths.get(product)
            if depth is None or not depth.buy_orders or not depth.sell_orders:
                continue

            best_bid = max(depth.buy_orders)
            best_ask = min(depth.sell_orders)
            mid_px   = (best_bid + best_ask) / 2.0
            if mid_px < 5:
                continue

            iv   = max(IV_SLOPE[K] * global_t + IV_INTERCEPT[K], 1e-6)
            fair = bs_call_fair(S, K, iv, T)
            pos  = state.position.get(product, 0)
            limit = self.VEV_LIMIT[K]

            last_buy_px  = saved.get(f'vev_last_buy_{K}',  None)
            last_sell_px = saved.get(f'vev_last_sell_{K}', None)

            if best_ask <= fair - self.VEV_ENTRY:
                if pos <= 0 or last_buy_px is None or best_ask < last_buy_px:
                    rungs = 0 if last_buy_px is None else int((last_buy_px - best_ask) // self.VEV_ADD_STEP)
                    qty = min(self.VEV_INIT_QTY + rungs * self.VEV_ADD_QTY, limit - pos, -depth.sell_orders[best_ask])
                    if qty > 0:
                        self.orders[product].append(Order(product, best_ask, qty))
                        saved[f'vev_last_buy_{K}'] = best_ask

            if best_bid >= fair + self.VEV_ENTRY:
                if pos >= 0 or last_sell_px is None or best_bid > last_sell_px:
                    rungs = 0 if last_sell_px is None else int((best_bid - last_sell_px) // self.VEV_ADD_STEP)
                    qty = min(self.VEV_INIT_QTY + rungs * self.VEV_ADD_QTY, limit + pos, depth.buy_orders[best_bid])
                    if qty > 0:
                        self.orders[product].append(Order(product, best_bid, -qty))
                        saved[f'vev_last_sell_{K}'] = best_bid

            if pos == 0:
                saved.pop(f'vev_last_buy_{K}',  None)
                saved.pop(f'vev_last_sell_{K}', None)

        return saved

    def trade_hydrogel(self, state: TradingState, saved: dict) -> dict:
        product = 'HYDROGEL_PACK'
        depth = state.order_depths.get(product)
        if depth is None:
            return saved

        buy_orders  = depth.buy_orders
        sell_orders = depth.sell_orders
        pos = state.position.get(product, 0)

        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        if best_bid is None or best_ask is None:
            return saved

        # Track avg entry price for unwind profitability check
        entry_px = saved.get('hg_entry_px', (best_bid + best_ask) / 2.0)
        if pos == 0:
            saved['hg_entry_px'] = (best_bid + best_ask) / 2.0

        # Unwind over cap only if profitable (price moved in our favor)
        if pos > self.HG_POS_CAP and best_bid > entry_px:
            unwind = min(pos, buy_orders[best_bid])
            if unwind > 0:
                self.orders[product].append(Order(product, best_bid, -unwind))
                saved['hg_entry_px'] = (best_bid + best_ask) / 2.0
            return saved
        if pos < -self.HG_POS_CAP and best_ask < entry_px:
            unwind = min(-pos, -sell_orders[best_ask])
            if unwind > 0:
                self.orders[product].append(Order(product, best_ask, unwind))
                saved['hg_entry_px'] = (best_bid + best_ask) / 2.0
            return saved

        # Quote inside the spread with inventory skew to stay near flat
        inv_skew = -pos * 0.3  # nudge quotes against position
        buy_px  = math.floor(best_bid - self.HG_EDGE + inv_skew)
        sell_px = math.ceil(best_ask  + self.HG_EDGE + inv_skew)

        # Safety: never cross the market
        buy_px  = min(buy_px,  best_bid)
        sell_px = max(sell_px, best_ask)

        buy_qty  = self.HG_QUOTE_SIZE if pos < self.HG_POS_CAP  else 0
        sell_qty = self.HG_QUOTE_SIZE if pos > -self.HG_POS_CAP else 0

        if buy_qty > 0:
            self.orders[product].append(Order(product, buy_px,   buy_qty))
        if sell_qty > 0:
            self.orders[product].append(Order(product, sell_px, -sell_qty))

        return saved


    def run(self, state: TradingState):
        self.orders = {p: [] for p in state.order_depths}
        self.conversions = 0

        try:
            saved = json.loads(state.traderData) if state.traderData and state.traderData != "{}" else {}
        except Exception:
            saved = {}

        prev_ts = saved.get('prev_ts', state.timestamp)
        if state.timestamp < prev_ts:
            saved['day'] = saved.get('day', self.DAY_OFFSET) + 1
        elif 'day' not in saved:
            saved['day'] = self.DAY_OFFSET
        saved['prev_ts'] = state.timestamp

        saved = self.trade_hydrogel(state, saved)
        saved = self.trade_vfe(state, saved)       # sets saved['vfe_fair']
        saved = self.trade_vouchers(state, saved)  # uses saved['vfe_fair'] as S

        self.traderData = json.dumps(saved)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData
