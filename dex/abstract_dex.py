#!/usr/bin/env python3

from abc import ABC, abstractmethod
import threading
import time
from typing import Optional

TICK_PRICE_MULTIPLIER = 0.1


class AbstractDex(ABC):

    def __init__(self):
        self.price_info = {}
        self.processed_orders = {}  # {'symbol': {'order_id': timestamp, ...}, ...}
        self.websocket_lock = threading.Lock()
        self.cleanup_timer_thread = None
        self.__schedule_cleanup()

    def cleanup_timer(self):
        if self.cleanup_timer_thread:
            self.cleanup_timer_thread.cancel()

    def __cleanup_processed_orders(self, expiration_time):
        current_timestamp = time.time()
        with self.websocket_lock:
            for symbol in list(self.processed_orders.keys()):
                for order_id in list(self.processed_orders[symbol].keys()):
                    if current_timestamp - self.processed_orders[symbol][order_id]["timestamp"] > expiration_time:
                        del self.processed_orders[symbol][order_id]
                if not self.processed_orders[symbol]:
                    del self.processed_orders[symbol]

    def __schedule_cleanup(self, expiration_time=10):
        self.__cleanup_processed_orders(expiration_time)
        self.cleanup_timer_thread = threading.Timer(
            expiration_time, self.__schedule_cleanup)
        self.cleanup_timer_thread.start()

    def modify_price_for_instant_fill(self, symbol: str, side: str, price: str):
        price_float = float(price)
        if side == 'BUY':
            price_float *= (1.0 + TICK_PRICE_MULTIPLIER)
        else:
            price_float *= (1.0 - TICK_PRICE_MULTIPLIER)
        return str(price_float)

    def clear_filled_order(self, symbol: str, order_id: str):
        with self.websocket_lock:
            if symbol in list(self.processed_orders.keys()):
                if order_id in list(self.processed_orders[symbol].keys()):
                    del self.processed_orders[symbol][order_id]
                    if not self.processed_orders[symbol]:
                        del self.processed_orders[symbol]

    @abstractmethod
    def get_ticker(self, symbol: str):
        pass

    @abstractmethod
    def get_filled_orders(self, symbol: str):
        pass

    @abstractmethod
    def get_balance(self):
        pass

    @abstractmethod
    def create_order(self, symbol: str, size: str, side: str, price: Optional[str]):
        pass

    @abstractmethod
    def cancel_order(self, order_id: str):
        pass

    @abstractmethod
    def close_all_positions(self, symbol: str):
        pass
