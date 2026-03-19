from __future__ import annotations

import asyncio
import json
import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import websockets
from websockets.exceptions import ConnectionClosed

from core.event import Event, EventBus, EventType
from market.feed import AbstractMarketFeed
from market.snapshot import MarketSnapshot, Tick

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"
RECONNECT_DELAY = 5  # seconds


class UpbitWebSocketFeed(AbstractMarketFeed):
    """
    Upbit WebSocket 실시간 피드.

    수신 데이터:
        - type=ticker: 현재가 (trade_price, trade_volume 등)

    처리 흐름:
        수신 → MarketSnapshot 갱신 → EventBus.publish(PRICE_UPDATED)
    """

    def __init__(
        self,
        symbols: list[str],
        snapshot: MarketSnapshot,
        event_bus: EventBus,
        ws_url: str = UPBIT_WS_URL,
    ) -> None:
        self._symbols = symbols
        self._snapshot = snapshot
        self._event_bus = event_bus
        self._ws_url = ws_url
        self._running = False
        self._ws = None

    async def connect(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._run()
            except ConnectionClosed as e:
                logger.warning("WebSocket 연결 끊김 (code=%s). %ss 후 재연결...", e.code, RECONNECT_DELAY)
            except Exception:
                logger.exception("WebSocket 예외 발생. %ss 후 재연결...", RECONNECT_DELAY)
            if self._running:
                await asyncio.sleep(RECONNECT_DELAY)

    async def disconnect(self) -> None:
        self._running = False
        if self._ws is not None:
            await self._ws.close()

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = symbols

    async def _run(self) -> None:
        logger.info("Upbit WebSocket 연결 중: %s", self._ws_url)
        async with websockets.connect(self._ws_url) as ws:
            self._ws = ws
            await self._send_subscribe(ws)
            logger.info("Upbit WebSocket 구독 완료: %s", self._symbols)
            async for raw in ws:
                if not self._running:
                    break
                await self._handle_message(raw)

    async def _send_subscribe(self, ws) -> None:
        payload = json.dumps([
            {"ticket": str(uuid.uuid4())},
            {
                "type": "ticker",
                "codes": self._symbols,
                "isOnlyRealtime": True,
            },
            {"format": "DEFAULT"},
        ])
        await ws.send(payload)

    async def _handle_message(self, raw: str | bytes) -> None:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data: dict = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("WebSocket 메시지 파싱 실패")
            return

        msg_type = data.get("type")
        if msg_type == "ticker":
            await self._on_ticker(data)

    async def _on_ticker(self, data: dict) -> None:
        symbol: str = data["code"]
        price = Decimal(str(data["trade_price"]))
        volume = Decimal(str(data.get("trade_volume", 0)))

        from datetime import datetime, timezone
        tick = Tick(
            symbol=symbol,
            price=price,
            volume=volume,
            timestamp=datetime.now(timezone.utc),
        )
        self._snapshot.update_tick(tick)

        await self._event_bus.publish(
            Event(
                type=EventType.PRICE_UPDATED,
                payload={
                    "symbol": symbol,
                    "price": float(price),
                    "volume": float(volume),
                    "change_rate": data.get("signed_change_rate", 0.0),
                    "high_52w": data.get("highest_52_week_price"),
                    "low_52w": data.get("lowest_52_week_price"),
                },
            )
        )
