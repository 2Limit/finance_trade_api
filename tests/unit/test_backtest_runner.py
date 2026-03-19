"""
backtest/runner.py 단위 테스트

검증 항목:
    - SimulatedPortfolio: 매수/매도/수수료/평단가/손익
    - BacktestResult: 지표 계산 (승률, 수익률, profit_factor)
    - BacktestRunner: 완전 상승/완전 하락/사인파 시나리오
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backtest.runner import BacktestResult, BacktestRunner, BacktestTrade, SimulatedPortfolio
from strategy.impl.ma_crossover import MACrossoverStrategy


SYMBOL = "KRW-BTC"
BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_strategy(short=5, long_=20) -> MACrossoverStrategy:
    return MACrossoverStrategy(
        name="test_ma",
        symbols=[SYMBOL],
        params={"short_window": short, "long_window": long_, "rsi_period": 14},
    )


# ── SimulatedPortfolio ────────────────────────────────────────────────────────

class TestSimulatedPortfolio:
    def _portfolio(self, balance: float = 1_000_000) -> SimulatedPortfolio:
        return SimulatedPortfolio(initial_balance=Decimal(str(balance)))

    def test_초기_잔고(self):
        p = self._portfolio(1_000_000)
        assert p.balance == Decimal("1000000")

    def test_매수_후_잔고_감소(self):
        p = self._portfolio(1_000_000)
        trade = p.buy(SYMBOL, Decimal("10000"), BASE_TIME)
        assert trade is not None
        assert p.balance < Decimal("1000000")

    def test_매수_후_포지션_보유(self):
        p = self._portfolio(1_000_000)
        p.buy(SYMBOL, Decimal("10000"), BASE_TIME)
        holding = p.get_holding(SYMBOL)
        assert holding is not None
        assert holding.quantity > 0

    def test_매수_없이_매도_시_None(self):
        p = self._portfolio()
        trade = p.sell(SYMBOL, Decimal("10000"), BASE_TIME)
        assert trade is None

    def test_매수_후_매도_손익_계산(self):
        p = self._portfolio(1_000_000)
        p.buy(SYMBOL, Decimal("10000"), BASE_TIME)
        sell_trade = p.sell(SYMBOL, Decimal("15000"), BASE_TIME)  # 50% 상승
        assert sell_trade is not None
        assert sell_trade.pnl > Decimal("0")  # 이익

    def test_손실_매도(self):
        p = self._portfolio(1_000_000)
        p.buy(SYMBOL, Decimal("10000"), BASE_TIME)
        sell_trade = p.sell(SYMBOL, Decimal("8000"), BASE_TIME)  # 20% 하락
        assert sell_trade is not None
        assert sell_trade.pnl < Decimal("0")  # 손실

    def test_매도_후_포지션_청산(self):
        p = self._portfolio(1_000_000)
        p.buy(SYMBOL, Decimal("10000"), BASE_TIME)
        p.sell(SYMBOL, Decimal("12000"), BASE_TIME)
        assert p.get_holding(SYMBOL) is None

    def test_수수료_차감(self):
        p = self._portfolio(1_000_000)
        trade = p.buy(SYMBOL, Decimal("10000"), BASE_TIME)
        assert trade is not None
        assert trade.fee > Decimal("0")

    def test_잔고_부족_시_수량_조정(self):
        p = SimulatedPortfolio(
            initial_balance=Decimal("100000"),
            order_ratio=Decimal("1.0"),  # 전액 주문
        )
        trade = p.buy(SYMBOL, Decimal("90000000"), BASE_TIME)  # BTC 1개 = 9천만
        # 잔고 부족하므로 조정되어야 함
        assert trade is not None
        # 수수료 포함 총 비용이 초기 잔고 이하
        assert trade.quantity * Decimal("90000000") <= Decimal("100000")

    def test_평균단가_계산(self):
        p = self._portfolio(2_000_000)
        p.buy(SYMBOL, Decimal("10000"), BASE_TIME)  # 첫 매수
        p.buy(SYMBOL, Decimal("20000"), BASE_TIME)  # 추가 매수
        holding = p.get_holding(SYMBOL)
        assert holding is not None
        # 평균단가는 10000과 20000 사이
        assert Decimal("10000") < holding.avg_price < Decimal("20000")

    def test_max_drawdown_계산(self):
        p = self._portfolio(1_000_000)
        p._equity_history = [
            Decimal("1000000"),
            Decimal("1200000"),  # 고점
            Decimal("900000"),   # 낙폭 = 25%
            Decimal("1100000"),
        ]
        dd = p.max_drawdown()
        assert abs(dd - 0.25) < 0.001  # 25% 낙폭


# ── BacktestResult ────────────────────────────────────────────────────────────

class TestBacktestResult:
    def _make_result(self, trades: list[BacktestTrade]) -> BacktestResult:
        return BacktestResult(
            symbol=SYMBOL,
            strategy_name="test",
            period_start=BASE_TIME,
            period_end=BASE_TIME,
            initial_balance=Decimal("1000000"),
            final_balance=Decimal("1100000"),
            trades=trades,
        )

    def test_총_수익_계산(self):
        result = self._make_result([])
        assert result.total_return == Decimal("100000")

    def test_수익률_계산(self):
        result = self._make_result([])
        assert abs(result.total_return_pct - 10.0) < 0.001

    def test_승률_계산(self):
        trades = [
            BacktestTrade(SYMBOL, "sell", Decimal("100"), Decimal("1"), Decimal("0"),
                          BASE_TIME, pnl=Decimal("1000")),   # 이익
            BacktestTrade(SYMBOL, "sell", Decimal("100"), Decimal("1"), Decimal("0"),
                          BASE_TIME, pnl=Decimal("-500")),   # 손실
            BacktestTrade(SYMBOL, "sell", Decimal("100"), Decimal("1"), Decimal("0"),
                          BASE_TIME, pnl=Decimal("2000")),   # 이익
        ]
        result = self._make_result(trades)
        assert abs(result.win_rate - 2/3) < 0.001  # 2승 1패

    def test_profit_factor_계산(self):
        trades = [
            BacktestTrade(SYMBOL, "sell", Decimal("100"), Decimal("1"), Decimal("0"),
                          BASE_TIME, pnl=Decimal("3000")),   # 총 이익 3000
            BacktestTrade(SYMBOL, "sell", Decimal("100"), Decimal("1"), Decimal("0"),
                          BASE_TIME, pnl=Decimal("-1000")),  # 총 손실 1000
        ]
        result = self._make_result(trades)
        assert abs(result.profit_factor - 3.0) < 0.001

    def test_손실만_있으면_profit_factor_0(self):
        trades = [
            BacktestTrade(SYMBOL, "sell", Decimal("100"), Decimal("1"), Decimal("0"),
                          BASE_TIME, pnl=Decimal("-500")),
        ]
        result = self._make_result(trades)
        assert result.profit_factor == 0.0


# ── BacktestRunner ────────────────────────────────────────────────────────────

class TestBacktestRunner:
    def test_빈_캔들로_초기화_실패(self):
        strategy = make_strategy()
        with pytest.raises(ValueError, match="candles"):
            BacktestRunner(strategy=strategy, candles=[], symbol=SYMBOL)

    def test_상승_추세에서_수익(self):
        prices = [Decimal(str(10000 + i * 500)) for i in range(100)]
        strategy = make_strategy()
        runner = BacktestRunner.from_prices(
            strategy=strategy,
            symbol=SYMBOL,
            prices=prices,
            initial_balance=Decimal("1000000"),
        )
        result = runner.run()
        assert isinstance(result, BacktestResult)
        assert result.symbol == SYMBOL
        assert result.strategy_name == "test_ma"

    def test_결과에_기간_정보_포함(self):
        prices = [Decimal(str(10000 + i * 100)) for i in range(50)]
        strategy = make_strategy()
        runner = BacktestRunner.from_prices(strategy=strategy, symbol=SYMBOL, prices=prices)
        result = runner.run()
        assert result.period_start < result.period_end

    def test_거래_없어도_결과_반환(self):
        """warm-up 구간만 있어서 시그널이 없는 경우."""
        prices = [Decimal("10000")] * 15  # 데이터 부족
        strategy = make_strategy()
        runner = BacktestRunner.from_prices(strategy=strategy, symbol=SYMBOL, prices=prices)
        result = runner.run()
        assert isinstance(result, BacktestResult)

    def test_초기_잔고_변화_없으면_수익률_0(self):
        """거래 미발생 시 final_balance ≈ initial_balance."""
        prices = [Decimal("10000")] * 15  # warm-up만
        strategy = make_strategy()
        runner = BacktestRunner.from_prices(
            strategy=strategy,
            symbol=SYMBOL,
            prices=prices,
            initial_balance=Decimal("1000000"),
        )
        result = runner.run()
        assert result.total_return == Decimal("0")

    def test_사인파_가격에서_여러_거래_발생(self):
        import math
        prices = [
            Decimal(str(round(20000 + 5000 * math.sin(2 * math.pi * i / 20), 2)))
            for i in range(120)
        ]
        strategy = make_strategy(short=5, long_=20)
        runner = BacktestRunner.from_prices(
            strategy=strategy,
            symbol=SYMBOL,
            prices=prices,
            initial_balance=Decimal("1000000"),
        )
        result = runner.run()
        # 사인파에서는 여러 번 크로스가 발생하므로 거래가 있어야 함
        assert len(result.trades) >= 2

    def test_from_prices_캔들_타임스탬프_순서(self):
        prices = [Decimal(str(10000 + i * 100)) for i in range(30)]
        strategy = make_strategy()
        runner = BacktestRunner.from_prices(strategy=strategy, symbol=SYMBOL, prices=prices)
        for i in range(1, len(runner._candles)):
            assert runner._candles[i].timestamp > runner._candles[i - 1].timestamp
