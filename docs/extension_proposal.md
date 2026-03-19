# 프로그램 확장 제안서 (Extension Proposal)

> 자동화 암호화폐 트레이딩 시스템
> 작성일: 2026-03-19 | 최종 수정: 2026-03-19 | 버전: 2.0

---

## 개요

초기 MVP(단일 전략 · 단일 거래소 · 단일 심볼)에서 출발하여 1차 확장을 완료하였습니다.
현재 시스템은 **DB 영속화 · Alembic 마이그레이션 · 멀티 심볼 백테스트 · 파라미터 최적화 · 일일 리포트 · Email 알림 · 통합 테스트** 를 갖춘 안정화 단계에 있습니다.
본 제안서는 남은 안정화 항목과 이후 기능 확장 · 아키텍처 고도화의 우선순위 로드맵을 제시합니다.

---

## 완료된 항목 (2026-03-19 기준)

| 구분 | 항목 | 파일 |
|------|------|------|
| 안정화 | Alembic 마이그레이션 (7개 테이블) | `alembic/` |
| 안정화 | 일일 손실 카운터 자동 리셋 | `execution/risk.py` + `scheduler.py` |
| 안정화 | 포지션 내역 DB 영속화 | `db/models/position.py` |
| 안정화 | 잔고 이력 DB 저장 | `db/models/balance.py` |
| 안정화 | 통합·E2E 테스트 16개 추가 (총 100개) | `tests/integration/` |
| 기능 | Email 알림 (aiosmtplib) | `alert/email.py` |
| 기능 | 멀티 심볼 백테스트 | `backtest/runner.py` |
| 기능 | 파라미터 최적화 Grid Search | `backtest/optimizer.py` |
| 기능 | 일일 리포트 생성 | `report/daily_report.py` |

---

## Phase 1 — 안정화 잔여 (Stability Remaining) `우선순위: 높음`

Phase 1 중 아직 구현되지 않은 2개 항목입니다. 운영 투입 전 반드시 완료해야 합니다.

### 1.1 손절매 / 익절매 (Stop-Loss / Take-Profit) `★★★ 최우선`

**배경**: 전략 시그널(MA 크로스)이 늦게 반응하는 구간에서 급격한 손실이 무제한으로 누적될 수 있습니다.

**제안 사항**:
```python
# execution/stop_loss.py
@dataclass
class StopLossConfig:
    stop_loss_pct: float = 0.05    # -5% 이하 자동 손절
    take_profit_pct: float = 0.10  # +10% 이상 자동 익절

class StopLossMonitor:
    """PRICE_UPDATED 이벤트마다 보유 포지션 수익률 체크."""
    async def on_price_updated(self, event: Event) -> None:
        for symbol, position in self._position_mgr.get_all_positions().items():
            pnl_pct = float(position.unrealized_pnl(price) / (position.avg_price * position.quantity))
            if pnl_pct <= -self._config.stop_loss_pct:
                await self._event_bus.publish(Event(SIGNAL_GENERATED, {"signal": "SELL", ...}))
            elif pnl_pct >= self._config.take_profit_pct:
                await self._event_bus.publish(Event(SIGNAL_GENERATED, {"signal": "SELL", ...}))
```

**기대 효과**: 전략과 독립적인 리스크 하한선 · 목표 수익 자동 실현

---

### 1.2 중복 주문 방지 (Order Deduplication) `★★★ 최우선`

**배경**: WebSocket 시세가 연속으로 수신될 때 SIGNAL_GENERATED 이벤트가 연속 발행되면 동일 심볼에 중복 주문이 제출될 수 있습니다.

**제안 사항**:
```python
# execution/order_manager.py 에 추가
class OrderManager:
    _last_order_time: dict[str, datetime] = {}
    ORDER_COOLDOWN_SEC: int = 60  # 설정 가능

    async def on_signal(self, event: Event) -> None:
        symbol = event.payload["symbol"]
        now = datetime.now(timezone.utc)
        last = self._last_order_time.get(symbol)
        if last and (now - last).total_seconds() < self.ORDER_COOLDOWN_SEC:
            logger.info("쿨다운 중 — 중복 주문 스킵: %s", symbol)
            return
        self._last_order_time[symbol] = now
        ...
```

**기대 효과**: 슬리피지 및 불필요한 수수료 방지

---

## Phase 2 — 기능 확장 (Feature Enhancement) `우선순위: 중간`

안정화 완료 후 트레이딩 성능과 운용 편의를 높입니다.

### 2.1 신규 전략 추가 `★★☆`

기존 `StrategyRegistry` + `AbstractStrategy` 구조를 그대로 활용합니다.

**RSI 전략 (`strategy/impl/rsi_strategy.py`)**:
- 과매도 구간(RSI < 30) 진입 후 30 회복 시 BUY
- 과매수 구간(RSI > 70) 진입 후 70 이탈 시 SELL

**볼린저 밴드 전략 (`strategy/impl/bollinger_strategy.py`)**:
- 하단 밴드 터치 후 반등 시 BUY, 상단 밴드 터치 후 하락 시 SELL

**MACD 전략 (`strategy/impl/macd_strategy.py`)**:
- MACD 라인이 시그널 라인을 상향 돌파 시 BUY, 하향 이탈 시 SELL

**등록 방법**: `StrategyRegistry.register("rsi", RsiStrategy)` 한 줄로 즉시 사용 가능

---

### 2.2 전략 앙상블 (Strategy Aggregator) `★★☆`

**배경**: 단일 전략의 오신호를 여러 전략의 합의로 필터링하여 정확도를 높입니다.

**제안 사항**:
```python
# strategy/aggregator.py
class StrategyAggregator:
    """여러 전략의 시그널을 투표로 취합."""
    def aggregate(self, signals: list[Signal | None]) -> Signal | None:
        buy_votes  = sum(1 for s in signals if s and s.signal_type == SignalType.BUY)
        sell_votes = sum(1 for s in signals if s and s.signal_type == SignalType.SELL)
        threshold  = len(signals) * 0.6   # 60% 이상 동의 시 발행
        if buy_votes / len(signals) >= threshold:
            return Signal(signal_type=SignalType.BUY, ...)
        if sell_votes / len(signals) >= threshold:
            return Signal(signal_type=SignalType.SELL, ...)
        return None
```

---

### 2.3 포지션 분할 매수/매도 (DCA) `★★☆`

**배경**: 단일 주문보다 분할 진입/청산으로 가격 리스크를 분산합니다.

**제안 사항**:
- BUY 시그널 시 시그널 강도(strength)에 비례한 3회 분할 매수
- SELL 시그널 시 50% 부분 매도 → 추가 조건 충족 시 잔여 청산
- `OrderManager` 에 `split_count`, `split_interval_sec` 설정 추가

---

### 2.4 멀티 거래소 지원 `★☆☆`

**배경**: `AbstractBroker` / `AbstractMarketFeed` 가 이미 추상화되어 있어 구현 비용이 낮습니다.

```
broker/
├── upbit/      (완료)
├── binance/    ← REST + WebSocket 추가
└── bithumb/    ← REST + WebSocket 추가
```

**기대 효과**: 거래소 간 가격 차이를 활용한 차익거래(arbitrage) 전략 기반 마련

---

### 2.5 백테스트 결과 시각화 `★☆☆`

**배경**: 현재 `print_summary()` 텍스트 출력만 지원합니다.

**제안 사항**:
- `matplotlib` 기반 자산 곡선 · 드로다운 · 거래 표시 차트
- HTML 리포트 자동 생성 (`backtest/report.py`)
- 파라미터 최적화 결과 히트맵 시각화

---

## Phase 3 — 아키텍처 고도화 (Architecture) `우선순위: 낮음 (장기)`

서비스 규모가 커질 때 대비한 구조적 개선입니다.

### 3.1 REST API 서버 (FastAPI) `★★☆`

**배경**: CLI 전용 구조에서 웹 대시보드 · 외부 시스템 연동을 가능하게 합니다.

```
api/
├── main.py              # FastAPI app (asyncio 공유)
├── routers/
│   ├── portfolio.py     # GET /positions, /balances
│   ├── orders.py        # GET /orders, POST /orders/cancel
│   ├── backtest.py      # POST /backtest/run
│   └── strategy.py      # GET/PATCH /strategy/config
└── schemas/             # Pydantic 요청/응답 스키마
```

**기대 효과**: React/Vue 대시보드, 모바일 앱, Webhook 연동

---

### 3.2 분산 이벤트 버스 (Redis Pub/Sub) `★☆☆`

**배경**: 현재 `EventBus` 는 단일 프로세스 내부 통신 전용입니다. 멀티 프로세스 배포 시 컴포넌트 간 통신이 불가합니다.

```python
# core/redis_event_bus.py
class RedisEventBus(EventBus):
    async def publish(self, event: Event) -> None:
        await self._redis.publish(event.type.value, event.model_dump_json())
```

- 수집 서비스 / 전략 서비스 / 주문 서비스를 별도 컨테이너로 분리 가능
- Kafka로 업그레이드 시 이벤트 순서 보장 및 재처리 지원

---

### 3.3 ML 전략 인터페이스 `★☆☆`

```python
# strategy/impl/ml_strategy.py
class MLStrategy(AbstractStrategy):
    def __init__(self, model_path: str, ...): ...
    def _evaluate(self, features: Features) -> Signal | None:
        X = self._to_feature_vector(features)
        pred = self._model.predict([X])[0]
        ...
```

- `FeatureBuilder.Features` → 고정 크기 벡터 변환 표준화
- 모델 재학습 파이프라인 (MLflow 연동)
- 온라인 학습 지원 (강화학습 에이전트)

---

## 우선순위 로드맵 요약

```
현재 상태 (안정화 1차 완료, 2026-03-19)
    │
    │  ✅ Alembic 마이그레이션
    │  ✅ 일일 손실 자동 리셋
    │  ✅ 포지션·잔고 DB 영속화
    │  ✅ Email 알림
    │  ✅ 멀티 심볼 백테스트 + Grid Search 최적화
    │  ✅ 일일 리포트
    │  ✅ 통합·E2E 테스트 (100개)
    │
    ▼ Phase 1 잔여 (즉시 ~ 2주)         ← 지금 여기
    ├─ 🔴 손절매/익절매 (StopLossMonitor)
    └─ 🔴 중복 주문 방지 (ORDER_COOLDOWN)
    │
    ▼ Phase 2 (1~3개월)
    ├─ 🟡 신규 전략 — RSI, 볼린저, MACD
    ├─ 🟡 전략 앙상블 (StrategyAggregator)
    ├─ 🟡 포지션 분할 매수/매도 (DCA)
    ├─ 🟠 멀티 거래소 — Binance, Bithumb
    └─ 🟠 백테스트 시각화 (matplotlib)
    │
    ▼ Phase 3 (3~6개월 이후)
    ├─ 🔵 FastAPI 대시보드 API
    ├─ 🔵 Redis 분산 이벤트 버스
    └─ 🔵 ML 전략 인터페이스
```

**범례**: 🔴 즉시 착수 · 🟡 높음 · 🟠 중간 · 🔵 장기

---

## 기술 부채 및 주의사항

| 항목 | 현황 | 권장 조치 |
|------|------|-----------|
| SQLite → PostgreSQL | 단일 파일 DB, 동시성 제한 | 운영 환경에서 PostgreSQL 전환 (Alembic 이미 준비됨) |
| API 키 관리 | .env 파일, 평문 저장 | AWS Secrets Manager / HashiCorp Vault 도입 |
| 오류 재시도 로직 | 주문 실패 시 단순 이벤트 발행만 | Exponential Backoff 재시도 + 최대 횟수 제한 |
| 손절매 없음 | 전략 시그널에만 의존 | Phase 1 잔여 항목 (StopLossMonitor) 즉시 구현 |
| 테스트 커버리지 | 단위 84 + 통합·E2E 16 = 100개 | 신규 전략 추가 시 해당 단위 테스트 동시 작성 필수 |
| 로그 수집 | 로컬 파일만 (trading.log) | ELK Stack / CloudWatch 연동 (Phase 3 이후) |
