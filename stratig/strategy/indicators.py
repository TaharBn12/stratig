"""المؤشرات الفنية — محسوبة داخلياً بـ pandas (بدون مكتبة ta).

النتائج مطابقة تماماً لمكتبة `ta` التي كان يستخدمها الكود الأصلي
(نفس طريقة التمهيد: Wilder / EMA و rolling بنفس min_periods)،
وهناك اختبار يقارنها بـ ta عند توفّرها: tests/test_strategy.py
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

BUY = "buy"
SELL = "sell"


@dataclass
class IndicatorResult:
    name: str
    side: Optional[str]      # buy | sell | None
    value: float
    reason: str

    @property
    def has_signal(self) -> bool:
        return self.side in (BUY, SELL)


# ═════════════════════════ اللبنات الأساسية ═════════════════════════
def ema(series: pd.Series, window: int) -> pd.Series:
    """المتوسط المتحرك الأُسّي (نفس سلوك ta.trend.ema_indicator)."""
    window = max(1, int(window))
    return series.ewm(span=window, min_periods=window, adjust=False).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """مؤشر القوة النسبية بتمهيد Wilder (نفس ta.momentum.RSIIndicator)."""
    window = max(1, int(window))
    diff = close.diff(1)
    up = diff.where(diff > 0, 0.0)
    down = -diff.where(diff < 0, 0.0)
    ema_up = up.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    ema_down = down.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        # القسمة على صفر تعطي inf → RSI = 100 (نفس سلوك مكتبة ta)
        return 100 - (100 / (1 + ema_up / ema_down))


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, lbp: int = 14) -> pd.Series:
    """Williams %R (نفس ta.momentum.WilliamsRIndicator)."""
    lbp = max(1, int(lbp))
    highest_high = high.rolling(lbp, min_periods=lbp).max()
    lowest_low = low.rolling(lbp, min_periods=lbp).min()
    span = (highest_high - lowest_low).replace(0, float("nan"))
    return -100 * (highest_high - close) / span


# ═════════════════════════ الإشارات ═════════════════════════
def rsi_signal(
    close: pd.Series,
    period: int = 14,
    oversold: float = 30,
    overbought: float = 70,
    lookback: int = 3,
) -> IndicatorResult:
    """نمط الاختراق: شموع تحت خط التشبّع البيعي ثم اختراق للأعلى = شراء.

    مطابق لمنطق Derivatives.py:
        rsi[-3] < 30 and rsi[-2] < 30 and rsi[-1] > 30  →  شراء
    """
    values = rsi(close, period).dropna()
    lookback = max(2, int(lookback))
    if len(values) < lookback:
        return IndicatorResult("RSI", None, float("nan"), "بيانات غير كافية")

    window = values.iloc[-lookback:-1]
    current = float(values.iloc[-1])

    if (window < oversold).all() and current > oversold:
        return IndicatorResult("RSI", BUY, current, f"اختراق صاعد من تشبّع بيعي ({current:.1f} > {oversold})")
    if (window > overbought).all() and current < overbought:
        return IndicatorResult("RSI", SELL, current, f"كسر هابط من تشبّع شرائي ({current:.1f} < {overbought})")
    return IndicatorResult("RSI", None, current, f"محايد ({current:.1f})")


def williams_r_signal(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lbp: int = 24,
    ema_window: int = 24,
    extreme_oversold: float = -99.5,
    extreme_overbought: float = -0.5,
    oversold: float = -75,
    overbought: float = -25,
) -> IndicatorResult:
    """Williams %R مع EMA: إشارة من التشبّع الشديد أو من تقاطع EMA."""
    values = williams_r(high, low, close, lbp).dropna()
    if len(values) < max(ema_window, lbp) + 2:
        return IndicatorResult("W%R", None, float("nan"), "بيانات غير كافية")
    ema_values = ema(values, ema_window).dropna()

    cur, prev = float(values.iloc[-1]), float(values.iloc[-2])
    cur_e, prev_e = float(ema_values.iloc[-1]), float(ema_values.iloc[-2])

    if cur < extreme_oversold:
        return IndicatorResult("W%R", BUY, cur, f"تشبّع بيعي شديد ({cur:.1f})")
    if cur > extreme_overbought:
        return IndicatorResult("W%R", SELL, cur, f"تشبّع شرائي شديد ({cur:.1f})")
    if cur < oversold and prev < oversold and prev < prev_e and cur > cur_e:
        return IndicatorResult("W%R", BUY, cur, f"تقاطع صاعد فوق EMA ({cur:.1f})")
    if cur > overbought and prev > overbought and prev > prev_e and cur < cur_e:
        return IndicatorResult("W%R", SELL, cur, f"تقاطع هابط تحت EMA ({cur:.1f})")
    return IndicatorResult("W%R", None, cur, f"محايد ({cur:.1f})")
