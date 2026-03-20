"""
BacktestRunner: 히스토리컬 데이터 기반 전략 백테스트

설계 원칙:
    - DB / 네트워크 의존성 없음 (순수 in-memory)
    - 실제 트레이딩과 동일한 FeatureBuilder + 전략 평가 로직 사용
    - 시뮬레이션 포트폴리오로 수익/손실/지표 계산

흐름:
    list[Candle] → (캔들 1개씩 주입) → MarketSnapshot
                → FeatureBuilder.build()
                → strategy._evaluate()     ← DB 저장 없이 시그널만
                → SimulatedPortfolio.execute()
                → BacktestResult
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from data.processor.feature_builder import FeatureBuilder
from market.snapshot import Candle, MarketSnapshot
from strategy.base import Signal, SignalType

if TYPE_CHECKING:
    from strategy.impl.ma_crossover import MACrossoverStrategy


# ── 도메인 모델 ────────────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    """백테스트 내 단일 거래 기록."""
    symbol: str
    side: str                    # buy | sell
    price: Decimal
    quantity: Decimal
    fee: Decimal
    timestamp: datetime
    pnl: Decimal = Decimal("0")  # sell 시 실현 손익 (fee 포함)
    signal_strength: float = 0.0

    @property
    def total_value(self) -> Decimal:
        return self.quantity * self.price


@dataclass
class BacktestResult:
    """백테스트 최종 결과."""
    symbol: str
    strategy_name: str
    period_start: datetime
    period_end: datetime
    initial_balance: Decimal
    final_balance: Decimal
    trades: list[BacktestTrade] = field(default_factory=list)

    # ── 계산 지표 ──────────────────────────────────────────────────────────────

    @property
    def total_return(self) -> Decimal:
        return self.final_balance - self.initial_balance

    @property
    def total_return_pct(self) -> float:
        if self.initial_balance == 0:
            return 0.0
        return float((self.total_return / self.initial_balance) * 100)

    @property
    def buy_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.side == "buy"]

    @property
    def sell_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.side == "sell"]

    @property
    def total_fee(self) -> Decimal:
        return sum(t.fee for t in self.trades)

    @property
    def winning_trades(self) -> list[BacktestTrade]:
        return [t for t in self.sell_trades if t.pnl > 0]

    @property
    def losing_trades(self) -> list[BacktestTrade]:
        return [t for t in self.sell_trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        if not self.sell_trades:
            return 0.0
        return len(self.winning_trades) / len(self.sell_trades)

    @property
    def avg_profit(self) -> Decimal:
        if not self.winning_trades:
            return Decimal("0")
        return sum(t.pnl for t in self.winning_trades) / len(self.winning_trades)

    @property
    def avg_loss(self) -> Decimal:
        if not self.losing_trades:
            return Decimal("0")
        return sum(t.pnl for t in self.losing_trades) / len(self.losing_trades)

    @property
    def profit_factor(self) -> float:
        """총 이익 / 총 손실 (> 1이면 수익)."""
        total_profit = sum(t.pnl for t in self.winning_trades)
        total_loss = abs(sum(t.pnl for t in self.losing_trades))
        if total_loss == 0:
            return float("inf") if total_profit > 0 else 0.0
        return float(total_profit / total_loss)

    def print_summary(self) -> None:
        bar = "─" * 50
        print(f"\n{'='*50}")
        print(f"  백테스트 결과: {self.strategy_name} / {self.symbol}")
        print(f"{'='*50}")
        print(f"  기간       : {self.period_start:%Y-%m-%d} ~ {self.period_end:%Y-%m-%d}")
        print(f"  초기 자본  : {self.initial_balance:>15,.0f} KRW")
        print(f"  최종 자본  : {self.final_balance:>15,.0f} KRW")
        sign = "+" if self.total_return >= 0 else ""
        print(f"  수익       : {sign}{self.total_return:>14,.0f} KRW  ({sign}{self.total_return_pct:.2f}%)")
        print(f"  총 수수료  : {self.total_fee:>15,.2f} KRW")
        print(bar)
        print(f"  총 거래    : {len(self.trades):>6}회  (매수 {len(self.buy_trades)} / 매도 {len(self.sell_trades)})")
        print(f"  승률       : {self.win_rate:>6.1%}  ({len(self.winning_trades)}승 {len(self.losing_trades)}패)")
        print(f"  평균 수익  : {float(self.avg_profit):>10,.2f} KRW")
        print(f"  평균 손실  : {float(self.avg_loss):>10,.2f} KRW")
        print(f"  손익비     : {self.profit_factor:>6.2f}")
        print(f"{'='*50}\n")


# ── 시뮬레이션 포트폴리오 ───────────────────────────────────────────────────────

@dataclass
class _Holding:
    quantity: Decimal
    avg_price: Decimal


class SimulatedPortfolio:
    """
    백테스트용 페이퍼 트레이딩 포트폴리오.

    - 수수료 적용 (기본 0.05% = Upbit 기준)
    - 잔고 부족 시 가용 잔고 내에서 수량 자동 조정
    - 보유 수량 초과 매도 방지
    """

    DEFAULT_FEE_RATE = Decimal("0.0005")  # 0.05%

    def __init__(
        self,
        initial_balance: Decimal,
        fee_rate: Decimal = DEFAULT_FEE_RATE,
        order_ratio: float = 0.3,          # 가용 잔고 중 주문 비중
    ) -> None:
        self._balance = initial_balance
        self._fee_rate = fee_rate
        self._order_ratio = Decimal(str(order_ratio))
        self._holdings: dict[str, _Holding] = {}
        self._equity_history: list[Decimal] = [initial_balance]

    @property
    def balance(self) -> Decimal:
        return self._balance

    def get_holding(self, symbol: str) -> _Holding | None:
        return self._holdings.get(symbol)

    def total_equity(self, current_prices: dict[str, Decimal]) -> Decimal:
        holdings_value = sum(
            h.quantity * current_prices.get(sym, h.avg_price)
            for sym, h in self._holdings.items()
        )
        return self._balance + holdings_value

    def buy(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime,
        strength: float = 1.0,
    ) -> BacktestTrade | None:
        order_krw = self._balance * self._order_ratio
        if order_krw <= Decimal("1000"):  # 최소 주문금액
            return None

        quantity = (order_krw / price).quantize(Decimal("0.00000001"))
        fee = (quantity * price * self._fee_rate).quantize(Decimal("0.01"))
        total_cost = quantity * price + fee

        if total_cost > self._balance:
            # 수수료 포함 재계산
            quantity = (
                (self._balance / (price * (1 + self._fee_rate)))
            ).quantize(Decimal("0.00000001"))
            fee = (quantity * price * self._fee_rate).quantize(Decimal("0.01"))
            total_cost = quantity * price + fee

        if quantity <= 0:
            return None

        self._balance -= total_cost

        # 보유 포지션 업데이트 (평균단가)
        holding = self._holdings.get(symbol)
        if holding:
            total_qty = holding.quantity + quantity
            holding.avg_price = (
                (holding.quantity * holding.avg_price + quantity * price) / total_qty
            )
            holding.quantity = total_qty
        else:
            self._holdings[symbol] = _Holding(quantity=quantity, avg_price=price)

        return BacktestTrade(
            symbol=symbol,
            side="buy",
            price=price,
            quantity=quantity,
            fee=fee,
            timestamp=timestamp,
            signal_strength=strength,
        )

    def sell(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime,
        strength: float = 1.0,
    ) -> BacktestTrade | None:
        holding = self._holdings.get(symbol)
        if not holding or holding.quantity <= 0:
            return None

        quantity = holding.quantity
        gross = quantity * price
        fee = (gross * self._fee_rate).quantize(Decimal("0.01"))
        net = gross - fee

        # 손익 계산 (매도 수익 - 매수 원가 - 수수료)
        cost_basis = holding.avg_price * quantity
        buy_fee = (cost_basis * self._fee_rate).quantize(Decimal("0.01"))
        pnl = net - cost_basis - buy_fee

        self._balance += net
        del self._holdings[symbol]

        return BacktestTrade(
            symbol=symbol,
            side="sell",
            price=price,
            quantity=quantity,
            fee=fee,
            timestamp=timestamp,
            pnl=pnl,
            signal_strength=strength,
        )

    def record_equity(self, current_prices: dict[str, Decimal]) -> None:
        self._equity_history.append(self.total_equity(current_prices))

    def max_drawdown(self) -> float:
        """최대 낙폭 계산 (0~1)."""
        if len(self._equity_history) < 2:
            return 0.0
        peak = self._equity_history[0]
        max_dd = 0.0
        for equity in self._equity_history:
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = float((peak - equity) / peak)
                max_dd = max(max_dd, dd)
        return max_dd

    def sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """연간화 샤프 비율 (daily 기준)."""
        if len(self._equity_history) < 2:
            return 0.0
        returns = [
            float((self._equity_history[i] - self._equity_history[i - 1])
                  / self._equity_history[i - 1])
            for i in range(1, len(self._equity_history))
            if self._equity_history[i - 1] > 0
        ]
        if not returns:
            return 0.0
        n = len(returns)
        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / n
        std_r = math.sqrt(variance)
        if std_r == 0:
            return 0.0
        daily_rf = risk_free_rate / 252
        return (mean_r - daily_rf) / std_r * math.sqrt(252)


# ── 백테스트 러너 ──────────────────────────────────────────────────────────────

class BacktestRunner:
    """
    전략을 히스토리컬 캔들 데이터로 백테스트.

    사용 예:
        candles = load_candles(...)   # list[Candle]
        strategy = MACrossoverStrategy("ma_crossover", ["KRW-BTC"], {...})

        runner = BacktestRunner(
            strategy=strategy,
            candles=candles,
            symbol="KRW-BTC",
            initial_balance=Decimal("1_000_000"),
        )
        result = runner.run()
        result.print_summary()
    """

    def __init__(
        self,
        strategy,
        symbol: str,
        initial_balance: Decimal = Decimal("1_000_000"),
        fee_rate: Decimal = SimulatedPortfolio.DEFAULT_FEE_RATE,
        order_ratio: float = 0.3,
        candles: list[Candle] | None = None,
    ) -> None:
        if candles is not None and len(candles) == 0:
            raise ValueError("candles는 비어있을 수 없습니다.")
        self._strategy = strategy
        self._candles: list[Candle] = sorted(candles, key=lambda c: c.timestamp) if candles else []
        self._symbol = symbol
        self._initial_balance = initial_balance
        self._fee_rate = fee_rate
        self._order_ratio = order_ratio

    def run(self, candles: list[Candle] | None = None) -> BacktestResult:
        """캔들을 순서대로 주입하며 전략을 실행. DB 의존성 없음."""
        if candles is not None:
            self._candles = sorted(candles, key=lambda c: c.timestamp)
        if not self._candles:
            raise ValueError("candles는 비어있을 수 없습니다.")

        snapshot = MarketSnapshot()
        portfolio = SimulatedPortfolio(
            initial_balance=self._initial_balance,
            fee_rate=self._fee_rate,
            order_ratio=self._order_ratio,
        )

        # 전략에 snapshot 주입 (MACrossoverStrategy.set_snapshot 활용)
        if hasattr(self._strategy, "set_snapshot"):
            self._strategy.set_snapshot(snapshot)

        # MLStrategy: 학습이 안 된 경우 앞 70% 캔들로 자동 학습 (데이터 누출 방지)
        if hasattr(self._strategy, "is_trained") and not self._strategy.is_trained():
            if hasattr(self._strategy, "train"):
                train_end = max(1, int(len(self._candles) * 0.7))
                self._strategy.train(self._candles[:train_end])

        # FeatureBuilder: 전략이 필요한 만큼 충분한 캔들 히스토리 확보
        req_candles = self._strategy.required_candles()
        feature_builder = FeatureBuilder(
            snapshot=snapshot,
            short_window=self._strategy.params.get("short_window", 5),
            long_window=self._strategy.params.get("long_window", 20),
            rsi_period=self._strategy.params.get("rsi_period", 14),
            snapshot_limit=req_candles,
        )

        trades: list[BacktestTrade] = []

        for candle in self._candles:
            snapshot.update_candle(candle)
            current_prices = {self._symbol: candle.close}
            portfolio.record_equity(current_prices)

            features = feature_builder.build(self._symbol)
            if features is None:
                continue  # 데이터 부족 (warm-up 구간)

            # DB 저장 없이 순수 시그널 평가 (_evaluate는 DB 비의존)
            signal: Signal | None = self._strategy._evaluate(features)
            if signal is None:
                continue

            trade: BacktestTrade | None = None
            if signal.signal_type == SignalType.BUY:
                trade = portfolio.buy(
                    symbol=self._symbol,
                    price=candle.close,
                    timestamp=candle.timestamp,
                    strength=signal.strength,
                )
            elif signal.signal_type == SignalType.SELL:
                trade = portfolio.sell(
                    symbol=self._symbol,
                    price=candle.close,
                    timestamp=candle.timestamp,
                    strength=signal.strength,
                )

            if trade:
                trades.append(trade)

        # 미청산 포지션은 마지막 가격으로 청산
        last_candle = self._candles[-1]
        final_sell = portfolio.sell(
            symbol=self._symbol,
            price=last_candle.close,
            timestamp=last_candle.timestamp,
        )
        if final_sell:
            final_sell.side = "sell(force_close)"
            trades.append(final_sell)

        return BacktestResult(
            symbol=self._symbol,
            strategy_name=self._strategy.name,
            period_start=self._candles[0].timestamp,
            period_end=self._candles[-1].timestamp,
            initial_balance=self._initial_balance,
            final_balance=portfolio.balance,
            trades=trades,
        )

    @staticmethod
    def from_prices(
        strategy: "MACrossoverStrategy",
        symbol: str,
        prices: list[Decimal],
        initial_balance: Decimal = Decimal("1_000_000"),
        base_time: datetime | None = None,
        **kwargs: Any,
    ) -> "BacktestRunner":
        """
        가격 리스트로 간단히 백테스트 생성 (테스트/데모용).

        prices: 종가 리스트 (시간 순)
        """
        from datetime import timedelta
        start = base_time or datetime(2024, 1, 1, tzinfo=timezone.utc)
        candles = [
            Candle(
                symbol=symbol,
                interval="1m",
                open=p,
                high=p * Decimal("1.01"),
                low=p * Decimal("0.99"),
                close=p,
                volume=Decimal("1.0"),
                timestamp=start + timedelta(minutes=i),
            )
            for i, p in enumerate(prices)
        ]
        return BacktestRunner(
            strategy=strategy,
            candles=candles,
            symbol=symbol,
            initial_balance=initial_balance,
            **kwargs,
        )


# ── 멀티 심볼 백테스트 ──────────────────────────────────────────────────────────

@dataclass
class MultiSymbolBacktestResult:
    """멀티 심볼 백테스트 집계 결과."""
    strategy_name: str
    results: dict[str, BacktestResult]   # symbol → result
    initial_balance: Decimal
    final_balance: Decimal

    @property
    def total_return(self) -> Decimal:
        return self.final_balance - self.initial_balance

    @property
    def total_return_pct(self) -> float:
        if self.initial_balance == 0:
            return 0.0
        return float(self.total_return / self.initial_balance * 100)

    @property
    def avg_win_rate(self) -> float:
        rates = [r.win_rate for r in self.results.values() if r.sell_trades]
        return sum(rates) / len(rates) if rates else 0.0

    @property
    def avg_profit_factor(self) -> float:
        factors = [r.profit_factor for r in self.results.values() if r.sell_trades]
        finite = [f for f in factors if f != float("inf")]
        return sum(finite) / len(finite) if finite else 0.0

    def print_summary(self) -> None:
        print(f"\n{'='*55}")
        print(f"  멀티 심볼 백테스트: {self.strategy_name}")
        print(f"{'='*55}")
        for symbol, result in self.results.items():
            sign = "+" if result.total_return >= 0 else ""
            print(
                f"  {symbol:<15} "
                f"{sign}{result.total_return_pct:+.2f}%  "
                f"승률={result.win_rate:.1%}  "
                f"거래={len(result.sell_trades)}"
            )
        print(f"{'─'*55}")
        sign = "+" if self.total_return >= 0 else ""
        print(f"  합계 수익     : {sign}{self.total_return_pct:.2f}%")
        print(f"  평균 승률     : {self.avg_win_rate:.1%}")
        print(f"  평균 손익비   : {self.avg_profit_factor:.2f}")
        print(f"{'='*55}\n")


class MultiSymbolBacktestRunner:
    """
    여러 심볼을 독립적으로 백테스트하고 결과를 집계.

    각 심볼은 별도의 SimulatedPortfolio 로 실행 (자본 분리).
    심볼당 initial_balance_per_symbol 을 투자한다고 가정.

    사용 예:
        price_data = {
            "KRW-BTC": btc_prices,
            "KRW-ETH": eth_prices,
        }
        runner = MultiSymbolBacktestRunner(
            strategy_factory=lambda sym: MACrossoverStrategy("ma", [sym], params),
            price_data=price_data,
            initial_balance=Decimal("2_000_000"),
        )
        result = runner.run()
        result.print_summary()
    """

    def __init__(
        self,
        strategy_factory,
        price_data: dict[str, list[Decimal]],
        initial_balance: Decimal = Decimal("1_000_000"),
        fee_rate: Decimal = SimulatedPortfolio.DEFAULT_FEE_RATE,
        order_ratio: float = 0.3,
        base_time: datetime | None = None,
    ) -> None:
        if not price_data:
            raise ValueError("price_data 는 비어있을 수 없습니다.")
        self._factory = strategy_factory
        self._price_data = price_data
        self._initial_balance = initial_balance
        self._fee_rate = fee_rate
        self._order_ratio = order_ratio
        self._base_time = base_time

    def run(self) -> MultiSymbolBacktestResult:
        symbols = list(self._price_data.keys())
        balance_per_sym = self._initial_balance / Decimal(str(len(symbols)))

        results: dict[str, BacktestResult] = {}
        total_final = Decimal("0")

        for symbol in symbols:
            strategy = self._factory(symbol)
            runner = BacktestRunner.from_prices(
                strategy=strategy,
                symbol=symbol,
                prices=self._price_data[symbol],
                initial_balance=balance_per_sym,
                fee_rate=self._fee_rate,
                order_ratio=self._order_ratio,
                base_time=self._base_time,
            )
            result = runner.run()
            results[symbol] = result
            total_final += result.final_balance

        return MultiSymbolBacktestResult(
            strategy_name=results[symbols[0]].strategy_name if results else "unknown",
            results=results,
            initial_balance=self._initial_balance,
            final_balance=total_final,
        )
