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
from core.event_bus_redis import RedisEventBus
from data.collector.market_collector import MarketCollector
from db.session import close_db, init_db
from execution.order_manager import OrderManager
from execution.risk import RiskConfig, RiskManager
from execution.stop_loss import StopLossConfig, StopLossMonitor
from market.snapshot import MarketSnapshot
from portfolio.account import AccountManager
from portfolio.position import PositionManager
from report.daily_report import DailyReportGenerator
from scheduler import TradingScheduler
from strategy.aggregator import StrategyAggregator
from strategy.impl.bollinger_strategy import BollingerStrategy
from strategy.impl.ma_crossover import MACrossoverStrategy
from strategy.impl.macd_strategy import MacdStrategy
from strategy.impl.ml_strategy import MLStrategy
from strategy.impl.rsi_strategy import RsiStrategy
from strategy.registry import StrategyRegistry
from strategy.store import strategy_store

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


async def build_app() -> tuple[TradingEngine, TradingScheduler, DiscordAlert, UpbitRestClient, EventBus]:
    """모든 컴포넌트를 조립하고 의존성을 주입한다."""
    settings = get_settings()

    # ── Infrastructure ────────────────────────────────────────────────────────
    await init_db()

    # Redis EventBus: redis_url 설정 시 활성화, 없으면 in-memory fallback
    if settings.redis_url:
        event_bus: EventBus = RedisEventBus(settings.redis_url)
        await event_bus.connect()  # type: ignore[union-attr]
        logger.info("RedisEventBus 활성화")
    else:
        event_bus = EventBus()
        logger.info("in-memory EventBus 사용")

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
        order_cooldown_sec=settings.order_cooldown_sec,
    )

    # ── Stop-Loss / Take-Profit ───────────────────────────────────────────────
    stop_loss_monitor = StopLossMonitor(
        config=StopLossConfig(
            stop_loss_pct=settings.stop_loss_pct,
            take_profit_pct=settings.take_profit_pct,
        ),
        position_manager=position,
        event_bus=event_bus,
    )
    event_bus.subscribe(EventType.PRICE_UPDATED, stop_loss_monitor.on_price_updated)

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
    registry.register("rsi", RsiStrategy)
    registry.register("bollinger", BollingerStrategy)
    registry.register("macd", MacdStrategy)
    registry.register("ml", MLStrategy)

    # MA Crossover
    ma_strategy = registry.create(
        name="ma_crossover",
        symbols=settings.symbols,
        params={"short_window": 5, "long_window": 20, "rsi_period": 14},
    )
    assert isinstance(ma_strategy, MACrossoverStrategy)
    ma_strategy.set_snapshot(snapshot)

    # RSI
    rsi_strategy = registry.create(
        name="rsi",
        symbols=settings.symbols,
        params={"rsi_period": 14, "oversold_level": 30.0, "overbought_level": 70.0},
    )
    assert isinstance(rsi_strategy, RsiStrategy)
    rsi_strategy.set_snapshot(snapshot)

    # Bollinger
    bollinger_strategy = registry.create(
        name="bollinger",
        symbols=settings.symbols,
        params={"window": 20, "num_std": 2.0},
    )
    assert isinstance(bollinger_strategy, BollingerStrategy)
    bollinger_strategy.set_snapshot(snapshot)

    # MACD
    macd_strategy = registry.create(
        name="macd",
        symbols=settings.symbols,
        params={"fast": 12, "slow": 26, "signal": 9},
    )
    assert isinstance(macd_strategy, MacdStrategy)
    macd_strategy.set_snapshot(snapshot)

    # Redis 연결된 경우 StrategyStore에 Redis 공유
    if isinstance(event_bus, RedisEventBus) and event_bus.is_redis_connected:
        strategy_store.set_redis(event_bus._redis)

    # 개별 전략 엔진 등록
    for strat in [ma_strategy, rsi_strategy, bollinger_strategy, macd_strategy]:
        engine.register_strategy(strat)
        strategy_store.register(strat)  # 대시보드 공유

    # Redis StrategyStore 초기 동기화
    if isinstance(event_bus, RedisEventBus) and event_bus.is_redis_connected:
        await strategy_store.sync_all_to_redis()

    # 앙상블 (PRICE_UPDATED 직접 구독 — 엔진의 on_tick과 별개로 동작)
    aggregator = StrategyAggregator(
        strategies=[ma_strategy, rsi_strategy, bollinger_strategy],
        event_bus=event_bus,
        threshold=0.6,
        name="aggregator",
    )
    event_bus.subscribe(EventType.PRICE_UPDATED, aggregator.on_tick_event)

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

    return engine, scheduler, discord, rest_client, event_bus


async def _run_dashboard(port: int = 8000) -> None:
    """대시보드 서버를 현재 asyncio 루프에서 실행."""
    import uvicorn
    from api.dashboard import app
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    setup_logging()
    logger.info("=== Finance Trade API 시작 ===")

    engine, scheduler, discord, rest_client, event_bus = await build_app()

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(*_) -> None:
        logger.info("종료 시그널 수신")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    scheduler.start()
    logger.info("대시보드: http://localhost:8000")

    tasks = [
        asyncio.create_task(engine.start()),
        asyncio.create_task(_run_dashboard(port=8000)),
        asyncio.create_task(stop_event.wait()),
    ]

    # Redis 파라미터 변경 감시 태스크
    if isinstance(event_bus, RedisEventBus):
        async def _on_param_update(data: dict) -> None:
            name = data.get("name")
            params = data.get("params", {})
            if name and params:
                from strategy.store import strategy_store as _store
                _store.update_params(name, params)
                logger.info("파라미터 업데이트 수신: %s → %s", name, params)

        event_bus.add_param_update_callback(_on_param_update)
        tasks.append(asyncio.create_task(event_bus.watch_param_updates()))

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        logger.info("종료 중...")
        for t in tasks:
            t.cancel()
        await engine.stop()
        scheduler.stop()
        await rest_client.close()
        await discord.close()
        if isinstance(event_bus, RedisEventBus):
            await event_bus.disconnect()
        await close_db()
        logger.info("=== 종료 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
