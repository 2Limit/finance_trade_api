from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class TradingScheduler:
    """
    APScheduler 기반 정기 작업 관리.

    역할:
        - 캔들 수집 (MarketCollector) 주기적 실행
        - 계좌 잔고 동기화 (AccountManager) 주기적 실행
        - 실시간 루프(WebSocket)는 TradingEngine이 직접 관리하므로 여기서 불필요

    사용:
        scheduler = TradingScheduler()
        scheduler.register_candle_job(collector.collect_candles, interval_minutes=1)
        scheduler.start()
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    def register_candle_job(self, func, interval_minutes: int = 1) -> None:
        """캔들 수집 작업 등록."""
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="candle_collector",
            replace_existing=True,
            misfire_grace_time=30,
        )
        logger.info("캔들 수집 작업 등록: %d분 간격", interval_minutes)

    def register_account_sync_job(self, func, interval_minutes: int = 5) -> None:
        """계좌 잔고 동기화 작업 등록."""
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="account_sync",
            replace_existing=True,
        )
        logger.info("계좌 동기화 작업 등록: %d분 간격", interval_minutes)

    def register_daily_report_job(self, func, hour: int = 9, minute: int = 0) -> None:
        """일일 리포트 작업 등록 (매일 지정 시간)."""
        self._scheduler.add_job(
            func,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_report",
            replace_existing=True,
        )
        logger.info("일일 리포트 작업 등록: 매일 %02d:%02d", hour, minute)

    def register_daily_loss_reset_job(self, func, hour: int = 0, minute: int = 0) -> None:
        """일일 손실 카운터 리셋 작업 등록 (기본: 자정 KST)."""
        self._scheduler.add_job(
            func,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_loss_reset",
            replace_existing=True,
        )
        logger.info("일일 손실 리셋 작업 등록: 매일 %02d:%02d KST", hour, minute)

    def start(self) -> None:
        self._scheduler.start()
        logger.info("TradingScheduler 시작")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("TradingScheduler 종료")
