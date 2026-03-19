# 요구사항 설계서 (Requirements Specification)

> 자동화 암호화폐 트레이딩 시스템 — Upbit 거래소 대상
> 작성일: 2026-03-19 | 버전: 1.0

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
- [x] 골든크로스 / 데드크로스 감지
- [x] 과매수(RSI > 70) / 과매도(RSI < 30) 감지

### 2.2 MA Crossover 전략
- [x] 골든크로스 발생 시 BUY 시그널 생성
- [x] 데드크로스 발생 시 SELL 시그널 생성
- [x] 과매수 상태에서 BUY 시그널 억제
- [x] 과매도 상태에서 SELL 시그널 억제
- [x] 동일 상태 중복 시그널 방지 (_prev_cross 추적)
- [x] 시그널 강도(strength) 계산 — SMA 이격도 기반
- [x] 시그널을 DB에 저장 (SignalModel)
- [x] SIGNAL_GENERATED 이벤트 발행

### 2.3 전략 레지스트리
- [x] 전략 이름으로 동적 등록/조회 (StrategyRegistry)
- [x] 멀티 심볼 지원 (symbols 리스트)
- [x] 전략 파라미터 외부 주입 (params dict)

---

## 3. 주문 실행 (Order Execution)

### 3.1 주문 생성
- [x] SIGNAL_GENERATED 이벤트 수신 시 주문 생성
- [x] 가용 잔고 기반 주문 수량 계산
- [x] REST API를 통한 Upbit 주문 전송 (지정가/시장가)
- [x] JWT + SHA512 query hash 인증
- [x] 주문 결과를 OrderModel로 DB 저장
- [x] ORDER_FILLED / ORDER_FAILED 이벤트 발행

### 3.2 주문 취소
- [x] 미체결 주문 취소 API 호출
- [x] 취소 결과 상태 업데이트

---

## 4. 리스크 관리 (Risk Management)

### 4.1 단일 주문 한도
- [x] 주문 금액이 max_order_krw 초과 시 수량 자동 축소
- [x] 조정 후 승인 (거부 아님)

### 4.2 일일 손실 한도
- [x] 미실현 손실 > max_daily_loss_krw 시 매도 거부
- [x] RISK_TRIGGERED 이벤트 발행
- [x] 이익 포지션 매도는 손실 한도 검사 스킵
- [x] 포지션 없는 경우 손실 한도 검사 스킵
- [x] 손실 누적 기록 (record_loss)
- [x] 일일 자정 기준 손실 카운터 자동 리셋 (reset_daily_loss() + scheduler job)

### 4.3 포지션 비중 한도
- [x] 주문 후 포지션 비중 > max_position_ratio 시 매수 거부
- [x] RISK_TRIGGERED 이벤트 발행

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
- [x] Email 알림 (alert/email.py — aiosmtplib 기반)

---

## 7. 데이터 저장 (Data Persistence)

### 7.1 DB 모델
- [x] OrderModel (주문 내역)
- [x] TradeModel (체결 내역)
- [x] CandleModel (캔들 데이터)
- [x] SignalModel (전략 시그널)
- [x] SystemLogModel (시스템 로그)
- [x] PositionModel (포지션 이력)
- [x] BalanceHistoryModel (잔고 이력)

### 7.2 Repository 패턴
- [x] BaseRepository[T] 제네릭 (get/save/delete/list)
- [x] OrderRepository (상태별 조회, 심볼별 조회)
- [x] TradeRepository (일별 손익, 최근 체결 조회)
- [x] PositionRepository (심볼별 이력, 최근 포지션)
- [x] BalanceRepository (통화별 이력, 기간 조회)

### 7.3 마이그레이션
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
- [x] 멀티 심볼 백테스트 (MultiSymbolBacktestRunner)
- [x] 파라미터 최적화 (Grid Search — backtest/optimizer.py)

---

## 9. 운영 / 인프라 (Operations & Infrastructure)

### 9.1 스케줄러
- [x] APScheduler(AsyncIOScheduler) 기반 주기적 작업
- [x] 캔들 수집 주기 설정
- [x] 계좌 동기화 주기 설정
- [x] 일일 리포트 생성 (report/daily_report.py — DailyReportGenerator)

### 9.2 설정 관리
- [x] pydantic-settings 기반 환경변수 관리
- [x] 개발/운영 환경 분리 (dev.py / prod.py)
- [x] .env 파일 지원

### 9.3 로깅
- [x] YAML 기반 로깅 설정
- [x] 로테이팅 파일 핸들러 (trading.log, error.log)
- [x] 모듈별 로그 레벨 설정

### 9.4 종료 처리
- [x] SIGINT / SIGTERM 시그널 핸들링
- [x] Graceful Shutdown (진행 중 작업 완료 후 종료)

---

## 10. 테스트 (Testing)

### 10.1 단위 테스트
- [x] 지표 계산 (sma, ema, rsi) — 14개 테스트
- [x] 시장 스냅샷 (Tick/Candle 저장) — 10개 테스트
- [x] Feature Builder (지표→Features 변환) — 9개 테스트
- [x] EventBus (pub/sub, 예외 격리) — 8개 테스트
- [x] RiskManager (3단계 검증) — 7개 테스트
- [x] MA Crossover 전략 (시그널 결정 로직) — 12개 테스트
- [x] Backtest Runner (포트폴리오/결과/실행기) — 24개 테스트
- **합계: 84개 테스트, 전체 통과**

### 10.2 통합 테스트
- [x] on_tick() → DB 저장 흐름 (test_on_tick_db.py — 3개)
- [x] 주문 실행 → 포지션 업데이트 흐름 (test_order_position.py — 4개)
- [x] 리스크 검사 → 알림 발행 흐름 (test_risk_alert.py — 5개)

### 10.3 E2E 테스트
- [x] 전체 파이프라인 검증 (test_e2e_pipeline.py — 4개, in-memory DB)
- **통합+E2E 합계: 16개 테스트, 전체 통과**
- **전체 합계: 100개 테스트, 전체 통과**
