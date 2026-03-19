"""
DailyReportGenerator: 일일 거래 결과 리포트

역할:
    - 전일 거래 내역 조회 (TradeRepository)
    - 수익/손실/수수료/거래 횟수 집계
    - 알림 채널(Discord 등)으로 리포트 발송

스케줄러 연동:
    scheduler.register_daily_report_job(report.generate, hour=9, minute=0)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from db.models.trade import TradeModel
from db.session import get_session
from db.repositories.trade_repo import TradeRepository

if TYPE_CHECKING:
    from alert.base import AbstractAlert

logger = logging.getLogger(__name__)


class DailyReportGenerator:
    """전일 거래 데이터를 집계하여 알림 채널로 발송."""

    def __init__(self, alerts: list["AbstractAlert"]) -> None:
        self._alerts = alerts

    async def generate(self) -> None:
        """어제(KST 기준) 거래 리포트 생성 및 발송."""
        now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
        yesterday_kst = now_kst - timedelta(days=1)
        target_date = yesterday_kst.replace(
            hour=0, minute=0, second=0, microsecond=0,
            tzinfo=None,
        )
        # UTC 기준으로 변환 (DB 저장은 UTC)
        target_utc = target_date - timedelta(hours=9)

        try:
            report = await self._build_report(target_utc)
            message = self._format_report(report, yesterday_kst)
            for alert in self._alerts:
                await alert.send(message)
            logger.info("일일 리포트 발송 완료: %s", yesterday_kst.strftime("%Y-%m-%d"))
        except Exception:
            logger.exception("일일 리포트 생성 실패")

    async def _build_report(self, date_utc: datetime) -> dict:
        """DB에서 해당 날짜 거래 집계."""
        async with get_session() as session:
            repo = TradeRepository(session)
            daily = await repo.get_daily_pnl(date_utc)

        buy_info = daily.get("buy", {})
        sell_info = daily.get("sell", {})

        buy_value = Decimal(str(buy_info.get("value") or 0))
        sell_value = Decimal(str(sell_info.get("value") or 0))
        buy_fee = Decimal(str(buy_info.get("fee") or 0))
        sell_fee = Decimal(str(sell_info.get("fee") or 0))
        total_fee = buy_fee + sell_fee
        gross_pnl = sell_value - buy_value
        net_pnl = gross_pnl - total_fee

        return {
            "buy_value": buy_value,
            "sell_value": sell_value,
            "total_fee": total_fee,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
        }

    def _format_report(self, report: dict, date: datetime) -> str:
        net_pnl = report["net_pnl"]
        sign = "+" if net_pnl >= 0 else ""
        emoji = "📈" if net_pnl >= 0 else "📉"

        return (
            f"{emoji} **일일 리포트** — {date.strftime('%Y-%m-%d')}\n"
            f"```\n"
            f"매수 총액 : {float(report['buy_value']):>15,.0f} KRW\n"
            f"매도 총액 : {float(report['sell_value']):>15,.0f} KRW\n"
            f"총 수수료 : {float(report['total_fee']):>15,.2f} KRW\n"
            f"────────────────────────────\n"
            f"순 손익   : {sign}{float(net_pnl):>14,.0f} KRW\n"
            f"```"
        )
