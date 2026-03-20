# 프로그램 기능 설명서 (Program Functionality Description)

> 자동화 암호화폐 트레이딩 시스템 — Upbit 거래소 대상 (멀티 거래소 확장 가능)
> 작성일: 2026-03-19 | 최종 수정: 2026-03-20 | 버전: 2.1

---

## 1. 시스템 개요

본 시스템은 Upbit 암호화폐 거래소를 대상으로 실시간 시세 수집, 전략 기반 시그널 생성, 자동 주문 실행, 리스크 관리, 알림 발송, 실시간 대시보드를 수행하는 완전 자동화 트레이딩 시스템입니다.

Python 3.11+ `asyncio` 기반의 비동기 이벤트 루프 위에서 동작하며, 이벤트 드리븐 아키텍처(Event-Driven Architecture)를 채택하여 컴포넌트 간 결합도를 최소화합니다.

---

## 2. 시스템 아키텍처

```text
┌─────────────────────────────────────────────────────────────────┐
│                        main.py / TradingEngine                  │
│  (전체 컴포넌트 조립, 이벤트 라우팅, Graceful Shutdown)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ EventBus (pub/sub) — in-memory 또는 Redis
         ┌──────────────────┼──────────────────┬──────────────────┐
         ▼                  ▼                  ▼                  ▼
┌─────────────┐   ┌──────────────────┐   ┌────────────────┐  ┌──────────┐
│  WebSocket  │   │  Strategy Engine │   │  Order Manager │  │Dashboard │
│    Feed     │   │  MA / RSI /      │   │  (주문 실행)    │  │WebSocket │
│ (실시간 시세)│   │  Bollinger /MACD │   │  RiskManager   │  │  push    │
└──────┬──────┘   └────────┬─────────┘   └───────┬────────┘  └──────────┘
       │                   │                      │
       ▼                   ▼                      ▼
┌─────────────┐   ┌──────────────────┐   ┌────────────────────────────┐
│  Market     │   │  SignalModel     │   │  OrderModel  (주문 원장)    │
│  Snapshot   │   │  DB 저장         │   │  TradeModel  (체결 내역)    │
│ (인메모리)   │   └──────────────────┘   │  exchange 컬럼 (거래소 구분)│
└─────────────┘                          └────────────────────────────┘
       │
       ▼
┌─────────────┐   ┌──────────────────┐   ┌────────────────┐
│  Scheduler  │   │  PositionManager │   │  DiscordAlert  │
│ (주기적 작업)│   │  AccountManager  │   │  (알림 발송)   │
└─────────────┘   └──────────────────┘   └────────────────┘
```

---

## 3. 데이터 흐름

### 3.1 실시간 트레이딩 파이프라인

```text
Upbit WebSocket
    │
    │ (ticker 메시지)
    ▼
UpbitWebSocketFeed.on_message()
    │ MarketSnapshot.update_tick()
    │ EventBus.publish(PRICE_UPDATED)
    ▼
TradingEngine.on_price_updated()
    │
    ├─► FeatureBuilder.build(symbol)
    │       └─ sma(), ema(), rsi(), bollinger_bands(), macd() 계산
    │
    ├─► strategy._evaluate(features)   ← MA / RSI / Bollinger / MACD / ML
    │       └─ Signal 생성 (BUY/SELL/None)
    │
    └─► if signal:
            EventBus.publish(SIGNAL_GENERATED)
                │
                ├─► WebSocketManager.on_event()    ← 대시보드 실시간 push
                │
                └─► OrderManager.on_signal()
                        │
                        ├─► SignalModel DB 저장 (쿨다운 전, 모든 시그널 기록)
                        │
                        │ [쿨다운 검사 — 중복 주문 방지]
                        │ [RiskManager.check() — 3단계 검증]
                        │
                        ├─► broker.place_order()
                        │       └─ _get_broker(symbol): 심볼별 거래소 라우팅
                        │
                        ├─► OrderModel DB 저장
                        ├─► TradeModel DB 저장 (exchange 컬럼 포함)
                        │
                        └─► EventBus.publish(ORDER_FILLED)
                                │
                                ├─► PositionManager.on_order_filled()
                                │       └─ 보유 수량 / 평균단가 갱신
                                │       └─ PositionModel DB 저장
                                │
                                ├─► WebSocketManager.on_event()  ← 대시보드 push
                                │
                                └─► DiscordAlert.on_order_filled()
                                        └─ Discord Embed 전송
```

### 3.2 스케줄러 파이프라인

```text
APScheduler (AsyncIOScheduler)
    │
    ├─► [매 1분] MarketCollector.fetch_and_store()
    │       └─ REST API 캔들 조회
    │       └─ MarketSnapshot 업데이트
    │       └─ CandleModel DB 저장 (중복 방지)
    │
    ├─► [매 10분] AccountManager.sync()
    │       └─ REST API 잔고 조회
    │       └─ _balance 갱신
    │
    └─► [매일 09:00] DailyReportGenerator.generate()
            └─ 일일 거래 요약 → Discord 전송
```

### 3.3 백테스트 파이프라인

```text
BacktestRunner.from_prices(prices)
    │ 가격 리스트 → Candle 객체 변환
    ▼
BacktestRunner.run()
    │
    ├─► strategy.required_candles() → FeatureBuilder snapshot_limit 설정
    │
    ├─► 캔들 순차 처리 (warm-up 구간 건너뜀)
    ├─► MarketSnapshot 업데이트
    ├─► FeatureBuilder.build() — 지표 계산
    ├─► strategy._evaluate(features) — 시그널 결정
    │       (DB 저장 없음, 순수 로직만)
    │
    ├─► BUY: SimulatedPortfolio.buy()
    │   SELL: SimulatedPortfolio.sell()
    │
    └─► BacktestResult 반환
            ├─ total_return / total_return_pct
            ├─ win_rate / profit_factor / max_drawdown
            └─ 거래 내역 (BacktestTrade 리스트)
```

### 3.4 실시간 대시보드 WebSocket 브리지

```text
[in-memory 모드: Redis 없음]
    EventBus.publish(event)
        └─► WebSocketManager.on_event(event)  ← EventBus 직접 구독
                └─► ws.send_text(JSON)  → 브라우저 실시간 반영

[Redis 모드: 별도 프로세스]
    RedisEventBus → Redis Stream "events:all"
        └─► WebSocketManager.start_redis_reader()
                └─► ws.send_text(JSON)  → 브라우저 실시간 반영
```

---

## 4. 주요 컴포넌트 설명

### 4.1 EventBus (`core/event.py`, `core/event_bus_redis.py`)

| 기능 | 설명 |
|------|------|
| subscribe(type, handler) | 이벤트 타입에 비동기 핸들러 등록 |
| publish(event) | 해당 타입의 모든 핸들러를 순차 호출 |
| 예외 격리 | 하나의 핸들러 실패가 다른 핸들러에 영향 없음 |
| Redis 모드 | RedisEventBus: Redis Streams fan-out + Pub/Sub 파라미터 갱신 |

**이벤트 타입:**

| EventType | 발행 시점 | 주요 구독자 |
|-----------|-----------|-------------|
| PRICE_UPDATED | WebSocket ticker 수신 | TradingEngine, StopLossMonitor, ws_manager |
| SIGNAL_GENERATED | 전략 시그널 생성 | OrderManager, DiscordAlert, ws_manager |
| ORDER_FILLED | 주문 체결 | PositionManager, DiscordAlert, ws_manager |
| ORDER_FAILED | 주문 실패 | DiscordAlert, ws_manager |
| RISK_TRIGGERED | 리스크 한도 초과 | DiscordAlert, ws_manager |
| POSITION_UPDATED | 포지션 변경 | (확장용) |
| BALANCE_UPDATED | 잔고 변경 | (확장용) |

---

### 4.2 FeatureBuilder (`data/processor/feature_builder.py`)

MarketSnapshot에서 캔들 데이터를 읽어 기술적 지표를 계산하고 `Features` 객체로 반환합니다.

| 속성 | 설명 |
|------|------|
| current_price | 마지막 캔들 종가 |
| sma_short / sma_long | 단기/장기 SMA |
| rsi_14 | RSI (기본: 14봉) |
| close_prices | 최근 캔들 종가 목록 (Bollinger/MACD 계산용) |
| is_golden_cross / is_dead_cross | SMA 크로스 상태 |
| is_overbought / is_oversold | RSI 과매수/과매도 상태 |

`snapshot_limit` 파라미터로 조회할 캔들 수를 제어합니다. BacktestRunner는 `strategy.required_candles()`를 사용해 각 전략에 필요한 최소 캔들 수를 보장합니다.

---

### 4.3 전략 (strategy/impl/)

| 전략 | 파일 | 신호 조건 |
|------|------|-----------|
| MA Crossover | ma_crossover.py | 골든/데드크로스 + RSI 필터 |
| RSI | rsi_strategy.py | 과매도→30 회복 시 BUY, 과매수→70 이탈 시 SELL |
| Bollinger Bands | bollinger_strategy.py | 하단 밴드 이탈 시 BUY, 상단 밴드 이탈 시 SELL |
| MACD | macd_strategy.py | MACD 라인이 시그널 라인 상향 돌파 시 BUY |
| ML | ml_strategy.py | scikit-learn / lightgbm 모델 예측 |
| Aggregator | aggregator.py | 다수결 앙상블 (threshold 60%) |

모든 전략은 `required_candles() -> int`로 필요한 최소 캔들 수를 선언합니다.

---

### 4.4 데이터 추적 파이프라인

```text
시그널 생성
  └─► SignalModel 저장 (strategy_name, symbol, signal_type, strength, metadata)
          ↓
주문 체결
  └─► OrderModel 저장 (주문 원장, 상태 추적)
  └─► TradeModel 저장 (체결 내역, exchange 컬럼으로 거래소 구분)
          ↓
포지션 변경
  └─► PositionModel 저장 (avg_price, unrealized_pnl)
          ↓
분석 · 추적
  └─► TradeRepository.get_daily_pnl()       → 일별 손익
  └─► SignalRepository.get_by_strategy()    → 전략별 시그널 정확도 분석
  └─► WebSocket push                        → 대시보드 실시간 반영
```

**모든 저장은 `OrderManager._submit()` 단일 경로를 통과하므로 MA/RSI/Bollinger/MACD/ML 등 어떤 전략이 추가되어도 별도 코드 없이 자동 적용됩니다.**

---

### 4.5 RiskManager (`execution/risk.py`)

3단계 순차 검증:

```text
1단계: 단일 주문 금액 한도 (max_order_krw)
    → 초과 시: qty 자동 축소 후 승인

2단계: 일일 손실 한도 (매도 시만, max_daily_loss_krw)
    → 미실현 손실 > 한도 시 거부 + RISK_TRIGGERED 발행

3단계: 포지션 비중 한도 (매수 시만, max_position_ratio)
    → 주문금액 / (가용잔고 + 주문금액) > 한도 시 거부
```

---

### 4.6 SimulatedPortfolio (`backtest/runner.py`)

백테스트 전용 가상 포트폴리오:

| 메서드 | 동작 |
|--------|------|
| buy(symbol, price, time) | 잔고 × order_ratio 만큼 매수, 수수료 차감 |
| sell(symbol, price, time) | 전량 매도, 손익 계산, 포지션 청산 |
| max_drawdown() | 자산 이력 기반 최대 낙폭 계산 |
| sharpe_ratio(rf) | 수익률 표준편차 기반 샤프 비율 |

---

## 5. 설정 구조

```text
config/
├── base.py       # 공통 설정 (pydantic BaseSettings)
├── dev.py        # 개발 환경 오버라이드
├── prod.py       # 운영 환경 오버라이드
└── logging.yaml  # 로깅 설정 (rotating file handler)
```

주요 설정 항목:

| 항목 | 기본값 | 설명 |
|------|--------|------|
| UPBIT_ACCESS_KEY | (필수) | Upbit API 접근 키 |
| UPBIT_SECRET_KEY | (필수) | Upbit API 시크릿 키 |
| DB_URL | sqlite+aiosqlite:///... | DB 연결 문자열 |
| REDIS_URL | "" | Redis 연결 URL (비어있으면 in-memory 모드) |
| EVENT_BUS_BACKEND | "memory" | "memory" 또는 "redis" |
| SYMBOLS | ["KRW-BTC"] | 거래 대상 심볼 목록 |
| MAX_ORDER_KRW | 500,000 | 단일 주문 최대 금액 |
| MAX_DAILY_LOSS_KRW | 1,000,000 | 일일 최대 손실 허용 금액 |
| MAX_POSITION_RATIO | 0.3 | 포트폴리오 대비 최대 포지션 비중 |
| STOP_LOSS_PCT | 0.05 | 손절매 비율 (-5%) |
| TAKE_PROFIT_PCT | 0.10 | 익절매 비율 (+10%) |
| DISCORD_WEBHOOK_URL | (선택) | Discord 알림 웹훅 URL |

---

## 6. 디렉토리 구조

```text
finance_trade_api/
├── main.py                  # 진입점, 컴포넌트 조립
├── scheduler.py             # APScheduler 래퍼
├── config/                  # 환경 설정
├── core/
│   ├── event.py             # EventBus, EventType
│   ├── engine.py            # TradingEngine (이벤트 라우터)
│   └── event_bus_redis.py   # RedisEventBus (분산 이벤트 버스)
├── broker/
│   ├── base.py              # AbstractBroker (exchange_name 속성 포함)
│   └── upbit/
│       ├── rest.py          # REST API 클라이언트 (exchange_name="upbit")
│       └── websocket.py     # WebSocket 피드
├── market/
│   ├── feed.py              # AbstractMarketFeed
│   └── snapshot.py          # MarketSnapshot (인메모리)
├── data/
│   ├── collector/           # 데이터 수집기
│   └── processor/
│       ├── feature_builder.py  # FeatureBuilder (snapshot_limit 지원)
│       └── indicators/      # sma, ema, rsi, bollinger, macd
├── strategy/
│   ├── base.py              # AbstractStrategy (required_candles, param_schema)
│   ├── registry.py          # StrategyRegistry
│   ├── store.py             # StrategyStore (Redis 동기화 지원)
│   ├── aggregator.py        # StrategyAggregator (앙상블)
│   └── impl/
│       ├── ma_crossover.py
│       ├── rsi_strategy.py
│       ├── bollinger_strategy.py
│       ├── macd_strategy.py
│       └── ml_strategy.py
├── execution/
│   ├── order_manager.py     # 주문 관리 (SignalModel + TradeModel 저장 연결)
│   ├── risk.py              # 리스크 관리
│   └── stop_loss.py         # StopLossMonitor (손절매/익절매)
├── portfolio/
│   ├── account.py           # AccountManager
│   └── position.py          # PositionManager
├── alert/
│   ├── base.py              # AbstractAlert
│   ├── discord.py           # Discord 알림
│   └── email.py             # Email 알림 (aiosmtplib)
├── api/
│   └── dashboard.py         # FastAPI 대시보드 (WebSocket push 지원)
├── backtest/
│   ├── runner.py            # BacktestRunner, SimulatedPortfolio
│   ├── optimizer.py         # Grid Search 파라미터 최적화
│   └── visualization.py     # matplotlib 차트 (adaptive X-axis)
├── report/
│   └── daily_report.py      # 일일 리포트 생성기
├── db/
│   ├── base.py              # SQLAlchemy Base
│   ├── session.py           # 세션 관리
│   ├── models/              # ORM 모델 (7개 테이블)
│   └── repositories/        # Repository 패턴 (SignalRepository 포함)
├── tests/
│   ├── conftest.py          # 공유 픽스처
│   ├── unit/                # 단위 테스트
│   └── integration/         # 통합·E2E 테스트
└── docs/                    # 문서
```

---

## 7. 기술 스택

| 분류 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| 비동기 | asyncio, aiohttp |
| DB ORM | SQLAlchemy 2.x (async), aiosqlite |
| 설정 관리 | pydantic-settings |
| 스케줄러 | APScheduler (AsyncIOScheduler) |
| 인증 | JWT (PyJWT), SHA512 |
| 테스트 | pytest, pytest-asyncio |
| 알림 | Discord Webhook (aiohttp), Email (aiosmtplib) |
| 대시보드 | FastAPI + Bootstrap 5 + WebSocket |
| 분산 버스 | Redis Streams + Pub/Sub (redis[hiredis]) |
| 시각화 | matplotlib (backtest 차트, adaptive X-axis) |
| ML | scikit-learn / lightgbm (선택적) |
