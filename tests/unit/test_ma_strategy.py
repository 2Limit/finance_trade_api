"""
strategy/impl/ma_crossover.py 단위 테스트

설계 원칙:
    - Features는 MagicMock으로 주입 (feature 계산은 test_feature_builder에서 검증)
    - _evaluate() 의 순수 결정 로직만 검증
    - DB / EventBus 의존성 없음
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from strategy.base import SignalType
from strategy.impl.ma_crossover import MACrossoverStrategy


SYMBOL = "KRW-BTC"


def make_strategy(short=5, long_=20, rsi=14) -> MACrossoverStrategy:
    return MACrossoverStrategy(
        name="test_ma",
        symbols=[SYMBOL],
        params={"short_window": short, "long_window": long_, "rsi_period": rsi},
    )


def make_features(
    symbol: str = SYMBOL,
    golden_cross: bool = False,
    dead_cross: bool = False,
    overbought: bool = False,
    oversold: bool = False,
    sma_short: float = 20000.0,
    sma_long: float = 19000.0,
    rsi_val: float = 50.0,
) -> MagicMock:
    """Features 객체를 Mock으로 생성. 속성값을 직접 제어."""
    f = MagicMock()
    f.symbol = symbol
    f.is_golden_cross = golden_cross
    f.is_dead_cross = dead_cross
    f.is_overbought = overbought
    f.is_oversold = oversold
    f.sma_short = Decimal(str(sma_short))
    f.sma_long = Decimal(str(sma_long))
    f.rsi_14 = Decimal(str(rsi_val))
    return f


class TestMACrossoverEvaluate:
    def test_골든크로스_시_BUY_시그널(self):
        strategy = make_strategy()
        features = make_features(golden_cross=True, overbought=False, rsi_val=55.0)
        signal = strategy._evaluate(features)
        assert signal is not None
        assert signal.signal_type == SignalType.BUY
        assert signal.symbol == SYMBOL

    def test_데드크로스_시_SELL_시그널(self):
        strategy = make_strategy()
        features = make_features(dead_cross=True, oversold=False, rsi_val=55.0,
                                  sma_short=19000.0, sma_long=20000.0)
        signal = strategy._evaluate(features)
        assert signal is not None
        assert signal.signal_type == SignalType.SELL

    def test_크로스_상태_변화_없으면_두번째는_None(self):
        """동일한 골든크로스 상태가 연속이면 두 번째 호출은 None."""
        strategy = make_strategy()
        features = make_features(golden_cross=True, overbought=False)

        first = strategy._evaluate(features)
        assert first is not None  # 첫 번째: prev=none → golden 전환 → 발행

        second = strategy._evaluate(features)
        assert second is None     # 두 번째: prev=golden → 중복 → 없음

    def test_과매수_시_BUY_시그널_없음(self):
        """RSI > 70인 골든크로스 상황에서 BUY를 내지 않는다."""
        strategy = make_strategy()
        features = make_features(golden_cross=True, overbought=True, rsi_val=80.0)
        signal = strategy._evaluate(features)
        assert signal is None

    def test_과매도_시_SELL_시그널_없음(self):
        """RSI < 30인 데드크로스 상황에서 SELL을 내지 않는다."""
        strategy = make_strategy()
        features = make_features(dead_cross=True, oversold=True, rsi_val=20.0)
        signal = strategy._evaluate(features)
        assert signal is None

    def test_시그널_강도_0_이상_1_이하(self):
        strategy = make_strategy()
        features = make_features(golden_cross=True, sma_short=20200.0, sma_long=20000.0)
        signal = strategy._evaluate(features)
        if signal is not None:
            assert 0.0 <= signal.strength <= 1.0

    def test_시그널_강도_SMA_이격도_비례(self):
        """SMA 이격이 클수록 strength도 크다."""
        strategy1 = make_strategy()
        features_small = make_features(golden_cross=True, sma_short=20100.0, sma_long=20000.0)
        s1 = strategy1._evaluate(features_small)

        strategy2 = make_strategy()
        features_large = make_features(golden_cross=True, sma_short=21000.0, sma_long=20000.0)
        s2 = strategy2._evaluate(features_large)

        assert s1 is not None and s2 is not None
        assert s2.strength > s1.strength

    def test_시그널_metadata에_지표값_포함(self):
        strategy = make_strategy()
        features = make_features(golden_cross=True, sma_short=20500.0,
                                  sma_long=20000.0, rsi_val=55.0)
        signal = strategy._evaluate(features)
        assert signal is not None
        assert "sma_short" in signal.metadata
        assert "sma_long" in signal.metadata
        assert "rsi" in signal.metadata
        assert signal.metadata["sma_short"] == 20500.0
        assert signal.metadata["rsi"] == 55.0

    def test_골든_데드_크로스_전환(self):
        """골든 → 데드 전환 시 SELL 시그널 발행."""
        strategy = make_strategy()

        # 먼저 골든크로스 상태 설정
        strategy._evaluate(make_features(golden_cross=True))

        # 데드크로스로 전환
        dead = make_features(dead_cross=True, oversold=False,
                              sma_short=19000.0, sma_long=20000.0)
        signal = strategy._evaluate(dead)
        assert signal is not None
        assert signal.signal_type == SignalType.SELL

    def test_prev_cross_상태_리셋_후_재발생(self):
        """새 인스턴스는 _prev_cross가 초기화되어 동일 상태에서도 시그널 발행."""
        features = make_features(golden_cross=True)

        strategy1 = make_strategy()
        s1 = strategy1._evaluate(features)
        assert s1 is not None  # 새 인스턴스: prev=none → 발행

        strategy2 = make_strategy()
        s2 = strategy2._evaluate(features)
        assert s2 is not None  # 또 다른 새 인스턴스: prev=none → 발행

    def test_크로스_없으면_None(self):
        """골든/데드 모두 아닌 상태에서는 항상 None."""
        strategy = make_strategy()
        features = make_features(golden_cross=False, dead_cross=False)
        assert strategy._evaluate(features) is None

    def test_strategy_name_시그널에_포함(self):
        strategy = make_strategy()
        signal = strategy._evaluate(make_features(golden_cross=True))
        assert signal is not None
        assert signal.strategy_name == "test_ma"
