"""
StopLossMonitor: 손절매 / 익절매 자동 실행

동작 방식:
    PRICE_UPDATED 이벤트마다 모든 보유 포지션의 미실현 수익률을 계산.
    - 수익률 <= -stop_loss_pct  → 자동 손절 (SELL 시그널 발행)
    - 수익률 >= take_profit_pct → 자동 익절 (SELL 시그널 발행)

설계 원칙:
    - 전략 시그널과 완전 독립: MA 크로스 등 전략이 신호를 못 잡아도 동작
    - 중복 발행 방지: 심볼별 발동 후 포지션 청산까지 재발동 없음
    - 실제 주문은 OrderManager.on_signal() 이 처리 (관심사 분리)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from core.event import Event, EventBus, EventType
from strategy.base import SignalType

if TYPE_CHECKING:
    from core.event import Event
    from portfolio.position import PositionManager

logger = logging.getLogger(__name__)


@dataclass
class StopLossConfig:
    stop_loss_pct: float = 0.05      # -5% 이하 자동 손절
    take_profit_pct: float = 0.10    # +10% 이상 자동 익절
    strategy_name: str = "stop_loss_monitor"


class StopLossMonitor:
    """
    PRICE_UPDATED 이벤트마다 포지션 수익률을 체크하여
    손절/익절 조건 충족 시 SIGNAL_GENERATED 이벤트를 발행한다.
    """

    def __init__(
        self,
        config: StopLossConfig,
        position_manager: "PositionManager",
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._positions = position_manager
        self._event_bus = event_bus
        # 이미 발동된 심볼은 포지션이 청산될 때까지 재발동 방지
        self._triggered: set[str] = set()

    async def on_price_updated(self, event: "Event") -> None:
        """PRICE_UPDATED 이벤트 핸들러."""
        payload = event.payload
        symbol: str = payload.get("symbol", "")
        price_raw = payload.get("price")
        if not symbol or price_raw is None:
            return

        price = Decimal(str(price_raw))
        position = self._positions.get_position(symbol)

        if not position.is_open:
            # 포지션 청산 → 발동 이력 제거 (다음 진입 시 재활성화)
            self._triggered.discard(symbol)
            return

        if symbol in self._triggered:
            return

        pnl = position.unrealized_pnl(price)
        cost = position.avg_price * position.quantity
        if cost == 0:
            return

        pnl_pct = float(pnl / cost)

        if pnl_pct <= -self._config.stop_loss_pct:
            reason = f"손절 발동: {pnl_pct:.2%} (한도 -{self._config.stop_loss_pct:.0%})"
            logger.warning("[StopLoss] %s | %s", symbol, reason)
            await self._publish_sell(symbol, price, reason)

        elif pnl_pct >= self._config.take_profit_pct:
            reason = f"익절 발동: {pnl_pct:.2%} (목표 +{self._config.take_profit_pct:.0%})"
            logger.info("[TakeProfit] %s | %s", symbol, reason)
            await self._publish_sell(symbol, price, reason)

    async def _publish_sell(self, symbol: str, price: Decimal, reason: str) -> None:
        self._triggered.add(symbol)
        await self._event_bus.publish(
            Event(
                type=EventType.SIGNAL_GENERATED,
                payload={
                    "symbol": symbol,
                    "signal": SignalType.SELL.value,
                    "price": str(price),
                    "strength": 1.0,
                    "strategy": self._config.strategy_name,
                    "reason": reason,
                },
            )
        )
