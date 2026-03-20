"""
RedisEventBus: Redis Streams 기반 크로스 프로세스 이벤트 버스

기존 EventBus를 확장한다:
  1. 로컬 핸들러 → 기존과 동일 (같은 프로세스 내 직접 호출)
  2. Redis Stream 발행 → 다른 프로세스(대시보드, 모니터 등)가 구독 가능

스트림 키: "events:all"
  각 메시지 필드: {"type": "...", "payload": "{...json...}", "ts": "..."}
  MAXLEN 2000으로 최근 이벤트만 보관

Redis Pub/Sub 채널: "strategy:param_updates"
  대시보드 → 엔진으로 파라미터 변경 신호 전달

Redis 연결 실패 시 로컬 EventBus로 자동 폴백 (무중단).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from core.event import Event, EventBus, EventType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

STREAM_KEY = "events:all"
STREAM_MAXLEN = 2000
PARAM_UPDATE_CHANNEL = "strategy:param_updates"


def _event_to_dict(event: Event) -> dict[str, str]:
    """Event → Redis Stream 필드 dict."""
    return {
        "type": event.type.name,
        "payload": json.dumps(event.payload, default=str),
        "ts": event.timestamp.isoformat(),
    }


def _dict_to_event(data: dict) -> Event | None:
    """Redis Stream 필드 dict → Event."""
    try:
        event_type = EventType[data[b"type"].decode() if isinstance(data[b"type"], bytes) else data["type"]]
        raw_payload = data[b"payload"] if b"payload" in data else data["payload"]
        payload = json.loads(raw_payload)
        return Event(type=event_type, payload=payload)
    except Exception as e:
        logger.warning("Redis 이벤트 역직렬화 실패: %s", e)
        return None


class RedisEventBus(EventBus):
    """
    EventBus + Redis Streams 팬아웃.

    같은 프로세스 내에서는 기존 EventBus와 동일하게 동작하고,
    추가로 Redis Stream에 이벤트를 발행하여 다른 프로세스도 구독할 수 있다.
    """

    def __init__(self, redis_url: str) -> None:
        super().__init__()
        self._redis_url = redis_url
        self._redis: Any | None = None  # redis.asyncio.Redis
        self._connected = False
        self._param_update_callbacks: list = []

    async def connect(self) -> None:
        """Redis 연결 초기화. 실패해도 로컬 EventBus로 폴백."""
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=False,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            await self._redis.ping()
            self._connected = True
            logger.info("RedisEventBus: Redis 연결 성공 (%s)", self._redis_url)
        except Exception as e:
            logger.warning("RedisEventBus: Redis 연결 실패 → in-memory 폴백 (%s)", e)
            self._redis = None
            self._connected = False

    async def disconnect(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            self._connected = False

    async def publish(self, event: Event) -> None:
        """로컬 핸들러 호출 + Redis Stream 발행."""
        # 1. 로컬 핸들러 (기존 동작 그대로)
        await super().publish(event)

        # 2. Redis Stream 발행 (실패해도 무시)
        if self._connected and self._redis is not None:
            try:
                fields = _event_to_dict(event)
                await self._redis.xadd(STREAM_KEY, fields, maxlen=STREAM_MAXLEN)
            except Exception as e:
                logger.debug("Redis Stream 발행 실패 (무시): %s", e)

    def add_param_update_callback(self, callback) -> None:
        """파라미터 변경 알림 수신 콜백 등록."""
        self._param_update_callbacks.append(callback)

    async def watch_param_updates(self) -> None:
        """
        Redis Pub/Sub 구독 → 대시보드에서 파라미터 변경 시 콜백 호출.
        main.py에서 asyncio.create_task()로 실행.
        """
        if not self._connected or self._redis is None:
            logger.info("Redis 미연결 — 파라미터 변경 감시 비활성")
            return

        try:
            import redis.asyncio as aioredis
            # 별도 연결 (pub/sub 전용)
            pubsub_redis = aioredis.from_url(self._redis_url, decode_responses=True)
            pubsub = pubsub_redis.pubsub()
            await pubsub.subscribe(PARAM_UPDATE_CHANNEL)
            logger.info("RedisEventBus: 파라미터 변경 채널 구독 시작")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    for cb in self._param_update_callbacks:
                        await cb(data) if asyncio.iscoroutinefunction(cb) else cb(data)
                except Exception as e:
                    logger.warning("파라미터 변경 처리 실패: %s", e)
        except asyncio.CancelledError:
            logger.info("RedisEventBus: 파라미터 감시 태스크 종료")
        except Exception as e:
            logger.error("RedisEventBus: 파라미터 감시 오류: %s", e)

    @property
    def is_redis_connected(self) -> bool:
        return self._connected


async def create_redis_event_bus(redis_url: str) -> RedisEventBus:
    """RedisEventBus 인스턴스 생성 및 연결."""
    bus = RedisEventBus(redis_url)
    await bus.connect()
    return bus
