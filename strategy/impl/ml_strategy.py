"""
MLStrategy: scikit-learn 기반 머신러닝 전략

입력 피처 (Features → 6차원 벡터):
    [0] price_change_1  : 직전 봉 대비 수익률
    [1] price_change_5  : 5봉 전 대비 수익률
    [2] sma_ratio       : sma_short / sma_long - 1
    [3] ema_ratio       : ema_short / ema_long - 1
    [4] rsi_norm        : RSI / 100 (0.0~1.0)
    [5] volatility_5    : 최근 5봉 표준편차/평균

레이블:
    BUY  ( 1): future_return(look_ahead 봉) > threshold
    SELL (-1): future_return < -threshold
    HOLD ( 0): 그 외

사용 방법:
    strategy = MLStrategy(name="ml", symbols=["KRW-BTC"], params={})
    strategy.train(candles)          # 역사 데이터로 학습
    strategy.set_snapshot(snapshot)  # 실시간 피처 빌더 연결
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from strategy.base import AbstractStrategy, Signal, SignalType

if TYPE_CHECKING:
    from market.snapshot import Candle, MarketSnapshot
    from core.event import Event, EventBus
    from data.processor.feature_builder import Features

logger = logging.getLogger(__name__)

_FEATURE_NAMES = [
    "price_change_1", "price_change_5",
    "sma_ratio", "ema_ratio",
    "rsi_norm", "volatility_5",
]


def _features_to_vector(features: "Features") -> list[float] | None:
    """Features → 6차원 float 벡터. 필드 누락 시 None."""
    if any(v is None for v in [
        features.sma_short, features.sma_long,
        features.ema_short, features.ema_long,
        features.rsi_14,
    ]):
        return None

    closes = [float(c) for c in features.close_prices]
    if len(closes) < 5:
        return None

    price_change_1 = closes[-1] / closes[-2] - 1 if closes[-2] != 0 else 0.0
    price_change_5 = closes[-1] / closes[-5] - 1 if closes[-5] != 0 else 0.0

    sma_long = float(features.sma_long)  # type: ignore[arg-type]
    ema_long = float(features.ema_long)  # type: ignore[arg-type]
    sma_ratio = float(features.sma_short) / sma_long - 1 if sma_long != 0 else 0.0  # type: ignore[arg-type]
    ema_ratio = float(features.ema_short) / ema_long - 1 if ema_long != 0 else 0.0  # type: ignore[arg-type]

    rsi_norm = float(features.rsi_14) / 100.0  # type: ignore[arg-type]

    recent = closes[-5:]
    mean = sum(recent) / len(recent)
    std = (sum((x - mean) ** 2 for x in recent) / len(recent)) ** 0.5
    volatility_5 = std / mean if mean != 0 else 0.0

    return [price_change_1, price_change_5, sma_ratio, ema_ratio, rsi_norm, volatility_5]


class MLStrategy(AbstractStrategy):
    """
    RandomForestClassifier 기반 전략.

    params:
        short_window (int=5)   : 단기 이동평균 기간
        long_window  (int=20)  : 장기 이동평균 기간
        rsi_period   (int=14)  : RSI 기간
        look_ahead   (int=5)   : 레이블 산출에 사용할 미래 봉 수
        threshold    (float=0.005): 수익률 임계치 (0.5%)
        n_estimators (int=100) : RandomForest 트리 수
    """

    DEFAULT_PARAMS: dict[str, Any] = {
        "short_window": 5,
        "long_window": 20,
        "rsi_period": 14,
        "look_ahead": 5,
        "threshold": 0.005,
        "n_estimators": 100,
    }

    def __init__(
        self,
        name: str,
        symbols: list[str],
        params: dict[str, Any] | None = None,
    ) -> None:
        merged = {**self.DEFAULT_PARAMS, **(params or {})}
        super().__init__(name=name, symbols=symbols, params=merged)

        self._model: Any | None = None          # sklearn estimator
        self._is_trained = False
        self._snapshot: "MarketSnapshot | None" = None
        self._feature_builder: Any | None = None

    # ── Snapshot 연결 (실시간) ────────────────────────────────────────────────

    def set_snapshot(self, snapshot: "MarketSnapshot") -> None:
        self._snapshot = snapshot
        self._rebuild_feature_builder()

    def _rebuild_feature_builder(self) -> None:
        if self._snapshot is None:
            return
        from data.processor.feature_builder import FeatureBuilder
        self._feature_builder = FeatureBuilder(
            snapshot=self._snapshot,
            short_window=int(self.params["short_window"]),
            long_window=int(self.params["long_window"]),
            rsi_period=int(self.params["rsi_period"]),
        )

    def required_candles(self) -> int:
        return int(self.params["long_window"]) + int(self.params["look_ahead"]) + 15

    # ── 학습 ─────────────────────────────────────────────────────────────────

    def train(self, candles: list["Candle"]) -> None:
        """
        캔들 시퀀스로 모델 학습.

        슬라이딩 윈도우로 피처/레이블 쌍을 생성한 뒤 RandomForest 학습.
        최소 required_candles() + look_ahead 봉이 필요.
        """
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            logger.error("scikit-learn이 없습니다. pip install scikit-learn")
            return

        from data.processor.feature_builder import FeatureBuilder

        if not candles or len(candles) < self.required_candles():
            logger.warning("MLStrategy.train: 캔들 수 부족 (%d < %d)",
                           len(candles), self.required_candles())
            return

        long_w = int(self.params["long_window"])
        rsi_p  = int(self.params["rsi_period"])
        short_w = int(self.params["short_window"])
        look_ahead = int(self.params["look_ahead"])
        threshold = float(self.params["threshold"])

        symbol = candles[0].symbol
        X: list[list[float]] = []
        y: list[int] = []

        for i in range(long_w + rsi_p, len(candles) - look_ahead):
            # i번째까지의 캔들로 임시 스냅샷 생성 (FeatureBuilder는 캔들만 사용)
            from market.snapshot import MarketSnapshot as _Snap
            tmp = _Snap()
            for c in candles[: i + 1]:
                tmp.update_candle(c)

            fb = FeatureBuilder(
                snapshot=tmp,
                short_window=short_w,
                long_window=long_w,
                rsi_period=rsi_p,
            )
            features = fb.build(symbol)
            if features is None:
                continue

            vec = _features_to_vector(features)
            if vec is None:
                continue

            # 미래 수익률로 레이블 산출
            future_price = float(candles[i + look_ahead].close)
            current_price = float(candles[i].close)
            future_return = (future_price / current_price) - 1 if current_price != 0 else 0.0

            if future_return > threshold:
                label = 1       # BUY
            elif future_return < -threshold:
                label = -1      # SELL
            else:
                label = 0       # HOLD

            X.append(vec)
            y.append(label)

        if len(X) < 10:
            logger.warning("MLStrategy.train: 학습 샘플 부족 (%d개)", len(X))
            return

        import numpy as np
        X_arr = np.array(X)
        y_arr = np.array(y)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_arr)

        clf = RandomForestClassifier(
            n_estimators=int(self.params["n_estimators"]),
            random_state=42,
            n_jobs=-1,
        )
        clf.fit(X_scaled, y_arr)

        # scaler와 모델을 함께 보관
        class _Pipeline:
            def __init__(self, sc, model):
                self.sc = sc
                self.model = model

            def predict(self, x):
                import numpy as _np
                return self.model.predict(self.sc.transform(_np.array([x])))[0]

        self._model = _Pipeline(scaler, clf)
        self._is_trained = True

        # 간단 성능 로그
        import numpy as np
        preds = np.array([self._model.predict(x) for x in X])
        acc = (preds == y_arr).mean()
        buy_cnt = (y_arr == 1).sum()
        sell_cnt = (y_arr == -1).sum()
        logger.info(
            "MLStrategy '%s' 학습 완료: 샘플=%d, 정확도=%.2f%%, BUY=%d SELL=%d HOLD=%d",
            self.name, len(X), acc * 100, buy_cnt, sell_cnt, (y_arr == 0).sum()
        )

    def is_trained(self) -> bool:
        return self._is_trained

    # ── 예측 ─────────────────────────────────────────────────────────────────

    def _predict(self, features: "Features") -> SignalType | None:
        """Features → SignalType 예측. 미학습 또는 피처 부족 시 None."""
        if not self._is_trained or self._model is None:
            return None
        vec = _features_to_vector(features)
        if vec is None:
            return None
        try:
            label = self._model.predict(vec)
            if label == 1:
                return SignalType.BUY
            elif label == -1:
                return SignalType.SELL
            return SignalType.HOLD
        except Exception as e:
            logger.debug("MLStrategy 예측 오류: %s", e)
            return None

    # ── 백테스트 호환 ─────────────────────────────────────────────────────────

    def _evaluate(self, features: "Features") -> Signal | None:
        """BacktestRunner가 호출하는 피처 기반 시그널 생성."""
        signal_type = self._predict(features)
        if signal_type is None or signal_type == SignalType.HOLD:
            return None
        return Signal(
            strategy_name=self.name,
            symbol=features.symbol,
            signal_type=signal_type,
            strength=0.6,
            metadata={"source": "ml_predict"},
        )

    # ── 실시간 거래 ───────────────────────────────────────────────────────────

    async def on_tick(self, event: "Event", bus: "EventBus") -> None:
        if not self._is_trained or self._feature_builder is None:
            return
        payload = event.payload
        symbol: str = payload.get("symbol", "")
        if symbol not in self.symbols:
            return

        features = self._feature_builder.build(symbol)
        if features is None:
            return

        signal_type = self._predict(features)
        if signal_type is None or signal_type == SignalType.HOLD:
            return

        from core.event import Event as CoreEvent, EventType
        await bus.publish(CoreEvent(
            type=EventType.SIGNAL_GENERATED,
            payload={
                "symbol": symbol,
                "signal": signal_type.value,
                "price": str(payload.get("price", "0")),
                "strategy": self.name,
                "strength": 0.6,
            },
        ))

    def on_candle_closed(self, event: "Event") -> Signal | None:
        return None

    # ── 파라미터 갱신 ─────────────────────────────────────────────────────────

    def update_params(self, new_params: dict[str, Any]) -> None:
        super().update_params(new_params)
        self._rebuild_feature_builder()
        # 파라미터 변경 시 재학습 필요 플래그
        if any(k in new_params for k in ["short_window", "long_window", "rsi_period"]):
            self._is_trained = False
            logger.info("MLStrategy '%s': 파라미터 변경으로 재학습 필요", self.name)

    def required_candles(self) -> int:
        return int(self.params["long_window"]) + int(self.params["look_ahead"]) + 15
