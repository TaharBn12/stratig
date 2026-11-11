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


# ═════════════════════════ بولينجر و ATR ═════════════════════════
def sma(values: Sequence[float], window: int) -> list[float]:
    """متوسط بسيط متحرك — أول window-1 قيمة NaN مثل pandas rolling().mean()."""
    window = max(1, int(window))
    out: list[float] = []
    total = 0.0
    for index, value in enumerate(values):
        total += float(value)
        if index >= window:
            total -= float(values[index - window])
        out.append(total / window if index >= window - 1 else NAN)
    return out


def rolling_std(values: Sequence[float], window: int, ddof: int = 1) -> list[float]:
    """انحراف معياري متحرك — ddof=1 هو سلوك pandas التلقائي (وما تستخدمه pandas_ta)."""
    window = max(1, int(window))
    divisor = window - int(ddof)
    if divisor <= 0:
        divisor = window
    out: list[float] = []
    for index in range(len(values)):
        if index < window - 1:
            out.append(NAN)
            continue
        chunk = [float(v) for v in values[index - window + 1 : index + 1]]
        mean = sum(chunk) / window
        variance = sum((x - mean) ** 2 for x in chunk) / divisor
        out.append(math.sqrt(variance) if variance > 0 else 0.0)
    return out


def bbands(
    close: Sequence[float],
    length: int = 15,
    std: float = 1.5,
    ddof: int = 1,
) -> tuple[list[float], list[float], list[float]]:
    """بولينجر باندز: (سفلي، أوسط، علوي) — مثل ta.bbands(close, length, std)."""
    middle = sma(close, length)
    deviation = rolling_std(close, length, ddof=ddof)
    lower = [
        m - std * d if not (math.isnan(m) or math.isnan(d)) else NAN
        for m, d in zip(middle, deviation)
    ]
    upper = [
        m + std * d if not (math.isnan(m) or math.isnan(d)) else NAN
        for m, d in zip(middle, deviation)
    ]
    return lower, middle, upper


def true_range(
    high: Sequence[float], low: Sequence[float], close: Sequence[float], drift: int = 1
) -> list[float]:
    """المدى الحقيقي TR = max(H-L, |H - إغلاق سابق|, |إغلاق سابق - L|)."""
    out: list[float] = []
    for index in range(len(close)):
        if index < drift:
            out.append(NAN)
            continue
        previous = float(close[index - drift])
        out.append(
            max(
                float(high[index]) - float(low[index]),
                abs(float(high[index]) - previous),
                abs(previous - float(low[index])),
            )
        )
    return out


def rma(values: Sequence[float], length: int) -> list[float]:
    """Wilder's RMA كما يعرّفه pandas_ta: ewm(alpha=1/length, min_periods=length).

    ملاحظة: pandas_ta يستخدم الصيغة المُعدَّلة (adjust=True) لا صيغة ويلدر
    التكرارية — والفرق بينهما يتلاشى بعد بضع عشرات من الشموع.
    """
    length = max(1, int(length))
    alpha = 1.0 / length
    out: list[float] = [NAN] * len(values)
    numerator = denominator = 0.0
    seen = 0
    started = False
    for index, raw in enumerate(values):
        value = float(raw)
        if math.isnan(value):
            continue
        seen += 1
        if not started:
            numerator, denominator, started = value, 1.0, True
        else:
            numerator = (1 - alpha) * numerator + value
            denominator = (1 - alpha) * denominator + 1
        if seen >= length:
            out[index] = numerator / denominator
    return out


def wilder_ma(values: Sequence[float], length: int) -> list[float]:
    """تنعيم ويلدر الكلاسيكي (بذرة SMA ثم المتوسط المتحرك بويلدر)."""
    length = max(1, int(length))
    out: list[float] = [NAN] * len(values)
    seed: list[float] = []
    previous: float | None = None
    for index, raw in enumerate(values):
        value = float(raw)
        if math.isnan(value):
            continue
        if previous is None:
            seed.append(value)
            if len(seed) == length:
                previous = sum(seed) / length
                out[index] = previous
        else:
            previous = (previous * (length - 1) + value) / length
            out[index] = previous
    return out


def atr(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    length: int = 7,
    mode: str = "rma",
) -> list[float]:
    """متوسط المدى الحقيقي — مثل ta.atr(high, low, close, length)."""
    moving = wilder_ma if str(mode).lower().startswith("w") else rma
    return moving(true_range(high, low, close), length)


def adx(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    length: int = 14,
) -> tuple[list[float], list[float], list[float]]:
    """مؤشر الاتجاه ADX مع ‎+DI‎ و‎−DI‎ — مثل ta.trend.ADXIndicator.

    ADX يقيس **قوة** الاتجاه بلا جهة:
        ADX > 25  → سوق متّجه (استراتيجيات الاختراق تعمل)
        ADX < 20  → سوق جانبي (استراتيجيات الارتداد تعمل)

    هذا هو المعيار الذي نستخدمه لاختيار النظام المناسب للاستراتيجية،
    لأن قياسنا أثبت أن `rsi_williams` تكسب في الجانبي وتخسر في المتّجه.
    """
    length = max(1, int(length))
    size = len(close)
    tr = true_range(high, low, close)
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for i in range(size):
        if i == 0:
            plus_dm.append(0.0)
            minus_dm.append(0.0)
            continue
        up = float(high[i]) - float(high[i - 1])
        down = float(low[i - 1]) - float(low[i])
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    atr_values = wilder_ma(tr, length)
    plus_smooth = wilder_ma(plus_dm, length)
    minus_smooth = wilder_ma(minus_dm, length)

    plus_di = [NAN] * size
    minus_di = [NAN] * size
    dx_values: list[float] = []
    for i in range(size):
        a = atr_values[i]
        p = plus_smooth[i]
        m = minus_smooth[i]
        if math.isnan(a) or math.isnan(p) or math.isnan(m) or a == 0:
            dx_values.append(NAN)
            continue
        plus_di[i] = 100.0 * p / a
        minus_di[i] = 100.0 * m / a
        total = plus_di[i] + minus_di[i]
        dx_values.append(NAN if total == 0 else 100.0 * abs(plus_di[i] - minus_di[i]) / total)

    adx_values = wilder_ma(dx_values, length)
    return adx_values, plus_di, minus_di


def atr_pct(high, low, close, length: int = 14, price: float | None = None) -> float:
    """التقلّب كنسبة من السعر (ATR ÷ السعر) — لفلتر التقلّب."""
    values = atr(high, low, close, length, mode="wilder")
    if not values:
        return NAN
    last = values[-1]
    if math.isnan(last):
        return NAN
    reference = float(price) if price else float(close[-1])
    return last / reference if reference else NAN


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
