"""
StrategyRegistry: 전략 등록 및 탐색

책임:
    - 전략 클래스를 이름으로 등록
    - 설정 파일 기반으로 전략 인스턴스 생성
    - TradingEngine에 등록할 전략 목록 반환

사용 예:
    registry = StrategyRegistry()
    registry.register("ma_crossover", MACrossoverStrategy)
    strategy = registry.create("ma_crossover", symbols=["KRW-BTC"], params={...})
"""
from __future__ import annotations

import logging
from typing import Any, Type

from strategy.base import AbstractStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, Type[AbstractStrategy]] = {}

    def register(self, name: str, cls: Type[AbstractStrategy]) -> None:
        self._registry[name] = cls
        logger.info("Strategy registered: %s", name)

    def create(self, name: str, symbols: list[str], params: dict[str, Any]) -> AbstractStrategy:
        if name not in self._registry:
            raise KeyError(f"Unknown strategy: '{name}'. Available: {list(self._registry)}")
        return self._registry[name](name=name, symbols=symbols, params=params)

    def available(self) -> list[str]:
        return list(self._registry.keys())
