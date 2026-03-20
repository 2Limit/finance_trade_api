# 프로그램 확장 제안서 (Extension Proposal)

> 자동화 암호화폐 트레이딩 시스템
> 작성일: 2026-03-19 | 최종 수정: 2026-03-20 | 버전: 3.0

---

## 개요

MVP(단일 전략 · 단일 거래소 · 단일 심볼)에서 출발하여 Phase 1~3을 완료하였습니다.
현재 시스템은 **다중 전략 · ML 전략 · 앙상블 · 대시보드 · WebSocket push · Redis 분산 버스 · 완전한 데이터 추적 파이프라인**을 갖춘 안정화 단계에 있습니다.
본 제안서는 현재까지 완료된 항목과 이후 선택적 고도화 로드맵을 제시합니다.

---

## 완료된 항목 (2026-03-20 기준)

### Phase 1 — 안정화

| 항목 | 파일 |
| --- | --- |
| Alembic 마이그레이션 (7개 테이블) | alembic/ |
| 일일 손실 카운터 자동 리셋 | execution/risk.py + scheduler.py |
| 포지션 내역 DB 영속화 | db/models/position.py |
| 잔고 이력 DB 저장 | db/models/balance.py |
| 중복 주문 방지 (ORDER_COOLDOWN) | execution/order_manager.py |
| 손절매 / 익절매 (StopLossMonitor) | execution/stop_loss.py |
| 통합·E2E 테스트 16개 추가 (총 100개) | tests/integration/ |

### Phase 2 — 기능 확장

| 항목 | 파일 |
| --- | --- |
| RSI 전략 | strategy/impl/rsi_strategy.py |
| 볼린저 밴드 전략 | strategy/impl/bollinger_strategy.py |
| MACD 전략 | strategy/impl/macd_strategy.py |
| ML 전략 인터페이스 | strategy/impl/ml_strategy.py |
| 전략 앙상블 (StrategyAggregator) | strategy/aggregator.py |
| DCA 분할 매수 | execution/order_manager.py |
| 멀티 거래소 라우팅 기반 | broker/base.py (exchange_name), order_manager.py |
| 백테스트 시각화 (adaptive X-axis) | backtest/visualization.py |
| 파라미터 최적화 Grid Search | backtest/optimizer.py |
| Email 알림 | alert/email.py |
| 멀티 심볼 백테스트 | backtest/runner.py |
| 일일 리포트 생성 | report/daily_report.py |
| 대시보드 전략 파라미터 실시간 수정 | api/dashboard.py |
| 백테스트 대시보드 (다전략 지원) | api/dashboard.py |

### Phase 3 — 아키텍처 고도화

| 항목 | 파일 |
| --- | --- |
| FastAPI 독립 대시보드 (WebSocket push) | api/dashboard.py |
| Redis EventBus (Streams + Pub/Sub) | core/event_bus_redis.py |
| StrategyStore Redis 동기화 | strategy/store.py |
| **SignalModel 저장 연결** | execution/order_manager.py |
| **TradeModel 저장 연결** | execution/order_manager.py |
| **SignalRepository 생성** | db/repositories/signal_repo.py |
| **TradeModel.exchange 컬럼** | db/models/trade.py |
| **WebSocket in-process 브리지** | api/dashboard.py, main.py |

---

## 데이터 추적 아키텍처 (현재 상태)

```text
전략 시그널 → SignalModel  (strategy_name, symbol, signal_type, strength, metadata)
주문 체결  → OrderModel   (주문 원장, 상태 추적)
           → TradeModel   (체결 내역, exchange 컬럼으로 거래소 구분)
포지션 변경 → PositionModel (avg_price, unrealized_pnl)
잔고 변경  → BalanceHistoryModel
```

**모든 저장은 `OrderManager._submit()` 단일 경로를 통과하므로
MA / RSI / Bollinger / MACD / ML / Aggregator 등 어떤 전략이 추가되어도
별도 코드 없이 자동으로 추적됩니다.**

---

## 선택적 고도화 항목 (검토 대기)

아래 항목들은 운영 규모·요구사항에 따라 선택적으로 도입합니다.

### A. 모니터링 (Prometheus + Grafana)

**배경**: 프로덕션 운영 시 메트릭 기반 장애 감지가 필요합니다.

```text
구현 범위:
  api/metrics.py  — prometheus_client 기반 /metrics 엔드포인트
  주요 메트릭:
    trade_count_total (strategy, exchange, symbol 라벨)
    signal_count_total (strategy, signal_type 라벨)
    order_latency_seconds (주문 제출~체결 지연)
    position_unrealized_pnl (symbol 라벨)
  Grafana 대시보드 JSON 파일 (grafana/dashboards/)
```

**기대 효과**: 실시간 트레이딩 상태 모니터링, 이상 감지 알람

---

### B. 로그 집계 (structlog + Loki / ELK)

**배경**: 현재 로컬 파일(trading.log) 기반이라 다중 인스턴스 운영 시 로그가 분산됩니다.

```text
구현 범위:
  structlog JSON 포맷 — 모든 로거를 structlog로 전환
  컨텍스트 자동 첨부: strategy_name, symbol, order_id
  Loki 연동 (Docker Compose promtail 추가) 또는
  ELK 연동 (Logstash TCP handler)
```

**기대 효과**: 전략·심볼·주문 단위 로그 추적, 대시보드 통합

---

### C. 알림 고도화

**배경**: 단순 Discord 알림에서 채널 다양화 및 리포트 고도화가 필요합니다.

```text
구현 범위:
  Discord rate-limit 처리 — 429 응답 시 exponential backoff 재시도
  Telegram 알림 채널 추가 (alert/telegram.py — python-telegram-bot)
  일일 리포트 HTML 포맷 — 자산 곡선 차트 임베드, 전략별 승률 테이블
  주간/월간 리포트 (scheduler 주기 추가)
```

---

### D. PostgreSQL 전환

**배경**: SQLite는 동시 쓰기 성능 한계가 있어 고빈도 거래 시 병목이 됩니다.

```text
구현 범위:
  docker-compose.yml — PostgreSQL 서비스 추가
  db/session.py — asyncpg 풀 설정 (pool_size, max_overflow)
  alembic/env.py — asyncpg URL 처리
  .env.example — DB_URL, REDIS_URL 문서화
```

**마이그레이션 전략**: Alembic이 이미 준비되어 있어 DB_URL 변경만으로 전환 가능합니다.

---

### E. 멀티 거래소 구현 (Binance)

**배경**: `AbstractBroker`와 `exchange_name` 속성이 이미 준비되어 있어 구현 비용이 낮습니다.

```text
구현 범위:
  broker/binance/rest.py    — BinanceRestClient (exchange_name="binance")
  broker/binance/websocket.py — BinanceWebSocketFeed
  OrderManager.symbol_brokers 맵으로 심볼별 라우팅
  TradeModel.exchange 컬럼으로 체결 거래소 자동 구분
```

**기대 효과**: 거래소 간 가격 차이를 활용한 차익거래 전략 기반 마련

---

### F. ML 전략 학습 파이프라인

**배경**: 현재 `MLStrategy`는 사전 학습된 모델을 로드하는 인터페이스만 제공합니다.

```text
구현 범위:
  mlflow 연동 — 모델 버전 관리, 실험 추적
  학습 데이터: TradeModel + SignalModel 기록 → 라벨 생성
  피처: Features 객체 (rsi, sma, bollinger, macd) → 고정 벡터
  온라인 학습: 실거래 결과로 주기적 재학습 (scheduler 활용)
  SignalModel.metadata_ 에 confidence, model_version 저장
```

---

## 현재 기술 부채 및 권장 조치

| 항목 | 현황 | 권장 조치 |
| --- | --- | --- |
| SQLite | 단일 파일 DB, 동시성 제한 | 고빈도 시 PostgreSQL 전환 (Alembic 준비됨) |
| API 키 관리 | .env 파일, 평문 저장 | AWS Secrets Manager 도입 |
| 오류 재시도 | 주문 실패 시 이벤트 발행만 | Exponential Backoff + 최대 횟수 제한 |
| 로그 수집 | 로컬 파일만 | Loki / ELK 연동 (항목 B) |
| ML 재학습 | 수동 모델 교체만 | mlflow 파이프라인 (항목 F) |
| Telegram | 미구현 | 항목 C에서 처리 |

---

## 우선순위 로드맵 요약

```text
현재 상태 (Phase 3 완료, 2026-03-20)
    │
    │  ✅ 다중 전략 (MA / RSI / Bollinger / MACD / ML / Aggregator)
    │  ✅ DCA 분할 매수
    │  ✅ 손절매 / 익절매
    │  ✅ SignalModel + TradeModel 저장 연결 (전 전략 자동 추적)
    │  ✅ TradeModel.exchange 컬럼 (멀티 거래소 준비)
    │  ✅ SignalRepository (전략별 시그널 분석)
    │  ✅ FastAPI 대시보드 + WebSocket 실시간 push
    │  ✅ Redis EventBus + StrategyStore 동기화
    │  ✅ 백테스트 시각화 (adaptive X-axis)
    │  ✅ 통합·E2E 테스트 100개
    │
    ▼ 선택적 고도화 (필요 시 순서대로)
    ├─ 🔵 A. Prometheus + Grafana 모니터링
    ├─ 🔵 B. structlog + Loki 로그 집계
    ├─ 🔵 C. 알림 고도화 (Telegram, rate-limit, HTML 리포트)
    ├─ 🔵 D. PostgreSQL 전환
    ├─ 🔵 E. 멀티 거래소 구현 (Binance)
    └─ 🔵 F. ML 학습 파이프라인 (mlflow)
```

**범례**: 🔵 선택적 고도화 (현재 운영 가능, 규모 확장 시 도입)
