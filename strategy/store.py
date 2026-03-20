"""
StrategyStore: 실행 중인 전략 인스턴스 레지스트리

두 가지 모드:
  1. in-memory (기본): 같은 프로세스에서 대시보드와 엔진을 함께 실행할 때
  2. Redis 동기화: 대시보드와 엔진이 별도 프로세스일 때

Redis 동기화 활성화:
    strategy_store.set_redis(redis_client)  # main.py에서 호출

Redis 구조:
  Hash "strategy:configs"
    field: strategy_name
    value: JSON { name, class, symbols, params, param_schema }

  Pub/Sub 채널 "strategy:param_updates"
    대시보드 → 엔진으로 파라미터 변경 신호 (RedisEventBus가 수신)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from strategy.base import AbstractStrategy

logger = logging.getLogger(__name__)

REDIS_HASH_KEY = "strategy:configs"


class StrategyStore:
    """실행 중인 전략 인스턴스를 이름으로 관리."""

    def __init__(self) -> None:
        self._strategies: dict[str, "AbstractStrategy"] = {}
        self._redis: Any | None = None  # redis.asyncio.Redis (선택)

    # ── Redis 연결 ────────────────────────────────────────────────────────────

    def set_redis(self, redis_client: Any) -> None:
        """Redis 클라이언트 주입 (main.py에서 RedisEventBus 연결 후 호출)."""
        self._redis = redis_client
        logger.info("StrategyStore: Redis 동기화 활성화")

    # ── 전략 관리 ─────────────────────────────────────────────────────────────

    def register(self, strategy: "AbstractStrategy") -> None:
        self._strategies[strategy.name] = strategy
        logger.info("StrategyStore: registered '%s'", strategy.name)
        # Redis 비동기 동기화 (실패해도 무시)
        if self._redis is not None:
            asyncio.create_task(self._sync_one_to_redis(strategy))

    def get(self, name: str) -> "AbstractStrategy | None":
        return self._strategies.get(name)

    def get_all(self) -> list["AbstractStrategy"]:
        return list(self._strategies.values())

    def update_params(self, name: str, new_params: dict) -> bool:
        strategy = self._strategies.get(name)
        if strategy is None:
            return False
        strategy.update_params(new_params)
        logger.info("StrategyStore: updated params for '%s': %s", name, new_params)
        if self._redis is not None:
            asyncio.create_task(self._sync_one_to_redis(strategy))
        return True

    # ── 직렬화 ────────────────────────────────────────────────────────────────

    def to_dict_list(self) -> list[dict]:
        """in-memory 전략 목록 → 대시보드 직렬화."""
        return [_strategy_to_dict(s) for s in self._strategies.values()]

    # ── Redis 동기화 ──────────────────────────────────────────────────────────

    async def _sync_one_to_redis(self, strategy: "AbstractStrategy") -> None:
        try:
            payload = json.dumps(_strategy_to_dict(strategy))
            await self._redis.hset(REDIS_HASH_KEY, strategy.name, payload)
        except Exception as e:
            logger.debug("Redis 전략 동기화 실패 (무시): %s", e)

    async def sync_all_to_redis(self) -> None:
        """모든 전략을 Redis에 일괄 동기화."""
        if self._redis is None:
            return
        for strategy in self._strategies.values():
            await self._sync_one_to_redis(strategy)
        logger.info("StrategyStore: %d개 전략 Redis 동기화 완료", len(self._strategies))

    async def load_from_redis(self) -> list[dict]:
        """
        Redis Hash에서 전략 설정 조회.
        대시보드 독립 실행 시 Redis에서 엔진의 전략 상태를 읽는다.
        """
        if self._redis is None:
            return []
        try:
            raw = await self._redis.hgetall(REDIS_HASH_KEY)
            return [json.loads(v) for v in raw.values()] if raw else []
        except Exception as e:
            logger.debug("Redis 전략 로드 실패: %s", e)
            return []


def _strategy_to_dict(strategy: "AbstractStrategy") -> dict:
    return {
        "name": strategy.name,
        "class": type(strategy).__name__,
        "symbols": strategy.symbols,
        "params": strategy.params,
        "param_schema": strategy.param_schema(),
    }


# 프로세스 전역 싱글톤
strategy_store = StrategyStore()
