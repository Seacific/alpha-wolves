from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string

class commodityData:
    
    def __init__(self, name):
        self.name = name
        self.runningVolume = 0
        self.runningTotalPrice = 0
        self.fairPrice



def calculatePrice(product, )
    

class Trader:

    commodityMap = {}

    priceCalculators = {}

    

    def bid(self):
        return 15
    
    def run(self, state: TradingState):
        """Only method required. It takes all buy and sell orders for all
        symbols as an input, and outputs a list of orders to be sent."""


        commodityMap = self.commodityMap

        print("traderData: " + state.traderData)
        print("Observations: " + str(state.observations))

        # Orders to be placed on exchange matching engine
        result = {}
        for product in state.order_depths:

            if product not in commodityMap:
                commodityMap[product] = commodityData(product)

            for trade in state.market_trades[product]:
                commodityMap[product].runningVolume += trade.quantity
                commodityMap[product].runningTotalPrice += trade.price
                    
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            acceptable_price = commodityMap[product].runningTotalPrice / commodityMap[product].runningVolume  # Participant should calculate this value
            print("Acceptable price : " + str(acceptable_price))
            print("Buy Order depth : " + str(len(order_depth.buy_orders)) + ", Sell order depth : " + str(len(order_depth.sell_orders)))
    
            if len(order_depth.sell_orders) != 0:
                best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                if int(best_ask) < acceptable_price:
                    print("BUY", str(-best_ask_amount) + "x", best_ask)
                    orders.append(Order(product, best_ask, -best_ask_amount))
    
            if len(order_depth.buy_orders) != 0:
                best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]
                if int(best_bid) > acceptable_price:
                    print("SELL", str(best_bid_amount) + "x", best_bid)
                    orders.append(Order(product, best_bid, -best_bid_amount))
            
            result[product] = orders
    
        traderData = ""  # No state needed - we check position directly
        conversions = 0
        return result, conversions, traderData
