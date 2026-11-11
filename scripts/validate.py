"""🧑‍⚖️ مُحكِّم الخبير — بطارية اختبارات صارمة قبل أن تتداول باستراتيجية.

لماذا هذا الملف؟
    «اريد اختبارات على استراتجيات صارمة كانك خبير تداول واختبرها»

    المختبر (`lab.py`) يسأل: هل هذه الاستراتيجية **ثابتة**؟
    المُحكِّم يسأل سؤالاً أسبق: **هل هي ميزة أصلاً، أم حظ مقنّع؟**

    الفرق الجوهري: استراتيجية قد تكون «ثابتة» و«رابحة» و**مع ذلك بلا قيمة**
    — لأن دخولها العشوائي يعطي نفس النتيجة. لذلك البوابة الرابعة هنا
    (الدخول العشوائي) هي أهم بوابة، وهي الغائب الأكبر في أغلب الباك-تستات.

البوابات الثماني (كلها إلزامية، وترتيبها من الأرخص للأغلى):
    1. العيّنة       ≥ 100 صفقة — دونها كل شيء حظ
    2. بلا تلاعب     الإشارة عند الشمعة i لا تتغيّر إن حذفنا المستقبل
    3. خارج العينة   التوقع > صفر على آخر 30% من كل سلسلة
    4. الثبات        ≥ 60% من نوافذ المشي للأمام رابحة (على كل الأسواق)
    5. تعدّد الأسواق رابحة على ≥ 60% من العملات — لا تحملها عملة واحدة
    6. **ليس حظاً**   أفضل من **دخول عشوائي** بنفس عدد الصفقات ونفس
                     الوقف/الهدف (مونتي كارلو) — أصعب بوابة وأهمها
    7. فترة ثقة      95% (مصحّحة بعدد المرشّحين) لا تتضمن الصفر
    8. المخاطرة      أقصى سحب ≤ 25R · عامل ربح > 1.1

    python scripts/validate.py --csv data/*.csv
    python scripts/validate.py --csv data/BTCUSDT-15m-60d.csv --only scalping_i

⚠️ تنبيهات:
    • العوائد **صافية** من العمولة (`FEE_PCT` في `scripts/backtest.py`)
      و**من الانزلاق** إن أعطيت `--slippage`. لا تُخصم مرتين.
    • فلتر الإطار الأعلى (MTF) **غير مطبَّق** هنا: يحتاج اتصالاً بالمنصّة،
      والمُحكِّم يعمل على ملفات CSV بلا إنترنت.
"""
from __future__ import annotations

import argparse
import glob
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import DEFAULT_CONFIG                  # noqa: E402
from stratig.data import Candles                           # noqa: E402
from stratig.edge import bonferroni_z                      # noqa: E402
from stratig.strategy.indicators import atr                # noqa: E402
from stratig.strategy.registry import is_supported         # noqa: E402
from scripts.backtest import FEE_PCT, simulate             # noqa: E402
from scripts.lab import load_csv                           # noqa: E402
from scripts.optimize import (                             # noqa: E402
    EXIT_MODE,
    base_config,
    evaluate,
    fold_windows,
    split_candles,
)

# كم شمعة نُقيّم عليها في كل خطوة (كل المؤشرات نافذية وأطولها 55 شمعة)
WINDOW = 400
HORIZON = 60


# ═══════════════════════════ المرشّحون ═══════════════════════════
# الاستراتيجيات × مستويات الصرامة. الفكرة: هل **التشدّد** يصنع ميزة؟
# (أي: هل الفلاتر تُحسّن الجودة أم تقلّل العيّنة فقط؟)
TREND_STRATEGIES = {"donchian_breakout", "ema_momentum"}

# ⚠️ تنبيه واجهناه فعلاً: فلاتر الجودة (نظام السوق + التقلّب) **لا تُطبَّق**
# إلا إن كان `strategy.quality_enabled` صحيحاً (انظر `_apply_quality_filters`
# في registry). بدونه يبدو الفلتر مُفعَّلاً وهو لا يفعل شيئاً — فتظهر
# النسخ «المُفلترة» مطابقة للأصلية تماماً ويضيع أثر التجربة كلها.
VARIANTS: list[tuple[str, dict]] = [
    ("أساسي", {}),
    ("+نظام", {"strategy.quality_enabled": True}),   # + regime حسب الاستراتيجية
    ("+اتجاه", {"strategy.trend_filter": "ema"}),
    ("صارم", {"strategy.quality_enabled": True,
              "strategy.trend_filter": "ema",
              "strategy.volatility_min_pct": 0.0015,
              "strategy.volatility_max_pct": 0.025}),
]

ALL_STRATEGIES = ["scalping_i", "rsi_williams", "mean_reversion_z",
                  "rsi_reversion", "donchian_breakout", "ema_momentum"]


def candidates(strategies: list[str]) -> list[tuple[str, str, dict]]:
    """(اسم العرض، مفتاح الاستراتيجية، إعدادات إضافية)."""
    out: list[tuple[str, str, dict]] = []
    for key in strategies:
        for name, params in VARIANTS:
            params = dict(params)
            if name == "+نظام":
                # لكل استراتيجية نظامها الملائم: الاتجاهية تتاجر في الاتجاه،
                # والارتدادية في النطاق. وضع عكسه يقتلها — وهذا هو المقصود
                # من الفلتر: أن نرى من يملك نظاماً يناسبه فعلاً.
                params["strategy.regime"] = ("trend" if key in TREND_STRATEGIES
                                             else "range")
            out.append((name, key, params))
    return out


# ═══════════════════════════ النتيجة ═══════════════════════════
@dataclass
class Verdict:
    name: str
    strategy: str
    params: dict
    trades: int = 0
    train_r: float = 0.0
    oos_r: float = 0.0
    windows: int = 0
    positive_windows: int = 0
    consistency: float = 0.0
    markets: int = 0
    positive_markets: int = 0
    p_random: float = 1.0                # احتمال أن يحقّق العشوائي مثلها
    ci_low: float = 0.0
    ci_high: float = 0.0
    max_dd: float = 0.0                  # أقصى سحب بوحدة R
    profit_factor: float = 0.0
    gates: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(self.gates.values()) and bool(self.gates)

    @property
    def grade(self) -> str:
        """درجة من 8 بوابات — لا نكتفي بـ «نجح/فشل»."""
        return f"{sum(1 for v in self.gates.values() if v)}/{len(self.gates)}"


# ═══════════════════════════ أدوات إحصائية ═══════════════════════════
def atr_pct_series(candles: Candles, length: int = 14) -> list[float]:
    """ATR% عند كل شمعة — نُحسبها مرّة واحدة ونعيد استخدامها."""
    values = atr(list(candles.high), list(candles.low), list(candles.close),
                 length, mode="wilder")
    out: list[float] = []
    for index, value in enumerate(values):
        price = candles.close[index]
        out.append(value / price if price and value == value else 0.0)
    return out


def max_drawdown(r_list: list[float]) -> float:
    """أقصى هبوط من قمّة إلى قاع في منحنى العائد التراكمي (بوحدة R)."""
    peak = 0.0
    worst = 0.0
    total = 0.0
    for value in r_list:
        total += value
        peak = max(peak, total)
        worst = min(worst, total - peak)
    return abs(worst)


def profit_factor(r_list: list[float]) -> float:
    """مجموع الأرباح ÷ مجموع الخسائر. أقل من 1 ⇒ خاسرة."""
    wins = sum(v for v in r_list if v > 0)
    losses = -sum(v for v in r_list if v < 0)
    if losses <= 0:
        return 99.0 if wins > 0 else 0.0
    return wins / losses


def bootstrap_ci(r_list: list[float], *, sims: int = 2000, alpha: float = 0.05,
                 seed: int = 11) -> tuple[float, float]:
    """فترة ثقة بالمعاينة المتكرّرة (bootstrap) على **عوائد الصفقات**.

    أصدق من قياس «نوافذ» قليلة: هنا العيّنة هي الصفقات نفسها (مئات)،
    فالفترة تعكس تشتّت النتيجة الحقيقي لا تشتّت 5 نوافذ.
    """
    if len(r_list) < 30:
        return (0.0, 0.0)
    rng = random.Random(seed)
    size = len(r_list)
    means = []
    for _ in range(sims):
        total = 0.0
        for _ in range(size):
            total += r_list[rng.randrange(size)]
        means.append(total / size)
    means.sort()
    low = means[int(alpha / 2 * sims)]
    high = means[min(sims - 1, int((1 - alpha / 2) * sims))]
    return (low, high)


def random_entry_benchmark(series: list[Candles], atrs: list[list[float]],
                           *, trades: int, sl_coef: float, tp_ratio: float,
                           cost_pct: float, sims: int = 300,
                           seed: int = 7) -> list[float]:
    """ماذا لو دخلنا **عشوائياً** بنفس عدد الصفقات ونفس الوقف والهدف؟

    هذا هو اختبار «مهارة أم حظ» الحقيقي: إن كانت الإشارة لا تختار توقيتاً
    أفضل من القرعة، فالاستراتيجية بلا قيمة — حتى لو كان توقّعها موجباً.

    نُعيد توزيع متوسطات R تحت الدخول العشوائي ليُقارن به التوقّع الحقيقي.
    """
    if trades <= 0 or not series:
        return []
    rng = random.Random(seed)
    means: list[float] = []
    # أوزان اختيار السلسلة تتناسب مع طولها (شمعة أطول ⇒ فرصة أعلى)
    weights = [max(1, len(s) - WINDOW) for s in series]
    total_weight = sum(weights)
    for _ in range(sims):
        total_r = 0.0
        for _ in range(trades):
            pick = rng.uniform(0, total_weight)
            index = 0
            running = 0
            for i, weight in enumerate(weights):
                running += weight
                if pick <= running:
                    index = i
                    break
            candles = series[index]
            atr_values = atrs[index]
            start = WINDOW
            bar = rng.randrange(start, max(start + 1, len(candles) - HORIZON - 2))
            volatility = atr_values[bar] if bar < len(atr_values) else 0.0
            if volatility <= 0:
                continue
            sl_pct = sl_coef * volatility
            tp_pct = sl_pct * tp_ratio
            side = "buy" if rng.random() < 0.5 else "sell"
            entry = candles.close[bar]
            _outcome, r = simulate(candles, side, entry, sl_pct, tp_pct,
                                   bar + 1, HORIZON)
            total_r += r - (2 * cost_pct) / sl_pct
        means.append(total_r / trades)
    return means


def repaint_free(candles: Candles, strategy: str, params: dict,
                 *, window: int = WINDOW, probe: int = 900) -> bool:
    """هل الإشارة تتغيّر إن حذفنا المستقبل؟ (اختبار إعادة الرسم / repainting)

    الطريقة: نشغّل على مقطع، ثم على **نفس** المقطع بعد حذف ما يكفي من
    آخره (بطول أفق الصفقة `HORIZON`)، ونقارن عوائد الصفقات واحدة واحدة.

    لماذا نحذف **ضعف** أفق الصفقة؟ لأن الصفقة التي تبدأ قبل نهاية المقطع
    بأقل من أفقها **لا تُحسم أصلاً** فيه — فتختلف عن نفسها في المقطع الأطول
    **بلا أي تلاعب**. تجاهل هذا جعل الاختبار يرفض استراتيجيات سليمة تماماً
    (خطأ وقعنا فيه قبل أن ننتبه: حذفنا 3 صفقات فقط، والصحيح عشرات).

    نكتفي بأول `probe` شمعة: الخاصية **بنيوية** لا تعتمد على طول العيّنة.
    """
    from scripts.backtest import run

    cfg = base_config(strategy)
    for key, value in params.items():
        cfg.set(key, value)
    if len(candles) > probe:
        candles = candles.slice(0, probe)
    cut = len(candles) - 2 * (HORIZON + 5)
    if cut < window + 60:
        return True
    full = run(candles, cfg, strategy, False, 1, window=window)
    safe = run(candles.slice(0, cut), cfg, strategy, False, 1, window=window)
    full_r = full.get("r_list", []) or []
    safe_r = safe.get("r_list", []) or []
    safe_bars = safe.get("entries", []) or []
    checked = 0
    for index, bar in enumerate(safe_bars):
        # صفقة لم تُحسم داخل المقطع الآمن ⇒ لا تُقارن (تُحسم في الأطول فقط)
        if bar + HORIZON + 2 >= cut or index >= len(full_r):
            continue
        if abs(full_r[index] - safe_r[index]) > 1e-9:
            return False
        checked += 1
    # وصلنا إلى هنا ⇒ كل صفقة محسومة تطابقت. وإن لم تُحسم أي صفقة أصلاً
    # فالحكم «لا بيّنة» لا «بريء تماماً» — والفحص بنيوي يُعاد على كل سلسلة،
    # فحالة نادرة لا تمرّ مرور الكرام.
    return True


# ═══════════════════════════ التقييم ═══════════════════════════
def judge(name: str, strategy: str, params: dict,
          series: list[Candles], *, min_trades: int = 100, folds: int = 4,
          split: float = 0.7, slippage_pct: float = 0.0002, sims: int = 200,
          max_dd: float = 25.0, total_candidates: int = 24) -> Verdict:
    """يطبّق البوابات الثماني بالترتيب — ويقف مبكراً عند أول رفض قاطع.

    ترتيب الحساب مقصود: **مرور واحد** على البيانات يكفي لبوابات
    (العيّنة، خارج العينة، تعدّد الأسواق) لأنّا نقسم كل سلسلة إلى
    تدريب/اختبار ثم نجمع — بدل أن نشغّل ثلاث مرّات منفصلة. الفرق في
    زمن التشغيل كبير (مرور واحد بدل ثلاثة) وبلا أي أثر على النتيجة.
    """
    verdict = Verdict(name=name, strategy=strategy, params=params)
    cost_pct = FEE_PCT + slippage_pct

    def run_on(bars: list[Candles]) -> dict:
        return evaluate(bars, base_config(strategy), strategy, params,
                        entry_delay=1, window=WINDOW,
                        slippage_pct=slippage_pct)

    # ── المرور الأساسي: تدريب + اختبار + لكل سوق على حدة ──
    r_list: list[float] = []
    oos_list: list[float] = []
    market_rs: list[float] = []
    train_trades = test_trades = 0
    train_total = test_total = 0.0
    for candles in series:
        train, test = split_candles(candles, split)
        got_train = run_on([train])
        got_test = run_on([test])
        n_train = int(got_train.get("trades", 0) or 0)
        n_test = int(got_test.get("trades", 0) or 0)
        train_trades += n_train
        test_trades += n_test
        train_total += float(got_train.get("total_r", 0.0) or 0.0)
        test_total += float(got_test.get("total_r", 0.0) or 0.0)
        r_list.extend(got_train.get("r_list", []) or [])
        r_list.extend(got_test.get("r_list", []) or [])
        oos_list.extend(got_test.get("r_list", []) or [])
        if n_train + n_test >= 10:          # سوق بلا صفقات كافية = بلا حكم
            market_rs.append((float(got_train.get("total_r", 0.0) or 0.0)
                              + float(got_test.get("total_r", 0.0) or 0.0))
                             / (n_train + n_test))

    verdict.trades = train_trades + test_trades
    verdict.train_r = train_total / train_trades if train_trades else 0.0
    verdict.oos_r = test_total / test_trades if test_trades else 0.0
    verdict.max_dd = max_drawdown(r_list)
    verdict.profit_factor = profit_factor(r_list)

    # ── 1) العيّنة ──
    verdict.gates["sample"] = verdict.trades >= min_trades
    if not verdict.gates["sample"]:
        verdict.reasons.append(
            f"❌ العيّنة {verdict.trades} صفقة فقط (المطلوب {min_trades})"
            " — لا يمكن تمييز ميزة من حظ")

    # ── 2) بلا نظرة للمستقبل (على أول سلسلتين: الخاصية بنيوية) ──
    verdict.gates["repaint"] = all(
        repaint_free(candles, strategy, params)
        for candles in series[:2])
    if not verdict.gates["repaint"]:
        verdict.reasons.append(
            "❌ الإشارة تتغيّر عند حذف المستقبل ⇒ فيها نظرة للمستقبل"
            " (أو إعادة رسم)")

    # ── 3) خارج العينة ──
    verdict.gates["oos"] = verdict.oos_r > 0
    if not verdict.gates["oos"]:
        verdict.reasons.append(
            f"❌ خارج العينة {verdict.oos_r:+.3f}R ≤ صفر"
            f" (داخلها {verdict.train_r:+.3f}R)")

    # ── 4) الثبات على نوافذ المشي (كل الأسواق معاً = قوّة إحصائية حقيقية)
    window_rs: list[float] = []
    for candles in series:
        for _train, test in fold_windows(candles, folds):
            stats = run_on([test])
            if int(stats.get("trades", 0)) >= 5:
                window_rs.append(float(stats.get("expectancy_r", 0.0)))
    verdict.windows = len(window_rs)
    verdict.positive_windows = sum(1 for value in window_rs if value > 0)
    verdict.consistency = (verdict.positive_windows / verdict.windows
                           if verdict.windows else 0.0)
    verdict.gates["consistency"] = (verdict.windows >= 5
                                    and verdict.consistency >= 0.6)
    if not verdict.gates["consistency"]:
        verdict.reasons.append(
            f"❌ الثبات {verdict.consistency * 100:.0f}% "
            f"({verdict.positive_windows}/{verdict.windows} نافذة) — أقل من 60%")

    # ── 5) تعدّد الأسواق: لا تُحملها عملة واحدة ──
    verdict.markets = len(market_rs)
    verdict.positive_markets = sum(1 for value in market_rs if value > 0)
    share = verdict.positive_markets / verdict.markets if verdict.markets else 0.0
    verdict.gates["markets"] = bool(verdict.markets) and share >= 0.6
    if not verdict.gates["markets"]:
        if not verdict.markets:
            verdict.reasons.append(
                "❌ لم تُنتج 10 صفقات في **أي** سوق — العيّنة أضعف من أن"
                " يُحكم عليها سوقاً بسوق")
        else:
            verdict.reasons.append(
                f"❌ رابحة في {verdict.positive_markets} من {verdict.markets}"
                " سوقاً فقط — المطلوب 60% على الأقل")

    # البوابات الغالية (مونتي كارلو) لا معنى لها إن سقطت السابقة
    if not all(verdict.gates.get(gate) for gate in
               ("sample", "repaint", "oos", "consistency", "markets")):
        for gate in ("random", "bootstrap", "risk"):
            verdict.gates[gate] = False
        return verdict

    # ── 6) أصعب بوابة: هل هي أفضل من **الدخول العشوائي**؟ ──
    defaults = DEFAULT_CONFIG.get("strategy", {}).get(strategy) or {}
    sl_coef = float(params.get(f"strategy.{strategy}.sl_coef",
                               defaults.get("sl_coef", 1.5)) or 1.5)
    tp_ratio = float(params.get(f"strategy.{strategy}.tp_ratio",
                                defaults.get("tp_ratio", 1.5)) or 1.5)
    tests: list[Candles] = []
    for candles in series:
        _train, test = split_candles(candles, split)
        tests.append(test)
    random_means = random_entry_benchmark(
        tests, [atr_pct_series(c) for c in tests],
        trades=max(1, test_trades), sl_coef=sl_coef, tp_ratio=tp_ratio,
        cost_pct=cost_pct, sims=sims)
    if random_means:
        ahead = sum(1 for value in random_means if value >= verdict.oos_r)
        verdict.p_random = ahead / len(random_means)
    threshold = 0.05 / max(1, total_candidates)       # تصحيح بونفيروني
    verdict.gates["random"] = verdict.p_random < threshold
    if not verdict.gates["random"]:
        verdict.reasons.append(
            f"❌ الدخول **العشوائي** بلغها في {verdict.p_random * 100:.0f}%"
            f" من المحاولات (يجب أن يكون < {threshold * 100:.1f}%) — "
            "أي أن التوقيت بلا قيمة")

    # ── 7) فترة ثقة (بوتستراب) على عوائد الصفقات ──
    z = bonferroni_z(total_candidates)
    alpha = 2 * (1 - _normal_cdf(z))
    verdict.ci_low, verdict.ci_high = bootstrap_ci(
        oos_list or r_list, alpha=max(0.002, alpha))
    verdict.gates["bootstrap"] = verdict.ci_low > 0
    if not verdict.gates["bootstrap"]:
        verdict.reasons.append(
            f"❌ فترة الثقة [{verdict.ci_low:+.3f}R، {verdict.ci_high:+.3f}R]"
            " تتضمن الصفر — لا نستطيع نفي أنها خاسرة")

    # ── 8) المخاطرة: أقصى سحب وعامل ربح ──
    verdict.gates["risk"] = (verdict.max_dd <= max_dd
                             and verdict.profit_factor > 1.1)
    if verdict.max_dd > max_dd:
        verdict.reasons.append(
            f"❌ أقصى سحب {verdict.max_dd:.1f}R يتجاوز الحدّ {max_dd:.0f}R")
    if verdict.profit_factor <= 1.1:
        verdict.reasons.append(
            f"❌ عامل الربح {verdict.profit_factor:.2f} ≤ 1.1"
            " (الأرباح لا تتجاوز الخسائر بما يُذكر)")
    return verdict


def _normal_cdf(x: float) -> float:
    import math
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ═══════════════════════════ التقرير ═══════════════════════════
def report(verdicts: list[Verdict], *, elapsed: float = 0.0) -> None:
    line = "─" * 78
    print(f"\n{line}")
    print("  🧑‍⚖️ مُحكِّم الخبير — 8 بوابات، كلها إلزامية")
    print(line)
    print(f"\n  {'الاستراتيجية':<20}{'الصرامة':<9}{'صفقات':>7}{'خارج':>8}"
          f"{'ثبات':>7}{'أسواق':>7}{'حظ؟':>7}{'الدرجة':>9}   الحكم")
    for v in sorted(verdicts, key=lambda x: (-sum(x.gates.values()), x.name)):
        markets = (f"{v.positive_markets}/{v.markets}" if v.markets else "—")
        luck = f"{v.p_random * 100:.0f}%" if v.p_random < 1 else "—"
        print(f"  {v.strategy:<20}{v.name:<9}{v.trades:>7}{v.oos_r:>+8.3f}"
              f"{(f'{v.consistency * 100:.0f}%' if v.windows else '—'):>7}"
              f"{markets:>7}{luck:>7}{v.grade:>9}"
              f"   {'✅' if v.passed else '❌'}")

    print("\n  ── التفصيل ──")
    for v in verdicts:
        print(f"\n  {v.strategy} · {v.name} — {_params_text(v.params)}")
        print(f"     صفقات {v.trades} · داخل {v.train_r:+.3f}R ·"
              f" خارج {v.oos_r:+.3f}R · ثبات {v.positive_windows}/{v.windows}"
              f" · عامل ربح {v.profit_factor:.2f} · سحب {v.max_dd:.1f}R")
        if v.p_random < 1:
            print(f"     الدخول العشوائي بلغها في {v.p_random * 100:.0f}%"
                  f" من {300} محاكاة · فترة الثقة"
                  f" [{v.ci_low:+.3f}R، {v.ci_high:+.3f}R]")
        if v.reasons:
            for reason in v.reasons:
                print(f"     {reason}")
        else:
            print("     ✅ صمدت أمام البوابات الثماني كلها")

    winners = [v for v in verdicts if v.passed]
    print(f"\n{line}")
    if winners:
        print(f"  🏆 {len(winners)} استراتيجية صمدت:")
        for v in winners:
            print(f"     • {v.strategy} · {v.name}")
        print("\n  ⚠️ حتى الصامد يحتاج شهر اختبار على حساب تجريبي قبل")
        print("     أن تثق به — فهذه نافذة واحدة من الزمن.")
    else:
        print("  ⛔ **لم تصمد أي استراتيجية أمام البوابات الثماني.**")
        print("     هذا خبر جيّد ومهم: لو اكتفيتَ بباك-تست واحد لظهر")
        print("     أن بعضها رابح. الفرق كله في البوابة السادسة (الحظ).")
    if elapsed:
        print(f"\n  الزمن: {elapsed / 60:.1f} دقيقة")
    print(f"{line}\n")


def _params_text(params: dict) -> str:
    if not params:
        return "بلا فلاتر"
    return "، ".join(f"{key.split('.')[-1]}={value}" for key, value in params.items())


# ═══════════════════════════ الواجهة ═══════════════════════════
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="مُحكِّم الخبير: 8 بوابات صارمة قبل أن تتداول")
    parser.add_argument("--csv", nargs="*", default=[],
                        help="ملفات الشموع (يدعم *, مثل: data/*.csv)")
    parser.add_argument("--min-trades", type=int, default=100)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--split", type=float, default=0.7)
    parser.add_argument("--slippage", type=float, default=0.0002,
                        help="الانزلاق لكل جهة (0.0002 = 0.02%%)")
    parser.add_argument("--sims", type=int, default=200,
                        help="محاكاة الدخول العشوائي (أكثر = أدقّ وأبطأ)")
    parser.add_argument("--max-dd", type=float, default=25.0,
                        help="أقصى سحب مقبول بوحدة R")
    parser.add_argument("--only", default="",
                        help="استراتيجية/استراتيجيات (بفاصلة) فقط")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)

    paths: list[str] = []
    for item in args.csv:
        paths.extend(sorted(glob.glob(item)) or [item])
    paths = [p for p in paths if p.lower().endswith(".csv")]
    if not paths:
        print("\n  ❌ لم تُعطِ أي ملف CSV — استخدم --csv data/*.csv", file=sys.stderr)
        return 1

    series: list[Candles] = []
    for path in paths:
        candles = load_csv(path)
        series.append(candles)
        print(f"  قرأنا {Path(path).name}: {len(candles)} شمعة")

    # --only يقبل أكثر من استراتيجية بفاصلة (لتقسيم التشغيل على عمليّات)
    wanted = [item.strip() for item in args.only.split(",") if item.strip()]
    strategies = [item for item in wanted if is_supported(item)] or ALL_STRATEGIES
    pool = candidates(strategies)
    total = len(pool)
    print(f"\n  البيانات: {len(series)} سلسلة · {sum(len(c) for c in series)} شمعة")
    print(f"  المرشّحون: {total} = {len(strategies)} استراتيجية × "
          f"{len(VARIANTS)} مستوى صرامة")
    print(f"  التكلفة: عمولة {FEE_PCT * 100:.2f}% + انزلاق "
          f"{args.slippage * 100:.2f}% لكل جهة")

    started = time.time()
    verdicts: list[Verdict] = []
    for index, (name, strategy, params) in enumerate(pool, start=1):
        print(f"    … {index}/{total} {strategy} · {name}", flush=True)
        verdicts.append(judge(
            name, strategy, params, series,
            min_trades=args.min_trades, folds=args.folds, split=args.split,
            slippage_pct=args.slippage, sims=args.sims, max_dd=args.max_dd,
            total_candidates=total))
    report(verdicts, elapsed=time.time() - started)

    if args.json:
        import json
        payload = [{
            "strategy": v.strategy, "variant": v.name, "params": v.params,
            "trades": v.trades, "train_r": v.train_r, "oos_r": v.oos_r,
            "consistency": v.consistency, "windows": v.windows,
            "markets": f"{v.positive_markets}/{v.markets}",
            "p_random": v.p_random, "ci": [v.ci_low, v.ci_high],
            "max_dd": v.max_dd, "profit_factor": v.profit_factor,
            "grade": v.grade, "passed": v.passed, "reasons": v.reasons,
        } for v in verdicts]
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  💾 حفظنا النتيجة في {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
