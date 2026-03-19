"""
StrategyStore: 실행 중인 전략 인스턴스 레지스트리

목적:
    - 대시보드가 실행 중인 전략 목록과 파라미터를 조회/수정할 수 있도록
    - 트레이딩 엔진과 같은 프로세스에서 실행될 때 메모리 공유

사용:
    # main.py / engine
    from strategy.store import strategy_store
    strategy_store.register(my_strategy)

    # dashboard
    from strategy.store import strategy_store
    all_strategies = strategy_store.get_all()
    strategy_store.update_params("ma_crossover", {"short_window": 7})
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategy.base import AbstractStrategy

logger = logging.getLogger(__name__)


class StrategyStore:
    """실행 중인 전략 인스턴스를 이름으로 관리하는 싱글톤 저장소."""

    def __init__(self) -> None:
        self._strategies: dict[str, "AbstractStrategy"] = {}

    def register(self, strategy: "AbstractStrategy") -> None:
        self._strategies[strategy.name] = strategy
        logger.info("StrategyStore: registered '%s'", strategy.name)

    def get(self, name: str) -> "AbstractStrategy | None":
        return self._strategies.get(name)

    def get_all(self) -> list["AbstractStrategy"]:
        return list(self._strategies.values())

    def update_params(self, name: str, new_params: dict) -> bool:
        """전략 파라미터를 실시간 갱신. 반환값: 성공 여부."""
        strategy = self._strategies.get(name)
        if strategy is None:
            return False
        strategy.update_params(new_params)
        logger.info("StrategyStore: updated params for '%s': %s", name, new_params)
        return True

    def to_dict_list(self) -> list[dict]:
        """대시보드 직렬화용."""
        result = []
        for s in self._strategies.values():
            result.append({
                "name": s.name,
                "class": type(s).__name__,
                "symbols": s.symbols,
                "params": s.params,
                "param_schema": s.param_schema(),
            })
        return result


# 프로세스 전역 싱글톤
strategy_store = StrategyStore()
