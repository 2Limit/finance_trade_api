"""
BinanceRestClient: Binance REST API v3 구현체

인증:
    - HMAC-SHA256 서명 (Upbit의 JWT와 다름)
    - X-MBX-APIKEY 헤더 + signature 쿼리 파라미터

심볼 규칙:
    - Binance: "BTCUSDT", "ETHUSDT" (구분자 없음)
    - 내부 포맷 "BTC/USDT" → to_binance_symbol() 변환

주요 엔드포인트:
    POST   /api/v3/order          주문 제출
    DELETE /api/v3/order          주문 취소
    GET    /api/v3/order          주문 조회
    GET    /api/v3/account        잔고 조회
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from broker.base import AbstractBroker, OrderRequest, OrderResult, OrderSide, OrderType

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com"


def to_binance_symbol(symbol: str) -> str:
    """내부 심볼 → Binance 심볼. 'BTC/USDT' → 'BTCUSDT', 'BTCUSDT' → 'BTCUSDT'."""
    return symbol.replace("/", "").replace("-", "").upper()


class BinanceRestClient(AbstractBroker):
    """
    Binance Spot REST API 클라이언트.

    사용 예:
        broker = BinanceRestClient(api_key="...", secret_key="...")
        result = await broker.place_order(OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.001"),
        ))
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = BINANCE_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key.encode()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=10.0,
            headers={
                "X-MBX-APIKEY": api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    # ── 인증 ────────────────────────────────────────────────────────────────

    def _sign(self, params: dict) -> str:
        """파라미터 dict → HMAC-SHA256 서명."""
        query = urlencode(params)
        return hmac.new(self._secret_key, query.encode(), hashlib.sha256).hexdigest()

    def _signed_params(self, params: dict) -> dict:
        """timestamp + signature 추가."""
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._sign(params)
        return params

    # ── AbstractBroker 구현 ─────────────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> OrderResult:
        symbol = to_binance_symbol(request.symbol)
        params: dict = {
            "symbol": symbol,
            "side": request.side.value.upper(),   # BUY | SELL
            "type": request.order_type.value.upper(),  # MARKET | LIMIT
        }

        if request.order_type == OrderType.MARKET:
            if request.side == OrderSide.BUY:
                # 시장가 매수: quoteOrderQty (USDT 금액 기준)
                params["quoteOrderQty"] = str(request.quantity)
            else:
                params["quantity"] = str(request.quantity)
        else:  # LIMIT
            if request.price is None:
                raise ValueError("LIMIT 주문은 price가 필요합니다.")
            params["quantity"] = str(request.quantity)
            params["price"] = str(request.price)
            params["timeInForce"] = "GTC"

        resp = await self._client.post(
            "/api/v3/order",
            data=urlencode(self._signed_params(params)),
        )
        resp.raise_for_status()
        return self._parse_order(resp.json(), request.symbol)

    async def cancel_order(self, order_id: str) -> bool:
        # order_id 형식: "<symbol>:<orderId>" 또는 orderId만
        parts = order_id.split(":", 1)
        if len(parts) == 2:
            symbol, oid = parts
        else:
            logger.error("Binance cancel_order: 심볼 정보 없음 ('%s'). '<symbol>:<orderId>' 형식 필요", order_id)
            return False

        params = self._signed_params({
            "symbol": to_binance_symbol(symbol),
            "orderId": int(oid),
        })
        resp = await self._client.delete(
            "/api/v3/order",
            params=params,
        )
        if resp.status_code == 400:
            logger.warning("Binance 주문 취소 실패: %s", resp.text)
            return False
        resp.raise_for_status()
        return True

    async def get_order(self, order_id: str) -> OrderResult:
        parts = order_id.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Binance get_order: '<symbol>:<orderId>' 형식 필요, got '{order_id}'")
        symbol, oid = parts
        params = self._signed_params({
            "symbol": to_binance_symbol(symbol),
            "orderId": int(oid),
        })
        resp = await self._client.get("/api/v3/order", params=params)
        resp.raise_for_status()
        return self._parse_order(resp.json(), symbol)

    async def get_balance(self, currency: str) -> Decimal:
        balances = await self.get_balances()
        return balances.get(currency.upper(), Decimal("0"))

    async def get_balances(self) -> dict[str, Decimal]:
        params = self._signed_params({})
        resp = await self._client.get("/api/v3/account", params=params)
        resp.raise_for_status()
        data = resp.json()
        return {
            b["asset"]: Decimal(b["free"]) + Decimal(b["locked"])
            for b in data.get("balances", [])
            if Decimal(b["free"]) + Decimal(b["locked"]) > 0
        }

    # ── 추가 API ────────────────────────────────────────────────────────────

    async def get_candles(
        self, symbol: str, interval: str = "1m", limit: int = 200
    ) -> list[dict]:
        """K-line OHLCV 조회. interval: '1m', '5m', '1h', '1d' 등."""
        resp = await self._client.get(
            "/api/v3/klines",
            params={
                "symbol": to_binance_symbol(symbol),
                "interval": interval,
                "limit": limit,
            },
        )
        resp.raise_for_status()
        return [
            {
                "open_time": row[0],
                "open":  row[1],
                "high":  row[2],
                "low":   row[3],
                "close": row[4],
                "volume": row[5],
            }
            for row in resp.json()
        ]

    async def get_ticker(self, symbol: str) -> dict:
        """현재가 조회."""
        resp = await self._client.get(
            "/api/v3/ticker/price",
            params={"symbol": to_binance_symbol(symbol)},
        )
        resp.raise_for_status()
        return resp.json()

    # ── 파싱 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_order(data: dict, original_symbol: str) -> OrderResult:
        executed_qty   = Decimal(str(data.get("executedQty",   "0")))
        cummulative_quote = Decimal(str(data.get("cummulativeQuoteQty", "0")))
        executed_price = (
            cummulative_quote / executed_qty
            if executed_qty > 0
            else Decimal(str(data.get("price", "0")))
        )
        # order_id에 심볼 정보 포함 (취소/조회 시 필요)
        order_id = f"{original_symbol}:{data['orderId']}"
        return OrderResult(
            order_id=order_id,
            symbol=original_symbol,
            side=OrderSide(data["side"].lower()),
            status=data["status"],
            executed_qty=executed_qty,
            executed_price=executed_price,
        )

    async def close(self) -> None:
        await self._client.aclose()
