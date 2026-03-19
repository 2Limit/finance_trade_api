"""
StrategyOptimizer: Grid Search 기반 파라미터 최적화

설계 원칙:
    - DB / 네트워크 의존성 없음 (순수 in-memory)
    - BacktestRunner 를 재사용하여 각 파라미터 조합 평가
    - 최적화 지표 선택 가능 (total_return_pct / win_rate / profit_factor / sharpe)

사용 예:
    optimizer = StrategyOptimizer(
        strategy_cls=MACrossoverStrategy,
        strategy_name="ma",
        symbols=["KRW-BTC"],
        candles={"KRW-BTC": btc_candles},
        param_grid={
            "short_window": [3, 5, 10],
            "long_window":  [15, 20, 30],
            "rsi_period":   [14],
        },
        metric="total_return_pct",
    )
    best = optimizer.run()
    print(best.best_params, best.best_score)
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backtest.runner import BacktestResult, BacktestRunner
from market.snapshot import Candle

logger = logging.getLogger(__name__)

SUPPORTED_METRICS = {"total_return_pct", "win_rate", "profit_factor"}


@dataclass
class OptimizationResult:
    """Grid Search 최적화 결과."""
    best_params: dict[str, Any]
    best_score: float
    metric: str
    all_results: list[dict[str, Any]] = field(default_factory=list)

    def print_summary(self, top_n: int = 5) -> None:
        print(f"\n{'='*55}")
        print(f"  파라미터 최적화 결과  (metric={self.metric})")
        print(f"{'='*55}")
        sorted_results = sorted(
            self.all_results, key=lambda x: x["score"], reverse=True
        )
        for i, row in enumerate(sorted_results[:top_n], 1):
            print(
                f"  [{i}] score={row['score']:.4f}  "
                f"params={row['params']}"
            )
        print(f"{'─'*55}")
        print(f"  최적 파라미터 : {self.best_params}")
        print(f"  최적 점수     : {self.best_score:.4f}")
        print(f"{'='*55}\n")


class StrategyOptimizer:
    """
    단일 심볼 Grid Search 최적화.

    param_grid 의 모든 조합을 BacktestRunner 로 평가하여 최적 파라미터를 반환.
    """

    def __init__(
        self,
        strategy_cls,
        strategy_name: str,
        symbol: str,
        candles: list[Candle],
        param_grid: dict[str, list[Any]],
        metric: str = "total_return_pct",
        initial_balance: Decimal = Decimal("1_000_000"),
        fee_rate: Decimal = Decimal("0.0005"),
        order_ratio: float = 0.3,
    ) -> None:
        if metric not in SUPPORTED_METRICS:
            raise ValueError(
                f"지원하지 않는 metric: {metric}. "
                f"사용 가능: {SUPPORTED_METRICS}"
            )
        self._cls = strategy_cls
        self._name = strategy_name
        self._symbol = symbol
        self._candles = candles
        self._param_grid = param_grid
        self._metric = metric
        self._initial_balance = initial_balance
        self._fee_rate = fee_rate
        self._order_ratio = order_ratio

    def _all_combinations(self) -> list[dict[str, Any]]:
        keys = list(self._param_grid.keys())
        values = [self._param_grid[k] for k in keys]
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    def _score(self, result: BacktestResult) -> float:
        if self._metric == "total_return_pct":
            return result.total_return_pct
        if self._metric == "win_rate":
            return result.win_rate
        if self._metric == "profit_factor":
            pf = result.profit_factor
            return pf if pf != float("inf") else 999.0
        return 0.0

    def run(self) -> OptimizationResult:
        combos = self._all_combinations()
        logger.info(
            "Grid Search 시작: %d 조합 (metric=%s)", len(combos), self._metric
        )

        all_results: list[dict[str, Any]] = []
        best_score = float("-inf")
        best_params: dict[str, Any] = {}

        for params in combos:
            strategy = self._cls(
                name=self._name,
                symbols=[self._symbol],
                params=params,
            )
            runner = BacktestRunner(
                strategy=strategy,
                candles=self._candles,
                symbol=self._symbol,
                initial_balance=self._initial_balance,
                fee_rate=self._fee_rate,
                order_ratio=self._order_ratio,
            )
            result = runner.run()
            score = self._score(result)

            all_results.append({"params": params, "score": score, "result": result})

            if score > best_score:
                best_score = score
                best_params = params

            logger.debug("params=%s  score=%.4f", params, score)

        logger.info("Grid Search 완료. 최적 params=%s score=%.4f", best_params, best_score)

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            metric=self._metric,
            all_results=all_results,
        )
