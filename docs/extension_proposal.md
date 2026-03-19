# 프로그램 확장 제안서 (Extension Proposal)

> 자동화 암호화폐 트레이딩 시스템
> 작성일: 2026-03-19 | 버전: 1.0

---

## 개요

현재 시스템은 단일 전략(MA Crossover), 단일 거래소(Upbit), 단일 심볼 중심의 MVP 수준입니다. 본 제안서는 시스템을 단계별로 확장하여 프로덕션 수준의 멀티 전략 / 멀티 거래소 트레이딩 플랫폼으로 발전시키는 로드맵을 제시합니다.

---

## Phase 1 — 안정화 (Stability) `우선순위: 높음`

현재 구현의 미완성 항목을 마무리하고, 운영 환경에서 안정적으로 동작하도록 기반을 다집니다.

### 1.1 DB 마이그레이션 (Alembic)

**배경**: 현재 `init_db()`가 테이블을 직접 생성하지만, 운영 환경에서 스키마 변경 시 데이터 손실 위험이 있습니다.

**제안 사항**:
- Alembic 마이그레이션 환경 설정 (`alembic init`)
- 초기 스키마 마이그레이션 스크립트 작성
- 스키마 변경 시 자동 diff 생성 (`alembic revision --autogenerate`)

**기대 효과**: 스키마 버전 관리, 롤백 가능, CI/CD 파이프라인 통합 가능

---

### 1.2 손절매 / 익절매 (Stop-Loss / Take-Profit)

**배경**: 현재 시스템은 전략 시그널(MA 크로스)에만 의존하며, 급격한 가격 변동 시 손실을 자동 제한하는 메커니즘이 없습니다.

**제안 사항**:
```python
class StopLossConfig:
    stop_loss_pct: float = 0.05    # -5% 이하 시 자동 손절
    take_profit_pct: float = 0.10  # +10% 이상 시 자동 익절
```
- `RiskManager.check()` 또는 별도 `StopLossMonitor` 컴포넌트에서 주기적으로 포지션 체크
- 조건 충족 시 SIGNAL_GENERATED(SELL) 이벤트 직접 발행

**기대 효과**: 전략 독립적인 리스크 하한선 보장

---

### 1.3 일일 손실 카운터 자동 리셋

**배경**: `RiskManager._daily_loss`는 수동으로만 리셋됩니다.

**제안 사항**:
- `TradingScheduler`에 매일 00:00 KST 리셋 작업 추가
- `RiskManager.reset_daily_loss()` 메서드 추가

---

### 1.4 중복 주문 방지

**배경**: 동일 심볼에 SIGNAL_GENERATED 이벤트가 짧은 시간 내 중복 발생할 경우, 중복 주문이 제출될 수 있습니다.

**제안 사항**:
- `OrderManager`에 심볼별 마지막 주문 시각 추적
- 설정 가능한 쿨다운 인터벌 (예: 60초) 내 중복 주문 무시

---

### 1.5 통합 테스트 추가

**배경**: 현재 단위 테스트 84개는 각 컴포넌트를 독립적으로 검증하지만, 컴포넌트 간 연동 버그는 발견하지 못합니다.

**제안 사항**:
- `on_tick()` → DB 저장 흐름 통합 테스트
- 주문 실행 → 포지션 업데이트 흐름 통합 테스트
- 리스크 트리거 → Discord 알림 발행 흐름 통합 테스트

---

## Phase 2 — 기능 확장 (Feature Enhancement) `우선순위: 중간`

트레이딩 성능을 높이고 사용 편의성을 개선합니다.

### 2.1 신규 전략 추가

**RSI 전략 (`strategy/impl/rsi_strategy.py`)**:
- 과매도 구간(RSI < 30) 진입 후 회복 시 BUY
- 과매수 구간(RSI > 70) 진입 후 하락 시 SELL

**볼린저 밴드 전략 (`strategy/impl/bollinger_strategy.py`)**:
- 하단 밴드 터치 후 반등 시 BUY
- 상단 밴드 터치 후 하락 시 SELL

**MACD 전략 (`strategy/impl/macd_strategy.py`)**:
- MACD 히스토그램 전환점 기반 시그널

**통합 방법**: `StrategyRegistry.register()` 한 줄로 등록, 설정 파일에서 활성화 전략 선택

---

### 2.2 멀티 거래소 지원

**배경**: 현재 Upbit만 지원하며, `AbstractBroker` / `AbstractMarketFeed` 인터페이스는 이미 추상화되어 있습니다.

**제안 사항**:

```
broker/
├── upbit/
│   ├── rest.py
│   └── websocket.py
├── binance/          ← 신규 추가
│   ├── rest.py
│   └── websocket.py
└── bithumb/          ← 신규 추가
    ├── rest.py
    └── websocket.py
```

- 각 거래소 클라이언트가 `AbstractBroker` 구현
- 설정에서 활성 거래소 선택
- 거래소별 수수료율 설정

**기대 효과**: 거래소 간 차익거래(arbitrage) 전략 기반 마련

---

### 2.3 알림 채널 확장

| 채널 | 구현 방법 |
|------|-----------|
| Telegram | `alert/telegram.py` — Bot API |
| Email (SMTP) | `alert/email.py` — aiosmtplib |
| Slack | `alert/slack.py` — Webhook |
| SMS | `alert/sms.py` — Twilio API |

**통합 방법**: `AbstractAlert` 구현, `TradingEngine`에 복수 알림 등록 지원

---

### 2.4 백테스트 강화

**멀티 심볼 백테스트**:
```python
runner = BacktestRunner.from_prices(
    strategy=strategy,
    symbols=["KRW-BTC", "KRW-ETH"],
    price_data={"KRW-BTC": btc_prices, "KRW-ETH": eth_prices},
)
```

**파라미터 최적화 (Grid Search)**:
```python
optimizer = StrategyOptimizer(
    strategy_cls=MACrossoverStrategy,
    param_grid={"short_window": [5, 10], "long_window": [20, 50]},
    candles=historical_candles,
)
best_params = optimizer.run()
```

**백테스트 결과 시각화**:
- matplotlib 기반 자산 곡선, 드로다운 차트
- HTML 리포트 자동 생성

---

### 2.5 포지션 분할 매수/매도 (DCA)

**배경**: 현재는 시그널 발생 시 단일 주문 실행. DCA(Dollar-Cost Averaging) 방식으로 리스크 분산 가능.

**제안 사항**:
- BUY 시그널 시 3회로 분할 매수 (시그널 강도 기반 비중 차등)
- SELL 시그널 시 50% 부분 매도 후 추가 하락 시 잔여 매도

---

## Phase 3 — 아키텍처 고도화 (Architecture) `우선순위: 낮음 (장기)`

시스템 규모가 커질 때 대비한 구조적 개선입니다.

### 3.1 REST API 서버 (FastAPI)

**배경**: 현재 CLI만 지원. 웹 대시보드, 외부 시스템 연동을 위한 API 서버 필요.

**제안 사항**:
```
api/
├── main.py              # FastAPI app
├── routers/
│   ├── portfolio.py     # 포트폴리오 조회
│   ├── orders.py        # 주문 내역 조회
│   ├── backtest.py      # 백테스트 실행 API
│   └── strategy.py      # 전략 설정 변경 API
└── schemas/             # Pydantic 스키마
```

**기대 효과**: React/Vue 기반 대시보드 연동, 모바일 앱 연동

---

### 3.2 메시지 큐 (Redis / Kafka)

**배경**: 현재 `EventBus`는 인프로세스(in-process) pub/sub. 멀티 프로세스 / 마이크로서비스 확장 시 분산 이벤트 버스 필요.

**제안 사항**:
```python
class RedisEventBus(EventBus):
    """Redis Pub/Sub 기반 분산 이벤트 버스"""
    async def publish(self, event: Event) -> None:
        await self._redis.publish(event.type.value, event.json())
```

- 데이터 수집 서비스, 전략 서비스, 주문 서비스를 별도 프로세스/컨테이너로 분리
- 각 서비스가 Redis 채널 구독

---

### 3.3 전략 앙상블 (Strategy Aggregator)

**배경**: 단일 전략의 오신호를 여러 전략의 합의로 필터링.

**제안 사항**:
```python
class StrategyAggregator:
    """여러 전략의 시그널을 취합하여 최종 시그널 결정"""
    def aggregate(self, signals: list[Signal | None]) -> Signal | None:
        buy_votes = sum(1 for s in signals if s and s.signal_type == SignalType.BUY)
        sell_votes = sum(1 for s in signals if s and s.signal_type == SignalType.SELL)
        threshold = len(signals) * 0.6  # 60% 이상 동의 시 시그널 발행
        ...
```

---

### 3.4 ML 전략 인터페이스

**배경**: 룰 기반 전략 외에 머신러닝 모델 기반 시그널 생성 지원.

**제안 사항**:
```python
class MLStrategy(AbstractStrategy):
    """scikit-learn / PyTorch 모델 기반 전략"""
    def __init__(self, model_path: str, ...):
        self._model = joblib.load(model_path)

    def _evaluate(self, features: Features) -> Signal | None:
        X = self._extract_feature_vector(features)
        pred = self._model.predict([X])[0]
        ...
```

- 피처 벡터 추출 표준화
- 모델 재학습 파이프라인 (MLflow 연동)

---

## 우선순위 로드맵 요약

```
현재 (MVP)
    │
    ▼ Phase 1 (1~2개월)
    ├─ Alembic 마이그레이션
    ├─ 손절매/익절매
    ├─ 중복 주문 방지
    └─ 통합 테스트 추가
    │
    ▼ Phase 2 (3~6개월)
    ├─ 신규 전략 (RSI, 볼린저, MACD)
    ├─ 바이낸스 / 빗썸 지원
    ├─ 알림 채널 확장 (Telegram, Email)
    ├─ 백테스트 파라미터 최적화
    └─ 포지션 분할 매수/매도
    │
    ▼ Phase 3 (6개월~)
    ├─ FastAPI 대시보드 API
    ├─ Redis 분산 이벤트 버스
    ├─ 전략 앙상블
    └─ ML 전략 인터페이스
```

---

## 기술 부채 및 주의사항

| 항목 | 현황 | 권장 조치 |
|------|------|-----------|
| SQLite → PostgreSQL | 단일 파일 DB, 동시성 제한 | 운영 환경에서 PostgreSQL 전환 권장 |
| API 키 관리 | .env 파일, 평문 저장 | AWS Secrets Manager / Vault 도입 권장 |
| 오류 재시도 로직 | 주문 실패 시 단순 이벤트 발행만 | Exponential Backoff 재시도 구현 |
| 테스트 커버리지 | 단위 84개, 통합 0개 | 통합 테스트 우선 보완 |
| 로그 수집 | 로컬 파일만 | ELK Stack / CloudWatch 연동 권장 |
