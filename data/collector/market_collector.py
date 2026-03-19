from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from broker.upbit.rest import UpbitRestClient
from db.models.market import CandleModel
from db.repositories.base import BaseRepository
from db.session import get_session
from market.snapshot import Candle, MarketSnapshot

logger = logging.getLogger(__name__)


class MarketCollector:
    """
    REST API를 통해 캔들 데이터를 수집하고 DB에 저장.

    역할:
        - 정기적으로 과거 캔들 수집 (scheduler에서 호출)
        - MarketSnapshot에 캔들 등록
        - CandleModel DB 저장 (upsert)

    실시간 tick은 WebSocket(UpbitWebSocketFeed)이 담당.
    """

    def __init__(
        self,
        client: UpbitRestClient,
        snapshot: MarketSnapshot,
        symbols: list[str],
        interval: int = 1,  # 분 단위
    ) -> None:
        self._client = client
        self._snapshot = snapshot
        self._symbols = symbols
        self._interval = interval

    async def collect_candles(self, count: int = 200) -> None:
        """모든 심볼의 최신 캔들을 수집하여 DB + 스냅샷에 저장."""
        for symbol in self._symbols:
            try:
                await self._collect_symbol(symbol, count)
            except Exception:
                logger.exception("캔들 수집 실패: %s", symbol)

    async def _collect_symbol(self, symbol: str, count: int) -> None:
        raw_candles = await self._client.get_candles(
            symbol=symbol, interval=self._interval, count=count
        )
        candles = [self._parse_candle(symbol, c) for c in raw_candles]

        # 스냅샷 업데이트 (최신순 → 역순 정렬)
        for candle in reversed(candles):
            self._snapshot.update_candle(candle)

        # DB 저장
        async with get_session() as session:
            for candle in candles:
                model = CandleModel(
                    symbol=candle.symbol,
                    interval=candle.interval,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    timestamp=candle.timestamp,
                )
                session.add(model)
            try:
                await session.flush()
            except Exception:
                # UniqueConstraint 위반(중복) 시 무시
                await session.rollback()

        logger.debug("캔들 수집 완료: %s (%d개)", symbol, len(candles))

    def _parse_candle(self, symbol: str, raw: dict) -> Candle:
        return Candle(
            symbol=symbol,
            interval=f"{self._interval}m",
            open=Decimal(str(raw["opening_price"])),
            high=Decimal(str(raw["high_price"])),
            low=Decimal(str(raw["low_price"])),
            close=Decimal(str(raw["trade_price"])),
            volume=Decimal(str(raw["candle_acc_trade_volume"])),
            timestamp=datetime.fromisoformat(
                raw["candle_date_time_utc"].replace("Z", "+00:00")
            ),
        )
