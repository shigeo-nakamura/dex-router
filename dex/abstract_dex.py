#!/usr/bin/env python3

from abc import ABC, abstractmethod
from typing import Optional


class AbstractDex(ABC):

    @abstractmethod
    def get_ticker(self, symbol: str):
        pass

    @abstractmethod
    def get_yesterday_pnl(self):
        pass

    @abstractmethod
    def create_order(self, symbol: str, size: str, side: str, price: Optional[str]):
        pass

    @abstractmethod
    def close_all_positions(self, symbol: str):
        pass
