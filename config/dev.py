from decimal import Decimal

from config.base import Settings


class DevSettings(Settings):
    env: str = "dev"
    db_url: str = "sqlite+aiosqlite:///./trading_dev.db"
    log_level: str = "DEBUG"

    # dev는 리스크 한도를 낮게 설정해 실수 방지
    risk_max_order_krw: Decimal = Decimal("10000")
    risk_max_daily_loss_krw: Decimal = Decimal("50000")
