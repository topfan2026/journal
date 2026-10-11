"""Thin wrapper around ib_async for connecting, placing orders and managing stops."""
from __future__ import annotations

import math
import time

from ib_async import IB, MarketOrder, Stock, StopOrder, Trade

SETTLED = {"Filled", "Cancelled", "ApiCancelled", "Inactive", "Submitted", "PreSubmitted"}
DEAD = {"Cancelled", "ApiCancelled", "Inactive"}


class IBKRClient:
    def __init__(self, host: str, port: int, client_id: int, timeout: float = 10):
        self.ib = IB()
        self.ib.connect(host, port, clientId=client_id, timeout=timeout)
        # 3 = delayed data when no real-time subscription (free paper accounts), live otherwise.
        self.ib.reqMarketDataType(3)
        self._contracts: dict[str, Stock] = {}

    def contract(self, symbol: str) -> Stock:
        if symbol not in self._contracts:
            c = Stock(symbol, "SMART", "USD")
            qualified = self.ib.qualifyContracts(c)
            if not qualified or not getattr(qualified[0], "conId", 0):
                raise ValueError(f"could not qualify contract for {symbol}")
            self._contracts[symbol] = qualified[0]
        return self._contracts[symbol]

    def wait_settled(self, trade: Trade, timeout: float = 10, until_filled: bool = True) -> Trade:
        """Wait until the order leaves PendingSubmit (and, for market orders, until filled)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = trade.orderStatus.status
            if status in DEAD or status == "Filled":
                break
            if not until_filled and status in SETTLED:
                break
            self.ib.sleep(0.25)
        return trade

    def place_order(self, symbol: str, side: str, quantity: int, timeout: float = 10) -> Trade:
        order = MarketOrder(side.upper(), int(quantity), outsideRth=True)
        trade = self.ib.placeOrder(self.contract(symbol), order)
        return self.wait_settled(trade, timeout)

    def place_stop(self, symbol: str, quantity: int, stop_price: float) -> Trade:
        """Protective GTC sell stop. GTC so a crashed bot never leaves a position naked overnight."""
        order = StopOrder("SELL", int(quantity), round_price(stop_price), tif="GTC")
        trade = self.ib.placeOrder(self.contract(symbol), order)
        return self.wait_settled(trade, timeout=5, until_filled=False)

    def find_open_trade(self, order_id: int) -> Trade | None:
        for t in self.ib.openTrades():
            if t.order.orderId == order_id:
                return t
        return None

    def modify_stop(self, symbol: str, order_id: int | None, quantity: int, stop_price: float) -> Trade:
        """Move/resize an existing stop in place (no unprotected gap); place a new one if it's gone."""
        existing = self.find_open_trade(order_id) if order_id else None
        if existing is None:
            return self.place_stop(symbol, quantity, stop_price)
        order = existing.order
        order.totalQuantity = int(quantity)
        order.auxPrice = round_price(stop_price)
        trade = self.ib.placeOrder(existing.contract, order)
        return self.wait_settled(trade, timeout=5, until_filled=False)

    def cancel(self, order_id: int | None) -> bool:
        existing = self.find_open_trade(order_id) if order_id else None
        if existing is None:
            return False
        self.ib.cancelOrder(existing.order)
        self.ib.sleep(1)
        return True

    def position_qty(self, symbol: str) -> int:
        return int(sum(p.position for p in self.ib.positions() if p.contract.symbol == symbol))

    def held_symbols(self) -> set[str]:
        return {p.contract.symbol for p in self.ib.positions() if p.position != 0}

    def last_price(self, symbol: str) -> float:
        """Snapshot price (live or delayed). Returns nan if IBKR has nothing."""
        [ticker] = self.ib.reqTickers(self.contract(symbol))
        for value in (ticker.marketPrice(), ticker.last, ticker.close):
            if value is not None and not math.isnan(value) and value > 0:
                return float(value)
        return float("nan")

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()


def round_price(price: float) -> float:
    """US stocks >= $1 trade in $0.01 ticks; IBKR rejects stops with more decimals."""
    return round(float(price), 2) if price >= 1 else round(float(price), 4)
