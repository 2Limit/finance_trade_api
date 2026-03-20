# 종합 평가 보고서

- **작성일**: 2026-03-20
- **평가 대상**: finance_trade_api 자동화 트레이딩 시스템
- **평가 기준**: 실전 운용 가능성, 전략 경쟁력, 시스템 안정성, 리스크 관리
- **평가자 관점**: 퀀트 트레이딩 시스템 아키텍트 / 실운용 엔지니어

---

## 목차

1. [전략 경쟁력 (Edge 분석)](#1-전략-경쟁력-edge-분석)
2. [Execution 리스크 분석](#2-execution-리스크-분석)
3. [이벤트 기반 아키텍처 안정성](#3-이벤트-기반-아키텍처-안정성)
4. [RiskManager 평가](#4-riskmanager-평가)
5. [실전 운영 관점 분석](#5-실전-운영-관점-분석)
6. [개선 로드맵](#6-개선-로드맵)

---

## 1. 전략 경쟁력 (Edge 분석)

### 이 전략들이 왜 대부분 실패하는가

**근본 문제: 공개된 정보에는 alpha가 없다.**

MA, RSI, Bollinger, MACD는 모두 1990년대 이전에 발표된 지표들이다. 이 지표들이 알파를 생성할 수 있었던 시기는:

1. 전산화 이전 → 계산 자체가 희소 자원이었던 시기
2. 정보 비대칭이 극심했던 시기

2020년대 크립토 시장에서는 수천 개의 알고리즘이 동일한 신호를 동시에 감지한다. MA 골든크로스가 발생하는 순간, 해당 신호를 기다리던 봇들이 동시에 매수를 시도하고 그 충격 자체가 신호의 수익성을 소멸시킨다. **신호가 알려진 순간 alpha는 사라진다.**

**현재 전략 구조의 구조적 문제:**

```
MA Crossover  ─┐
RSI           ─┤  모두 동일한 price series에서
Bollinger     ─┤  파생된 후행 지표
MACD          ─┘
                ↓
         정보 내용 = 0 (모두 같은 정보를 다른 방식으로 표현)
```

5개 전략의 피처 상관계수를 측정하면 0.7~0.9 수준일 것이다. 앙상블(Aggregator)을 구성해도 독립적인 정보가 없으면 분산 감소 효과만 있을 뿐, 기대수익 자체는 개별 전략의 평균과 동일하다.

**ML 전략이 특히 위험한 이유:**

`strategy/impl/ml_strategy.py` — 피처 목록:

```python
_FEATURE_NAMES = [
    "price_change_1", "price_change_5",
    "sma_ratio", "ema_ratio",      # MA에서 파생
    "rsi_norm", "volatility_5",    # 가격에서 파생
]
```

6개 피처 전부 동일한 close price에서 파생된다. RandomForest가 아무리 복잡한 비선형 조합을 학습해도 **독립 정보가 없으면 새로운 예측력은 생기지 않는다.** In-sample accuracy가 높게 나오는 것은 과적합 때문이다.

### 단순 지표 기반 전략의 한계

| 한계 | 내용 |
|---|---|
| **후행성** | SMA/EMA는 과거 평균이므로 추세 전환을 뒤늦게 반영 |
| **공개 정보** | 수천 개의 봇이 동일 신호를 동시에 감지 → 신호 발생 즉시 alpha 소멸 |
| **레짐 무시** | 추세/횡보/고변동 레짐에 관계없이 동일 로직 적용 |
| **다중공선성** | MA, RSI, Bollinger, MACD 모두 동일 price series 파생 → 독립 정보 없음 |
| **비대칭 시장** | 크립토는 정규분포 가정이 깨지는 팻테일(fat tail) 분포 → 표준편차 기반 지표 오작동 |

### 어떤 전략 구조로 바꿔야 하는가

실전에서 검증된 alpha source:

| 카테고리 | 구체적 방법 | 난이도 |
|---|---|---|
| **호가창 정보** | Order book imbalance, bid-ask spread, iceberg 감지 | 중 |
| **체결 데이터** | Trade flow imbalance, large trade detection | 중 |
| **크로스-심볼** | BTC 선물-현물 premium, funding rate | 중 |
| **시장 레짐** | HMM 기반 bull/bear/sideways 분류 후 레짐별 전략 적용 | 상 |
| **통계적 재정거래** | 코인 간 cointegration 기반 pairs trading | 상 |
| **온체인 데이터** | Exchange inflow/outflow, whale 이동 탐지 | 상 |

**단기 현실적 개선 방향** (현재 구조 유지 시 최소 추가 항목):

1. 거래량 피처 (Volume × Price = Money Flow)
2. 펀딩비 (크립토 고유 alpha)
3. 레짐 필터 (ADX > 25 이면 추세 전략, ADX < 25 이면 평균 회귀 전략)
4. 볼륨 프로파일 (VPVR — 실제 거래가 많이 된 가격대)

---

## 2. Execution 리스크 분석

### SELL 수량 계산 버그 (치명적)

`execution/order_manager.py`:

```python
if side == OrderSide.BUY:
    quantity = self._default_order_krw / price
else:
    quantity = self._default_order_krw / price  # ← BUY와 동일! 실제 보유 수량 무시
```

**이것은 버그다.** SELL 시 실제 보유 수량을 참조하지 않고 BUY와 동일한 계산을 한다.
보유량보다 많은 수량을 매도 시도 → 거래소 오류 → `ORDER_FAILED` 이벤트 → 손실 포지션 유지.

### 슬리피지 처리 전무

백테스트와 실전 모두 시장가 주문의 체결가 = 신호 발생 시점의 가격으로 가정한다.

```
Upbit BTC/KRW 1억원 시장가 매수 예시:
  호가 1: 95,000,000 × 0.3 BTC  = 28,500,000 KRW
  호가 2: 95,050,000 × 0.4 BTC  = 38,020,000 KRW
  호가 3: 95,120,000 × 0.35 BTC = 33,292,000 KRW

  평균 체결가 ≈ 95,057,000 (신호가 대비 +0.06%)
  알트코인 유동성 낮은 경우 슬리피지 0.3~1% 발생 흔함
```

**연간 영향**: 전략 수익률 2%일 때 슬리피지 0.1% × 200거래 = 20% → 실질 손실.

### 부분 체결 처리 없음

`execution/order_manager.py` — `_submit()` 내부:

```python
result = await broker.place_order(request)
# result.executed_qty를 그대로 TradeModel에 저장
# 부분 체결(executed_qty < requested_qty) 여부 비교 없음
# 잔여 미체결 수량에 대한 추가 처리 없음
```

지정가 주문이나 시장 유동성 부족 시 부분 체결이 발생하면 시스템은 전량 체결로 처리하고,
포지션과 실제 잔고가 벌어진다.

### API Rate Limit 처리 없음

Upbit REST API 제한: 초당 10회 (주문), 초당 30회 (조회).
현재 구조에서 5개 전략이 동시에 신호를 발생시키면 5번의 `place_order` 호출이 동시에 발생한다.
Rate limit 초과 시 거래소가 429를 반환하면 `except Exception` 블록에서 잡혀 주문 실패로 처리될 뿐이다.
**재시도 로직 없음.**

### DCA fire-and-forget 위험

`execution/order_manager.py`:

```python
asyncio.create_task(
    self._submit_dca(symbol, side, split_qty, strategy_name, price)
)
return  # 완료 여부 추적 안 함
```

DCA 진행 중에 SELL 신호가 발생하면, 쿨다운이 만료된 경우 SELL과 DCA BUY가 경쟁적으로 실행된다.
**포지션 방향이 역전될 수 있다.**

---

## 3. 이벤트 기반 아키텍처 안정성

### EventBus 핸들러 동시 실행 → 쿨다운 Race Condition

`core/event.py`:

```python
await asyncio.gather(
    *[self._call(h, event) for h in handlers],
    return_exceptions=True,
)
```

`PRICE_UPDATED` 이벤트에 5개 전략이 구독되어 있으면 5개 코루틴이 **동시에** 실행된다.
각 전략이 같은 틱에 모두 BUY 신호를 내면 DB에 5개 시그널이 기록되고 `on_signal`이 5번 호출된다.

`execution/order_manager.py` — 쿨다운 체크:

```python
last = self._last_order_time.get(symbol)
if last and (now - last).total_seconds() < self._cooldown_sec:
    return
self._last_order_time[symbol] = now   # ← 읽기-검사-쓰기가 비원자적
```

`asyncio.gather`는 코루틴을 동시에 **시작**하므로, 모든 `on_signal` 호출이
`_last_order_time.get(symbol)` 시점에 아직 쿨다운이 없는 상태를 읽을 수 있다.
→ **5개 전략이 같은 틱에 모두 BUY 주문을 낼 수 있다.**

### 이벤트 유실

```python
async def _call(self, handler, event):
    try:
        await handler(event)
    except Exception:
        logger.exception(...)  # 로그만, 재시도 없음
```

핸들러 실패 시 해당 이벤트는 영구 유실된다. Dead letter queue, 재시도, alert 없음.

### 백프레셔(Backpressure) 없음

WebSocket 틱이 빠르게 들어올 때 (100ms 간격), 각 틱의 처리 시간이 100ms를 초과하면
이벤트가 쌓인다. 현재 구조는 큐 없이 `asyncio.gather`로 즉시 처리하므로
처리 지연 누적 시 스택이 깊어지고 메모리 사용이 증가한다.

### 개선 방안 요약

| 문제 | 개선 방법 |
|---|---|
| 핸들러 동시 실행 race | `asyncio.Lock` per symbol 또는 Queue 기반 순차 처리 |
| 이벤트 유실 | Dead letter queue (Redis List 또는 asyncio.Queue) |
| 백프레셔 | `asyncio.Queue(maxsize=N)` + consumer worker 분리 |
| 쿨다운 비원자성 | per-symbol Lock으로 감싸기 |

---

## 4. RiskManager 평가

### 코드에서 발견된 포트폴리오 계산 버그

`execution/risk.py`:

```python
available_krw = self._account.get_available_krw()
total_portfolio = available_krw + order_value  # ← 기존 보유 코인 가치 미포함
position_ratio = float(order_value / total_portfolio)
```

총 포트폴리오 = 현금만 계산. BTC 1억원 보유 중 1천만원 추가 매수 시도 시:

- 실제 비중: 1천만 / 1.1억 = 9.1%
- 시스템 계산: 1천만 / (현금 + 1천만) → 현금이 0이면 100%로 계산되어 차단

### 실전 운용에 반드시 필요한 리스크 요소

| 항목 | 현재 | 필요 | 이유 |
|---|---|---|---|
| **Volatility Filter** | 없음 | ATR 또는 일중 변동폭 기준 | 급등락 구간 진입 차단 |
| **Liquidity Filter** | 없음 | 일평균 거래량 대비 주문 크기 제한 | 슬리피지 폭발 방지 |
| **Max Drawdown Control** | 없음 | 고점 대비 N% 하락 시 거래 중단 | 연속 손실 방어 |
| **Correlation Guard** | 없음 | 동방향 전략 중복 진입 제한 | 5개 전략 동시 BUY 방지 |
| **Stop-Loss (실제)** | Config만 | 거래소 레벨 조건부 주문 | 포지션 갱신 실패 대비 |
| **Position Sizing** | 고정 금액 | Kelly Criterion 또는 ATR 기반 | 리스크 대비 수익 최적화 |
| **Exposure Limit** | 단일 비중만 | 총 노출 + 심볼별 한도 | 멀티 심볼 동시 과노출 방지 |
| **Time-based Filter** | 없음 | 유동성 낮은 시간대 거래 제한 | 새벽 3~6시 스프레드 확대 구간 |

---

## 5. 실전 운영 관점 분석

### 가장 먼저 터질 문제 TOP 10

실제 돈을 넣으면 발생 순서대로:

**1위 — SELL 수량 버그 (첫날 발생 가능)**

SELL 시 `default_order_krw / price`로 수량 계산 → 보유량보다 적게 팔거나 많이 팔려는 오류.
주문 실패 반복 또는 잔고 불일치.

**2위 — 5개 전략 동시 BUY 신호 → 중복 매수**

동일 틱에서 MA, RSI, Bollinger, MACD가 모두 BUY → `asyncio.gather`로 동시 처리
→ 쿨다운 비원자적 통과 가능 → 5배 과매수.

**3위 — 재시작 후 포지션 불일치**

`_daily_loss=0`, `_last_order_time={}` 초기화 → 쿨다운 없이 전 전략이 신호 발사
+ 당일 이미 발생한 손실 카운터 리셋.

**4위 — 미체결 지정가 주문 누적**

주문 발행 후 체결 확인 루프 없음 → 거래소에 pending 주문이 쌓이고,
시스템은 체결된 것으로 기록 → 포지션/잔고 불일치 심화.

**5위 — DB 세션 경합 (SQLite)**

5개 전략이 동시에 `SignalModel` DB write → SQLite write lock 경합
→ 일부 신호 저장 실패 → 예외 무시(`logger.exception` only) → 조용한 데이터 누락.

**6위 — WebSocket 재연결 중 틱 유실**

재연결 간격 동안 가격 급변 → 유실 구간의 이동평균 계산 오류
→ 잘못된 크로스 신호 발생.

**7위 — DCA 진행 중 방향 반전**

BUY DCA 3회 중 2회 완료 시점에 SELL 신호 발생
→ 3번째 BUY와 SELL이 경쟁 → 최악의 경우 고점 매수 + 즉시 매도.

**8위 — Rate Limit 초과**

여러 심볼 + 여러 전략 + 빠른 틱 → Upbit 초당 10회 주문 제한 초과
→ 429 오류 → ORDER_FAILED → 손실 포지션 방치.

**9위 — 메모리 누적 (장기 운영)**

전략 `_prev_cross`, `_prev_zone` 딕셔너리가 심볼별로 무한 누적.
MarketSnapshot 캔들 히스토리 상한 없으면 메모리 증가. 수개월 운영 시 OOM 위험.

**10위 — 시간대 불일치로 daily_loss 미리셋**

UTC 기준 자정 리셋. KST 09:00에 실제 KRW 시장이 가장 활발한데,
UTC 리셋은 KST 09:00에 발생 → 장중 손실 카운터가 갑자기 0으로 리셋 → 리스크 한도 무력화.

### 반드시 추가해야 할 시스템

| 시스템 | 이유 |
|---|---|
| **Monitoring (Prometheus + Grafana)** | 주문 성공률, 슬리피지, 포지션 P&L 실시간 추적 없으면 문제를 사후에야 발견 |
| **Reconciliation Service** | 주기적으로 거래소 실잔고 ↔ 내부 DB 대조. 불일치 시 알림 + 자동 동기화 |
| **Circuit Breaker** | 연속 N회 주문 실패, 또는 N분 내 M% 손실 시 전체 거래 중단 |
| **State Persistence** | `_daily_loss`, `open_positions`, `_last_order_time`을 Redis 또는 DB에 영속화 |
| **Order Status Poller** | 미체결 주문을 주기적으로 거래소에서 조회하여 상태 동기화 |
| **Alert Escalation** | Discord 알림 → 임계 초과 시 SMS/전화 → 최악의 경우 자동 전량 청산 |
| **Paper Trading Mode** | 실제 주문 없이 동일 로직으로 모의 운영하여 전략 검증 |

---

## 6. 개선 로드맵

### Phase 1 — 실제 운용 가능한 시스템 (4~6주)

목표: "돈을 잃지 않는 시스템". 수익성보다 안정성 우선.

```
[P0] SELL 수량 버그 수정 (position.qty 참조로 교체)
[P0] 쿨다운 체크 per-symbol Lock 적용 (동시 신호 차단)
[P0] 상태 영속화: daily_loss, last_order_time → Redis/DB
[P0] 재시작 시 거래소 잔고 + 미체결 주문 동기화 루프

[P1] Order Status Poller (5초 간격 미체결 주문 상태 확인)
[P1] DB → PostgreSQL 전환 (write lock 경합 제거)
[P1] 부분 체결 처리 (executed_qty < requested_qty 감지 + 잔여 주문 처리)
[P1] Rate Limiter (토큰 버킷 방식, Upbit 제한 내로 주문 속도 제한)
[P1] Circuit Breaker (연속 3회 주문 실패 시 5분 거래 중단)

[P2] RiskManager 포트폴리오 계산 버그 수정 (코인 평가액 포함)
[P2] Reconciliation Service (10분 주기 거래소 ↔ DB 잔고 대조)
[P2] 기본 Monitoring (Prometheus metrics: 주문 수, 성공률, P&L)
```

### Phase 2 — 안정적인 트레이딩 시스템 (2~3개월)

목표: "신뢰할 수 있는 시스템". 장기 무인 운영 가능.

```
[P0] Volatility Filter: 일중 ATR이 평균 2배 이상이면 신규 진입 차단
[P0] Max Drawdown Control: 고점 대비 10% 하락 시 자동 거래 중단
[P0] Position Sizing: ATR 기반 동적 수량 결정 (고변동성 = 소량 진입)

[P1] EventBus → asyncio.Queue 기반 재설계 (백프레셔, 순서 보장)
[P1] Dead Letter Queue (실패 이벤트 로깅 + 재시도)
[P1] WebSocket 지수 백오프 재연결 + heartbeat 모니터링

[P2] Grafana 대시보드 (전략별 성과, 슬리피지 추적, 포지션 현황)
[P2] Alert Escalation (Discord → PagerDuty 또는 SMS)
[P2] Paper Trading 모드 (config 플래그로 실주문 없이 전 로직 동일 실행)

[P3] Walk-forward validation 인프라 (전략 유효성 주기적 재검증)
[P3] KST 기반 시간 처리 통일 (daily_loss 리셋, 보고서 기준)
```

### Phase 3 — 수익 최적화 시스템 (3~6개월)

목표: "실제 alpha를 가진 시스템". 전략 경쟁력 자체를 높인다.

```
[P0] 레짐 분류기: ADX + 변동성 기반으로 추세/횡보/고변동 레짐 구분
     → 레짐별 전략 활성화/비활성화 (MA는 추세에만, RSI는 횡보에만)

[P1] 호가창 데이터 수집: Order book imbalance 피처 추가
[P1] 거래량 피처: Money Flow Index, Volume Profile
[P1] 크립토 고유 데이터: 펀딩비, 선물-현물 프리미엄, 공포-탐욕 지수

[P2] ML 전략 재설계:
     - 가격 외 독립 피처 포함 (거래량, 펀딩비, order imbalance)
     - Walk-forward CV (expanding window, 3개월 재학습)
     - predict_proba → 신호 강도로 활용
     - OOS Sharpe ratio 기준 모델 배포 여부 결정

[P2] 전략 성과 Attribution:
     - 전략별 독립 손익 추적
     - 기여도 낮은 전략 자동 비활성화

[P3] TWAP/VWAP 실행 알고리즘 (대형 주문의 시장 충격 최소화)
[P3] Pairs Trading (BTC-ETH 또는 거래소간 차익 기회 탐색)
```

---

## 종합 점수

| 항목 | 점수 | 비고 |
|---|---|---|
| 아키텍처 설계 | 7 / 10 | 이벤트 드리븐, 레이어 분리, 비동기 구조는 잘 설계됨 |
| 전략 경쟁력 | 2 / 10 | 공개 지표 의존, alpha 부재 |
| Execution 안정성 | 3 / 10 | SELL 버그, 슬리피지 미처리, race condition |
| 리스크 관리 | 3 / 10 | 3개 항목만 존재, 포트폴리오 계산 버그 |
| 운영 가능성 | 2 / 10 | 모니터링, 상태 영속화, reconciliation 전무 |
| **종합** | **2.5 / 10** | Phase 1 완료 전 실전 투입 불가 |

---

## 결론

> **Phase 1을 완료하기 전에는 실제 자금을 투입하지 마라.**
> 현재 상태에서 가장 먼저 발생할 일은
> "시스템이 조용히 잘못된 주문을 낸 뒤, 아무도 눈치채지 못하는 것"이다.

아키텍처는 Junior → Senior 수준으로 잘 설계됐다. 코드 품질도 좋다.
그러나 **트레이딩 시스템에서 아키텍처는 필요조건이지 충분조건이 아니다.**

**우선순위 요약:**

1. SELL 수량 버그 수정 (즉시)
2. 쿨다운 race condition 수정 (즉시)
3. 상태 영속화 + 재시작 복구 (1주 이내)
4. 슬리피지 포함 백테스트 재실행 (전략 유효성 재검증)
5. PostgreSQL 전환 + Order Status Poller (2주 이내)
6. 전략 alpha 재설계 (레짐 필터, 거래량 피처 추가)
