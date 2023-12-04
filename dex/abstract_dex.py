#!/usr/bin/env python3

from abc import ABC, abstractmethod
import signal
import threading
import time
from typing import Optional

TICK_SIZE_MULTIPLIER = 10


class AbstractDex(ABC):

    def __init__(self):
        self.price_info = {}
        self.processed_orders = {}  # {'symbol': {'order_id': timestamp, ...}, ...}
        self.websocket_lock = threading.Lock()
        self.cleanup_timer = None
        self.__schedule_cleanup()
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        if self.cleanup_timer:
            self.cleanup_timer.cancel()

    def __cleanup_processed_orders(self, expiration_time):
        current_timestamp = time.time()
        with self.websocket_lock:
            for symbol in list(self.processed_orders.keys()):
                for order_id in list(self.processed_orders[symbol].keys()):
                    if current_timestamp - self.processed_orders[symbol][order_id] > expiration_time:
                        del self.processed_orders[symbol][order_id]
                if not self.processed_orders[symbol]:
                    del self.processed_orders[symbol]

    def __schedule_cleanup(self, expiration_time=60):
        self.__cleanup_processed_orders(expiration_time)
        self.cleanup_timer = threading.Timer(
            expiration_time, self.__schedule_cleanup)
        self.cleanup_timer.start()

    def modify_price_for_instant_fill(self, symbol: str, side: str, price: str, tick_size: float):
        price_float = float(price)
        if side == 'BUY':
            price_float += tick_size * TICK_SIZE_MULTIPLIER
        else:
            price_float -= tick_size * TICK_SIZE_MULTIPLIER
        return str(price_float)

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
    def close_all_positions(self, symbol: str):
        pass
