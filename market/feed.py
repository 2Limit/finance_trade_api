"""
AbstractMarketFeed: 실시간 시장 데이터 피드 인터페이스

구현체:
    - broker/upbit/websocket.py (UpbitWebSocketFeed)

책임:
    - WebSocket 연결/재연결
    - 수신한 틱/캔들 데이터를 EventBus에 발행
    - Broker 주문 로직과 완전히 분리
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractMarketFeed(ABC):
    """실시간 가격 피드 추상 인터페이스."""

    @abstractmethod
    async def connect(self) -> None:
        """WebSocket 연결 시작 및 데이터 수신 루프."""
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """연결 종료."""
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """구독할 심볼 목록 등록."""
        raise NotImplementedError
