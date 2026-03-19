"""
UpbitWebSocketFeed: Upbit WebSocket 실시간 피드 구현체

책임:
    - AbstractMarketFeed 구현
    - wss://api.upbit.com/websocket/v1 연결
    - 틱/캔들 수신 → EventBus.publish(PRICE_UPDATED)
    - 연결 끊김 시 자동 재연결

REST 주문은 broker/upbit/rest.py 참고
"""
from __future__ import annotations

from market.feed import AbstractMarketFeed

# Upbit WebSocket 피드 구현체
