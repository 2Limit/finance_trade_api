"""
Alembic 마이그레이션 환경 설정.

async SQLAlchemy (aiosqlite / asyncpg) 지원.
DB URL은 config.Settings 에서 읽으므로 .env 파일로 제어 가능.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── 프로젝트 모델 임포트 ────────────────────────────────────────────────────────
# 모든 모델을 임포트해야 autogenerate 가 테이블을 인식한다.
from db.base import Base
import db.models  # noqa: F401 — side-effect import (모든 모델 등록)

# ── Alembic 설정 ────────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """설정 파일 또는 프로젝트 Settings 에서 DB URL 반환."""
    try:
        from config import get_settings
        url = get_settings().db_url
        # aiosqlite → sqlite 로 변환 (alembic offline 모드는 sync 드라이버 필요)
        return url.replace("aiosqlite", "pysqlite").replace("+aiosqlite", "")
    except Exception:
        return config.get_main_option("sqlalchemy.url", "sqlite:///./trading.db")


def run_migrations_offline() -> None:
    """
    오프라인 모드: DB 연결 없이 SQL 스크립트만 생성.

        alembic upgrade head --sql
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """온라인 모드: async 엔진으로 실제 DB에 마이그레이션 적용."""
    try:
        from config import get_settings
        db_url = get_settings().db_url
    except Exception:
        db_url = config.get_main_option("sqlalchemy.url")

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """온라인 모드 진입점."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
