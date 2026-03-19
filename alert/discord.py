"""
DiscordAlert: Discord Webhook 알림 구현체

책임:
    - AbstractAlert 구현
    - Discord Webhook URL로 메시지 발송
    - 에러 시 재시도 없이 로깅 (트레이딩 루프 블로킹 방지)
"""
from __future__ import annotations

import logging

from alert.base import AbstractAlert

logger = logging.getLogger(__name__)


class DiscordAlert(AbstractAlert):
    """Discord Webhook 알림 발송."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send(self, message: str) -> None:
        # Discord Webhook 발송 구현 예정
        raise NotImplementedError
