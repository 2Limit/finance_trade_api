"""
UpbitRestClient: Upbit REST API 브로커 구현체

책임:
    - AbstractBroker 구현 (주문/취소/잔고)
    - Upbit REST API v1 통신
    - JWT 인증 처리

WebSocket 피드는 broker/upbit/websocket.py 참고
"""
from __future__ import annotations

from broker.base import AbstractBroker

# Upbit REST API 구현체
