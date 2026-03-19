"""
EmailAlert: SMTP 기반 이메일 알림

설정:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO
    환경변수 또는 config 에서 주입.

특징:
    - aiosmtplib 기반 비동기 전송
    - 전송 실패 시 로깅만 (트레이딩 루프 블로킹 없음)
    - HTML 본문 지원 (Embed 스타일 포맷)
"""
from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

import aiosmtplib

from alert.base import AbstractAlert

if TYPE_CHECKING:
    from core.event import Event

logger = logging.getLogger(__name__)


class EmailAlert(AbstractAlert):
    """SMTP 이메일 알림."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        to_address: str,
        use_tls: bool = True,
    ) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._user = smtp_user
        self._password = smtp_password
        self._to = to_address
        self._use_tls = use_tls

    async def send(self, message: str) -> None:
        """일반 텍스트 메시지 발송."""
        await self._send_email(subject="[Trading] 알림", body=message, html=False)

    async def send_html(self, subject: str, html_body: str) -> None:
        """HTML 메시지 발송."""
        await self._send_email(subject=subject, body=html_body, html=True)

    # ── 이벤트별 포맷 ─────────────────────────────────────────────────────────

    async def on_signal(self, event: "Event") -> None:
        p = event.payload
        signal = p.get("signal", "").upper()
        symbol = p.get("symbol", "")
        price = p.get("price", 0)
        strength = p.get("strength", 0)
        strategy = p.get("strategy", "-")

        color = "#2ECC71" if signal == "BUY" else "#E74C3C"
        subject = f"[Trading] {'📈' if signal == 'BUY' else '📉'} {signal} 시그널 - {symbol}"
        body = f"""
        <div style="font-family: Arial, sans-serif; border-left: 4px solid {color}; padding: 12px;">
            <h2 style="color: {color};">{signal} 시그널</h2>
            <table>
                <tr><td><b>심볼</b></td><td>{symbol}</td></tr>
                <tr><td><b>전략</b></td><td>{strategy}</td></tr>
                <tr><td><b>현재가</b></td><td>{float(price):,.0f} KRW</td></tr>
                <tr><td><b>강도</b></td><td>{float(strength):.1%}</td></tr>
            </table>
        </div>
        """
        await self.send_html(subject, body)

    async def on_order_filled(self, event: "Event") -> None:
        p = event.payload
        side = p.get("side", "").upper()
        symbol = p.get("symbol", "")
        qty = p.get("quantity", 0)
        price = p.get("price", 0)
        total = float(qty) * float(price)
        color = "#2ECC71" if side == "BUY" else "#E74C3C"

        subject = f"[Trading] ✅ 주문 체결 ({side}) - {symbol}"
        body = f"""
        <div style="font-family: Arial, sans-serif; border-left: 4px solid {color}; padding: 12px;">
            <h2>주문 체결 ({side})</h2>
            <table>
                <tr><td><b>심볼</b></td><td>{symbol}</td></tr>
                <tr><td><b>수량</b></td><td>{qty}</td></tr>
                <tr><td><b>체결가</b></td><td>{float(price):,.0f} KRW</td></tr>
                <tr><td><b>총액</b></td><td>{total:,.0f} KRW</td></tr>
            </table>
        </div>
        """
        await self.send_html(subject, body)

    async def on_risk_triggered(self, event: "Event") -> None:
        reason = event.payload.get("reason", "")
        subject = "[Trading] ⚠️ 리스크 한도 도달"
        body = f"""
        <div style="font-family: Arial, sans-serif; border-left: 4px solid #F39C12; padding: 12px;">
            <h2 style="color: #F39C12;">⚠️ 리스크 한도 도달</h2>
            <p>{reason}</p>
        </div>
        """
        await self.send_html(subject, body)

    # ── SMTP 전송 ─────────────────────────────────────────────────────────────

    async def _send_email(self, subject: str, body: str, html: bool = False) -> None:
        if not all([self._host, self._user, self._to]):
            logger.debug("Email 설정 미완료 — 발송 스킵")
            return
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._user
            msg["To"] = self._to
            mime_type = "html" if html else "plain"
            msg.attach(MIMEText(body, mime_type, "utf-8"))

            await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                username=self._user,
                password=self._password,
                use_tls=self._use_tls,
            )
            logger.info("이메일 발송 완료: %s → %s", subject, self._to)
        except Exception:
            logger.exception("이메일 발송 실패 (무시)")
