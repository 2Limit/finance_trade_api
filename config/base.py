from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ────────────────────────────────────────
    env: str = "dev"

    # ── Database ───────────────────────────────────────────
    db_url: str = "sqlite+aiosqlite:///./trading.db"

    # ── Upbit ──────────────────────────────────────────────
    upbit_access_key: str = ""
    upbit_secret_key: str = ""
    upbit_base_url: str = "https://api.upbit.com"
    upbit_ws_url: str = "wss://api.upbit.com/websocket/v1"

    # ── Discord ────────────────────────────────────────────
    discord_webhook_url: str = ""

    # ── Trading ────────────────────────────────────────────
    symbols: list[str] = Field(default=["KRW-BTC", "KRW-ETH"])

    # ── Risk ───────────────────────────────────────────────
    risk_max_order_krw: Decimal = Decimal("500000")
    risk_max_daily_loss_krw: Decimal = Decimal("1000000")
    risk_max_position_ratio: float = 0.3  # 포트폴리오 대비 비중

    # ── Stop-Loss / Take-Profit ────────────────────────────
    stop_loss_pct: float = 0.05       # -5% 이하 자동 손절
    take_profit_pct: float = 0.10     # +10% 이상 자동 익절

    # ── Order Deduplication ────────────────────────────────
    order_cooldown_sec: int = 60      # 심볼별 주문 쿨다운 (초)

    # ── Logging ────────────────────────────────────────────
    log_level: str = "INFO"

    @field_validator("symbols", mode="before")
    @classmethod
    def parse_symbols(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
