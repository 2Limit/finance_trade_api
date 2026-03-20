from __future__ import annotations

import hashlib
import logging
import uuid
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import jwt

from broker.base import AbstractBroker, OrderRequest, OrderResult, OrderSide, OrderType

logger = logging.getLogger(__name__)

UPBIT_BASE_URL = "https://api.upbit.com"


class UpbitRestClient(AbstractBroker):
    exchange_name = "upbit"

    """
    Upbit REST API v1 구현체.

    인증:
        - 쿼리 파라미터 없는 요청: access_key + nonce → JWT
        - 쿼리 파라미터 있는 요청: 위 + query_hash (SHA512) → JWT
    """

    def __init__(self, access_key: str, secret_key: str, base_url: str = UPBIT_BASE_URL) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._base_url = base_url
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=10.0,
            headers={"Content-Type": "application/json"},
        )

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _make_jwt(self, query_params: dict | None = None) -> str:
        payload: dict = {
            "access_key": self._access_key,
            "nonce": str(uuid.uuid4()),
        }
        if query_params:
            query_string = urlencode(query_params).encode()
            m = hashlib.sha512()
            m.update(query_string)
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"
        return jwt.encode(payload, self._secret_key, algorithm="HS256")

    def _auth_headers(self, query_params: dict | None = None) -> dict:
        token = self._make_jwt(query_params)
        return {"Authorization": f"Bearer {token}"}

    # ── AbstractBroker 구현 ───────────────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> OrderResult:
        params = {
            "market": request.symbol,
            "side": request.side.value,
            "ord_type": request.order_type.value,
            "volume": str(request.quantity),
        }
        if request.order_type == OrderType.LIMIT:
            if request.price is None:
                raise ValueError("LIMIT 주문은 price가 필요합니다.")
            params["price"] = str(request.price)
        elif request.order_type == OrderType.MARKET and request.side == OrderSide.BUY:
            # Upbit 시장가 매수는 price(금액) 기준
            params.pop("volume", None)
            params["price"] = str(request.quantity)  # 여기서 quantity = KRW 금액

        logger.info("주문 요청: %s", params)
        resp = await self._client.post(
            "/v1/orders",
            json=params,
            headers=self._auth_headers(params),
        )
        resp.raise_for_status()
        data = resp.json()
        return self._parse_order_result(data)

    async def cancel_order(self, order_id: str) -> bool:
        params = {"uuid": order_id}
        resp = await self._client.delete(
            "/v1/order",
            params=params,
            headers=self._auth_headers(params),
        )
        if resp.status_code == 404:
            logger.warning("취소할 주문을 찾을 수 없음: %s", order_id)
            return False
        resp.raise_for_status()
        logger.info("주문 취소 완료: %s", order_id)
        return True

    async def get_order(self, order_id: str) -> OrderResult:
        params = {"uuid": order_id}
        resp = await self._client.get(
            "/v1/order",
            params=params,
            headers=self._auth_headers(params),
        )
        resp.raise_for_status()
        return self._parse_order_result(resp.json())

    async def get_balance(self, currency: str) -> Decimal:
        balances = await self.get_balances()
        return balances.get(currency.upper(), Decimal("0"))

    async def get_balances(self) -> dict[str, Decimal]:
        resp = await self._client.get(
            "/v1/accounts",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return {
            item["currency"]: Decimal(item["balance"])
            for item in resp.json()
        }

    # ── 추가 API ──────────────────────────────────────────────────────────────

    async def get_candles(
        self, symbol: str, interval: int = 1, count: int = 200
    ) -> list[dict]:
        """분봉 OHLCV 조회. interval: 분 단위 (1, 3, 5, 15, 30, 60, 240)."""
        resp = await self._client.get(
            f"/v1/candles/minutes/{interval}",
            params={"market": symbol, "count": count},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_ticker(self, symbols: list[str]) -> list[dict]:
        """현재가 조회."""
        markets = ",".join(symbols)
        resp = await self._client.get(
            "/v1/ticker",
            params={"markets": markets},
        )
        resp.raise_for_status()
        return resp.json()

    # ── 파싱 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_order_result(data: dict) -> OrderResult:
        executed_price = data.get("avg_price") or data.get("price") or "0"
        return OrderResult(
            order_id=data["uuid"],
            symbol=data["market"],
            side=OrderSide(data["side"]),
            status=data["state"],
            executed_qty=Decimal(data.get("executed_volume") or "0"),
            executed_price=Decimal(executed_price),
        )

    async def close(self) -> None:
        await self._client.aclose()
