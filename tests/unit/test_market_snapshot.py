"""
market/snapshot.py 단위 테스트
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from market.snapshot import Candle, MarketSnapshot, Tick


@pytest.fixture
def snapshot() -> MarketSnapshot:
    return MarketSnapshot()


@pytest.fixture
def btc_tick() -> Tick:
    return Tick(
        symbol="KRW-BTC",
        price=Decimal("90000000"),
        volume=Decimal("0.5"),
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def make_candle(symbol: str = "KRW-BTC", close: float = 90000000.0) -> Candle:
    return Candle(
        symbol=symbol,
        interval="1m",
        open=Decimal(str(close)),
        high=Decimal(str(close * 1.01)),
        low=Decimal(str(close * 0.99)),
        close=Decimal(str(close)),
        volume=Decimal("1.0"),
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


class TestTick:
    def test_tick_업데이트_후_조회(self, snapshot, btc_tick):
        snapshot.update_tick(btc_tick)
        result = snapshot.get_tick("KRW-BTC")
        assert result is not None
        assert result.price == Decimal("90000000")

    def test_없는_심볼은_None(self, snapshot):
        assert snapshot.get_tick("KRW-ETH") is None

    def test_get_price_편의_메서드(self, snapshot, btc_tick):
        snapshot.update_tick(btc_tick)
        assert snapshot.get_price("KRW-BTC") == Decimal("90000000")

    def test_get_price_없으면_None(self, snapshot):
        assert snapshot.get_price("KRW-BTC") is None

    def test_tick_덮어쓰기(self, snapshot, btc_tick):
        snapshot.update_tick(btc_tick)
        new_tick = Tick(
            symbol="KRW-BTC",
            price=Decimal("95000000"),
            volume=Decimal("1.0"),
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        snapshot.update_tick(new_tick)
        assert snapshot.get_price("KRW-BTC") == Decimal("95000000")


class TestCandle:
    def test_캔들_추가_후_조회(self, snapshot):
        candle = make_candle()
        snapshot.update_candle(candle)
        result = snapshot.get_candles("KRW-BTC")
        assert len(result) == 1
        assert result[0].close == Decimal("90000000")

    def test_캔들_없는_심볼_빈_리스트(self, snapshot):
        assert snapshot.get_candles("KRW-ETH") == []

    def test_limit_파라미터(self, snapshot):
        for i in range(50):
            snapshot.update_candle(make_candle(close=float(10000 + i)))
        result = snapshot.get_candles("KRW-BTC", limit=10)
        assert len(result) == 10

    def test_limit는_최신_순서로_슬라이싱(self, snapshot):
        """limit=5이면 마지막 5개 캔들을 반환해야 한다."""
        closes = [float(10000 + i * 1000) for i in range(20)]
        for c in closes:
            snapshot.update_candle(make_candle(close=c))
        result = snapshot.get_candles("KRW-BTC", limit=5)
        assert result[-1].close == Decimal(str(closes[-1]))  # 마지막 = 최신

    def test_여러_심볼_독립_관리(self, snapshot):
        snapshot.update_candle(make_candle(symbol="KRW-BTC", close=90000000.0))
        snapshot.update_candle(make_candle(symbol="KRW-ETH", close=3000000.0))
        assert len(snapshot.get_candles("KRW-BTC")) == 1
        assert len(snapshot.get_candles("KRW-ETH")) == 1
        assert snapshot.get_candles("KRW-BTC")[0].close != snapshot.get_candles("KRW-ETH")[0].close
