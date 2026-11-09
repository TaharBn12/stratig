"""المؤشرات الفنية — نفس منطق الكود الأصلي (Derivatives.py) مع إمكانية الضبط.

كل مؤشر يُرجع IndicatorResult أو None عندما لا توجد إشارة.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import ta

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


def _last(series: pd.Series, offset: int) -> float:
    """آخر قيمة صالحة (يتجاهل NaN)."""
    try:
        return float(series.iloc[offset])
    except (IndexError, ValueError):
        return float("nan")


# ───────────────────────── RSI ─────────────────────────
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
    rsi = ta.momentum.RSIIndicator(close, window=int(period)).rsi()
    lookback = max(2, int(lookback))
    need = lookback  # نحتاج آخر `lookback` قيم
    if len(rsi) < need or not rsi.notna().all():
        rsi = rsi.dropna()
    if len(rsi) < need:
        return IndicatorResult("RSI", None, float("nan"), "بيانات غير كافية")

    window = rsi.iloc[-lookback:-1]
    current = float(rsi.iloc[-1])

    if (window < oversold).all() and current > oversold:
        return IndicatorResult("RSI", BUY, current, f"اختراق صاعد من تشبّع بيعي ({current:.1f} > {oversold})")
    if (window > overbought).all() and current < overbought:
        return IndicatorResult("RSI", SELL, current, f"كسر هابط من تشبّع شرائي ({current:.1f} < {overbought})")
    return IndicatorResult("RSI", None, current, f"محايد ({current:.1f})")


# ───────────────────── Williams %R ─────────────────────
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
    w = ta.momentum.WilliamsRIndicator(high, low, close, lbp=int(lbp)).williams_r()
    w = w.dropna()
    if len(w) < ema_window + 2:
        return IndicatorResult("W%R", None, float("nan"), "بيانات غير كافية")
    ema_w = ta.trend.ema_indicator(w, window=int(ema_window))
    ema_w = ema_w.dropna()

    cur, prev = float(w.iloc[-1]), float(w.iloc[-2])
    cur_e, prev_e = float(ema_w.iloc[-1]), float(ema_w.iloc[-2])

    if cur < extreme_oversold:
        return IndicatorResult("W%R", BUY, cur, f"تشبّع بيعي شديد ({cur:.1f})")
    if cur > extreme_overbought:
        return IndicatorResult("W%R", SELL, cur, f"تشبّع شرائي شديد ({cur:.1f})")
    if cur < oversold and prev < oversold and prev < prev_e and cur > cur_e:
        return IndicatorResult("W%R", BUY, cur, f"تقاطع صاعد فوق EMA ({cur:.1f})")
    if cur > overbought and prev > overbought and prev > prev_e and cur < cur_e:
        return IndicatorResult("W%R", SELL, cur, f"تقاطع هابط تحت EMA ({cur:.1f})")
    return IndicatorResult("W%R", None, cur, f"محايد ({cur:.1f})")
