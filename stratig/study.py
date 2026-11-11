"""دراسة الشموع — إجابة عن سؤال واحد: **هل في الشموع بنية قابلة للاستغلال؟**

لماذا هذه الدراسة؟
    كل قياساتنا السابقة كانت على **بيانات اصطناعية**، واكتشفنا أن مولّد
    النطاق الجانبي فيها مرتدٌّ إلى المتوسط بالبناء — أي أن نتائجها **متحيّزة**
    لصالح استراتيجيات الارتداد. لا يجوز بناء قرار مالي على ذلك.

    هذه الوحدة تُجري الدراسة على **بيانات حقيقية** (يشغّلها المستخدم على
    جهازه عبر `scripts/candle_study.py`)، وتجيب بصرامة إحصائية.

الأسئلة الثلاثة، بالترتيب:

1. **الارتباط الذاتي للعوائد** (الأهم):
       سالب ⇒ السوق يرتدّ ⇒ استراتيجيات الارتداد لها أساس نظري
       موجب ⇒ السوق يستمرّ ⇒ استراتيجيات الاتجاه لها أساس
       ≈ صفر ⇒ سير عشوائي ⇒ **لا شيء يعمل**، وأي استراتيجية تدفع عمولة بلا مقابل

2. **تشريح الشمعة**: كم يتحرّك السعر في الشمعة الواحدة؟ ما حجم الفتائل؟
   هذا يحدّد **أصغر وقف ممكن** قبل أن يبتلعه الضجيج.

3. **اختبار الأنماط** (hammer, engulfing, …) — **مع تصحيح بونفيروني**:
   اختبار 6 أنماط بمستوى 95% يعطي ≈ 26% احتمال أن يظهر أحدها «مهماً»
   بالمصادفة. بلا التصحيح تكون الدراسة مطاردة ضجيج.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .edge import EdgeStats, bonferroni_z, measure

# أنماط اتجاهية: لها جهة متوقّعة، فتُقاس بعائد موقّع
DIRECTIONAL_PATTERNS = (
    "hammer",            # مطرقة: فتيل سفلي طويل → ارتداد صاعد
    "shooting_star",     # شهاب: فتيل علوي طويل → ارتداد هابط
    "bull_engulf",       # ابتلاع شرائي
    "bear_engulf",       # ابتلاع بيعي
    "big_green",         # شمعة خضراء كبيرة → استمرار صاعد (زخم)
    "big_red",           # شمعة حمراء كبيرة → استمرار هابط (زخم)
)

PATTERN_TITLES = {
    "hammer": "مطرقة (hammer)",
    "shooting_star": "شهاب (shooting star)",
    "bull_engulf": "ابتلاع شرائي",
    "bear_engulf": "ابتلاع بيعي",
    "big_green": "شمعة خضراء كبيرة",
    "big_red": "شمعة حمراء كبيرة",
    "inside_bar": "شمعة داخلية (inside bar)",
    "outside_bar": "شمعة خارجية (outside bar)",
    "doji": "دوجي (doji)",
}

# جهة الصفقة المتوقّعة لكل نمط (+1 شراء، −1 بيع)
PATTERN_SIDE = {
    "hammer": 1, "bull_engulf": 1, "big_green": 1,
    "shooting_star": -1, "bear_engulf": -1, "big_red": -1,
}


# ═══════════════════════ 1) تشريح الشمعة ═══════════════════════
@dataclass
class Anatomy:
    """أبعاد الشمعة كنسبة من سعرها."""

    body_pct: float = 0.0        # |إغلاق − فتح| ÷ فتح
    upper_wick_pct: float = 0.0  # الفتيل العلوي ÷ فتح
    lower_wick_pct: float = 0.0  # الفتيل السفلي ÷ فتح
    range_pct: float = 0.0       # (أعلى − أدنى) ÷ فتح
    bull_ratio: float = 0.0      # نسبة الشموع الصاعدة


def candle_parts(candles, i: int) -> tuple[float, float, float, float]:
    """(الجسم، الفتيل العلوي، الفتيل السفلي، المدى) كنسب من سعر الفتح."""
    open_ = float(candles.open[i])
    close = float(candles.close[i])
    high = float(candles.high[i])
    low = float(candles.low[i])
    if open_ <= 0:
        return 0.0, 0.0, 0.0, 0.0
    top = max(open_, close)
    bottom = min(open_, close)
    body = abs(close - open_) / open_
    upper = (high - top) / open_
    lower = (bottom - low) / open_
    total = (high - low) / open_
    return body, upper, lower, total


def anatomy(candles) -> Anatomy:
    """متوسط أبعاد الشموع — يحدّد **أصغر وقف ممكن** قبل أن يبتلعه الضجيج."""
    count = len(candles)
    if count == 0:
        return Anatomy()
    bodies, uppers, lowers, ranges = [], [], [], []
    bulls = 0
    for i in range(count):
        body, upper, lower, total = candle_parts(candles, i)
        bodies.append(body)
        uppers.append(upper)
        lowers.append(lower)
        ranges.append(total)
        if float(candles.close[i]) >= float(candles.open[i]):
            bulls += 1
    return Anatomy(
        body_pct=statistics.fmean(bodies),
        upper_wick_pct=statistics.fmean(uppers),
        lower_wick_pct=statistics.fmean(lowers),
        range_pct=statistics.fmean(ranges),
        bull_ratio=100.0 * bulls / count,
    )


# ═══════════════════════ 2) الارتباط الذاتي ═══════════════════════
def returns(closes: Sequence[float]) -> list[float]:
    """العوائد النسبية بين الإغلاقات المتتالية."""
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = float(closes[i - 1])
        if prev > 0:
            out.append(float(closes[i]) / prev - 1.0)
    return out


def autocorrelation(values: Sequence[float], lag: int) -> float:
    """معامل ارتباط بيرسون بين السلسلة ونفسها بفاصل `lag`.

    موجب ⇒ الزخم (الارتفاع يتبعه ارتفاع) · سالب ⇒ الارتداد.
    """
    if lag <= 0 or len(values) <= lag + 2:
        return 0.0
    x = list(values[:-lag])
    y = list(values[lag:])
    n = min(len(x), len(y))
    if n < 3:
        return 0.0
    x, y = x[:n], y[:n]
    mx, my = statistics.fmean(x), statistics.fmean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def autocorr_profile(closes: Sequence[float],
                     lags: Iterable[int] = (1, 2, 3, 5, 10, 20)) -> dict[int, dict]:
    """الارتباط الذاتي عند عدّة فواصل — **مع دلالة إحصائية**.

    الخطأ المعياري للارتباط ≈ 1/√n، فالقيمة «مهمّة» إن تجاوزت 1.96/√n.
    """
    values = returns(closes)
    n = len(values)
    if n < 30:
        return {}
    threshold = 1.96 / math.sqrt(n)
    out: dict[int, dict] = {}
    for lag in lags:
        value = autocorrelation(values, lag)
        out[lag] = {
            "value": value,
            "threshold": threshold,
            "significant": abs(value) > threshold,
            # سالب ⇒ ارتداد · موجب ⇒ زخم
            "kind": "ارتداد" if value < 0 else "زخم",
        }
    return out


# ═══════════════════════ 3) الأنماط ═══════════════════════
def detect(candles, i: int) -> list[str]:
    """يُصنّف الشمعة رقم i — قد تحمل أكثر من نمط."""
    if i < 1 or i >= len(candles):
        return []
    body, upper, lower, total = candle_parts(candles, i)
    if total <= 0:
        return []
    open_ = float(candles.open[i])
    close = float(candles.close[i])
    prev_open = float(candles.open[i - 1])
    prev_close = float(candles.close[i - 1])
    prev_body = abs(prev_close - prev_open)

    found: list[str] = []
    bullish = close >= open_
    small_body = body <= 0.35 * total

    # أنماط الفتائل
    if small_body and lower >= 0.5 * total and upper <= 0.15 * total:
        found.append("hammer")
    if small_body and upper >= 0.5 * total and lower <= 0.15 * total:
        found.append("shooting_star")
    if body <= 0.1 * total:
        found.append("doji")

    # الابتلاع
    if prev_body > 0:
        if (bullish and prev_close < prev_open
                and close >= prev_open and open_ <= prev_close):
            found.append("bull_engulf")
        if (not bullish and prev_close > prev_open
                and close <= prev_open and open_ >= prev_close):
            found.append("bear_engulf")

    # الشموع الكبيرة (مقارنة بمتوسط آخر 20 شمعة)
    start = max(0, i - 20)
    window = [candle_parts(candles, j)[3] for j in range(start, i)]
    if window:
        mean_range = statistics.fmean(window)
        if mean_range > 0 and total >= 1.8 * mean_range:
            found.append("big_green" if bullish else "big_red")

    # التقلّب
    high = float(candles.high[i])
    low = float(candles.low[i])
    prev_high = float(candles.high[i - 1])
    prev_low = float(candles.low[i - 1])
    if high <= prev_high and low >= prev_low:
        found.append("inside_bar")
    if high > prev_high and low < prev_low:
        found.append("outside_bar")
    return found


def forward_return(candles, i: int, horizon: int, side: int = 1) -> float | None:
    """العائد بعد `horizon` شموع من إغلاق الشمعة i، موقّعاً بجهة الصفقة."""
    j = i + horizon
    if j >= len(candles):
        return None
    entry = float(candles.close[i])
    if entry <= 0:
        return None
    return (float(candles.close[j]) / entry - 1.0) * side


def pattern_samples(candles, horizon: int = 3) -> dict[str, list[float]]:
    """العوائد الموقّعة لكل نمط — العيّنة الخام قبل أي قياس."""
    samples: dict[str, list[float]] = {name: [] for name in DIRECTIONAL_PATTERNS}
    last = len(candles) - horizon - 1
    for i in range(1, max(1, last)):
        for name in detect(candles, i):
            if name not in PATTERN_SIDE:
                continue
            value = forward_return(candles, i, horizon, PATTERN_SIDE[name])
            if value is not None:
                samples[name].append(value)
    return samples


def pattern_study(candles, horizon: int = 3, min_trades: int = 30) -> dict[str, EdgeStats]:
    """يقيس كل نمط اتجاهي: العائد الموقّع بعده + فترة ثقة **مصحّحة**.

    تصحيح بونفيروني لأننا نختبر 6 أنماط دفعة واحدة: بلا تصحيح، احتمال
    أن يظهر أحدها «مهماً» بالمصادفة ≈ 26%.
    """
    z = bonferroni_z(len(DIRECTIONAL_PATTERNS))
    samples = pattern_samples(candles, horizon)
    return {name: measure(values, min_trades=min_trades, z=z)
            for name, values in samples.items()}


def volatility_after(candles, horizon: int = 3) -> dict[str, dict]:
    """هل يتبع النمط تقلّب أكبر؟ (للأنماط بلا جهة: inside/outside/doji)."""
    ranges = [candle_parts(candles, i)[3] for i in range(len(candles))]
    baseline = statistics.median(ranges) if ranges else 0.0
    out: dict[str, dict] = {}
    for name in ("inside_bar", "outside_bar", "doji"):
        nxt: list[float] = []
        last = len(candles) - horizon - 1
        for i in range(1, max(1, last)):
            if name in detect(candles, i):
                nxt.append(statistics.fmean(
                    candle_parts(candles, j)[3] for j in range(i + 1, i + 1 + horizon)))
        if not nxt or baseline <= 0:
            continue
        out[name] = {
            "count": len(nxt),
            "ratio": statistics.fmean(nxt) / baseline,
            "baseline_pct": baseline,
        }
    return out


# ═══════════════════════ 4) التقرير ═══════════════════════
@dataclass
class StudyResult:
    symbol: str = ""
    timeframe: str = ""
    bars: int = 0
    anatomy: Anatomy = field(default_factory=Anatomy)
    autocorr: dict[int, dict] = field(default_factory=dict)
    patterns: dict[str, EdgeStats] = field(default_factory=dict)
    volatility: dict[str, dict] = field(default_factory=dict)
    # العيّنات الخام: ضرورية لدمج الرموز. إعادة بنائها من المتوسط تُصفّر
    # التشتّت فيبدو كل شيء «مهماً» زوراً.
    pattern_samples: dict[str, list[float]] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        """الخلاصة: هل في هذه الشموع بنية قابلة للاستغلال؟"""
        significant = [(lag, info) for lag, info in self.autocorr.items()
                       if info.get("significant")]
        if not significant:
            return "سير عشوائي: لا ارتباط ذاتي مهم ⇒ لا ارتداد ولا زخم"
        first = self.autocorr.get(1, {})
        value = first.get("value", 0.0)
        if first.get("significant") and value < 0:
            return ("ارتباط ذاتي **سالب** عند lag 1 ⇒ السوق يرتدّ ⇒ "
                    "استراتيجيات الارتداد لها أساس (rsi_williams في النطاق الجانبي)")
        if first.get("significant") and value > 0:
            return ("ارتباط ذاتي **موجب** عند lag 1 ⇒ السوق يستمرّ ⇒ "
                    "استراتيجيات الاتجاه لها أساس (مع مخارج تتبّع الاتجاه)")
        strongest = min(significant, key=lambda kv: kv[1]["value"])
        return (f"أقوى أثر عند lag {strongest[0]}: "
                f"{strongest[1]['kind']} ({strongest[1]['value']:+.4f})")

    @property
    def best_pattern(self) -> tuple[str, EdgeStats] | None:
        winners = [(n, s) for n, s in self.patterns.items() if s.is_winning]
        if not winners:
            return None
        return max(winners, key=lambda kv: kv[1].expectancy_r)

    @property
    def min_stop_pct(self) -> float:
        """أصغر وقف قبل أن يبتلعه ضجيج الشمعة الواحدة."""
        return self.anatomy.range_pct


def study(candles, symbol: str = "", timeframe: str = "",
          horizon: int = 3, min_trades: int = 30) -> StudyResult:
    """يجري الدراسة كاملة على سلسلة واحدة."""
    closes = list(candles.close)
    raw = pattern_samples(candles, horizon)
    return StudyResult(
        symbol=symbol,
        timeframe=timeframe,
        bars=len(candles),
        anatomy=anatomy(candles),
        autocorr=autocorr_profile(closes),
        patterns=pattern_study(candles, horizon, min_trades),
        volatility=volatility_after(candles, horizon),
        pattern_samples=raw,
    )


def merge(results: Iterable[StudyResult], min_trades: int = 30) -> StudyResult:
    """يدمج عدّة رموز في دراسة واحدة — العيّنة الأكبر تعطي حكماً أصدق."""
    items = list(results)
    if not items:
        return StudyResult()
    if len(items) == 1:
        return items[0]

    out = StudyResult(
        symbol="+".join(r.symbol for r in items if r.symbol),
        timeframe=items[0].timeframe,
        bars=sum(r.bars for r in items),
    )
    # التشريح: متوسط مرجّح بعدد الشموع
    total = max(1, out.bars)
    out.anatomy = Anatomy(
        body_pct=sum(r.anatomy.body_pct * r.bars for r in items) / total,
        upper_wick_pct=sum(r.anatomy.upper_wick_pct * r.bars for r in items) / total,
        lower_wick_pct=sum(r.anatomy.lower_wick_pct * r.bars for r in items) / total,
        range_pct=sum(r.anatomy.range_pct * r.bars for r in items) / total,
        bull_ratio=sum(r.anatomy.bull_ratio * r.bars for r in items) / total,
    )
    # الارتباط الذاتي: متوسط مرجّح بعدد العوائد
    for lag in items[0].autocorr:
        weight = sum(max(0, r.bars - lag) for r in items if lag in r.autocorr)
        if not weight:
            continue
        value = sum(r.autocorr[lag]["value"] * max(0, r.bars - lag)
                    for r in items if lag in r.autocorr) / weight
        n = max(1, out.bars)
        threshold = 1.96 / math.sqrt(n)
        out.autocorr[lag] = {
            "value": value,
            "threshold": threshold,
            "significant": abs(value) > threshold,
            "kind": "ارتداد" if value < 0 else "زخم",
        }

    # الأنماط: ندمج **العيّنات الخام** من كل الرموز ثم نقيس مرة واحدة.
    # (دمج المتوسطات وحدها يُصفّر التشتّت ويُنتج دلالة زائفة.)
    samples: dict[str, list[float]] = {}
    for result in items:
        for name, values in result.pattern_samples.items():
            samples.setdefault(name, []).extend(values)
    z = bonferroni_z(len(DIRECTIONAL_PATTERNS))
    out.patterns = {name: measure(values, min_trades=min_trades, z=z)
                    for name, values in samples.items()}
    out.pattern_samples = samples
    return out
