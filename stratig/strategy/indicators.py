"""المؤشرات الفنية — حساب خالص بلغة بايثون (بدون pandas/numpy/ta).

النتائج مطابقة تماماً لمكتبة `ta` (نفس منطق التمهيد)، وهناك اختبار
يقارنها بـ ta عند توفّرها: tests/test_strategy.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from ..data import NAN

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
def _ewm(values: Sequence[float], alpha: float, min_periods: int) -> list[float]:
    """متوسط أُسّي متحرك بصيغة adjust=False (مثل pandas ewm).

    أول min_periods-1 قيمة تكون NaN مثل سلوك pandas مع min_periods.
    """
    if not values:
        return []
    out = [float(values[0])]
    for value in values[1:]:
        out.append((1 - alpha) * out[-1] + alpha * float(value))
    for i in range(min(len(out), max(0, min_periods - 1))):
        out[i] = NAN
    return out


def ema(values: Sequence[float], window: int) -> list[float]:
    """EMA بنفس سلوك ta.trend.ema_indicator / pandas ewm(span=window)."""
    window = max(1, int(window))
    return _ewm(values, 2 / (window + 1), min_periods=window)


def rsi(closes: Sequence[float], window: int = 14) -> list[float]:
    """مؤشر القوة النسبية بتمهيد Wilder (مثل ta.momentum.RSIIndicator)."""
    window = max(1, int(window))
    size = len(closes)
    if size < 2:
        return [NAN] * size

    ups = [0.0]
    downs = [0.0]
    for i in range(1, size):
        diff = float(closes[i]) - float(closes[i - 1])
        ups.append(diff if diff > 0 else 0.0)
        downs.append(-diff if diff < 0 else 0.0)

    ema_up = _ewm(ups, 1 / window, min_periods=window)
    ema_down = _ewm(downs, 1 / window, min_periods=window)

    out = [NAN] * size
    for i in range(size):
        up_value, down_value = ema_up[i], ema_down[i]
        if math.isnan(up_value) or math.isnan(down_value):
            continue
        out[i] = 100.0 if down_value == 0 else 100 - (100 / (1 + up_value / down_value))
    return out


def williams_r(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], lbp: int = 14
) -> list[float]:
    """Williams %R (مثل ta.momentum.WilliamsRIndicator)."""
    lbp = max(1, int(lbp))
    size = len(closes)
    out = [NAN] * size
    for i in range(lbp - 1, size):
        window_high = max(float(h) for h in highs[i - lbp + 1 : i + 1])
        window_low = min(float(l) for l in lows[i - lbp + 1 : i + 1])
        span = window_high - window_low
        out[i] = NAN if span == 0 else -100 * (window_high - float(closes[i])) / span
    return out


def _valid(values: Sequence[float]) -> list[float]:
    """يزيل قيم النقص (مثل dropna)."""
    return [v for v in values if not math.isnan(v)]


# ═════════════════════════ الإشارات ═════════════════════════
def rsi_signal(
    close: Sequence[float],
    period: int = 14,
    oversold: float = 30,
    overbought: float = 70,
    lookback: int = 3,
) -> IndicatorResult:
    """نمط الاختراق: شموع تحت التشبّع البيعي ثم اختراق للأعلى = شراء.

    مطابق لمنطق Derivatives.py:
        rsi[-3] < 30 and rsi[-2] < 30 and rsi[-1] > 30  →  شراء
    """
    values = _valid(rsi(close, period))
    lookback = max(2, int(lookback))
    if len(values) < lookback:
        return IndicatorResult("RSI", None, NAN, "بيانات غير كافية")

    window = values[-lookback:-1]
    current = values[-1]

    if all(v < oversold for v in window) and current > oversold:
        return IndicatorResult("RSI", BUY, current, f"اختراق صاعد من تشبّع بيعي ({current:.1f} > {oversold})")
    if all(v > overbought for v in window) and current < overbought:
        return IndicatorResult("RSI", SELL, current, f"كسر هابط من تشبّع شرائي ({current:.1f} < {overbought})")
    return IndicatorResult("RSI", None, current, f"محايد ({current:.1f})")


def williams_r_signal(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    lbp: int = 24,
    ema_window: int = 24,
    extreme_oversold: float = -99.5,
    extreme_overbought: float = -0.5,
    oversold: float = -75,
    overbought: float = -25,
) -> IndicatorResult:
    """Williams %R مع EMA: إشارة من التشبّع الشديد أو من تقاطع EMA."""
    raw = williams_r(high, low, close, lbp)
    values = _valid(raw)
    if len(values) < max(ema_window, lbp) + 2:
        return IndicatorResult("W%R", None, NAN, "بيانات غير كافية")
    ema_values = _valid(ema(values, ema_window))

    cur, prev = values[-1], values[-2]
    cur_e, prev_e = ema_values[-1], ema_values[-2]

    if cur < extreme_oversold:
        return IndicatorResult("W%R", BUY, cur, f"تشبّع بيعي شديد ({cur:.1f})")
    if cur > extreme_overbought:
        return IndicatorResult("W%R", SELL, cur, f"تشبّع شرائي شديد ({cur:.1f})")
    if cur < oversold and prev < oversold and prev < prev_e and cur > cur_e:
        return IndicatorResult("W%R", BUY, cur, f"تقاطع صاعد فوق EMA ({cur:.1f})")
    if cur > overbought and prev > overbought and prev > prev_e and cur < cur_e:
        return IndicatorResult("W%R", SELL, cur, f"تقاطع هابط تحت EMA ({cur:.1f})")
    return IndicatorResult("W%R", None, cur, f"محايد ({cur:.1f})")
