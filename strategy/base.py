"""
AbstractStrategy: 전략 엔진 인터페이스

책임:
    - 틱/캔들 이벤트 수신 (on_tick)
    - 시그널 생성 후 EventBus에 발행
    - 전략별 파라미터 관리

구현체 위치: strategy/impl/
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.event import EventBus, Event


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    strategy_name: str
    symbol: str
    signal_type: SignalType
    strength: float           # 0.0 ~ 1.0 (확신도)
    metadata: dict[str, Any]  # 전략별 추가 정보


class AbstractStrategy(ABC):
    """모든 전략의 기반 클래스."""

    def __init__(self, name: str, symbols: list[str], params: dict[str, Any]) -> None:
        self.name = name
        self.symbols = symbols
        self.params = dict(params)  # 방어적 복사

    @abstractmethod
    async def on_tick(self, event: "Event", bus: "EventBus") -> None:
        """가격 이벤트 수신 시 호출. 시그널 발행은 bus.publish()로."""
        raise NotImplementedError

    @abstractmethod
    def on_candle_closed(self, event: "Event") -> Signal | None:
        """캔들 확정 시 호출. 없으면 None."""
        raise NotImplementedError

    def required_candles(self) -> int:
        """백테스트용 FeatureBuilder가 확보해야 할 최소 캔들 수. 전략마다 override."""
        return 50

    def update_params(self, new_params: dict[str, Any]) -> None:
        """파라미터 실시간 갱신. 내부 상태 재초기화가 필요한 전략은 override."""
        self.params.update(new_params)

    def param_schema(self) -> dict[str, dict]:
        """
        대시보드 표시용 파라미터 스키마.
        반환 형식: { "param_name": {"type": "int"|"float"|"str", "default": ..., "description": "..."} }
        기본 구현은 현재 params에서 타입을 추론.
        """
        schema = {}
        for k, v in self.params.items():
            if isinstance(v, bool):
                t = "bool"
            elif isinstance(v, int):
                t = "int"
            elif isinstance(v, float):
                t = "float"
            else:
                t = "str"
            schema[k] = {"type": t, "default": v, "description": ""}
        return schema
