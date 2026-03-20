# 전략 이력 (Strategy History)

전략 구성의 변경 이력을 날짜 및 버전별로 누적 기록한다.

---

## v0.1.0 — 2026-03-20 (초기 구현 상태 기록)

> 전략 수정 이전 최초 상태. 모든 전략은 `strategy/impl/` 하위에 구현되어 있으며,
> EventBus를 통해 `PRICE_UPDATED` 이벤트를 수신하고 `SIGNAL_GENERATED` 이벤트를 발행한다.
> 각 전략은 `AbstractStrategy`를 상속하며, 실시간(`on_tick`)과 백테스트(`_evaluate`) 경로를 모두 지원한다.

---

### 공통 판단 구조

| 구성 요소 | 역할 |
|---|---|
| `FeatureBuilder` | MarketSnapshot에서 캔들을 읽어 SMA/EMA/RSI/Bollinger/MACD 피처를 계산 |
| `Features` | 전략에 주입되는 데이터 컨테이너 (symbol, close_prices, sma_short/long, ema_short/long, rsi_14 등) |
| `Signal` | 전략이 반환하는 신호 객체 (signal_type, strength, metadata) |
| `SignalType` | BUY / SELL / HOLD |
| `RiskManager` | 주문 발행 전 3단계 검증 (order size → daily loss → position ratio) |
| `OrderManager` | 신호 수신 → cooldown 확인 → RiskManager 통과 → broker 주문 발행 |

---

### 전략 1: MA Crossover (이동평균 크로스오버)

- **파일**: `strategy/impl/ma_crossover.py`
- **클래스**: `MACrossoverStrategy`
- **기본 파라미터**: `short_window=5`, `long_window=20`, `rsi_period=14`

- **설명**:
  단기 SMA와 장기 SMA의 교차를 기반으로 매수·매도 신호를 생성한다.
  골든크로스(단기 > 장기 상향 돌파) 발생 시 BUY,
  데드크로스(단기 < 장기 하향 이탈) 발생 시 SELL.
  RSI 필터를 추가로 적용하여 골든크로스 시 RSI < 70(과매수 아님),
  데드크로스 시 RSI > 30(과매도 아님) 조건을 만족할 때만 신호를 발행.
  크로스 전환 시점에만 신호를 1회 발행하며 (`_prev_cross` 상태 관리), 중복 신호를 방지한다.
  신호 강도(strength)는 SMA 이격도 비율로 계산 (이격 1% = strength 0.1, 최대 1.0).

- **역할**:
  추세 추종(Trend Following) 전략. 상승 추세 진입 및 하락 추세 이탈 포착.
  RSI 필터로 극단적 과매수/과매도 구간에서의 오진입 억제.

- **사용한 이유**:
  구현이 단순하고 직관적이며, 크립토 시장의 추세 구간에서 어느 정도 유효성이 알려진 베이스라인 전략.
  시스템 아키텍처(FeatureBuilder 연동, EventBus 발행, DB 저장, 백테스트 경로)를 검증하는 참조 구현으로도 활용.

- **문제점 및 한계**:
  - SMA는 후행 지표(lagging indicator)로, 추세 전환을 뒤늦게 감지한다.
  - 횡보(sideways) 구간에서 잦은 거짓 신호(whipsaw) 발생 → 거래비용 누적.
  - `short_window=5`, `long_window=20`은 1분봉 기준 최적화 검증 없이 설정된 기본값이다.
  - 크로스 전환 감지가 캔들 확정 시점이 아닌 실시간 틱 기준이므로, 캔들 미확정 구간에서 거짓 전환이 발생할 수 있다.
  - RSI 필터 임계값(30/70)이 하드코딩에 가깝고, 시장 레짐에 따라 최적값이 달라진다.
  - 신호 강도 계산(`ratio * 10`)은 임의적 스케일링으로, 실제 포지션 크기 결정에 직접 활용하기 어렵다.

- **대안**:
  - 캔들 확정 시점(`on_candle_closed`) 기준으로 크로스 판단
  - Hull MA, DEMA 등 후행성을 줄인 이동평균 지표 도입
  - ATR 기반 레짐 필터 추가 (추세 구간에서만 전략 활성화)
  - 파라미터 최적화: 1분봉/5분봉 구간별 walk-forward 검증

---

### 전략 2: RSI (상대강도지수 반전)

- **파일**: `strategy/impl/rsi_strategy.py`
- **클래스**: `RsiStrategy`
- **기본 파라미터**: `rsi_period=14`, `oversold_level=30`, `overbought_level=70`

- **설명**:
  RSI 값의 구간 전환을 기반으로 신호를 생성하는 평균 회귀(Mean Reversion) 전략.
  RSI가 `oversold_level`(기본 30) 미만으로 진입 후 다시 그 이상으로 회복할 때 BUY,
  `overbought_level`(기본 70) 초과 진입 후 그 이하로 이탈할 때 SELL.
  구간 전환 순간에만 1회 신호를 발행한다 (`_prev_zone` 상태: `oversold` / `overbought` / `neutral`).
  신호 강도는 구간 경계에서의 회복 거리 비율로 계산.

- **역할**:
  단기 과매수/과매도 반전 포착. MA Crossover와 독립적으로 작동하여 신호 다양성 확보.

- **사용한 이유**:
  가장 널리 사용되는 오실레이터 지표 중 하나로, 크립토 단기 변동성 구간에서 반전 신호로 활용 사례가 많음.
  MA Crossover와 다른 성격(추세 추종 vs 평균 회귀)으로 포트폴리오 내 신호 상관 완화를 의도.

- **문제점 및 한계**:
  - 강한 추세 구간에서 RSI는 오랫동안 과매수/과매도 상태를 유지 → 조기 반전 신호로 손실 유발.
  - RSI `period=14`는 1분봉 기준 14분 데이터로, 노이즈에 매우 민감하다.
  - `oversold=30`, `overbought=70`은 전통적 기준값이며 크립토 변동성에 맞게 조정 필요성이 있다.
  - 실시간 틱 기준으로 구간 전환을 감지하므로, 캔들 미확정 시 일시적 진입·이탈 반복 가능성이 있다.
  - `on_tick` 내에서 `get_candles` → RSI 전체 재계산을 매 틱마다 수행 (증분 계산 없음).

- **대안**:
  - 캔들 확정 기준 신호 발행으로 변경
  - RSI 기간 다변화 (RSI-7, RSI-21 등 멀티 타임프레임 확인)
  - Stochastic RSI, CCI 등 더 민감한 오실레이터 비교 검토
  - 추세 지표(ADX 등)와 조합하여 추세 구간에서 RSI 신호 비활성화

---

### 전략 3: Bollinger Band (볼린저 밴드 반전)

- **파일**: `strategy/impl/bollinger_strategy.py`
- **클래스**: `BollingerStrategy`
- **기본 파라미터**: `window=20`, `num_std=2.0`

- **설명**:
  볼린저 밴드의 상·하단 터치 후 회복을 기반으로 신호를 생성하는 평균 회귀 전략.
  가격이 하단 밴드 이하로 진입 후 다시 밴드 내로 회복할 때 BUY,
  상단 밴드 이상으로 진입 후 다시 밴드 내로 하락할 때 SELL.
  `_prev_zone` 상태(`below_lower` / `above_upper` / `neutral`)로 전환 시점만 포착.
  신호 강도는 밴드 폭 대비 회복 거리 비율로 계산.

- **역할**:
  단기 가격 변동성 기반 반전 포착. RSI 전략과 유사한 역할이지만 가격 밴드 절대값 기준으로 보완.

- **사용한 이유**:
  볼린저 밴드는 변동성을 가격 단위로 직접 표현하므로, RSI의 상대적 강도와 다른 관점의 신호를 제공.
  밴드 폭(Band Width)이 좁아질 때 Squeeze 발생 → 변동성 폭발 전 조기 포착 가능성 고려.

- **문제점 및 한계**:
  - 볼린저 밴드 자체가 SMA 기반이므로 MA Crossover와 피처 중복(동일 price series 파생).
  - 강한 추세에서 가격이 밴드를 타고 이동하는 경우(Band Riding), 반전 신호가 지속적으로 오발.
  - `window=20` 기준 밴드가 1분봉에서 너무 좁아 빈번한 밴드 이탈 발생 가능.
  - `num_std=2.0`은 가격의 약 95% 구간을 포함하는 통계적 설정이지만, 크립토의 비정규분포 특성 고려 미흡.
  - RSI 전략과 신호 상관이 높아(동일한 과매도/과매수 구간에서 함께 발생) 중복 진입 위험.

- **대안**:
  - Keltner Channel(ATR 기반)과 병행하여 Squeeze 감지 고도화
  - 밴드 폭 필터 추가 (Band Width가 일정 수준 이상일 때만 신호 활성화)
  - RSI 전략과의 상관 분석 후 둘 중 하나 제거 또는 가중치 조정 검토
  - 멀티 타임프레임 볼린저 밴드 (1분봉 + 5분봉) 조합

---

### 전략 4: MACD (이동평균 수렴·발산)

- **파일**: `strategy/impl/macd_strategy.py`
- **클래스**: `MacdStrategy`
- **기본 파라미터**: `fast=12`, `slow=26`, `signal=9`

- **설명**:
  MACD 라인(단기 EMA - 장기 EMA)과 시그널 라인(MACD의 EMA)의 교차를 기반으로 신호를 생성.
  MACD 라인이 시그널 라인을 상향 돌파(골든크로스) 시 BUY,
  하향 이탈(데드크로스) 시 SELL.
  `_prev_position` 상태(`above` / `below`)로 교차 순간만 포착.
  신호 강도는 히스토그램 절댓값을 100으로 나눈 값(최대 1.0).

- **역할**:
  추세의 모멘텀 변화 포착. MA Crossover가 가격 직접 교차를 보는 것과 달리, MACD는 EMA 간 거리의 변화율을 본다.

- **사용한 이유**:
  MA Crossover보다 빠른 모멘텀 전환 감지 가능성. 히스토그램을 통한 신호 강도 정량화가 용이.
  전통적으로 일봉 기준으로 유효성이 검증된 지표로, 프로젝트 초기 베이스라인 전략군에 포함.

- **문제점 및 한계**:
  - `fast=12`, `slow=26`, `signal=9`는 일봉 기준 기본값. 1분봉 적용 시 전혀 다른 특성을 가진다.
  - 매 틱마다 `slow + signal` 길이의 전체 EMA를 재계산 (`for i in range(signal + slow, len(prices) + 1)`). 증분 계산 없어 캔들 누적 시 CPU 부하 증가.
  - MA Crossover와 근본적으로 동일한 이동평균 교차 로직이어서 신호 상관이 높다.
  - 히스토그램 기반 강도 계산에서 `/100` 정규화는 BTC 가격 스케일과 무관하게 설계되어, 실제로 strength ≈ 0에 가까운 값이 대부분 나올 수 있다.

- **대안**:
  - 증분 EMA 계산으로 교체 (성능 개선)
  - 1분봉 전용 파라미터 탐색 (`fast=3`, `slow=8`, `signal=5` 등)
  - MA Crossover와의 신호 상관 계수 측정 후 중복 제거 여부 결정
  - MACD 히스토그램 방향 전환(`divergence`) 기반의 고도화된 진입 조건 검토

---

### 전략 5: ML Strategy (RandomForest 기반 머신러닝)

- **파일**: `strategy/impl/ml_strategy.py`
- **클래스**: `MLStrategy`
- **기본 파라미터**: `short_window=5`, `long_window=20`, `rsi_period=14`, `look_ahead=5`, `threshold=0.005`, `n_estimators=100`

- **설명**:
  scikit-learn `RandomForestClassifier`를 사용하는 지도 학습 전략.
  입력 피처: `price_change_1`, `price_change_5`, `sma_ratio`, `ema_ratio`, `rsi_norm`, `volatility_5` (6차원 벡터).
  레이블: `look_ahead`봉 후 수익률이 `threshold` 초과 시 BUY(1), 미만 시 SELL(-1), 그 외 HOLD(0).
  `StandardScaler`로 피처 정규화 후 RandomForest 학습.
  신호 강도는 항상 고정값 `0.6`.
  백테스트 시 전체 캔들의 70%로 학습, 30%로 평가 (BacktestRunner 처리).
  재학습은 수동 호출(`train()`) 또는 파라미터 변경 시 `_is_trained=False` 플래그 설정 후 재학습 필요.

- **역할**:
  기술적 지표만으로는 포착하기 어려운 복합 패턴을 학습하여, 규칙 기반 전략의 한계를 보완하는 목적.

- **사용한 이유**:
  규칙 기반 전략(MA, RSI, Bollinger, MACD)이 모두 동일한 price series에서 파생된 단순 지표에 의존하는 한계를 ML로 보완 시도.
  RandomForest는 비선형 패턴 학습, 피처 중요도 측정, 과적합 일부 완화 등의 이점이 있음.

- **문제점 및 한계**:
  - **입력 피처 6개 모두 동일한 price series에서 파생** (`sma_ratio`, `ema_ratio`, `price_change` 등 → 고도의 다중공선성). 모델이 실질적으로 학습할 독립 정보가 없다.
  - **Walk-forward validation 없음**: 70% 학습 / 30% 테스트 단일 분할. 백테스트 수익률이 과거 특정 구간에 과적합된 결과일 가능성이 높다.
  - **미래 데이터 의존 레이블**: `look_ahead`봉 후의 가격으로 레이블을 생성하는 구조는 정의상 올바르나, 학습 데이터 분포와 실전 데이터 분포가 상이할 경우 성능이 크게 저하된다 (distribution shift).
  - **신호 강도 하드코딩 0.6**: 모델의 예측 확률(predict_proba)을 반영하지 않아, 높은 확신도와 낮은 확신도의 신호가 동일하게 처리된다.
  - **학습 시 매 반복마다 MarketSnapshot을 새로 생성**: `train()` 내 O(N²) 루프 구조로, 캔들 수가 많을수록 학습 시간이 급증한다.
  - **정확도 검증이 학습 데이터 전체(in-sample)**: 성능 로그의 `acc`는 학습 샘플 전체를 다시 예측한 in-sample accuracy로, 실제 일반화 성능과 무관하다.
  - **실전 운영 중 재학습 스케줄 없음**: 시장 레짐 변화에 따른 모델 드리프트를 감지하거나 대응하는 메커니즘이 없다.
  - **호가창, 거래량, 체결 데이터 등 가격 외 정보 미활용**.

- **대안**:
  - 가격 파생 피처 외에 독립 정보 추가: 거래량 프로파일, order book imbalance, funding rate(선물)
  - Walk-forward cross-validation (expanding window 또는 rolling window) 도입
  - `predict_proba`를 신호 강도로 활용 (e.g., `strength = P(BUY) - P(SELL)`)
  - 학습 루프를 슬라이딩 피처 캐싱 방식으로 O(N) 개선
  - Out-of-sample 성능 지표(Sharpe, precision/recall per class) 기록
  - 정기 재학습 스케줄러 연동 및 성능 저하 감지 시 자동 비활성화

---

### 지표 계산 모듈 (data/processor/indicators/)

| 모듈 | 함수 | 설명 |
|---|---|---|
| `moving_average.py` | `sma(prices, window)` | 단순 이동평균. 데이터 부족 시 None 반환 |
| `moving_average.py` | `ema(prices, period)` | 지수 이동평균. multiplier = 2/(period+1) |
| `rsi.py` | `rsi(prices, period)` | Wilder 방식 RSI. 평균 상승/하락폭 기반 |
| `bollinger.py` | `bollinger_bands(prices, window, num_std)` | (upper, middle, lower) 반환 |
| `macd.py` | `macd(prices, fast, slow, signal)` | (macd_line, signal_line, histogram) 반환. 매 호출마다 full history 재계산 |

**공통 문제점**: 모든 지표가 매 틱마다 전체 price history를 재계산 (증분 계산 없음). 캔들 수 증가 시 CPU 부하 비례 증가.

---

### 버전 요약

| 버전 | 날짜 | 변경 내용 |
|---|---|---|
| v0.1.0 | 2026-03-20 | 초기 구현 상태 기록. MA Crossover, RSI, Bollinger, MACD, ML(RandomForest) 5개 전략 |

---

*다음 수정 시 이 파일 하단에 새 버전 섹션을 추가할 것.*
