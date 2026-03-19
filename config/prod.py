from config.base import Settings


class ProdSettings(Settings):
    env: str = "prod"
    log_level: str = "INFO"
    # prod DB_URL은 반드시 .env에서 주입 (PostgreSQL)
