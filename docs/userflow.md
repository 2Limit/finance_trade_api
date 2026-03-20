# 사용자 경험 흐름 (User Flow)

> 자동화 암호화폐 트레이딩 시스템 — 사용자 관점 운영 가이드
> 작성일: 2026-03-20 | 버전: 1.0

---

## 전체 사용자 여정 개요

```text
[초기 설정]          [전략 검증]         [실거래 운영]        [모니터링 · 개선]
     │                   │                   │                    │
1. 환경 구성        4. 백테스트 실행    7. 엔진 시작         10. 대시보드 확인
2. API 키 등록      5. 결과 분석        8. 실시간 시그널      11. 알림 수신
3. 전략 파라미터    6. 파라미터 최적화  9. 자동 주문 체결     12. 파라미터 조정
   초기 설정                                                   13. 성과 분석
```

---

## 1. 초기 설정 (Initial Setup)

### 1.1 환경 구성

```text
사용자                                시스템
  │                                     │
  ├─ .env 파일 생성 (.env.example 복사)  │
  │   UPBIT_ACCESS_KEY=...              │
  │   UPBIT_SECRET_KEY=...             │
  │   DISCORD_WEBHOOK_URL=...          │
  │   DB_URL=sqlite+aiosqlite:///...   │
  │   REDIS_URL= (비워두면 in-memory)  │
  │                                     │
  ├─ pip install -r requirements.txt   │
  │                                     │
  └─ alembic upgrade head ─────────────► DB 테이블 7개 생성
                                         (orders, trades, signals,
                                          positions, balances,
                                          candles, system_logs)
```

**결과**: 트레이딩에 필요한 모든 인프라가 준비됩니다.

---

### 1.2 전략 파라미터 초기 설정

사용자는 `config/dev.py` 또는 `.env`에서 주요 파라미터를 설정합니다.

| 설정 항목 | 기본값 | 의미 |
| --- | --- | --- |
| SYMBOLS | ["KRW-BTC"] | 거래할 코인 목록 |
| MAX_ORDER_KRW | 500,000 | 1회 주문 최대 금액 |
| MAX_DAILY_LOSS_KRW | 1,000,000 | 하루 최대 허용 손실 |
| MAX_POSITION_RATIO | 0.3 | 잔고 대비 최대 포지션 비중 |
| STOP_LOSS_PCT | 0.05 | 손절매 기준 (-5%) |
| TAKE_PROFIT_PCT | 0.10 | 익절매 기준 (+10%) |
| ORDER_COOLDOWN_SEC | 60 | 동일 심볼 중복 주문 방지 간격 |

---

## 2. 백테스트로 전략 검증 (Strategy Validation)

실거래 전에 반드시 백테스트를 수행해 전략의 유효성을 확인합니다.

### 2.1 대시보드에서 백테스트 실행

```text
브라우저: http://localhost:8000/backtest

사용자 흐름:
  1. 전략 선택 (MA Crossover / RSI / Bollinger / MACD)
     └─ 선택 시 해당 전략의 파라미터 입력 폼이 표시됨

  2. 파라미터 입력
     ┌─────────────────────────────────────────┐
     │ MA Crossover 예시:                       │
     │   단기 이동평균 (short_window): [5]      │
     │   장기 이동평균 (long_window):  [20]     │
     │   RSI 기간 (rsi_period):        [14]    │
     └─────────────────────────────────────────┘

  3. 데이터 범위 설정
     │   기간: [100] 봉  |  가격 변동폭: [10%]
     │   시작 가격: [50,000,000] KRW

  4. [백테스트 실행] 클릭
     │
     ▼
  5. 결과 확인 (약 1~3초 후 표시)
     ┌─────────────────────────────────────────────────────┐
     │ 총 수익:    +1,523,000 KRW  (+15.23%)               │
     │ 승률:       62.5% (10승 6패)                        │
     │ Profit Factor: 2.14                                 │
     │ Max Drawdown:  -8.3%                                │
     │ 기간:          100봉 (약 100시간)                   │
     ├─────────────────────────────────────────────────────┤
     │ [자산 곡선 차트]  [드로다운 차트]  [거래 표시]        │
     └─────────────────────────────────────────────────────┘
```

### 2.2 백테스트 결과 해석 기준

| 지표 | 양호 기준 | 주의 | 위험 |
| --- | --- | --- | --- |
| 총 수익률 | > 0% | 0% 근접 | 음수 |
| 승률 | > 50% | 45~50% | < 45% |
| Profit Factor | > 1.5 | 1.0~1.5 | < 1.0 |
| Max Drawdown | < 15% | 15~25% | > 25% |

### 2.3 파라미터 최적화 흐름

```text
백테스트 결과가 기준에 미달하는 경우:

사용자                            시스템
  │                                 │
  ├─ 파라미터 조정                  │
  │   short_window: 5 → 3          │
  │   long_window: 20 → 15         │
  │                                 │
  ├─ 재실행 ──────────────────────► 새 결과 계산
  │                                 │
  ├─ 결과 비교 (이전 vs 현재)       │
  │                                 │
  └─ 만족스러운 파라미터 확정       │
```

**TIP**: Grid Search 최적화를 코드에서 실행하면 파라미터 조합별 결과를 일괄 비교할 수 있습니다.

```python
# backtest/optimizer.py 활용
from backtest.optimizer import GridSearchOptimizer

optimizer = GridSearchOptimizer(
    strategy_class=MACrossoverStrategy,
    param_grid={"short_window": [3, 5, 7], "long_window": [15, 20, 30]},
)
best_params, best_result = optimizer.run(candles)
```

---

## 3. 실거래 엔진 시작 (Engine Start)

### 3.1 엔진 실행

```text
사용자                                  시스템
  │                                       │
  └─ python main.py ──────────────────► DB 초기화
                                          │
                                       ► EventBus 생성 (in-memory 또는 Redis)
                                          │
                                       ► 잔고 초기 동기화 (Upbit REST API)
                                          │
                                       ► 전략 인스턴스 생성 및 등록
                                          (MA / RSI / Bollinger / MACD / ML)
                                          │
                                       ► Upbit WebSocket 연결
                                          │
                                       ► APScheduler 시작 (캔들 수집 등)
                                          │
                                       ► 대시보드 서버 시작 (port 8000)
                                          │
                                       ► [실시간 시세 수신 시작]
                                          └─ "=== Finance Trade API 시작 ===" 로그 출력
```

### 3.2 정상 시작 확인 체크리스트

```text
로그에서 아래 메시지가 모두 출력되면 정상:

  ✅ "in-memory EventBus 사용" (또는 "RedisEventBus 활성화")
  ✅ "StrategyStore: registered 'ma_crossover'"
  ✅ "StrategyStore: registered 'rsi'"
  ✅ "WebSocket connected to Upbit"
  ✅ "대시보드: http://localhost:8000"

오류 발생 시:
  ❌ "Upbit API 인증 실패" → .env의 API 키 확인
  ❌ "DB 연결 실패"       → DB_URL 경로 및 권한 확인
  ❌ "Redis 연결 실패"    → REDIS_URL 비워두면 자동 in-memory 전환
```

---

## 4. 실시간 트레이딩 흐름 (Live Trading)

### 4.1 시그널 생성 ~ 주문 체결 상세 흐름

```text
[Upbit WebSocket 시세 수신]
        │
        │ 예: KRW-BTC 현재가 = 85,000,000 KRW
        ▼
[지표 계산]
  SMA(5)  = 84,500,000
  SMA(20) = 83,200,000   ← 골든크로스 감지!
  RSI(14) = 48.3         ← 과매수 아님 → 시그널 허용
        │
        ▼
[SignalModel DB 저장]
  strategy="ma_crossover", symbol="KRW-BTC"
  signal_type="buy", strength=0.73
  metadata={"price": "85000000"}
        │
        ▼
[쿨다운 검사]
  마지막 주문 후 60초 경과? → 통과
        │
        ▼
[리스크 검증]
  1단계: 주문금액 500,000 KRW ≤ max_order_krw → 통과
  2단계: 매수 → 손실 한도 검사 스킵 → 통과
  3단계: 포지션 비중 500,000 / 잔고 → 0.18 < 0.3 → 통과
        │
        ▼
[Upbit REST API 주문]
  POST /v1/orders  { market: "KRW-BTC", side: "bid", price: 500000 }
        │
        ▼
[OrderModel + TradeModel DB 저장]
  order_id="abc123", status="filled"
  exchange="upbit", qty=0.00588235
        │
        ▼
[이벤트 발행: ORDER_FILLED]
  ┌────────────────┬─────────────────────┬─────────────────┐
  ▼                ▼                     ▼                 ▼
PositionManager  DiscordAlert      WebSocket push     로그 기록
포지션 갱신      Discord 알림        대시보드 반영
avg_price 업데이트  "🟢 BUY 체결"      실시간 갱신
PositionModel 저장
```

### 4.2 손절매 / 익절매 자동 실행 흐름

```text
[매 틱 가격 수신 시 StopLossMonitor 동작]

  현재가: 80,750,000 KRW
  평균 매수가: 85,000,000 KRW
  미실현 손익: -5.0%

  -5.0% ≤ -stop_loss_pct(-5%) → 손절 조건 충족!
        │
        ▼
  SIGNAL_GENERATED 이벤트 발행 (signal="sell", strategy="stop_loss")
        │
  → 이후 동일한 주문 실행 흐름 진행
```

---

## 5. 대시보드 사용 흐름 (Dashboard Usage)

### 5.1 대시보드 구조

```text
http://localhost:8000

┌─────────────────────────────────────────────────────────────┐
│  네비게이션: 개요 | 전략 | 백테스트 | API Docs              │
├─────────────────────────────────────────────────────────────┤
│  [개요 페이지 /]                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ KRW 잔고 │  │ 포지션   │  │ 오늘 주문│  │ 시그널   │   │
│  │ 2,450,000│  │ BTC 0.01 │  │    3건   │  │   12건   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│                                                             │
│  [최근 주문 목록]          [실시간 이벤트 피드]              │
│  BTC BUY  85,000,000 filled │  🟢 BUY 시그널: ma_crossover  │
│  BTC SELL 80,750,000 filled │  📦 주문 체결: BTC 0.00588   │
│  ...                        │  ⚠️ RISK: 포지션 비중 초과   │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 전략 파라미터 실시간 수정 흐름

```text
브라우저: http://localhost:8000/strategies

사용자 흐름:
  1. 전략 목록에서 수정할 전략 카드 확인
     ┌─────────────────────────────┐
     │ MA Crossover                │
     │ 심볼: KRW-BTC               │
     │ short_window: [5  ]         │
     │ long_window:  [20 ]         │
     │ rsi_period:   [14 ]         │
     │          [Apply]            │
     └─────────────────────────────┘

  2. 값 변경: short_window 5 → 3

  3. [Apply] 클릭
     │
     ├─► PUT /api/strategies/ma_crossover/params
     │   body: {"short_window": 3}
     │
     ├─► StrategyStore.update_params() 호출
     │   → strategy.update_params() → FeatureBuilder 재생성
     │
     └─► 화면 피드백: "✓ 적용됨" (초록색)
         다음 PRICE_UPDATED 이벤트부터 새 파라미터로 동작
```

**주의**: 파라미터 변경은 즉시 적용되며 별도 재시작이 필요하지 않습니다.

### 5.3 WebSocket 실시간 이벤트 수신

```text
브라우저 연결: ws://localhost:8000/ws/events

수신 메시지 형식:
  {
    "type": "SIGNAL_GENERATED",
    "payload": {
      "symbol": "KRW-BTC",
      "signal": "buy",
      "price": "85000000",
      "strategy": "ma_crossover",
      "strength": 0.73
    },
    "ts": "2026-03-20T10:30:15.123456"
  }

지원 이벤트 타입:
  PRICE_UPDATED       → 실시간 가격 변동
  SIGNAL_GENERATED    → 전략 시그널 발생
  ORDER_FILLED        → 주문 체결
  ORDER_FAILED        → 주문 실패
  RISK_TRIGGERED      → 리스크 한도 초과
```

---

## 6. 알림 수신 흐름 (Alert Flow)

### 6.1 Discord 알림 예시

```text
시그널 발생 시:
  ┌──────────────────────────────────────┐
  │ 🟢 BUY 시그널                        │
  │ 전략: MA Crossover                   │
  │ 심볼: KRW-BTC                        │
  │ 현재가: 85,000,000 KRW               │
  │ 강도: 73%                            │
  └──────────────────────────────────────┘

주문 체결 시:
  ┌──────────────────────────────────────┐
  │ 📦 주문 체결                          │
  │ BUY KRW-BTC                          │
  │ 수량: 0.00588235 BTC                 │
  │ 체결가: 85,000,000 KRW               │
  │ 주문 ID: abc123                      │
  └──────────────────────────────────────┘

리스크 트리거 시:
  ┌──────────────────────────────────────┐
  │ ⚠️ 리스크 한도 초과                   │
  │ 사유: 포지션 비중 한도 초과            │
  │ 심볼: KRW-BTC                        │
  └──────────────────────────────────────┘
```

---

## 7. 성과 분석 흐름 (Performance Analysis)

### 7.1 일일 리포트 자동 수신 (매일 09:00)

```text
매일 오전 9시 → DailyReportGenerator.generate()

Discord / Email로 전송되는 리포트:
  ┌────────────────────────────────────────┐
  │ 📊 일일 트레이딩 리포트 (2026-03-20)   │
  │                                        │
  │ 오늘 거래: 총 8건                      │
  │   BUY  5건  | SELL 3건                │
  │                                        │
  │ 실현 손익:  +230,000 KRW              │
  │ 수수료:     -12,400 KRW               │
  │ 순손익:     +217,600 KRW              │
  │                                        │
  │ 전략별 시그널:                         │
  │   MA Crossover: BUY 3 / SELL 2       │
  │   RSI:          BUY 2 / SELL 1       │
  └────────────────────────────────────────┘
```

### 7.2 DB 직접 조회로 심층 분석

SignalRepository와 TradeRepository를 활용해 전략 성과를 분석합니다.

```python
# 전략별 시그널 이력 조회
async with get_session() as session:
    repo = SignalRepository(session)
    signals = await repo.get_by_strategy("ma_crossover", limit=100)
    # strategy_name, signal_type, strength, created_at, metadata

# 일별 손익 조회
async with get_session() as session:
    repo = TradeRepository(session)
    pnl = await repo.get_daily_pnl(date=datetime.today())
    # {"buy": {"value": ..., "fee": ...}, "sell": {"value": ..., "fee": ...}}

# 거래소별 체결 내역 (TradeModel.exchange 활용)
async with get_session() as session:
    result = await session.execute(
        select(TradeModel)
        .where(TradeModel.exchange == "upbit")
        .order_by(TradeModel.executed_at.desc())
    )
```

---

## 8. 엔진 종료 흐름 (Graceful Shutdown)

```text
사용자: Ctrl+C (또는 SIGTERM 전송)
        │
        ▼
  SIGINT 핸들러 호출 → stop_event.set()
        │
        ▼
  진행 중 작업 완료 대기
        │
        ├─► engine.stop()       ← WebSocket 연결 종료
        ├─► scheduler.stop()    ← 예약 작업 중단
        ├─► rest_client.close() ← HTTP 세션 정리
        ├─► discord.close()     ← Discord 세션 정리
        ├─► (Redis) event_bus.disconnect()
        └─► close_db()          ← DB 세션 풀 종료
        │
        ▼
  "=== 종료 완료 ===" 로그 출력

주의: 현재 처리 중인 주문이 있을 경우 체결 완료 후 종료됩니다.
```

---

## 9. 트러블슈팅 (Troubleshooting)

### 주요 문제 상황별 확인 경로

| 증상 | 확인 위치 | 조치 |
| --- | --- | --- |
| 시그널이 발생하지 않음 | SignalModel DB 조회 | 전략 파라미터 재확인, warm-up 캔들 수 부족 여부 확인 |
| 주문이 체결되지 않음 | OrderModel.status 확인 | Upbit API 키 잔여 권한, 잔고 부족, 리스크 거부 로그 |
| 대시보드 이벤트 미수신 | WebSocket 연결 상태 확인 | 브라우저 콘솔 에러, ws://localhost:8000/ws/events 직접 확인 |
| 손절/익절 미작동 | stop_loss.py 로그 확인 | STOP_LOSS_PCT, TAKE_PROFIT_PCT 설정값 확인 |
| Discord 알림 미수신 | discord.py 로그 확인 | DISCORD_WEBHOOK_URL 유효성 확인 |
| TradeModel 저장 누락 | order_manager.py 로그 | 주문 실패 여부 확인 (failed 상태면 TradeModel 미생성) |

### 데이터 추적 디버깅 쿼리

```sql
-- 최근 시그널 확인
SELECT strategy_name, symbol, signal_type, strength, created_at
FROM signals ORDER BY created_at DESC LIMIT 20;

-- 체결 내역 + 거래소 확인
SELECT symbol, side, quantity, price, exchange, strategy_name, executed_at
FROM trades ORDER BY executed_at DESC LIMIT 20;

-- 전략별 시그널 통계
SELECT strategy_name, signal_type, COUNT(*) as cnt
FROM signals GROUP BY strategy_name, signal_type;
```

---

## 10. 운영 시나리오별 권장 흐름

### 시나리오 A: 단독 전략 운영

```text
1. 백테스트로 MA Crossover 파라미터 최적화
2. python main.py 실행 (MA 전략만 활성화)
3. 대시보드에서 실시간 모니터링
4. 일일 리포트로 성과 확인
5. 매주 파라미터 미세 조정
```

### 시나리오 B: 앙상블 전략 운영

```text
1. 개별 전략 백테스트로 각 전략의 승률 확인
2. StrategyAggregator threshold 설정 (기본 60%)
3. python main.py 실행 (Aggregator 포함)
4. SignalRepository로 전략별 기여도 분석
   → 어느 전략이 가장 많은 BUY를 발생시켰는가?
   → TradeModel과 비교해 실제 수익으로 이어졌는가?
5. 성과 낮은 전략 제외, threshold 조정
```

### 시나리오 C: ML 전략 도입

```text
1. 실거래 데이터 수집 (최소 2~4주)
   → SignalModel: 어떤 시그널이 발생했는가?
   → TradeModel: 해당 시그널 후 수익이 났는가?
2. 위 데이터로 학습 라벨 생성
3. MLStrategy 모델 학습 및 저장
4. main.py에서 MLStrategy 활성화
5. 기존 전략과 병렬 운영 후 성과 비교
```
