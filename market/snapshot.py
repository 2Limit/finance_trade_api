"""
MarketSnapshot: 현재 시장 상태 스냅샷 (in-memory)

책임:
    - 최신 가격/호가/캔들 데이터를 메모리에 유지
    - 전략이 조회할 수 있는 단일 진실의 원천(Single Source of Truth)
    - DB 저장이 아닌 실시간 조회용
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class Tick:
    symbol: str
    price: Decimal
    volume: Decimal
    timestamp: datetime


@dataclass
class Candle:
    symbol: str
    interval: str         # "1m", "5m", "1h" 등
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timestamp: datetime


class MarketSnapshot:
    """심볼별 최신 틱/캔들을 메모리에서 관리."""

    def __init__(self) -> None:
        self._ticks: dict[str, Tick] = {}
        self._candles: dict[str, list[Candle]] = {}  # symbol → candle list

    def update_tick(self, tick: Tick) -> None:
        self._ticks[tick.symbol] = tick

    def update_candle(self, candle: Candle) -> None:
        self._candles.setdefault(candle.symbol, []).append(candle)

    def get_tick(self, symbol: str) -> Tick | None:
        return self._ticks.get(symbol)

    def get_candles(self, symbol: str, limit: int = 100) -> list[Candle]:
        return self._candles.get(symbol, [])[-limit:]

    def get_price(self, symbol: str) -> Decimal | None:
        tick = self._ticks.get(symbol)
        return tick.price if tick else None
