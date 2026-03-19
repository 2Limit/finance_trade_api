# 프로그램 기능 설명서 (Program Functionality Description)

> 자동화 암호화폐 트레이딩 시스템 — Upbit 거래소 대상
> 작성일: 2026-03-19 | 버전: 1.0

---

## 1. 시스템 개요

본 시스템은 Upbit 암호화폐 거래소를 대상으로 실시간 시세 수집, 전략 기반 시그널 생성, 자동 주문 실행, 리스크 관리, 알림 발송을 수행하는 완전 자동화 트레이딩 시스템입니다.

Python 3.11+ `asyncio` 기반의 비동기 이벤트 루프 위에서 동작하며, 이벤트 드리븐 아키텍처(Event-Driven Architecture)를 채택하여 컴포넌트 간 결합도를 최소화합니다.

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py / TradingEngine                  │
│  (전체 컴포넌트 조립, 이벤트 라우팅, Graceful Shutdown)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ EventBus (pub/sub)
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
┌─────────────┐   ┌──────────────────┐   ┌────────────────┐
│  WebSocket  │   │  Strategy Engine │   │  Order Manager │
│    Feed     │   │  (MA Crossover)  │   │  (주문 실행)    │
│ (실시간 시세)│   │  FeatureBuilder  │   │  RiskManager   │
└──────┬──────┘   └────────┬─────────┘   └───────┬────────┘
       │                   │                      │
       ▼                   ▼                      ▼
┌─────────────┐   ┌──────────────────┐   ┌────────────────┐
│  Market     │   │   SignalModel    │   │  OrderModel /  │
│  Snapshot   │   │   (DB 저장)      │   │  TradeModel    │
│ (인메모리)   │   └──────────────────┘   │  (DB 저장)     │
└─────────────┘                          └────────────────┘
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

```
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
    │       └─ sma(), ema(), rsi() 계산
    │       └─ is_golden_cross, is_overbought 등 판단
    │
    ├─► MACrossoverStrategy._evaluate(features)
    │       └─ 크로스 상태 변화 감지
    │       └─ RSI 필터 적용
    │       └─ Signal 생성 (BUY/SELL/None)
    │
    └─► if signal:
            EventBus.publish(SIGNAL_GENERATED)
                │
                ▼
            OrderManager.on_signal()
                │ qty 계산 (가용잔고 × order_ratio)
                │ RiskManager.check() — 3단계 검증
                │   ├─ max_order_krw 초과 시 qty 자동 축소
                │   ├─ 일일 손실 한도 초과 시 거부
                │   └─ 포지션 비중 초과 시 거부
                │
                ├─► UpbitRestClient.place_order()
                │
                ├─► OrderModel DB 저장
                │
                └─► EventBus.publish(ORDER_FILLED)
                        │
                        ├─► PositionManager.on_order_filled()
                        │       └─ 보유 수량 / 평균단가 갱신
                        │
                        └─► DiscordAlert.on_order_filled()
                                └─ Discord Embed 전송
```

### 3.2 스케줄러 파이프라인

```
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
    └─► [매일 00:00] DailyReport (미구현)
            └─ 일일 거래 요약 → Discord 전송
```

### 3.3 백테스트 파이프라인

```
BacktestRunner.from_prices(prices)
    │ 가격 리스트 → Candle 객체 변환
    │ 타임스탬프 순서 보장
    ▼
BacktestRunner.run()
    │
    ├─► 캔들 순차 처리 (warm-up 구간 건너뜀)
    │
    ├─► MarketSnapshot 업데이트
    │
    ├─► FeatureBuilder.build() — 지표 계산
    │
    ├─► strategy._evaluate(features) — 시그널 결정
    │       (DB 저장 없음, 순수 로직만)
    │
    ├─► BUY: SimulatedPortfolio.buy()
    │   SELL: SimulatedPortfolio.sell()
    │
    └─► BacktestResult 반환
            ├─ total_return / total_return_pct
            ├─ win_rate
            ├─ profit_factor
            ├─ max_drawdown
            └─ 거래 내역 (BacktestTrade 리스트)
```

---

## 4. 주요 컴포넌트 설명

### 4.1 EventBus (`core/event.py`)

| 기능 | 설명 |
|------|------|
| subscribe(type, handler) | 이벤트 타입에 비동기 핸들러 등록 |
| publish(event) | 해당 타입의 모든 핸들러를 순차 호출 |
| 예외 격리 | 하나의 핸들러 실패가 다른 핸들러에 영향 없음 |
| 중복 등록 허용 | 동일 핸들러를 여러 번 등록 가능 |

**이벤트 타입:**

| EventType | 발행 시점 | 주요 구독자 |
|-----------|-----------|-------------|
| PRICE_UPDATED | WebSocket ticker 수신 | TradingEngine |
| SIGNAL_GENERATED | 전략 시그널 생성 | OrderManager, DiscordAlert |
| ORDER_FILLED | 주문 체결 | PositionManager, DiscordAlert |
| ORDER_FAILED | 주문 실패 | DiscordAlert |
| RISK_TRIGGERED | 리스크 한도 초과 | DiscordAlert |
| POSITION_UPDATED | 포지션 변경 | (확장용) |
| BALANCE_UPDATED | 잔고 변경 | (확장용) |
| ERROR_OCCURRED | 시스템 오류 | (확장용) |
| HEARTBEAT | 주기적 생존 확인 | (확장용) |

---

### 4.2 FeatureBuilder (`data/processor/feature_builder.py`)

MarketSnapshot에서 캔들 데이터를 읽어 기술적 지표를 계산하고 `Features` 객체로 반환합니다.

| 속성 | 설명 |
|------|------|
| current_price | 마지막 캔들 종가 |
| sma_short | 단기 SMA (기본: 5봉) |
| sma_long | 장기 SMA (기본: 20봉) |
| rsi_14 | RSI (기본: 14봉) |
| is_golden_cross | short SMA > long SMA |
| is_dead_cross | short SMA < long SMA |
| is_overbought | RSI > 70 |
| is_oversold | RSI < 30 |

데이터가 long_window 미만이면 `None` 반환 (warm-up 구간).

---

### 4.3 MACrossoverStrategy (`strategy/impl/ma_crossover.py`)

| 조건 | 결과 |
|------|------|
| 골든크로스 + NOT 과매수 | BUY 시그널 |
| 데드크로스 + NOT 과매도 | SELL 시그널 |
| 동일 크로스 상태 연속 | None (중복 방지) |
| 골든크로스 + 과매수 | None (RSI 필터) |
| 데드크로스 + 과매도 | None (RSI 필터) |

시그널 강도(strength, 0.0~1.0)는 SMA 이격도(단기-장기 비율)에 비례합니다.

---

### 4.4 RiskManager (`execution/risk.py`)

3단계 순차 검증:

```
1단계: 단일 주문 금액 한도 (max_order_krw)
    → 초과 시: qty 자동 축소 후 승인
    → qty × price > max_order_krw → qty = max_order_krw / price

2단계: 일일 손실 한도 (매도 시만, max_daily_loss_krw)
    → 미실현 손실 > 한도 시 거부 + RISK_TRIGGERED 발행
    → 이익 포지션 / 포지션 없음 → 스킵

3단계: 포지션 비중 한도 (매수 시만, max_position_ratio)
    → 주문금액 / (가용잔고 + 주문금액) > 한도 시 거부
    → + RISK_TRIGGERED 발행
```

---

### 4.5 SimulatedPortfolio (`backtest/runner.py`)

백테스트 전용 가상 포트폴리오:

| 메서드 | 동작 |
|--------|------|
| buy(symbol, price, time) | 잔고 × order_ratio 만큼 매수, 수수료 차감 |
| sell(symbol, price, time) | 전량 매도, 손익 계산, 포지션 청산 |
| max_drawdown() | 자산 이력 기반 최대 낙폭 계산 |
| sharpe_ratio(rf) | 수익률 표준편차 기반 샤프 비율 |

---

## 5. 설정 구조

```
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
| DB_URL | sqlite+aioqlite:///... | DB 연결 문자열 |
| SYMBOLS | ["KRW-BTC"] | 거래 대상 심볼 목록 |
| MAX_ORDER_KRW | 500,000 | 단일 주문 최대 금액 |
| MAX_DAILY_LOSS_KRW | 1,000,000 | 일일 최대 손실 허용 금액 |
| MAX_POSITION_RATIO | 0.3 | 포트폴리오 대비 최대 포지션 비중 |
| DISCORD_WEBHOOK_URL | (선택) | Discord 알림 웹훅 URL |

---

## 6. 디렉토리 구조

```
finance_trade_api/
├── main.py                  # 진입점, 컴포넌트 조립
├── scheduler.py             # APScheduler 래퍼
├── config/                  # 환경 설정
├── core/
│   ├── event.py             # EventBus, EventType
│   └── engine.py            # TradingEngine (이벤트 라우터)
├── broker/
│   ├── base.py              # AbstractBroker
│   └── upbit/
│       ├── rest.py          # REST API 클라이언트
│       └── websocket.py     # WebSocket 피드
├── market/
│   ├── feed.py              # AbstractMarketFeed
│   └── snapshot.py          # MarketSnapshot (인메모리)
├── data/
│   ├── collector/           # 데이터 수집기
│   └── processor/           # 지표 계산, FeatureBuilder
├── strategy/
│   ├── base.py              # AbstractStrategy, Signal
│   ├── registry.py          # StrategyRegistry
│   └── impl/
│       └── ma_crossover.py  # MA Crossover 전략
├── execution/
│   ├── order_manager.py     # 주문 관리
│   └── risk.py              # 리스크 관리
├── portfolio/
│   ├── account.py           # AccountManager
│   └── position.py          # PositionManager
├── alert/
│   ├── base.py              # AbstractAlert
│   └── discord.py           # Discord 알림
├── backtest/
│   └── runner.py            # BacktestRunner, SimulatedPortfolio
├── db/
│   ├── base.py              # SQLAlchemy Base
│   ├── session.py           # 세션 관리
│   ├── models/              # ORM 모델
│   └── repositories/        # Repository 패턴
├── tests/
│   ├── conftest.py          # 공유 픽스처
│   └── unit/                # 단위 테스트 (84개)
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
| 알림 | Discord Webhook (aiohttp) |
