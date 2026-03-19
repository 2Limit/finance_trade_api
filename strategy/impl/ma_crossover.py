"""
MACrossoverStrategy: 이동평균 크로스오버 전략 구현체

파라미터:
    short_window (int): 단기 MA 기간 (e.g. 5)
    long_window  (int): 장기 MA 기간 (e.g. 20)

시그널:
    단기 MA > 장기 MA → BUY
    단기 MA < 장기 MA → SELL
"""
from __future__ import annotations

from strategy.base import AbstractStrategy, Signal

# MACrossoverStrategy 구현체
