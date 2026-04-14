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
        if len(value) <= max_length:
            return value

        return value[: max_length - 3] + "..."

logger = Logger()

class Trader:
    # definite init state
    def __init__(self):

        self.limits = {
            'TOMATOES' : 80,
            'EMERALDS' : 80,
        }

        self.orders = {}
        self.conversions = 0
        self.traderData = "SAMPLE"

        # tomato
        self.tomato_buy_orders = 0
        self.tomato_sell_orders = 0
        self.tomato_position = 0
        # tomato market-making / trend windows
        self.tomato_long_window_prices = []
        self.tomato_short_window_prices = []
        self.tomato_long_window = 30
        self.tomato_short_window = 5
        self.volatility_window_price_diffs = []
        self.volatility_window = 10
        self.prev_price = None
        self.prev_vol = None
        # track last logged trade timestamp per symbol to avoid duplicates
        self.last_logged_trade_timestamp = {}
        # accumulate tomato trades for end-of-day CSV export
        self.tomato_trade_records = []  # list of (timestamp, price, quantity, buyer, seller)
        self.last_seen_timestamp = -1

        # Kelp
        self.emerald_position = 0
        self.emerald_buy_orders = 0
        self.emerald_sell_orders = 0

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
        if product == 'TOMATOES':
            pos = state.position.get('TOMATOES', 0)
        elif product == 'EMERALDS':
            pos = state.position.get('EMERALDS', 0)
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
                    if product == 'TOMATOES':
                        size = min(self.limits["TOMATOES"]-self.tomato_position-self.tomato_buy_orders, -amount)

                        self.tomato_buy_orders += size 
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {str(size)} x @ {ask}")

                    elif product == 'EMERALDS':
                        size = min(self.limits["EMERALDS"]-self.emerald_position-self.emerald_buy_orders, -amount)
                        self.emerald_buy_orders += size 
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {str(size)} x @ {ask}")
                    
                    
    def search_sells(self, state, product, acceptable_price, depth=1):   
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            for bid, amount in orders[0:max(len(orders), depth)]: 
                
                pos = self.get_product_pos(state, product)   
                if int(bid) > acceptable_price or (abs(bid-acceptable_price) < 1 and (pos > 0 and abs(pos - amount) < abs(pos))):
                    if product == 'TOMATOES':
                        size = min(self.tomato_position + self.limits['TOMATOES'] - self.tomato_sell_orders, amount)
                        self.tomato_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {str(-size)} x @ {bid}")

                    elif product == 'EMERALDS':
                        size = min(self.emerald_position + self.limits['EMERALDS'] - self.emerald_sell_orders, amount)
                        self.emerald_sell_orders += size
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


    def trade_emerald(self, state):
        # Buy anything at a good price
        self.search_buys(state, 'EMERALDS', 10000, depth=3)
        self.search_sells(state, 'EMERALDS', 10000, depth=3)

        # Check if there's another market maker
        best_ask = self.get_ask(state, 'EMERALDS', 10000)
        best_bid =  self.get_bid(state, 'EMERALDS', 10000)

        # our ordinary market
        buy_price = 9996
        sell_price = 10004  

        # update market if someone else is better than us
        if best_ask is not None and best_bid is not None:
            ask = best_ask
            bid = best_bid
            
            sell_price = ask - 1
            buy_price = bid + 1
    
        max_buy = self.limits["EMERALDS"] - self.emerald_position - self.emerald_buy_orders 
        max_sell = self.emerald_position + self.limits["EMERALDS"] - self.emerald_sell_orders

        self.send_sell_order('EMERALDS', sell_price, -max_sell, msg=f"EMERALDS: MARKET MADE Sell {max_sell} @ {sell_price}")
        self.send_buy_order('EMERALDS', buy_price, max_buy, msg=f"EMERALDS: MARKET MADE Buy {max_buy} @ {buy_price}")

    def trade_tomato(self, state):
        # log recent market trades for TOMATOES
        self.log_trades(state, 'TOMATOES')
        # adapted squid-style tomato trading
        order_book = state.order_depths['TOMATOES']
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders

        if len(sell_orders) != 0 and len(buy_orders) != 0:
            # use largest-volume walls when available
            try:
                bid_wall_price, bid_wall_amount = max(buy_orders.items(), key=lambda x: x[1])
            except ValueError:
                bid_wall_price, bid_wall_amount = None, 0

            try:
                ask_wall_price, ask_wall_amount = max(sell_orders.items(), key=lambda x: abs(x[1]))
            except ValueError:
                ask_wall_price, ask_wall_amount = None, 0

            # fallback to worst levels if walls absent
            if bid_wall_price is None:
                bids_list = list(buy_orders.items())
                bid_wall_price = bids_list[-1][0]
            if ask_wall_price is None:
                asks_list = list(sell_orders.items())
                ask_wall_price = asks_list[-1][0]

            decimal_fair_price = (bid_wall_price + ask_wall_price) / 2

            # Append to windows
            self.tomato_long_window_prices.append(decimal_fair_price)
            self.tomato_long_window_prices = self.tomato_long_window_prices[-self.tomato_long_window:]
            self.tomato_short_window_prices.append(decimal_fair_price)
            self.tomato_short_window_prices = self.tomato_short_window_prices[-self.tomato_short_window:]

            if self.prev_price is not None:
                price_diff = decimal_fair_price - self.prev_price
                self.volatility_window_price_diffs.append(price_diff)
                self.volatility_window_price_diffs = self.volatility_window_price_diffs[-self.volatility_window:]

            sell_side = True
            buy_side = True

            # check volatility levels
            volatility = 0
            if len(self.volatility_window_price_diffs) == self.volatility_window:
                volatility = np.std(self.volatility_window_price_diffs)
                logger.print("TOMATOES: VOLATILITY: " + str(volatility))

            # check if we have enough data
            if len(self.tomato_long_window_prices) == self.tomato_long_window:
                logger.print("TOMATOES: VOLATILITY THRESHOLD REACHED, TURNING OFF MARKET MAKING")
                short_mean = np.mean(self.tomato_short_window_prices)
                long_mean = np.mean(self.tomato_long_window_prices)

                if long_mean < short_mean:
                    # market is up trending
                    buy_side = False
                    logger.print("TOMATOES: UP TRENDING, BUY SIDE OFF")

                elif long_mean > short_mean:
                    # market is down trending
                    sell_side = False
                    logger.print("TOMATOES: DOWN TRENDING, SELL SIDE OFF")

                size = self.get_product_pos(state, 'TOMATOES')

                tomato_pos_size = abs(size/self.limits['TOMATOES'])

                if tomato_pos_size > 0.8:
                    # near our position limit, enable both sides
                    buy_side = True
                    sell_side = True
                    logger.print("TOMATOES: NEAR POSITION LIMIT, BOTH SIDES ON")

                # flash crash check
                if self.prev_vol is not None:
                    delta_vol = abs(volatility - self.prev_vol)
                    self.prev_vol = volatility
                    logger.print("TOMATOES: delta volatility: " + str(delta_vol))
                    if delta_vol > 2:
                        logger.print("TOMATOES: HUGE VOLATILITY MOVE, FULL SEND OTHER DIRECTION")

                        if self.prev_price > decimal_fair_price:
                            # price moved UP, SELL SELL SELL
                            self.search_buys(state, 'TOMATOES', decimal_fair_price+4, depth=3)
                        elif self.prev_price < decimal_fair_price:
                            # price moved down BUY BUY BUY
                            self.search_sells(state, 'TOMATOES', decimal_fair_price-4, depth=3)
                else:
                    self.prev_vol = volatility

            logger.print(f"TOMATOES FAIR PRICE (walls): {decimal_fair_price} -- bid_wall={bid_wall_price}@{bid_wall_amount} ask_wall={ask_wall_price}@{ask_wall_amount}")
            # make market according to squid-style logic
            self.make_tomato_market(state, sell_side=sell_side, buy_side=buy_side, max_pos_percent=1)
            self.prev_price = decimal_fair_price

    def log_trades(self, state: TradingState, symbol: str) -> None:
        """Append new market trades for `symbol` to logs/<symbol>_trades.csv (timestamp,price,quantity,buyer,seller).
        Uses self.last_logged_trade_timestamp to avoid re-logging trades already written.
        """
        trades = state.market_trades.get(symbol)
        if not trades:
            return

        last_ts = self.last_logged_trade_timestamp.get(symbol, -1)
        new_trades = [t for t in trades if t.timestamp > last_ts]
        if not new_trades:
            return
        # Use the in-memory logger rather than writing files
        for t in new_trades:
            logger.print(f"TRADE_LOG,{symbol},{t.timestamp},{t.price},{t.quantity},{t.buyer},{t.seller}")
            # accumulate for end-of-day CSV
            if symbol == 'TOMATOES':
                self.tomato_trade_records.append((t.timestamp, t.price, t.quantity, t.buyer, t.seller))
            if t.timestamp > last_ts:
                last_ts = t.timestamp

        self.last_logged_trade_timestamp[symbol] = last_ts
        logger.print(f"Logged {len(new_trades)} {symbol} trades (in-stream)")

    def emit_daily_tomato_csv(self) -> None:
        """Emit accumulated TOMATOES trades as a single CSV via logger.print and then clear the buffer."""
        if not self.tomato_trade_records:
            logger.print("DAILY_TOMATO_CSV: no records to emit")
            return

        header = 'timestamp,price,quantity,buyer,seller'
        lines = [header]
        for rec in self.tomato_trade_records:
            ts, price, qty, buyer, seller = rec
            lines.append(f"{ts},{price},{qty},{buyer},{seller}")

        csv_text = "\n".join(lines)
        logger.print("DAILY_TOMATO_CSV_START")
        logger.print(csv_text)
        logger.print("DAILY_TOMATO_CSV_END")
        # clear records after emitting
        self.tomato_trade_records = []

    def make_tomato_market(self, state, sell_side=True, buy_side=True, take_buys=True, take_sells=True, max_pos_percent=1):
        # mirrored from squid-market logic adapted to TOMATOES
        low = -self.limits['TOMATOES']
        high = self.limits['TOMATOES']

        position = state.position.get("TOMATOES", 0)

        max_buy = high - position
        max_sell = position - low

        order_book = state.order_depths['TOMATOES']
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders

        if len(sell_orders) != 0 and len(buy_orders) != 0:
            # prefer wall-based fair price
            try:
                bid_wall_price, bid_wall_amount = max(buy_orders.items(), key=lambda x: x[1])
            except ValueError:
                bid_wall_price, bid_wall_amount = None, 0

            try:
                ask_wall_price, ask_wall_amount = max(sell_orders.items(), key=lambda x: abs(x[1]))
            except ValueError:
                ask_wall_price, ask_wall_amount = None, 0

            if bid_wall_price is None:
                bids_list = list(buy_orders.items())
                bid_wall_price = bids_list[-1][0]
            if ask_wall_price is None:
                asks_list = list(sell_orders.items())
                ask_wall_price = asks_list[-1][0]

            fair_price = int(math.ceil((bid_wall_price + ask_wall_price) / 2))
            decimal_fair_price = (bid_wall_price + ask_wall_price) / 2

            logger.print(f"TOMATOES FAIR PRICE (walls): {decimal_fair_price} -- bid_wall={bid_wall_price}@{bid_wall_amount} ask_wall={ask_wall_price}@{ask_wall_amount}")
            if buy_side:
                self.search_buys(state, 'TOMATOES', decimal_fair_price, depth=3)
            if sell_side:
                self.search_sells(state, 'TOMATOES', decimal_fair_price, depth=3)

            best_ask = self.get_ask(state, 'TOMATOES', fair_price)
            best_bid = self.get_bid(state, 'TOMATOES', fair_price)

            buy_price = math.floor(decimal_fair_price) - 3
            sell_price = math.ceil(decimal_fair_price) + 3

            if best_ask is not None and best_bid is not None:
                ask = best_ask
                bid = best_bid
                if ask - 1 > decimal_fair_price:
                    sell_price = ask - 1
                if bid + 1 < decimal_fair_price:
                    buy_price = bid + 1

            maximum_sizing = self.limits['TOMATOES']
            max_buy = maximum_sizing - state.position.get("TOMATOES", 0) - self.tomato_buy_orders
            max_sell = state.position.get("TOMATOES", 0) + maximum_sizing - self.tomato_sell_orders

            max_buy = max(0, max_buy)
            max_sell = max(0, max_sell)

            max_pos = self.limits['TOMATOES'] * max_pos_percent
            max_buy = min(max_buy, max_pos)
            max_sell = min(max_sell, max_pos)

            if buy_side:
                self.send_buy_order('TOMATOES', buy_price, max_buy, msg=f"TOMATOES: MARKET MADE Buy {max_buy} @ {buy_price}")
            if sell_side:
                self.send_sell_order('TOMATOES', sell_price, -max_sell, msg=f"TOMATOES: MARKET MADE Sell {max_sell} @ {sell_price}")



    # TODO: UPDATE WHENEVER YOU ADD A NEW PRODUCT
    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0

        # reset order counts and positions
        self.tomato_position = self.get_product_pos(state, 'TOMATOES')
        self.tomato_buy_orders = 0
        self.tomato_sell_orders = 0

        self.emerald_position = self.get_product_pos(state, 'EMERALDS')
        self.emerald_buy_orders = 0
        self.emerald_sell_orders = 0

        for product in state.order_depths:
            self.orders[product] = []

    def run(self, state: TradingState):        
        # detect day rollover by timestamp decreasing -> emit end-of-day CSV
        if self.last_seen_timestamp != -1 and state.timestamp < self.last_seen_timestamp:
            # end of previous day
            self.emit_daily_tomato_csv()

        self.last_seen_timestamp = state.timestamp

        self.reset_orders(state)

        self.trade_tomato(state)
        self.trade_emerald(state)

        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData