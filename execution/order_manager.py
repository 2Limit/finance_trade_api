from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
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
        → 쿨다운 검사 (중복 주문 방지)
        → RiskManager 검증
        → Broker 주문 제출
        → DB 저장
        → ORDER_FILLED / ORDER_FAILED 이벤트 발행
    """

    ORDER_COOLDOWN_SEC: int = 60  # 심볼별 주문 쿨다운 (초)

    def __init__(
        self,
        broker: AbstractBroker,
        risk: "RiskManager",
        event_bus: EventBus,
        default_order_krw: Decimal = Decimal("100000"),
        order_cooldown_sec: int | None = None,
        dca_split_count: int = 1,
        dca_interval_sec: float = 5.0,
    ) -> None:
        self._broker = broker
        self._risk = risk
        self._event_bus = event_bus
        self._default_order_krw = default_order_krw
        self._cooldown_sec = order_cooldown_sec if order_cooldown_sec is not None else self.ORDER_COOLDOWN_SEC
        self._last_order_time: dict[str, datetime] = {}
        # DCA 설정
        self._dca_split_count = max(1, dca_split_count)
        self._dca_interval_sec = dca_interval_sec

    async def on_signal(self, event: Event) -> None:
        """SIGNAL_GENERATED 이벤트 핸들러."""
        payload = event.payload
        symbol: str = payload["symbol"]
        signal: str = payload["signal"]
        price = Decimal(str(payload["price"]))
        strategy_name: str = payload.get("strategy", "unknown")

        if signal == SignalType.HOLD.value:
            return

        # 쿨다운 검사: 동일 심볼 연속 주문 방지
        now = datetime.now(timezone.utc)
        last = self._last_order_time.get(symbol)
        if last and (now - last).total_seconds() < self._cooldown_sec:
            logger.info("쿨다운 중 — 중복 주문 스킵: %s (%.1fs 남음)", symbol,
                        self._cooldown_sec - (now - last).total_seconds())
            return
        self._last_order_time[symbol] = now

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

        if self._dca_split_count > 1 and side == OrderSide.BUY:
            # DCA: 분할 매수 (백그라운드 태스크로 순차 실행)
            split_qty = (quantity / Decimal(self._dca_split_count)).quantize(Decimal("0.00000001"))
            asyncio.create_task(
                self._submit_dca(symbol, side, split_qty, strategy_name, price)
            )
            return

        request = OrderRequest(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
        )

        await self._submit(request, strategy_name, price)

    async def _submit_dca(
        self, symbol: str, side: OrderSide, split_qty: Decimal, strategy_name: str, price: Decimal
    ) -> None:
        """DCA 분할 주문: split_count 회 나누어 interval_sec 간격으로 제출."""
        for i in range(self._dca_split_count):
            if i > 0:
                await asyncio.sleep(self._dca_interval_sec)
            logger.info("DCA %d/%d: %s %s qty=%s", i + 1, self._dca_split_count, side.value, symbol, split_qty)
            request = OrderRequest(
                symbol=symbol, side=side,
                order_type=OrderType.MARKET, quantity=split_qty,
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
