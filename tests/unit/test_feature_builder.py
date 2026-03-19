"""
data/processor/feature_builder.py 단위 테스트
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from data.processor.feature_builder import FeatureBuilder, Features
from market.snapshot import Candle, MarketSnapshot


SYMBOL = "KRW-BTC"
BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


def fill_snapshot(prices: list[float], symbol: str = SYMBOL) -> MarketSnapshot:
    snapshot = MarketSnapshot()
    for i, p in enumerate(prices):
        snapshot.update_candle(Candle(
            symbol=symbol,
            interval="1m",
            open=Decimal(str(p)),
            high=Decimal(str(p * 1.01)),
            low=Decimal(str(p * 0.99)),
            close=Decimal(str(p)),
            volume=Decimal("1.0"),
            timestamp=BASE_TIME + timedelta(minutes=i),
        ))
    return snapshot


class TestFeatureBuilder:
    SHORT_W = 5
    LONG_W = 20
    RSI_P = 14

    def _builder(self, snapshot: MarketSnapshot) -> FeatureBuilder:
        return FeatureBuilder(
            snapshot=snapshot,
            short_window=self.SHORT_W,
            long_window=self.LONG_W,
            rsi_period=self.RSI_P,
        )

    def test_데이터_부족_시_None(self):
        snapshot = fill_snapshot([10000.0] * 5)  # long_window=20보다 적음
        builder = self._builder(snapshot)
        assert builder.build(SYMBOL) is None

    def test_충분한_데이터_시_Features_반환(self):
        snapshot = fill_snapshot([float(10000 + i * 100) for i in range(30)])
        builder = self._builder(snapshot)
        result = builder.build(SYMBOL)
        assert result is not None
        assert isinstance(result, Features)

    def test_현재가는_마지막_캔들_종가(self):
        prices = [float(10000 + i * 100) for i in range(30)]
        snapshot = fill_snapshot(prices)
        builder = self._builder(snapshot)
        result = builder.build(SYMBOL)
        assert result is not None
        assert result.current_price == Decimal(str(prices[-1]))

    def test_상승_추세에서_골든크로스(self):
        prices = [float(10000 + i * 500) for i in range(40)]
        snapshot = fill_snapshot(prices)
        builder = self._builder(snapshot)
        result = builder.build(SYMBOL)
        assert result is not None
        assert result.is_golden_cross is True
        assert result.is_dead_cross is False

    def test_하락_추세에서_데드크로스(self):
        prices = [float(50000 - i * 500) for i in range(40)]
        snapshot = fill_snapshot(prices)
        builder = self._builder(snapshot)
        result = builder.build(SYMBOL)
        assert result is not None
        assert result.is_dead_cross is True
        assert result.is_golden_cross is False

    def test_과매수_판단_rsi_70초과(self):
        prices = [float(10000 + i * 1000) for i in range(30)]
        snapshot = fill_snapshot(prices)
        builder = self._builder(snapshot)
        result = builder.build(SYMBOL)
        assert result is not None
        assert result.is_overbought is True

    def test_과매도_판단_rsi_30미만(self):
        prices = [float(50000 - i * 1000) for i in range(30)]
        snapshot = fill_snapshot(prices)
        builder = self._builder(snapshot)
        result = builder.build(SYMBOL)
        assert result is not None
        assert result.is_oversold is True

    def test_없는_심볼은_None(self):
        snapshot = fill_snapshot([10000.0] * 30)
        builder = self._builder(snapshot)
        assert builder.build("KRW-ETH") is None

    def test_sma_short가_sma_long보다_최신_가격에_민감(self):
        """상승 추세: short SMA > long SMA."""
        prices = [float(10000 + i * 200) for i in range(40)]
        snapshot = fill_snapshot(prices)
        builder = self._builder(snapshot)
        result = builder.build(SYMBOL)
        assert result is not None
        assert result.sma_short > result.sma_long
