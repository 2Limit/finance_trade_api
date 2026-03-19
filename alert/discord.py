from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from alert.base import AbstractAlert

logger = logging.getLogger(__name__)


class DiscordAlert(AbstractAlert):
    """
    Discord Webhook 알림.

    특징:
        - 트레이딩 루프 블로킹 방지: 전송 실패 시 재시도 없이 로깅만
        - Embed 포맷으로 가독성 향상
    """

    COLOR = {
        "buy": 0x2ECC71,      # 초록
        "sell": 0xE74C3C,     # 빨강
        "risk": 0xF39C12,     # 노랑
        "info": 0x3498DB,     # 파랑
        "error": 0x95A5A6,    # 회색
    }

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=5.0)

    async def send(self, message: str) -> None:
        await self._post({"content": message})

    async def send_embed(
        self,
        title: str,
        description: str,
        color: int = COLOR["info"],
        fields: list[dict] | None = None,
    ) -> None:
        embed: dict = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if fields:
            embed["fields"] = fields
        await self._post({"embeds": [embed]})

    # ── 이벤트별 포맷 ─────────────────────────────────────────────────────────

    async def on_signal(self, event) -> None:
        p = event.payload
        signal = p.get("signal", "").upper()
        color = self.COLOR["buy"] if signal == "BUY" else self.COLOR["sell"]
        await self.send_embed(
            title=f"{'📈' if signal == 'BUY' else '📉'} {signal} 시그널",
            description=f"**{p.get('symbol')}**",
            color=color,
            fields=[
                {"name": "전략", "value": p.get("strategy", "-"), "inline": True},
                {"name": "현재가", "value": f"{p.get('price', 0):,.0f} KRW", "inline": True},
                {"name": "강도", "value": f"{p.get('strength', 0):.1%}", "inline": True},
            ],
        )

    async def on_order_filled(self, event) -> None:
        p = event.payload
        side = p.get("side", "").upper()
        color = self.COLOR["buy"] if side == "BUY" else self.COLOR["sell"]
        total = float(p.get("quantity", 0)) * float(p.get("price", 0))
        await self.send_embed(
            title=f"✅ 주문 체결 ({side})",
            description=f"**{p.get('symbol')}**",
            color=color,
            fields=[
                {"name": "수량", "value": str(p.get("quantity")), "inline": True},
                {"name": "체결가", "value": f"{float(p.get('price', 0)):,.0f} KRW", "inline": True},
                {"name": "총액", "value": f"{total:,.0f} KRW", "inline": True},
                {"name": "전략", "value": p.get("strategy", "-"), "inline": True},
            ],
        )

    async def on_risk_triggered(self, event) -> None:
        await self.send_embed(
            title="⚠️ 리스크 한도 도달",
            description=event.payload.get("reason", ""),
            color=self.COLOR["risk"],
        )

    # ── HTTP ─────────────────────────────────────────────────────────────────

    async def _post(self, payload: dict) -> None:
        if not self._webhook_url:
            return
        try:
            resp = await self._client.post(self._webhook_url, json=payload)
            resp.raise_for_status()
        except Exception:
            logger.exception("Discord 알림 전송 실패 (무시)")

    async def close(self) -> None:
        await self._client.aclose()
