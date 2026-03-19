from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from broker.base import AbstractBroker, OrderRequest, OrderSide, OrderType
from core.event import Event, EventBus, EventType
from db.models.order import OrderModel
from db.session import get_session
from strategy.base import SignalType

if TYPE_CHECKING:
    from execution.risk import RiskManager

logger = logging.getLogger(__name__)


class OrderManager:
    """
    전략 시그널 → 주문 실행 오케스트레이터.

    흐름:
        SIGNAL_GENERATED 이벤트 수신
        → RiskManager 검증
        → Broker 주문 제출
        → DB 저장
        → ORDER_FILLED / ORDER_FAILED 이벤트 발행
    """

    def __init__(
        self,
        broker: AbstractBroker,
        risk: "RiskManager",
        event_bus: EventBus,
        default_order_krw: Decimal = Decimal("100000"),
    ) -> None:
        self._broker = broker
        self._risk = risk
        self._event_bus = event_bus
        self._default_order_krw = default_order_krw

    async def on_signal(self, event: Event) -> None:
        """SIGNAL_GENERATED 이벤트 핸들러."""
        payload = event.payload
        symbol: str = payload["symbol"]
        signal: str = payload["signal"]
        price = Decimal(str(payload["price"]))
        strategy_name: str = payload.get("strategy", "unknown")

        if signal == SignalType.HOLD.value:
            return

        side = OrderSide.BUY if signal == SignalType.BUY.value else OrderSide.SELL

        # 수량 계산: 시장가 매수는 KRW 금액, 매도는 전량
        if side == OrderSide.BUY:
            quantity = self._default_order_krw / price
        else:
            quantity = self._default_order_krw / price  # 실제로는 보유 수량 참조

        quantity = quantity.quantize(Decimal("0.00000001"))

        # 리스크 검증
        risk_result = await self._risk.check(
            symbol=symbol, side=side.value, quantity=quantity, price=price
        )
        if not risk_result.approved:
            logger.warning("주문 리스크 거부: %s | %s", symbol, risk_result.reason)
            return

        # 조정된 수량 적용
        if risk_result.adjusted_qty is not None:
            quantity = risk_result.adjusted_qty

        request = OrderRequest(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
        )

        await self._submit(request, strategy_name, price)

    async def _submit(
        self, request: OrderRequest, strategy_name: str, current_price: Decimal
    ) -> None:
        logger.info(
            "주문 제출: %s %s %s @ ~%.2f",
            request.side.value, request.symbol, request.quantity, current_price
        )

        # DB에 주문 기록 (제출 전)
        order_model = OrderModel(
            order_id="pending",
            symbol=request.symbol,
            side=request.side.value,
            order_type=request.order_type.value,
            quantity=request.quantity,
            price=request.price,
            status="pending",
            strategy_name=strategy_name,
        )

        try:
            result = await self._broker.place_order(request)
            order_model.order_id = result.order_id
            order_model.status = result.status
            order_model.executed_qty = result.executed_qty
            order_model.executed_price = result.executed_price

            async with get_session() as session:
                session.add(order_model)

            logger.info(
                "주문 완료: id=%s status=%s qty=%s price=%s",
                result.order_id, result.status, result.executed_qty, result.executed_price
            )

            await self._event_bus.publish(
                Event(
                    type=EventType.ORDER_FILLED,
                    payload={
                        "order_id": result.order_id,
                        "symbol": result.symbol,
                        "side": result.side.value,
                        "quantity": str(result.executed_qty),
                        "price": str(result.executed_price),
                        "strategy": strategy_name,
                    },
                )
            )

        except Exception as e:
            order_model.order_id = order_model.order_id or "error"
            order_model.status = "failed"
            order_model.error_msg = str(e)

            async with get_session() as session:
                session.add(order_model)

            logger.exception("주문 실패: %s %s", request.symbol, request.side.value)

            await self._event_bus.publish(
                Event(
                    type=EventType.ORDER_FAILED,
                    payload={
                        "symbol": request.symbol,
                        "side": request.side.value,
                        "error": str(e),
                    },
                )
            )
