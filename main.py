from __future__ import annotations

import asyncio
import logging
import logging.config
import signal
from pathlib import Path

import yaml

from alert.discord import DiscordAlert
from broker.upbit.rest import UpbitRestClient
from broker.upbit.websocket import UpbitWebSocketFeed
from config import get_settings
from core.engine import TradingEngine
from core.event import EventBus, EventType
from data.collector.market_collector import MarketCollector
from db.session import close_db, init_db
from execution.order_manager import OrderManager
from execution.risk import RiskConfig, RiskManager
from market.snapshot import MarketSnapshot
from portfolio.account import AccountManager
from portfolio.position import PositionManager
from report.daily_report import DailyReportGenerator
from scheduler import TradingScheduler
from strategy.impl.ma_crossover import MACrossoverStrategy
from strategy.registry import StrategyRegistry

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    config_path = Path("config/logging.yaml")
    if config_path.exists():
        with open(config_path) as f:
            logging.config.dictConfig(yaml.safe_load(f))
    else:
        settings = get_settings()
        logging.basicConfig(
            level=getattr(logging, settings.log_level),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )


async def build_app() -> tuple[TradingEngine, TradingScheduler, DiscordAlert, UpbitRestClient]:
    """모든 컴포넌트를 조립하고 의존성을 주입한다."""
    settings = get_settings()

    # ── Infrastructure ────────────────────────────────────────────────────────
    await init_db()

    event_bus = EventBus()
    snapshot = MarketSnapshot()

    # ── Broker ────────────────────────────────────────────────────────────────
    rest_client = UpbitRestClient(
        access_key=settings.upbit_access_key,
        secret_key=settings.upbit_secret_key,
        base_url=settings.upbit_base_url,
    )
    ws_feed = UpbitWebSocketFeed(
        symbols=settings.symbols,
        snapshot=snapshot,
        event_bus=event_bus,
        ws_url=settings.upbit_ws_url,
    )

    # ── Portfolio ─────────────────────────────────────────────────────────────
    account = AccountManager(broker=rest_client)
    position = PositionManager()
    await account.sync()  # 초기 잔고 동기화

    # ── Risk ──────────────────────────────────────────────────────────────────
    risk_config = RiskConfig(
        max_order_krw=settings.risk_max_order_krw,
        max_daily_loss_krw=settings.risk_max_daily_loss_krw,
        max_position_ratio=settings.risk_max_position_ratio,
    )
    risk = RiskManager(
        config=risk_config,
        account=account,
        position=position,
        event_bus=event_bus,
    )

    # ── Execution ─────────────────────────────────────────────────────────────
    order_manager = OrderManager(
        broker=rest_client,
        risk=risk,
        event_bus=event_bus,
        default_order_krw=settings.risk_max_order_krw,
    )

    # ── Alert ─────────────────────────────────────────────────────────────────
    discord = DiscordAlert(webhook_url=settings.discord_webhook_url)
    event_bus.subscribe(EventType.SIGNAL_GENERATED, discord.on_signal)
    event_bus.subscribe(EventType.ORDER_FILLED, discord.on_order_filled)
    event_bus.subscribe(EventType.RISK_TRIGGERED, discord.on_risk_triggered)

    # ── Engine ────────────────────────────────────────────────────────────────
    engine = TradingEngine(
        broker=rest_client,
        feed=ws_feed,
        order_manager=order_manager,
        position_manager=position,
        event_bus=event_bus,
    )

    # ── Strategies ────────────────────────────────────────────────────────────
    registry = StrategyRegistry()
    registry.register("ma_crossover", MACrossoverStrategy)

    ma_strategy = registry.create(
        name="ma_crossover",
        symbols=settings.symbols,
        params={"short_window": 5, "long_window": 20, "rsi_period": 14},
    )
    # MACrossover는 snapshot 주입 필요
    assert isinstance(ma_strategy, MACrossoverStrategy)
    ma_strategy.set_snapshot(snapshot)

    engine.register_strategy(ma_strategy)
    engine.register_alert(discord)

    # ── Scheduler ─────────────────────────────────────────────────────────────
    collector = MarketCollector(
        client=rest_client,
        snapshot=snapshot,
        symbols=settings.symbols,
        interval=1,
    )
    scheduler = TradingScheduler()
    scheduler.register_candle_job(collector.collect_candles, interval_minutes=1)
    scheduler.register_account_sync_job(account.sync, interval_minutes=5)
    scheduler.register_daily_loss_reset_job(risk.reset_daily_loss)  # 자정 리셋

    # ── Daily Report ──────────────────────────────────────────────────────────
    report_generator = DailyReportGenerator(alerts=[discord])
    scheduler.register_daily_report_job(report_generator.generate, hour=9, minute=0)

    return engine, scheduler, discord, rest_client


async def main() -> None:
    setup_logging()
    logger.info("=== Finance Trade API 시작 ===")

    engine, scheduler, discord, rest_client = await build_app()

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(*_) -> None:
        logger.info("종료 시그널 수신")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    scheduler.start()

    try:
        # 초기 캔들 수집
        settings = get_settings()
        collector = MarketCollector(
            client=rest_client,
            snapshot=MarketSnapshot(),  # 이미 engine 내부에서 공유 snapshot 사용
            symbols=settings.symbols,
        )

        # 엔진과 종료 대기를 동시 실행
        await asyncio.gather(
            engine.start(),
            stop_event.wait(),
        )
    finally:
        logger.info("종료 중...")
        await engine.stop()
        scheduler.stop()
        await rest_client.close()
        await discord.close()
        await close_db()
        logger.info("=== 종료 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
