from typing import List, Any
from typing import List, Any
import json
import math
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

# ─── Mean-reversion parameters for TOMATOES ───────────────────────────────────
MR_WINDOW       = 500    # rolling price history window
MR_ENTRY_Z      = 1.5   # z-score to enter a directional position
MR_EXIT_Z       = 0.4   # z-score to consider ourselves "back at mean"
MR_STOP_Z       = 3.5   # stop-loss: z-score too far against us → close
MR_Z_SCALE      = 1.5   # how much to adjust acceptable price per unit of z
# ──────────────────────────────────────────────────────────────────────────────

# ─── Mean-reversion parameters for TOMATOES ───────────────────────────────────
MR_WINDOW       = 40    # rolling price history window
MR_ENTRY_Z      = 1.5   # z-score to enter a directional position
MR_EXIT_Z       = 0.4   # z-score to consider ourselves "back at mean"
MR_STOP_Z       = 3.5   # stop-loss: z-score too far against us → close
MR_Z_SCALE      = 1.5   # how much to adjust acceptable price per unit of z
# ──────────────────────────────────────────────────────────────────────────────

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
                compressed.append(
                    [trade.symbol, trade.price, trade.quantity,
                     trade.buyer, trade.seller, trade.timestamp]
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
    def __init__(self):
        self.limits = {
            'TOMATOES': 80,
            'EMERALDS': 80,
        }

        self.orders = {}
        self.conversions = 0

        # Per-tick position & order trackers
        self.tomato_position    = 0
        self.tomato_buy_orders  = 0
        self.tomato_sell_orders = 0

        self.emerald_position    = 0
        self.emerald_buy_orders  = 0
        self.emerald_sell_orders = 0

        # Mean-reversion state – populated from traderData each tick
        self.tomato_price_history: list[float] = []

    # ── State persistence ──────────────────────────────────────────────────────

    def load_state(self, state: TradingState) -> None:
        """Deserialise persisted fields from traderData."""
        try:
            if state.traderData and state.traderData not in ("", "SAMPLE"):
                data = json.loads(state.traderData)
                self.tomato_price_history = data.get("tomato_prices", [])
        except Exception:
            self.tomato_price_history = []

    def build_trader_data(self) -> str:
        """Serialise state that must survive to the next tick."""
        return json.dumps({
            "tomato_prices": self.tomato_price_history[-MR_WINDOW:],
        })

    # ── Mean-reversion maths ───────────────────────────────────────────────────

    def compute_zscore(self, prices: list[float], window: int) -> float:
        """Z-score of the most-recent price relative to the rolling window."""
        if len(prices) < max(8, window // 5):
            return 0.0
        window_prices = prices[-window:]
        n = len(window_prices)
        mean = sum(window_prices) / n
        variance = sum((p - mean) ** 2 for p in window_prices) / n
        std = variance ** 0.5
        if std < 0.01:
            return 0.0
        return (window_prices[-1] - mean) / std

    # ── Order helpers ──────────────────────────────────────────────────────────

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))
        if msg is not None:
            logger.print(msg)

    def get_product_pos(self, state, product):
        if product == 'TOMATOES':
            return state.position.get('TOMATOES', 0)
        elif product == 'EMERALDS':
            return state.position.get('EMERALDS', 0)
        raise ValueError(f"Unknown product: {product}")

    def search_buys(self, state, product, acceptable_price, depth=1):
        order_depth = state.order_depths[product]
        if not order_depth.sell_orders:
            return
        orders = list(order_depth.sell_orders.items())
        for ask, amount in orders[:max(len(orders), depth)]:
            pos = self.get_product_pos(state, product)
            if int(ask) < acceptable_price or (
                abs(ask - acceptable_price) < 1 and pos < 0 and abs(pos - amount) < abs(pos)
            ):
                if product == 'TOMATOES':
                    size = min(self.limits["TOMATOES"] - self.tomato_position - self.tomato_buy_orders, -amount)
                    self.tomato_buy_orders += size
                    self.send_buy_order(product, ask, size, msg=f"TRADE BUY {size} x @ {ask}")
                elif product == 'EMERALDS':
                    size = min(self.limits["EMERALDS"] - self.emerald_position - self.emerald_buy_orders, -amount)
                    self.emerald_buy_orders += size
                    self.send_buy_order(product, ask, size, msg=f"TRADE BUY {size} x @ {ask}")

    def search_sells(self, state, product, acceptable_price, depth=1):
        order_depth = state.order_depths[product]
        if not order_depth.buy_orders:
            return
        orders = list(order_depth.buy_orders.items())
        for bid, amount in orders[:max(len(orders), depth)]:
            pos = self.get_product_pos(state, product)
            if int(bid) > acceptable_price or (
                abs(bid - acceptable_price) < 1 and pos > 0 and abs(pos - amount) < abs(pos)
            ):
                if product == 'TOMATOES':
                    size = min(self.tomato_position + self.limits['TOMATOES'] - self.tomato_sell_orders, amount)
                    self.tomato_sell_orders += size
                    self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {-size} x @ {bid}")
                elif product == 'EMERALDS':
                    size = min(self.emerald_position + self.limits['EMERALDS'] - self.emerald_sell_orders, amount)
                    self.emerald_sell_orders += size
                    self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {-size} x @ {bid}")

    def get_bid(self, state, product, price):
        order_depth = state.order_depths[product]
        if order_depth.buy_orders:
            for bid, _ in order_depth.buy_orders.items():
                if bid < price:
                    return bid
        return None

    def get_ask(self, state, product, price):
        order_depth = state.order_depths[product]
        if order_depth.sell_orders:
            for ask, _ in order_depth.sell_orders.items():
                if ask > price:
                    return ask
        return None

    def get_second_bid(self, state, product):
        orders = list(state.order_depths[product].buy_orders.items())
        return orders[1][0] if len(orders) >= 2 else None

    def get_second_ask(self, state, product):
        orders = list(state.order_depths[product].sell_orders.items())
        return orders[1][0] if len(orders) >= 2 else None

    # ── Product strategies ─────────────────────────────────────────────────────

    def trade_emerald(self, state):
        """EMERALDS: pure market-making around the known fair value of 10 000."""
        self.search_buys(state, 'EMERALDS', 10000, depth=3)
        self.search_sells(state, 'EMERALDS', 10000, depth=3)

        best_ask = self.get_ask(state, 'EMERALDS', 10000)
        best_bid = self.get_bid(state, 'EMERALDS', 10000)

        buy_price  = 9996
        sell_price = 10004

        if best_ask is not None and best_bid is not None:
            sell_price = best_ask - 1
            buy_price  = best_bid + 1

        max_buy  = self.limits["EMERALDS"] - self.emerald_position - self.emerald_buy_orders
        max_sell = self.emerald_position + self.limits["EMERALDS"] - self.emerald_sell_orders

        self.send_sell_order('EMERALDS', sell_price, -max_sell,
                             msg=f"EMERALDS: MARKET MADE Sell {max_sell} @ {sell_price}")
        self.send_buy_order('EMERALDS', buy_price, max_buy,
                            msg=f"EMERALDS: MARKET MADE Buy {max_buy} @ {buy_price}")

    def trade_tomato(self, state):
        """
        TOMATOES: mean-reversion strategy.

        Logic mirrored from reversion_algo (no external API):
          1. Maintain a rolling mid-price history (stored in traderData).
          2. Compute z-score of current mid vs. the rolling window.
          3. z < -ENTRY_Z  → price below mean, expect reversion up  → BUY aggressively.
          4. z >  ENTRY_Z  → price above mean, expect reversion down → SELL aggressively.
          5. |z| < EXIT_Z  → back at mean, unwind any open position.
          6. |z| > STOP_Z  → spread moved too far against us, stop out.
          7. Otherwise     → normal wall-based market making, skewed by z-score.
        """
        order_book  = state.order_depths['TOMATOES']
        sell_orders = order_book.sell_orders
        buy_orders  = order_book.buy_orders

        if not sell_orders or not buy_orders:
            return

        # ── Fair price from order-book walls ──────────────────────────────────
        try:
            bid_wall_price, _ = max(buy_orders.items(),  key=lambda x: x[1])
        except ValueError:
            bid_wall_price = max(buy_orders.keys())

        try:
            ask_wall_price, _ = max(sell_orders.items(), key=lambda x: abs(x[1]))
        except ValueError:
            ask_wall_price = min(sell_orders.keys())

        decimal_fair = (bid_wall_price + ask_wall_price) / 2
        decimal_fair_price = decimal_fair
        fair_price   = int(math.ceil(decimal_fair))

        # ── Mid-price for mean-reversion tracking ─────────────────────────────
        best_bid_price = max(buy_orders.keys())
        best_ask_price = min(sell_orders.keys())
        mid_price = (best_bid_price + best_ask_price) / 2

        self.tomato_price_history.append(mid_price)
        # trim to avoid unbounded growth between saves
        if len(self.tomato_price_history) > MR_WINDOW * 2:
            self.tomato_price_history = self.tomato_price_history[-MR_WINDOW:]

        z_score = self.compute_zscore(self.tomato_price_history, MR_WINDOW)

        pos = self.get_product_pos(state, 'TOMATOES')
        logger.print(f"TOMATOES: mid={mid_price:.1f} fair={decimal_fair:.1f} "
                     f"z={z_score:.3f} pos={pos} hist={len(self.tomato_price_history)}")

        # ── Z-score-adjusted acceptable prices ────────────────────────────────
        # When z < 0 (price low vs mean): raise buy threshold → take cheaper asks
        # When z > 0 (price high vs mean): lower sell threshold → take richer bids
        # Formula: acceptable = fair - z * scale
        #   z negative → acceptable rises  → more willing to buy
        #   z positive → acceptable falls  → more willing to sell
        z_adjusted = decimal_fair - z_score * MR_Z_SCALE

        # ── Regime decisions ──────────────────────────────────────────────────

        if abs(z_score) > MR_STOP_Z:
            # Stop-loss: price moved very far; close position at market
            if pos > 0:
                self.search_sells(state, 'TOMATOES', decimal_fair - MR_STOP_Z * 2, depth=5)
                logger.print(f"TOMATOES STOP-LOSS: closing long (z={z_score:.2f})")
            elif pos < 0:
                self.search_buys(state, 'TOMATOES', decimal_fair + MR_STOP_Z * 2, depth=5)
                logger.print(f"TOMATOES STOP-LOSS: closing short (z={z_score:.2f})")

        elif z_score < -MR_ENTRY_Z:
            # Price below rolling mean → expect reversion upward → BUY
            self.search_buys(state, 'TOMATOES', z_adjusted, depth=5)
            logger.print(f"TOMATOES LONG ENTRY (z={z_score:.2f})")

        elif z_score > MR_ENTRY_Z:
            # Price above rolling mean → expect reversion downward → SELL
            self.search_sells(state, 'TOMATOES', z_adjusted, depth=5)
            logger.print(f"TOMATOES SHORT ENTRY (z={z_score:.2f})")

        elif abs(z_score) < MR_EXIT_Z and pos != 0:
            # Back at mean: unwind at fair price
            if pos > 0:
                self.search_sells(state, 'TOMATOES', decimal_fair, depth=3)
                logger.print(f"TOMATOES EXIT long (z={z_score:.2f})")
            else:
                self.search_buys(state, 'TOMATOES', decimal_fair, depth=3)
                logger.print(f"TOMATOES EXIT short (z={z_score:.2f})")

        else:
            # Normal regime: market-take at wall-based fair price
            self.search_buys(state, 'TOMATOES', decimal_fair, depth=3)
            self.search_sells(state, 'TOMATOES', decimal_fair, depth=3)

        # ── Market-making quotes, skewed toward the reversion ─────────────────
         # Check if there's another market maker
            best_ask = self.get_ask(state, 'TOMATOES', fair_price)
            best_bid =  self.get_bid(state, 'TOMATOES', fair_price)

            ## our ordinary market
            buy_price = math.floor(decimal_fair_price) - 3
            sell_price = math.ceil(decimal_fair_price) + 3
  
        
            ## update market if someone else is better than us
            if best_ask is not None and best_bid is not None:
                ask = best_ask
                bid = best_bid
                
                sell_price = ask - 1
                buy_price = bid + 1

            max_buy =  self.limits["TOMATOES"] - self.tomato_position - self.tomato_buy_orders # MAXIMUM SIZE OF MARKET ON BUY SIDE
            max_sell = self.tomato_position + self.limits["TOMATOES"] - self.tomato_sell_orders # MAXIMUM SIZE OF MARKET ON SELL SIDE

        pos = self.get_product_pos(state, 'TOMATOES')
        logger.print(f"TOMATOES: mid={mid_price:.1f} fair={decimal_fair:.1f} "
                     f"z={z_score:.3f} pos={pos} hist={len(self.tomato_price_history)}")

        # ── Z-score-adjusted acceptable prices ────────────────────────────────
        # When z < 0 (price low vs mean): raise buy threshold → take cheaper asks
        # When z > 0 (price high vs mean): lower sell threshold → take richer bids
        # Formula: acceptable = fair - z * scale
        #   z negative → acceptable rises  → more willing to buy
        #   z positive → acceptable falls  → more willing to sell
        z_adjusted = decimal_fair - z_score * MR_Z_SCALE

        # ── Regime decisions ──────────────────────────────────────────────────

        if abs(z_score) > MR_STOP_Z:
            # Stop-loss: price moved very far; close position at market
            if pos > 0:
                self.search_sells(state, 'TOMATOES', decimal_fair - MR_STOP_Z * 2, depth=5)
                logger.print(f"TOMATOES STOP-LOSS: closing long (z={z_score:.2f})")
            elif pos < 0:
                self.search_buys(state, 'TOMATOES', decimal_fair + MR_STOP_Z * 2, depth=5)
                logger.print(f"TOMATOES STOP-LOSS: closing short (z={z_score:.2f})")

        elif z_score < -MR_ENTRY_Z:
            # Price below rolling mean → expect reversion upward → BUY
            self.search_buys(state, 'TOMATOES', z_adjusted, depth=5)
            logger.print(f"TOMATOES LONG ENTRY (z={z_score:.2f})")

        elif z_score > MR_ENTRY_Z:
            # Price above rolling mean → expect reversion downward → SELL
            self.search_sells(state, 'TOMATOES', z_adjusted, depth=5)
            logger.print(f"TOMATOES SHORT ENTRY (z={z_score:.2f})")

        elif abs(z_score) < MR_EXIT_Z and pos != 0:
            # Back at mean: unwind at fair price
            if pos > 0:
                self.search_sells(state, 'TOMATOES', decimal_fair, depth=3)
                logger.print(f"TOMATOES EXIT long (z={z_score:.2f})")
            else:
                self.search_buys(state, 'TOMATOES', decimal_fair, depth=3)
                logger.print(f"TOMATOES EXIT short (z={z_score:.2f})")

        else:
            # Normal regime: market-take at wall-based fair price
            self.search_buys(state, 'TOMATOES', decimal_fair, depth=3)
            self.search_sells(state, 'TOMATOES', decimal_fair, depth=3)

        # ── Market-making quotes, skewed toward the reversion ─────────────────
        BASE_SPREAD = 3

        if z_score < -MR_ENTRY_Z:
            # Lean on the buy side
            buy_price  = math.floor(decimal_fair) - 1
            sell_price = math.ceil(decimal_fair)  + BASE_SPREAD + 2
        elif z_score > MR_ENTRY_Z:
            # Lean on the sell side
            buy_price  = math.floor(decimal_fair) - BASE_SPREAD - 2
            sell_price = math.ceil(decimal_fair)  + 1
        else:
            buy_price  = math.floor(decimal_fair) - BASE_SPREAD
            sell_price = math.ceil(decimal_fair)  + BASE_SPREAD

        # Tighten if competitors are inside our spread
        competing_ask = self.get_ask(state, 'TOMATOES', fair_price)
        competing_bid = self.get_bid(state, 'TOMATOES', fair_price)

        if competing_ask is not None:
            sell_price = min(sell_price, competing_ask - 1)
        if competing_bid is not None:
            buy_price  = max(buy_price,  competing_bid + 1)

        max_buy  = self.limits["TOMATOES"] - self.tomato_position - self.tomato_buy_orders
        max_sell = self.tomato_position + self.limits["TOMATOES"] - self.tomato_sell_orders

        if max_buy > 0 and not (pos > 0 and float(buy_price) == decimal_fair):
            self.send_buy_order('TOMATOES', buy_price, max_buy,
                                msg=f"TOMATOES MM Buy {max_buy} @ {buy_price}")

        if max_sell > 0 and not (pos < 0 and float(sell_price) == decimal_fair):
            self.send_sell_order('TOMATOES', sell_price, -max_sell,
                                 msg=f"TOMATOES MM Sell {max_sell} @ {sell_price}")

    # ── Bookkeeping ────────────────────────────────────────────────────────────

    def reset_orders(self, state):
        self.orders      = {}
        self.conversions = 0

        self.tomato_position    = self.get_product_pos(state, 'TOMATOES')
        self.tomato_buy_orders  = 0
        self.tomato_sell_orders = 0

        self.emerald_position    = self.get_product_pos(state, 'EMERALDS')
        self.emerald_buy_orders  = 0
        self.emerald_sell_orders = 0

        for product in state.order_depths:
            self.orders[product] = []

    # ── Entry point ────────────────────────────────────────────────────────────

    def run(self, state: TradingState):
        self.load_state(state)
        self.reset_orders(state)

        self.trade_tomato(state)
        self.trade_emerald(state)

        new_trader_data = self.build_trader_data()
        logger.flush(state, self.orders, self.conversions, new_trader_data)
        return self.orders, self.conversions, new_trader_data
