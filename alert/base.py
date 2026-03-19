"""
AbstractAlert: 알림 발송 인터페이스

책임:
    - 알림 채널 추상화 (Discord / Slack / Telegram 등)
    - 이벤트 타입별 메시지 포맷 정의

구현체:
    - alert/discord.py (DiscordAlert)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.event import Event


class AbstractAlert(ABC):
    """알림 발송 추상 인터페이스."""

    @abstractmethod
    async def send(self, message: str) -> None:
        """원시 메시지 발송."""
        raise NotImplementedError

    async def on_signal(self, event: "Event") -> None:
        """SIGNAL_GENERATED 이벤트 → 메시지 포맷 후 발송."""
        p = event.payload
        msg = (
            f"[{p.get('strategy')}] **{p.get('signal')}** "
            f"`{p.get('symbol')}` @ {p.get('price')}"
        )
        await self.send(msg)

    async def on_order_filled(self, event: "Event") -> None:
        """ORDER_FILLED 이벤트 → 체결 알림."""
        p = event.payload
        msg = (
            f"[체결] {p.get('side').upper()} `{p.get('symbol')}` "
            f"qty={p.get('quantity')} price={p.get('price')}"
        )
        await self.send(msg)

    async def on_risk_triggered(self, event: "Event") -> None:
        """RISK_TRIGGERED 이벤트 → 긴급 알림."""
        msg = f"[RISK] {event.payload.get('reason')}"
        await self.send(msg)
