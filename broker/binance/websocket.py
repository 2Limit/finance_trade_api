"""
BinanceWebSocketFeed: Binance WebSocket 스트림 구현체

구독 스트림:
    <symbol>@trade       — 실시간 체결 (Tick 업데이트)
    <symbol>@kline_1m   — 1분봉 캔들 (완성된 봉만 처리)

연결 URL: wss://stream.binance.com:9443/ws/<stream1>/<stream2>/...

심볼 변환:
    내부 "BTC/USDT" → Binance "btcusdt"
"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import websockets

from core.event import Event, EventBus, EventType
from market.snapshot import Candle, MarketSnapshot, Tick

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"


def to_binance_stream_symbol(symbol: str) -> str:
    """내부 심볼 → Binance 스트림 심볼 소문자. 'BTC/USDT' → 'btcusdt'."""
    return symbol.replace("/", "").replace("-", "").lower()


class BinanceWebSocketFeed:
    """
    Binance 실시간 시세 WebSocket 피드.

    사용 예:
        feed = BinanceWebSocketFeed(
            symbols=["BTC/USDT", "ETH/USDT"],
            snapshot=snapshot,
            event_bus=event_bus,
        )
        await feed.start()
    """

    def __init__(
        self,
        symbols: list[str],
        snapshot: MarketSnapshot,
        event_bus: EventBus,
    ) -> None:
        self._symbols = symbols
        self._snapshot = snapshot
        self._event_bus = event_bus
        self._running = False

    def _build_ws_url(self) -> str:
        """복합 스트림 URL 생성."""
        streams = []
        for sym in self._symbols:
            bs = to_binance_stream_symbol(sym)
            streams.append(f"{bs}@trade")
            streams.append(f"{bs}@kline_1m")
        return f"{BINANCE_WS_URL}/{'/'.join(streams)}"

    async def start(self) -> None:
        """WebSocket 연결 시작 (재연결 루프 포함)."""
        self._running = True
        url = self._build_ws_url()
        logger.info("BinanceWebSocketFeed 시작: %s", url)

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Binance WebSocket 오류 (재연결): %s", e)
                await asyncio.sleep(3)

    async def stop(self) -> None:
        self._running = False

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except Exception:
            return

        event_type = data.get("e")

        if event_type == "trade":
            await self._handle_trade(data)
        elif event_type == "kline":
            await self._handle_kline(data)

    async def _handle_trade(self, data: dict) -> None:
        """체결 이벤트 → Tick + PRICE_UPDATED."""
        sym_raw = data["s"]   # e.g. "BTCUSDT"
        # 내부 심볼로 역변환 (최선 노력: 등록된 symbols에서 검색)
        symbol = self._find_symbol(sym_raw)
        price  = Decimal(data["p"])
        volume = Decimal(data["q"])
        ts     = datetime.fromtimestamp(data["T"] / 1000, tz=timezone.utc)

        tick = Tick(symbol=symbol, price=price, volume=volume, timestamp=ts)
        self._snapshot.update_tick(tick)

        await self._event_bus.publish(Event(
            type=EventType.PRICE_UPDATED,
            payload={"symbol": symbol, "price": str(price), "volume": str(volume)},
        ))

    async def _handle_kline(self, data: dict) -> None:
        """K-line 이벤트 → Candle. 확정 봉(x=True)만 처리."""
        k = data["k"]
        if not k.get("x"):          # 봉이 아직 미완성
            return

        sym_raw = k["s"]
        symbol  = self._find_symbol(sym_raw)
        ts      = datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc)

        candle = Candle(
            symbol=symbol,
            interval=k["i"],
            open=Decimal(k["o"]),
            high=Decimal(k["h"]),
            low=Decimal(k["l"]),
            close=Decimal(k["c"]),
            volume=Decimal(k["v"]),
            timestamp=ts,
        )
        self._snapshot.update_candle(candle)

        await self._event_bus.publish(Event(
            type=EventType.CANDLE_CLOSED,
            payload={
                "symbol": symbol,
                "interval": k["i"],
                "close": str(candle.close),
            },
        ))

    def _find_symbol(self, binance_sym: str) -> str:
        """Binance 심볼 문자열 → 등록된 내부 심볼. 매칭 실패 시 원본 반환."""
        bs_upper = binance_sym.upper()
        for sym in self._symbols:
            if to_binance_stream_symbol(sym).upper() == bs_upper:
                return sym
        return binance_sym
