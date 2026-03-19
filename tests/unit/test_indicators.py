"""
data/processor/indicators/ 단위 테스트

검증 항목:
    - sma: 정확한 산술 평균, 데이터 부족 시 None
    - ema: 첫 값, 지수 가중 방향성
    - rsi: 0~100 범위, 상승/하락 시 예상 방향
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from data.processor.indicators.moving_average import ema, sma
from data.processor.indicators.rsi import rsi


class TestSMA:
    def test_기본_계산(self):
        prices = [Decimal(str(i)) for i in range(1, 6)]  # [1,2,3,4,5]
        result = sma(prices, window=5)
        assert result == Decimal("3")

    def test_window보다_데이터_적으면_None(self):
        prices = [Decimal("100"), Decimal("200")]
        assert sma(prices, window=5) is None

    def test_window_1이면_마지막_값(self):
        prices = [Decimal("100"), Decimal("200"), Decimal("300")]
        assert sma(prices, window=1) == Decimal("300")

    def test_마지막_window개만_사용(self):
        prices = [Decimal(str(i * 100)) for i in range(1, 11)]  # 100~1000
        # 마지막 5개: 600, 700, 800, 900, 1000 → 평균 800
        result = sma(prices, window=5)
        assert result == Decimal("800")

    def test_단조_증가_시_short_window가_long_window보다_큼(self):
        prices = make_rising(30)
        short = sma(prices, window=5)
        long_ = sma(prices, window=20)
        assert short is not None and long_ is not None
        assert short > long_

    def test_단조_감소_시_short_window가_long_window보다_작음(self):
        prices = make_falling(30)
        short = sma(prices, window=5)
        long_ = sma(prices, window=20)
        assert short is not None and long_ is not None
        assert short < long_


class TestEMA:
    def test_데이터_부족_시_None(self):
        prices = [Decimal("100")]
        assert ema(prices, window=5) is None

    def test_단일_데이터_window_1(self):
        prices = [Decimal("500")]
        result = ema(prices, window=1)
        assert result is not None

    def test_상승_추세에서_SMA보다_최근_가격에_민감(self):
        """EMA는 SMA보다 최근 가격에 더 민감하게 반응해야 한다."""
        prices = make_rising(30)
        e = ema(prices, window=10)
        s = sma(prices, window=10)
        # 상승 추세에서 EMA > SMA (최근 가격을 더 반영)
        assert e is not None and s is not None
        assert e > s

    def test_window가_같으면_결과_타입이_Decimal(self):
        prices = [Decimal(str(i * 100)) for i in range(1, 21)]
        result = ema(prices, window=10)
        assert isinstance(result, Decimal)


class TestRSI:
    def test_데이터_부족_시_None(self):
        prices = [Decimal("100")] * 5
        assert rsi(prices, period=14) is None

    def test_완전_상승_시_100에_수렴(self):
        prices = make_rising(30)
        result = rsi(prices, period=14)
        assert result is not None
        assert result > Decimal("70")  # 과매수 구간

    def test_완전_하락_시_0에_수렴(self):
        prices = make_falling(30)
        result = rsi(prices, period=14)
        assert result is not None
        assert result < Decimal("30")  # 과매도 구간

    def test_결과_범위가_0_100_사이(self):
        import math
        prices = [
            Decimal(str(round(10000 + 1000 * math.sin(i), 2)))
            for i in range(30)
        ]
        result = rsi(prices, period=14)
        assert result is not None
        assert Decimal("0") <= result <= Decimal("100")

    def test_변화_없는_가격에서_loss가_0이면_100(self):
        """완전 상승(손실 없음) → RS = inf → RSI = 100."""
        prices = [Decimal("100")] * 14 + [Decimal("200")] * 2
        result = rsi(prices, period=14)
        assert result == Decimal("100")


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def make_rising(n: int, start: float = 1000.0, step: float = 100.0) -> list[Decimal]:
    return [Decimal(str(start + i * step)) for i in range(n)]


def make_falling(n: int, start: float = 10000.0, step: float = 100.0) -> list[Decimal]:
    return [Decimal(str(start - i * step)) for i in range(n)]
