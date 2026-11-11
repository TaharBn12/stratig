"""مقياس الميزة — هل استراتيجيتك رابحة فعلاً، أم أنك تتداول ضجيجاً؟

لماذا هذه الوحدة؟ لأن كل قياساتنا انتهت إلى نفس الحقيقة:

    «لا توجد معاملات تنقذ إشارة ميزتها صفر.»

قِسنا `scalping_i` على 2065 صفقة: الاتجاه الصرف (بلا وقف ولا هدف)
**−0.0010%** = صفر مطلق. ومسح نسب الهدف من 1:1 إلى 5:1 أعطى **كل نسبه
خاسرة** — لأن نسبة الهدف تُضخّم الميزة الموجودة، ولا تصنع ميزة من عدم.

إذن السؤال ليس «ما أفضل المعاملات؟» بل: **«هل هناك ميزة أصلاً؟»**

وهذا سؤال **إحصائي** لا يُجاب بالحدس:
  • 12 صفقة رابحة قد تكون حظاً (تقلّب R أكبر من متوسطه)
  • نحتاج فترة ثقة: هل تتجاوز الصفر أم تحتويه؟

`measure()` تحسب متوسط R وخطأه المعياري وفترة ثقة 95%، ثم تصدر حكماً:

    رابحة   ← الحد الأدنى للفترة > 0        ✅ تابع
    خاسرة   ← الحد الأعلى للفترة < 0        ⛔ توقف
    غير حاسمة ← الفترة تحتوي الصفر          ≈ تحتاج صفقات أكثر
    غير كافية ← أقل من الحد الأدنى للعيّنة  … لا حكم بعد

ملاحظة: نستخدم 1.96 (فترة ثقة 95% التقريبية) عمداً بدل توزيع t — لأن
الفرق ضئيل عند العيّنات التي تهمّنا (30+)، والبساطة تخدم الوضوح.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable

# ثابت فترة الثقة 95% (تقريبي)
Z95 = 1.96

# ── التسميات (بالعربية لأنها تظهر للمستخدم) ──
VERDICT_WIN = "رابحة"
VERDICT_LOSS = "خاسرة"
VERDICT_FLAT = "غير حاسمة"
VERDICT_UNKNOWN = "لا بيانات كافية"


@dataclass
class EdgeStats:
    """قياس الميزة لعيّنة صفقات."""

    trades: int = 0
    expectancy_r: float = 0.0      # متوسط R لكل صفقة
    stdev_r: float = 0.0
    stderr_r: float = 0.0          # الخطأ المعياري للمتوسط
    lower_r: float = 0.0           # الحد الأدنى لفترة ثقة 95%
    upper_r: float = 0.0           # الحد الأعلى
    win_rate: float = 0.0
    total_r: float = 0.0
    verdict: str = VERDICT_UNKNOWN

    @property
    def enough_data(self) -> bool:
        return self.trades > 0

    @property
    def is_winning(self) -> bool:
        return self.verdict == VERDICT_WIN

    @property
    def is_losing(self) -> bool:
        """خاسرة **إحصائياً** — أي أن فترة الثقة كلها تحت الصفر."""
        return self.verdict == VERDICT_LOSS

    @property
    def should_block(self) -> bool:
        """هل نمنع التداول؟ نعم فقط إن ثبتت الخسارة إحصائياً."""
        return self.is_losing

    def explain(self) -> str:
        """سبب الحكم — يظهر للمستخدم في /edge."""
        if self.trades == 0:
            return "لا توجد صفقات مسجّلة بعد"
        if self.verdict == VERDICT_UNKNOWN:
            return "العيّنة أصغر من الحد الأدنى للحكم"
        if self.verdict == VERDICT_LOSS:
            return ("فترة الثقة 95% كلها تحت الصفر: "
                    f"{self.upper_r:+.3f}R ≥ الصفر مستحيل")
        if self.verdict == VERDICT_WIN:
            return ("فترة الثقة 95% كلها فوق الصفر: "
                    f"{self.lower_r:+.3f}R ≤ الصفر مستحيل")
        return ("فترة الثقة تحتوي الصفر — النتيجة لا تفرّق عن الصفر إحصائياً: "
                f"بين {self.lower_r:+.3f}R و {self.upper_r:+.3f}R")


def bonferroni_z(tests: int, conf: float = 0.95) -> float:
    """قيمة z بعد تصحيح بونفيروني — **ضروري** عند اختبار أنماط متعدّدة.

    اختبار 8 أنماط شموع بمستوى 95% يعطي احتمالاً ≈ 34% أن يظهر أحدها
    «مهماً» بالمصادفة البحتة (1 − 0.95⁸). التصحيح يقسّم الخطأ على عدد
    الاختبارات فيرفع العتبة: 8 اختبارات ⇒ z يتحوّل من 1.96 إلى ≈ 2.73.

    بلا هذا التصحيح، كل «دراسة أنماط» هي مطاردة ضجيج.
    """
    from statistics import NormalDist

    tests = max(1, int(tests))
    alpha = (1.0 - conf) / tests
    return NormalDist().inv_cdf(1.0 - alpha / 2.0)


def measure(values: Iterable[float], min_trades: int = 30,
            z: float = Z95) -> EdgeStats:
    """يقيس ميزة عيّنة من العوائد بوحدة R.

    `z` يسمح برفع العتبة عند تعدّد الاختبارات (راجع `bonferroni_z`).
    """
    samples = [float(v) for v in values if v == v]      # استبعاد NaN
    count = len(samples)
    if not count:
        return EdgeStats(verdict=VERDICT_UNKNOWN)

    mean = statistics.fmean(samples)
    stdev = statistics.stdev(samples) if count > 1 else 0.0
    stderr = stdev / math.sqrt(count) if count else 0.0
    lower = mean - z * stderr
    upper = mean + z * stderr

    if count < min_trades:
        verdict = VERDICT_UNKNOWN
    elif lower > 0:
        verdict = VERDICT_WIN
    elif upper < 0:
        verdict = VERDICT_LOSS
    else:
        verdict = VERDICT_FLAT

    wins = [v for v in samples if v > 0]
    return EdgeStats(
        trades=count,
        expectancy_r=mean,
        stdev_r=stdev,
        stderr_r=stderr,
        lower_r=lower,
        upper_r=upper,
        win_rate=100.0 * len(wins) / count,
        total_r=sum(samples),
        verdict=verdict,
    )


def measure_trades(trades: Iterable, min_trades: int = 30,
                   z: float = Z95) -> EdgeStats:
    """يقيس ميزة كائنات Trade (تُقرأ منها r_multiple)."""
    return measure([float(getattr(t, "r_multiple", 0.0) or 0.0) for t in trades],
                   min_trades=min_trades, z=z)


def by_strategy(trades: Iterable, min_trades: int = 30,
                z: float = Z95) -> dict[str, EdgeStats]:
    """يقيس الميزة لكل استراتيجية على حدة — قد تكون إحداهما رابحة والأخرى لا."""
    groups: dict[str, list[float]] = {}
    for trade in trades:
        key = str(getattr(trade, "strategy", "") or "غير محدّد")
        groups.setdefault(key, []).append(float(getattr(trade, "r_multiple", 0.0) or 0.0))
    return {key: measure(values, min_trades, z) for key, values in groups.items()}
