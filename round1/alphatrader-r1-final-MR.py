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

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
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
    # definite init state
    def __init__(self):

        self.limits = {
            'ASH_COATED_OSMIUM' : 80,
            'INTARIAN_PEPPER_ROOT' : 80,
        }

        self.orders = {}
        self.conversions = 0
        self.traderData = "SAMPLE"

        # ash_coated_osmium (was tomato)
        self.osmium_buy_orders = 0
        self.osmium_sell_orders = 0
        self.osmium_position = 0
        # last-seen wall prices for osmium (used if that side is missing)
        self.osmium_prev_bid_wall = None
        self.osmium_prev_ask_wall = None

        # Intarian pepper root (was emerald)
        self.pepper_position = 0
        self.pepper_buy_orders = 0
        self.pepper_sell_orders = 0
        # regression parameters for pepper price prediction
        self.pepper_slope = None
        self.pepper_intercept = None
        self.pepper_t0 = None  # reference timestamp (ms) used when regression was fit
        self.pepper_prev_bid_wall = None
        self.pepper_prev_ask_wall = None

        # squid

    # define easier sell and buy order functions
    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))

        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))

        if msg is not None:
            logger.print(msg)

    def printStuff(self, state):
        logger.print("traderData: " + state.traderData)
        logger.print("Observations: " + str(state.observations))        

    # TODO: UPDATE WHENEVER YOU ADD A NEW PRODUCT
    def get_product_pos(self, state, product):
        if product == 'ASH_COATED_OSMIUM':
            pos = state.position.get('ASH_COATED_OSMIUM', 0)
        elif product == 'INTARIAN_PEPPER_ROOT':
            pos = state.position.get('INTARIAN_PEPPER_ROOT', 0)
        else:
            raise ValueError(f"Unknown product: {product}")

        return pos
                
    def search_buys(self, state, product, acceptable_price, depth=1):
        # Buys things if there are asks below or equal acceptable price
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            orders = list(order_depth.sell_orders.items())
            for ask, amount in orders[0:max(len(orders), depth)]: 

                pos = self.get_product_pos(state, product)                    
                if int(ask) < acceptable_price or (abs(ask - acceptable_price) < 1 and (pos < 0 and abs(pos - amount) < abs(pos))):
                    if product == 'ASH_COATED_OSMIUM':
                        size = min(self.limits["ASH_COATED_OSMIUM"]-self.osmium_position-self.osmium_buy_orders, -amount)

                        self.osmium_buy_orders += size 
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {str(size)} x @ {ask}")

                    elif product == 'INTARIAN_PEPPER_ROOT':
                        size = min(self.limits["INTARIAN_PEPPER_ROOT"]-self.pepper_position-self.pepper_buy_orders, -amount)
                        self.pepper_buy_orders += size 
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {str(size)} x @ {ask}")
                    
                    
    def search_sells(self, state, product, acceptable_price, depth=1):   
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            for bid, amount in orders[0:max(len(orders), depth)]: 
                
                pos = self.get_product_pos(state, product)   
                if int(bid) > acceptable_price or (abs(bid-acceptable_price) < 1 and (pos > 0 and abs(pos - amount) < abs(pos))):
                    if product == 'ASH_COATED_OSMIUM':
                        size = min(self.osmium_position + self.limits['ASH_COATED_OSMIUM'] - self.osmium_sell_orders, amount)
                        self.osmium_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {str(-size)} x @ {bid}")

                    elif product == 'INTARIAN_PEPPER_ROOT':
                        size = min(self.pepper_position + self.limits['INTARIAN_PEPPER_ROOT'] - self.pepper_sell_orders, amount)
                        self.pepper_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {str(-size)} x @ {bid}")
                    

    def get_bid(self, state, product, price):        
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            for bid, _ in orders: 
                if bid < price: # DONT COPY SHIT MARKETS
                    return bid
        
        return None

    def get_ask(self, state, product, price):      
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            orders = list(order_depth.sell_orders.items())
            for ask, _ in orders: 
                if ask > price: # DONT COPY A SHITY MARKET
                    return ask
        
        return None

    def get_second_bid(self, state, product):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            if len(orders) < 2:
                return None
            else:
                bid, _ = orders[1]
                return bid
            
        return None
    
    def get_second_ask(self, state, product):
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            orders = list(order_depth.sell_orders.items())
            if len(orders) < 2:
                return None
            else:
                ask, _ = orders[1]
                return ask
            
        return None        


    def trade_pepper(self, state):
        # Compute regression slope from recent market trades for INTARIAN_PEPPER_ROOT
        slope = None
        trades = state.market_trades.get('INTARIAN_PEPPER_ROOT', []) if hasattr(state, 'market_trades') else []
        # extract last up to 1000 trades
        if trades:
            try:
                arr = sorted(trades, key=lambda t: float(t.timestamp))
                N = min(len(arr), 1000)
                recent = arr[-N:]
                ts = np.array([float(t.timestamp) for t in recent], dtype=float)
                prices = np.array([float(t.price) for t in recent], dtype=float)
                if len(ts) >= 3:
                    # use seconds for slope units
                    t0 = ts[0]
                    t_rel = (ts - t0) / 1000.0
                    try:
                        from scipy import stats
                        slope, intercept, r_value, p_value, std_err = stats.linregress(t_rel, prices)
                    except Exception:
                        coeffs = np.polyfit(t_rel, prices, 1)
                        slope = float(coeffs[0])
                        intercept = float(coeffs[1])
                else:
                    slope = None
            except Exception:
                slope = None

        # fallback to previously computed regression if available
        if slope is None:
            slope = self.pepper_slope if self.pepper_slope is not None else 0.0
            t0_for_pred = self.pepper_t0
            intercept_for_pred = self.pepper_intercept
        else:
            self.pepper_slope = float(slope)
            self.pepper_intercept = float(intercept)
            self.pepper_t0 = float(t0)
            t0_for_pred = float(t0)
            intercept_for_pred = float(intercept)

        # search for attractive immediate trades around a wide band

        order_depth = state.order_depths.get('INTARIAN_PEPPER_ROOT')
        if order_depth is None:
            return

        buy_orders = order_depth.buy_orders
        sell_orders = order_depth.sell_orders
        no_bids = len(buy_orders) == 0
        no_asks = len(sell_orders) == 0

        # find bid/ask walls (largest resting orders on each side)
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
            if self.pepper_prev_bid_wall is None:
                return
            bid_wall_price = self.pepper_prev_bid_wall
            bid_wall_amount = 0
        if ask_wall_price is None:
            if self.pepper_prev_ask_wall is None:
                return
            ask_wall_price = self.pepper_prev_ask_wall
            ask_wall_amount = 0

        decimal_fair_price = (bid_wall_price + ask_wall_price) / 2
        self.pepper_prev_bid_wall = bid_wall_price
        self.pepper_prev_ask_wall = ask_wall_price

        # predict price using the regression line: intercept + slope * t_rel
        if t0_for_pred is not None and intercept_for_pred is not None:
            t_rel_now = (float(state.timestamp) - t0_for_pred) / 1000.0
            predicted = intercept_for_pred + slope * t_rel_now
        else:
            predicted = decimal_fair_price

        logger.print(f"INTARIAN_PEPPER_ROOT PREDICTED PRICE: {predicted:.6f}")
        self.search_buys(state, 'INTARIAN_PEPPER_ROOT', math.floor(decimal_fair_price+8), depth=10)
        #self.search_sells(state, 'INTARIAN_PEPPER_ROOT', decimal_fair_price, depth=5)

        # create market around predicted price — widen when that side has no competition
        buy_spread = 15 if no_bids else 8
        sell_spread = 15 if no_asks else 8
        buy_price = math.floor(predicted) - buy_spread
        sell_price = math.ceil(predicted) + sell_spread

        # If another maker present, step to their prices
        other_best_ask = self.get_ask(state, 'INTARIAN_PEPPER_ROOT', int(predicted))
        other_best_bid = self.get_bid(state, 'INTARIAN_PEPPER_ROOT', int(predicted))
        if other_best_ask is not None:
            sell_price = other_best_ask - 1
        if other_best_bid is not None:
            buy_price = other_best_bid + 1

        max_buy = self.limits["INTARIAN_PEPPER_ROOT"] - self.pepper_position - self.pepper_buy_orders
        max_sell = self.pepper_position + self.limits["INTARIAN_PEPPER_ROOT"] - self.pepper_sell_orders

        # Post our quotes
        if max_buy > 0:
            self.send_buy_order('INTARIAN_PEPPER_ROOT', buy_price, max_buy, msg=f"INTARIAN_PEPPER_ROOT: MARKET MADE Buy {max_buy} @ {buy_price} (pred={predicted:.3f})")
        #if max_sell > 0:
        #    self.send_sell_order('INTARIAN_PEPPER_ROOT', sell_price, -max_sell, msg=f"INTARIAN_PEPPER_ROOT: MARKET MADE Sell {max_sell} @ {sell_price} (pred={predicted:.3f})")

    def _osmium_fair(self, buy_orders, sell_orders):
        """Wall-based fair price for osmium. Updates prev wall state."""
        bid_wall_price = None
        ask_wall_price = None
        if buy_orders:
            try:
                bid_wall_price = max(buy_orders.items(), key=lambda x: x[1])[0]
            except Exception:
                pass
        if sell_orders:
            try:
                ask_wall_price = max(sell_orders.items(), key=lambda x: abs(x[1]))[0]
            except Exception:
                pass
        if bid_wall_price is None:
            bid_wall_price = self.osmium_prev_bid_wall
        if ask_wall_price is None:
            ask_wall_price = self.osmium_prev_ask_wall
        if bid_wall_price is not None:
            self.osmium_prev_bid_wall = bid_wall_price
        if ask_wall_price is not None:
            self.osmium_prev_ask_wall = ask_wall_price
        if bid_wall_price is None or ask_wall_price is None:
            return None
        return (bid_wall_price + ask_wall_price) / 2.0

    def _osmium_passive_buy_to(self, buy_orders, sell_orders, pos, target, fair, edge=3, max_clip=20):
        """Move toward a long target without paying the spread."""
        limit = self.limits['ASH_COATED_OSMIUM']
        to_buy = min(target - pos - self.osmium_buy_orders,
                     limit - pos - self.osmium_buy_orders,
                     max_clip)
        if to_buy <= 0:
            return

        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None

        px = math.floor(fair) - edge
        if best_bid is not None:
            px = min(best_bid + 1, px)
        if best_ask is not None:
            px = min(px, best_ask - 1)

        self.osmium_buy_orders += to_buy
        self.send_buy_order('ASH_COATED_OSMIUM', px, to_buy,
            msg=f"OSMIUM MR PASSIVE BUY {to_buy}@{px} target={target}")

    def _osmium_passive_sell_to(self, buy_orders, sell_orders, pos, target, fair, edge=3, max_clip=20):
        """Move toward a short target without paying the spread."""
        limit = self.limits['ASH_COATED_OSMIUM']
        to_sell = min(pos - target - self.osmium_sell_orders,
                      pos + limit - self.osmium_sell_orders,
                      max_clip)
        if to_sell <= 0:
            return

        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None

        px = math.ceil(fair) + edge
        if best_ask is not None:
            px = max(best_ask - 1, px)
        if best_bid is not None:
            px = max(px, best_bid + 1)

        self.osmium_sell_orders += to_sell
        self.send_sell_order('ASH_COATED_OSMIUM', px, -to_sell,
            msg=f"OSMIUM MR PASSIVE SELL {to_sell}@{px} target={target}")

    def _osmium_take_buy_to(self, sell_orders, pos, target, acceptable_price, max_clip=16):
        """Cross only asks that are still cheap versus the reversion anchor."""
        limit = self.limits['ASH_COATED_OSMIUM']
        to_buy = min(target - pos - self.osmium_buy_orders,
                     limit - pos - self.osmium_buy_orders,
                     max_clip)
        if to_buy <= 0:
            return

        for ask in sorted(sell_orders.keys()):
            if to_buy <= 0 or ask > acceptable_price:
                break
            size = min(to_buy, -sell_orders[ask])
            if size <= 0:
                continue
            self.osmium_buy_orders += size
            self.send_buy_order('ASH_COATED_OSMIUM', ask, size,
                msg=f"OSMIUM MR TAKE BUY {size}@{ask} acceptable={acceptable_price}")
            to_buy -= size

    def _osmium_take_sell_to(self, buy_orders, pos, target, acceptable_price, max_clip=16):
        """Cross only bids that are still rich versus the reversion anchor."""
        limit = self.limits['ASH_COATED_OSMIUM']
        to_sell = min(pos - target - self.osmium_sell_orders,
                      pos + limit - self.osmium_sell_orders,
                      max_clip)
        if to_sell <= 0:
            return

        for bid in sorted(buy_orders.keys(), reverse=True):
            if to_sell <= 0 or bid < acceptable_price:
                break
            size = min(to_sell, buy_orders[bid])
            if size <= 0:
                continue
            self.osmium_sell_orders += size
            self.send_sell_order('ASH_COATED_OSMIUM', bid, -size,
                msg=f"OSMIUM MR TAKE SELL {size}@{bid} acceptable={acceptable_price}")
            to_sell -= size

    def _osmium_market_make(self, buy_orders, sell_orders, pos, fair,
                            buy_side=True, sell_side=True, quote_size=None):
        """Market-make osmium using the review strategy: take imbalanced quotes then post around fair."""
        limit = self.limits['ASH_COATED_OSMIUM']
        no_bids = len(buy_orders) == 0
        no_asks = len(sell_orders) == 0

        # Take any asks below fair (search_buys equivalent)
        if buy_side:
            for ask_px in sorted(sell_orders.keys()):
                if ask_px >= fair:
                    break
                avail = limit - pos - self.osmium_buy_orders
                size = min(avail, -sell_orders[ask_px])
                if size <= 0:
                    continue
                self.osmium_buy_orders += size
                self.send_buy_order('ASH_COATED_OSMIUM', ask_px, size,
                    msg=f"OSMIUM MM TAKE BUY {size}@{ask_px}")

        # Take any bids above fair (search_sells equivalent)
        if sell_side:
            for bid_px in sorted(buy_orders.keys(), reverse=True):
                if bid_px <= fair:
                    break
                avail = pos + limit - self.osmium_sell_orders
                size = min(avail, buy_orders[bid_px])
                if size <= 0:
                    continue
                self.osmium_sell_orders += size
                self.send_sell_order('ASH_COATED_OSMIUM', bid_px, -size,
                    msg=f"OSMIUM MM TAKE SELL {size}@{bid_px}")

        # Find best quotes from other makers (outside our fair)
        best_ask_out = None
        for px in sorted(sell_orders.keys()):
            if px > math.ceil(fair):
                best_ask_out = px; break
        best_bid_out = None
        for px in sorted(buy_orders.keys(), reverse=True):
            if px < math.floor(fair):
                best_bid_out = px; break

        # Adaptive spread: wider when no competition, tighter when another maker present
        buy_spread  = 10 if no_bids else 6
        sell_spread = 10 if no_asks else 6
        buy_px  = math.floor(fair) - buy_spread
        sell_px = math.ceil(fair)  + sell_spread

        # Step one tick in front of the best outside quote
        if best_ask_out is not None:
            sell_px = best_ask_out - 1
        if best_bid_out is not None:
            buy_px  = best_bid_out + 1

        max_buy  = limit - pos - self.osmium_buy_orders
        max_sell = pos + limit - self.osmium_sell_orders
        if quote_size is not None:
            max_buy  = min(max_buy,  quote_size)
            max_sell = min(max_sell, quote_size)

        # Guard: don't deepen an existing position right at fair
        if buy_side and max_buy > 0:
            if not (pos > 0 and float(buy_px) == fair):
                self.osmium_buy_orders += max_buy
                self.send_buy_order('ASH_COATED_OSMIUM', buy_px, max_buy,
                    msg=f"OSMIUM MM BID {max_buy}@{buy_px}")
        if sell_side and max_sell > 0:
            if not (pos < 0 and float(sell_px) == fair):
                self.osmium_sell_orders += max_sell
                self.send_sell_order('ASH_COATED_OSMIUM', sell_px, -max_sell,
                    msg=f"OSMIUM MM ASK {max_sell}@{sell_px}")

    def trade_osmium(self, state, saved):
        """
        Fixed-fair mean-reversion for ASH_COATED_OSMIUM.

        Two signals only — no explicit exit logic:
          BUY  signal: best_ask <= FAIR - ENTRY_STEP  → buy toward +target (closes any short naturally)
          SELL signal: best_bid >= FAIR + ENTRY_STEP  → sell toward -target (closes any long naturally)
          Neither: neutral MM while waiting for next signal.
        """
        FAIR = 10000        # Hard-coded mean-reversion anchor.
        ENTRY_STEP = 1      # Enter this many ticks away from FAIR on either side.
        MIN_TARGET = 15     # Base target inventory once an entry level triggers.
        STEP_SIZE = 3       # Add this much target inventory per ENTRY_STEP away.
        MAX_TAKE = 15       # Cross aggressively — close + flip in one tick if possible.
        PASSIVE_EDGE = 0    # Passive quote distance from FAIR for ladder orders.

        order_book = state.order_depths.get('ASH_COATED_OSMIUM')
        if order_book is None:
            return saved

        sell_orders = order_book.sell_orders
        buy_orders  = order_book.buy_orders

        pos   = self.get_product_pos(state, 'ASH_COATED_OSMIUM')
        limit = self.limits['ASH_COATED_OSMIUM']

        best_ask = min(sell_orders.keys()) if sell_orders else None
        best_bid = max(buy_orders.keys()) if buy_orders else None

        logger.print(f"OSMIUM FIXED FAIR={FAIR} best_bid={best_bid} best_ask={best_ask} pos={pos}")

        if best_ask is not None and best_ask <= FAIR - ENTRY_STEP:
            # BUY signal: enter long / close short if already short
            discount = FAIR - best_ask
            target = min(limit, MIN_TARGET + (discount // ENTRY_STEP) * STEP_SIZE)
            self._osmium_take_buy_to(sell_orders, pos, target, FAIR - ENTRY_STEP, max_clip=MAX_TAKE)
            self._osmium_passive_buy_to(buy_orders, sell_orders, pos, target, FAIR,
                                        edge=PASSIVE_EDGE, max_clip=MAX_TAKE)

        elif best_bid is not None and best_bid >= FAIR + ENTRY_STEP:
            # SELL signal: enter short / close long if already long
            premium = best_bid - FAIR
            target = -min(limit, MIN_TARGET + (premium // ENTRY_STEP) * STEP_SIZE)
            self._osmium_take_sell_to(buy_orders, pos, target, FAIR + ENTRY_STEP, max_clip=MAX_TAKE)
            self._osmium_passive_sell_to(buy_orders, sell_orders, pos, target, FAIR,
                                         edge=PASSIVE_EDGE, max_clip=MAX_TAKE)

        else:
            # No signal: neutral MM while holding current position
            self._osmium_market_make(buy_orders, sell_orders, pos, FAIR, quote_size=10)

        return saved



    # TODO: UPDATE WHENEVER YOU ADD A NEW PRODUCT
    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0

        # reset order counts and positions
        self.osmium_position = self.get_product_pos(state, 'ASH_COATED_OSMIUM')
        self.osmium_buy_orders = 0
        self.osmium_sell_orders = 0

        self.pepper_position = self.get_product_pos(state, 'INTARIAN_PEPPER_ROOT')
        self.pepper_buy_orders = 0
        self.pepper_sell_orders = 0

        for product in state.order_depths:
            self.orders[product] = []

    def run(self, state: TradingState):
        self.reset_orders(state)

        try:
            saved = json.loads(state.traderData) if state.traderData and state.traderData != "SAMPLE" else {}
        except Exception:
            saved = {}

        saved = self.trade_osmium(state, saved)
        self.trade_pepper(state)

        new_trader_data = json.dumps(saved)
        logger.flush(state, self.orders, self.conversions, new_trader_data)
        return self.orders, self.conversions, new_trader_data
