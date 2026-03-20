# 요구사항 설계서 (Requirements Specification)

> 자동화 암호화폐 트레이딩 시스템 — Upbit 거래소 대상
> 작성일: 2026-03-19 | 최종 수정: 2026-03-20 | 버전: 2.1
>
> **구현 현황**: 전체 105개 항목 중 104개 완료 (Telegram 제외) | 테스트 100개 전체 통과

---

## 1. 데이터 수집 (Data Collection)

### 1.1 실시간 시세 수집

- [x] WebSocket으로 Upbit 실시간 ticker 구독
- [x] 연결 끊김 시 5초 후 자동 재연결
- [x] Tick 데이터를 MarketSnapshot에 인메모리 저장
- [x] 수신 시 PRICE_UPDATED 이벤트 발행

### 1.2 캔들 데이터 수집

- [x] REST API로 분봉/일봉 캔들 주기적 수집
- [x] 수집한 캔들을 MarketSnapshot에 업데이트
- [x] 중복 캔들 저장 방지 (symbol + interval + timestamp UniqueConstraint)
- [x] CandleModel로 DB 영속화

### 1.3 계좌 정보 수집

- [x] REST API로 계좌 잔고 주기적 동기화
- [x] KRW 가용 잔고 실시간 파악

---

## 2. 전략 엔진 (Strategy Engine)

### 2.1 지표 계산

- [x] SMA(단순이동평균) 계산
- [x] EMA(지수이동평균) 계산
- [x] RSI(14) 계산
- [x] 볼린저 밴드 계산 (bollinger_bands)
- [x] MACD 계산 (macd)
- [x] 골든크로스 / 데드크로스 감지
- [x] 과매수(RSI > 70) / 과매도(RSI < 30) 감지

### 2.2 MA Crossover 전략

- [x] 골든크로스 발생 시 BUY 시그널 생성
- [x] 데드크로스 발생 시 SELL 시그널 생성
- [x] 과매수 상태에서 BUY 시그널 억제
- [x] 과매도 상태에서 SELL 시그널 억제
- [x] 동일 상태 중복 시그널 방지 (_prev_cross 추적)
- [x] 시그널 강도(strength) 계산 — SMA 이격도 기반
- [x] SIGNAL_GENERATED 이벤트 발행

### 2.3 RSI 전략

- [x] 과매도 구간 진입 후 30 회복 시 BUY
- [x] 과매수 구간 진입 후 70 이탈 시 SELL
- [x] 존 전환 기반 중복 시그널 방지

### 2.4 볼린저 밴드 전략

- [x] 하단 밴드 이탈 감지 후 반등 시 BUY
- [x] 상단 밴드 이탈 감지 후 하락 시 SELL

### 2.5 MACD 전략

- [x] MACD 라인이 시그널 라인 상향 돌파 시 BUY
- [x] MACD 라인이 시그널 라인 하향 이탈 시 SELL

### 2.6 ML 전략

- [x] scikit-learn / lightgbm 모델 연동 인터페이스
- [x] Features 객체 → 입력 벡터 변환
- [x] 모델 파일 경로 기반 로드

### 2.7 전략 앙상블 (StrategyAggregator)

- [x] 다수결 투표 (threshold 60%)
- [x] MA + RSI + Bollinger 기본 조합

### 2.8 전략 레지스트리 및 스토어

- [x] 전략 이름으로 동적 등록/조회 (StrategyRegistry)
- [x] 멀티 심볼 지원 (symbols 리스트)
- [x] 전략 파라미터 외부 주입 (params dict)
- [x] required_candles() 인터페이스 — 전략별 필요 캔들 수 선언
- [x] param_schema() — 파라미터 타입 자동 추론
- [x] update_params() — 런타임 파라미터 변경
- [x] StrategyStore Redis 동기화 (대시보드 실시간 공유)

---

## 3. 주문 실행 (Order Execution)

### 3.1 주문 생성

- [x] SIGNAL_GENERATED 이벤트 수신 시 주문 생성
- [x] 가용 잔고 기반 주문 수량 계산
- [x] REST API를 통한 Upbit 주문 전송 (지정가/시장가)
- [x] JWT + SHA512 query hash 인증
- [x] 주문 결과를 OrderModel로 DB 저장
- [x] **SignalModel DB 저장 — 쿨다운 전, 모든 전략 시그널 기록**
- [x] **TradeModel DB 저장 — 체결 내역, exchange 컬럼으로 거래소 구분**
- [x] ORDER_FILLED / ORDER_FAILED 이벤트 발행

### 3.2 주문 취소

- [x] 미체결 주문 취소 API 호출
- [x] 취소 결과 상태 업데이트

### 3.3 멀티 거래소 라우팅

- [x] AbstractBroker.exchange_name 속성 (거래소 식별자)
- [x] symbol_brokers 맵으로 심볼별 브로커 선택
- [x] TradeModel.exchange 컬럼으로 체결 거래소 추적

### 3.4 DCA (분할 매수)

- [x] dca_split_count 회 나누어 interval_sec 간격으로 분할 매수
- [x] 백그라운드 asyncio.Task로 순차 실행

---

## 4. 리스크 관리 (Risk Management)

### 4.1 단일 주문 한도

- [x] 주문 금액이 max_order_krw 초과 시 수량 자동 축소

### 4.2 일일 손실 한도

- [x] 미실현 손실 > max_daily_loss_krw 시 매도 거부
- [x] RISK_TRIGGERED 이벤트 발행
- [x] 이익 포지션 / 포지션 없는 경우 스킵
- [x] 일일 자정 기준 손실 카운터 자동 리셋

### 4.3 포지션 비중 한도

- [x] 주문 후 포지션 비중 > max_position_ratio 시 매수 거부

### 4.4 손절매 / 익절매

- [x] StopLossMonitor: PRICE_UPDATED마다 포지션 수익률 체크
- [x] -stop_loss_pct 이하 시 자동 SELL 시그널
- [x] +take_profit_pct 이상 시 자동 SELL 시그널

---

## 5. 포트폴리오 관리 (Portfolio Management)

### 5.1 포지션 추적

- [x] 체결 이벤트(ORDER_FILLED) 수신 시 포지션 업데이트
- [x] 평균단가(avg_price) 계산 — 추가 매수 시 가중 평균
- [x] 미실현 손익(unrealized_pnl) 계산
- [x] 포지션 내역 DB 영속화 (PositionModel + PositionRepository)

### 5.2 계좌 잔고

- [x] Broker에서 잔고 조회
- [x] KRW 가용 잔고 제공 (get_available_krw)
- [x] 잔고 이력 DB 저장 (BalanceHistoryModel + BalanceRepository)

---

## 6. 알림 (Alert)

### 6.1 Discord 알림

- [x] 시그널 발생 시 알림 (BUY/SELL 색상 구분)
- [x] 주문 체결 시 알림
- [x] 리스크 트리거 시 알림
- [x] 비동기 전송 (실패해도 트레이딩 중단 없음)
- [ ] Telegram 알림 (범위 외)

### 6.2 Email 알림

- [x] Email 알림 (alert/email.py — aiosmtplib 기반)

---

## 7. 데이터 저장 (Data Persistence)

### 7.1 DB 모델

- [x] OrderModel (주문 내역)
- [x] TradeModel (체결 내역 — exchange 컬럼 포함)
- [x] CandleModel (캔들 데이터)
- [x] SignalModel (전략 시그널)
- [x] SystemLogModel (시스템 로그)
- [x] PositionModel (포지션 이력)
- [x] BalanceHistoryModel (잔고 이력)

### 7.2 Repository 패턴

- [x] BaseRepository[T] 제네릭 (get/save/delete/list)
- [x] OrderRepository (상태별 조회, 심볼별 조회)
- [x] TradeRepository (일별 손익, 최근 체결 조회)
- [x] **SignalRepository (전략별 조회, 심볼별 조회, 최근 시그널)**
- [x] PositionRepository (심볼별 이력, 최근 포지션)
- [x] BalanceRepository (통화별 이력, 기간 조회)

### 7.3 저장 연결 현황

- [x] OrderModel — OrderManager._submit() 성공 시 저장
- [x] TradeModel — OrderManager._submit() 성공 시 저장 (exchange 포함)
- [x] SignalModel — OrderManager.on_signal() 진입 시 저장 (쿨다운 전)
- [x] PositionModel — PositionManager.on_order_filled() 시 저장

### 7.4 마이그레이션

- [x] Alembic 마이그레이션 환경 설정 (alembic/env.py — async 지원)
- [x] 초기 스키마 마이그레이션 실행 (initial_schema, 7개 테이블)

---

## 8. 백테스트 (Backtest)

### 8.1 시뮬레이션 포트폴리오

- [x] 매수/매도 시뮬레이션
- [x] 수수료 차감 (0.05%)
- [x] 평균단가 추적
- [x] 잔고 부족 시 수량 자동 조정
- [x] Max Drawdown 계산
- [x] Sharpe Ratio 계산

### 8.2 백테스트 결과

- [x] 총 수익 / 수익률 계산
- [x] 승률(win_rate) 계산
- [x] Profit Factor 계산
- [x] 거래 내역 리스트 반환
- [x] print_summary() 요약 출력

### 8.3 백테스트 실행기

- [x] 캔들 데이터로 순차 시뮬레이션
- [x] DB 없이 순수 전략 로직만 사용
- [x] from_prices() 팩토리 메서드 (가격 리스트 → 캔들 자동 변환)
- [x] strategy.required_candles() 기반 FeatureBuilder snapshot_limit 자동 설정
- [x] 멀티 심볼 백테스트 (MultiSymbolBacktestRunner)
- [x] 파라미터 최적화 (Grid Search — backtest/optimizer.py)

### 8.4 시각화

- [x] matplotlib 기반 자산 곡선 / 드로다운 / 거래 표시 차트
- [x] adaptive X-axis (시간 범위에 따라 분/시/일/월 자동 전환)
- [x] HTML 임베드 (base64 PNG → 대시보드 표시)

---

## 9. 대시보드 (Dashboard)

### 9.1 웹 대시보드 (FastAPI)

- [x] 포트폴리오 개요 (잔고, 포지션, 최근 주문)
- [x] 전략 목록 및 파라미터 실시간 수정
- [x] 백테스트 실행 및 결과 시각화
- [x] WebSocket push — 실시간 이벤트 반영

### 9.2 WebSocket 실시간 브리지

- [x] in-memory 모드: EventBus → ws_manager.on_event() 직접 구독
- [x] Redis 모드: Redis Stream "events:all" 폴링 → WebSocket push
- [x] SIGNAL_GENERATED / ORDER_FILLED / ORDER_FAILED / RISK_TRIGGERED / PRICE_UPDATED 실시간 전송

---

## 10. 운영 / 인프라 (Operations & Infrastructure)

### 10.1 스케줄러

- [x] APScheduler(AsyncIOScheduler) 기반 주기적 작업
- [x] 캔들 수집 주기 설정
- [x] 계좌 동기화 주기 설정
- [x] 일일 리포트 생성 (report/daily_report.py — DailyReportGenerator)

### 10.2 설정 관리

- [x] pydantic-settings 기반 환경변수 관리
- [x] 개발/운영 환경 분리 (dev.py / prod.py)
- [x] .env 파일 지원
- [x] redis_url / event_bus_backend 설정

### 10.3 로깅

- [x] YAML 기반 로깅 설정
- [x] 로테이팅 파일 핸들러 (trading.log, error.log)
- [x] 모듈별 로그 레벨 설정

### 10.4 종료 처리

- [x] SIGINT / SIGTERM 시그널 핸들링
- [x] Graceful Shutdown (진행 중 작업 완료 후 종료)

---

## 11. 테스트 (Testing)

### 11.1 단위 테스트

- [x] 지표 계산 (sma, ema, rsi) — 14개 테스트
- [x] 시장 스냅샷 (Tick/Candle 저장) — 10개 테스트
- [x] Feature Builder (지표→Features 변환) — 9개 테스트
- [x] EventBus (pub/sub, 예외 격리) — 8개 테스트
- [x] RiskManager (3단계 검증) — 7개 테스트
- [x] MA Crossover 전략 (시그널 결정 로직) — 12개 테스트
- [x] Backtest Runner (포트폴리오/결과/실행기) — 24개 테스트
- **합계: 84개 테스트, 전체 통과**

### 11.2 통합 테스트

- [x] on_tick() → DB 저장 흐름 (test_on_tick_db.py — 3개)
- [x] 주문 실행 → 포지션 업데이트 흐름 (test_order_position.py — 4개)
- [x] 리스크 검사 → 알림 발행 흐름 (test_risk_alert.py — 5개)

### 11.3 E2E 테스트

- [x] 전체 파이프라인 검증 (test_e2e_pipeline.py — 4개, in-memory DB)
- **통합+E2E 합계: 16개 테스트, 전체 통과**
- **전체 합계: 100개 테스트, 전체 통과**
