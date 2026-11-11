"""مختبر الاستراتيجيات — يبحث عن استراتيجية **ثابتة** على **80+ صفقة**.

لماذا هذا المختبر؟
    «ابحث عن استراتيجيات لها ثبات في الصفقات، بأكثر من 80 صفقة ناجحة.»

    الثبات لا يعني ربحاً إجمالياً — بل أن تعمل الاستراتيجية في **معظم**
    النوافذ الزمنية. الربح الإجمالي قد يأتي من نافذة واحدة محظوظة،
    والثبات لا يمكن تزويره.

شروط القبول (كلها إلزامية):
    1. عدد الصفقات ≥ 80 (الافتراضي) — دونها قد يكون كل شيء حظاً
    2. التوقع خارج العينة > 0 على بيانات لم يرها البحث
    3. **الثبات**: رابحة في ≥ 60% من نوافذ المشي للأمام
    4. **الدلالة**: فترة ثقة 95% **بعد تصحيح بونفيروني** (نختبر مرشّحين
       كثيرين، وأحدهم سيبدو رابحاً بالمصادفة)

    python scripts/lab.py --synthetic --bars 1200 --series 4   # تجربة الأداة
    python scripts/lab.py --csv candles/BTCUSDT-1h.csv         # على بياناتك

    ⚠️ `--synthetic` للتحقّق من الأداة فقط: مُولّد البيانات الاصطناعية
    نفسه متحيّز (نظام `range` فيه ارتدادي بالبناء)، فلا يصحّ الاستنتاج منه.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config                        # noqa: E402
from stratig.data import Candles, make_candles           # noqa: E402
from stratig.edge import bonferroni_z, measure           # noqa: E402
from scripts.backtest import synthetic_series            # noqa: E402
from scripts.optimize import (                           # noqa: E402
    base_config,
    fold_windows,
    split_candles,
)

# أدنى عدد نوافذ لقياس «الثبات». نافذة أو ثلاث لا تقيس التكرار:
# ثبات 67% على 3 نوافذ يعني «2 من 3» — أي قرعة. خمس نوافذ حدٌّ أدنى.
MIN_WINDOWS = 5

# مرجع للمقارنة فقط: الاستراتيجيتان الموجودتان أصلاً. ليستا من المرشّحين
# (لا تدخلان في تصحيح بونفيروني) — الغرض أن ترى: هل الجديد أفضل من الذي
# تستعمله اليوم على **نفس** البيانات؟
BASELINES: list[tuple[str, str]] = [
    ("الحالية: الدفتر", "scalping_i"),
    ("الحالية: الأصلية", "rsi_williams"),
]

# المرشّحون: (اسم العرض، مفتاح الاستراتيجية، قائمة تركيبات المعاملات)
# التركيبات قليلة ومتعمدة: كلما زاد عدد المرشّحين زاد احتمال الفائز المزيّف.
CANDIDATES: list[tuple[str, str, list[dict]]] = [
    ("ارتداد المتوسط", "mean_reversion_z", [
        {"strategy.mean_reversion_z.length": 20, "strategy.mean_reversion_z.entry_z": 2.0,
         "strategy.mean_reversion_z.tp_ratio": 1.5},
        {"strategy.mean_reversion_z.length": 20, "strategy.mean_reversion_z.entry_z": 2.5,
         "strategy.mean_reversion_z.tp_ratio": 2.0},
        {"strategy.mean_reversion_z.length": 30, "strategy.mean_reversion_z.entry_z": 2.0,
         "strategy.mean_reversion_z.tp_ratio": 1.0},
    ]),
    ("ارتداد RSI", "rsi_reversion", [
        {"strategy.rsi_reversion.period": 14, "strategy.rsi_reversion.oversold": 25.0,
         "strategy.rsi_reversion.overbought": 75.0},
        {"strategy.rsi_reversion.period": 7, "strategy.rsi_reversion.oversold": 20.0,
         "strategy.rsi_reversion.overbought": 80.0},
        {"strategy.rsi_reversion.period": 14, "strategy.rsi_reversion.oversold": 30.0,
         "strategy.rsi_reversion.overbought": 70.0,
         "strategy.rsi_reversion.tp_ratio": 2.0},
    ]),
    ("اختراق دونشيان", "donchian_breakout", [
        {"strategy.donchian_breakout.length": 20, "strategy.donchian_breakout.tp_ratio": 2.0},
        {"strategy.donchian_breakout.length": 55, "strategy.donchian_breakout.tp_ratio": 3.0},
        {"strategy.donchian_breakout.length": 10, "strategy.donchian_breakout.tp_ratio": 1.5},
    ]),
    ("زخم EMA", "ema_momentum", [
        {"strategy.ema_momentum.fast": 9, "strategy.ema_momentum.slow": 21,
         "strategy.ema_momentum.tp_ratio": 2.0},
        {"strategy.ema_momentum.fast": 5, "strategy.ema_momentum.slow": 13,
         "strategy.ema_momentum.tp_ratio": 1.5},
        {"strategy.ema_momentum.fast": 20, "strategy.ema_momentum.slow": 50,
         "strategy.ema_momentum.tp_ratio": 3.0},
    ]),
]


@dataclass
class Result:
    name: str
    strategy: str
    params: dict
    trades: int = 0
    train_r: float = 0.0
    test_r: float = 0.0
    windows: int = 0
    positive_windows: int = 0
    mean_window_r: float = 0.0
    consistency: float = 0.0
    window_stats: object = None
    accepted: bool = False
    thin: bool = False                 # هامش خارج العينة داخل ضجيج التكلفة
    reasons: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """الأفضلية لمن جمع الثبات مع التوقع خارج العينة."""
        return self.test_r * self.consistency


# ═══════════════════════ القياس ═══════════════════════
def _run(series: list[Candles], strategy: str, params: dict,
         entry_delay: int = 1, horizon: int = 60) -> dict:
    """يقيس مرشّحاً على مجموعة سلاسل — يُرجع النتيجة المجمّعة."""
    from scripts.optimize import evaluate
    return evaluate(series, base_config(strategy), strategy, params,
                    entry_delay=entry_delay)


def load_csv(path: str | Path) -> Candles:
    """يقرأ شموعاً حقيقية من CSV: `time,open,high,low,close[,volume]`.

    هذا هو الطريق الوحيد الموثوق للحكم: المختبر على بيانات اصطناعية
    يتحقّق من الأداة، لكنه لا يقول شيئاً عن السوق. صدّر شموعك من أي
    مصدر (Binance → Export، أو `/data` في البوت) ثم:

        python scripts/lab.py --csv BTCUSDT-1h.csv

    يُتجاهل سطر الترويسة إن وُجد، وتُرتَّب الشموع تصاعدياً بالوقت.
    """
    rows: list[list[str]] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for raw in csv.reader(fh):
            if len(raw) < 5 or not raw[0].strip():
                continue
            try:
                float(raw[1])                      # ترويسة؟ العمود الثاني ليس رقماً
            except ValueError:
                continue
            rows.append(raw)
    if len(rows) < 60:
        raise ValueError(f"{path}: عدد الشموع قليل ({len(rows)}) — يحتاج 60 على الأقل")

    return make_candles([row[:6] for row in rows])


def evaluate_candidate(
    name: str,
    strategy: str,
    params: dict,
    series: list[Candles],
    *,
    min_trades: int = 80,
    folds: int = 4,
    split: float = 0.7,
    entry_delay: int = 1,
    min_windows: int = MIN_WINDOWS,
) -> Result:
    """يقيس مرشّحاً واحداً بكل الشروط، ويُرجع القرار مع أسبابه."""
    result = Result(name=name, strategy=strategy, params=params)

    trains, tests = [], []
    for candles in series:
        train, test = split_candles(candles, split)
        trains.append(train)
        tests.append(test)

    train = _run(trains, strategy, params, entry_delay)
    test = _run(tests, strategy, params, entry_delay)
    result.trades = int(train.get("trades", 0)) + int(test.get("trades", 0))
    result.train_r = float(train.get("expectancy_r", 0.0))
    result.test_r = float(test.get("expectancy_r", 0.0))

    # ── الثبات: نوافذ متتالية ──
    window_rs: list[float] = []
    for candles in series:
        for _tr, te in fold_windows(candles, folds):
            stats = _run([te], strategy, params, entry_delay)
            if int(stats.get("trades", 0)) >= 5:        # نافذة بلا صفقات = بلا حكم
                window_rs.append(float(stats.get("expectancy_r", 0.0)))
    result.windows = len(window_rs)
    result.positive_windows = sum(1 for value in window_rs if value > 0)
    if window_rs:
        result.mean_window_r = statistics.fmean(window_rs)
        result.consistency = result.positive_windows / len(window_rs)

    # ── الشروط ──
    if result.trades < min_trades:
        result.reasons.append(
            f"❌ {result.trades} صفقة فقط (المطلوب {min_trades}) — العيّنة "
            "أصغر من أن يُحكم عليها")
    if result.test_r <= 0:
        result.reasons.append(
            f"❌ التوقع خارج العينة {result.test_r:+.3f}R ≤ صفر — "
            "ربح داخل العينة لم يصمد خارجها")
    if result.windows and result.consistency < 0.6:
        result.reasons.append(
            f"❌ الثبات {result.consistency * 100:.0f}% "
            f"({result.positive_windows}/{result.windows} نوافذ) — أقل من 60%")
    if result.windows < min_windows:
        result.reasons.append(
            f"❌ {result.windows} نوافذ فقط (المطلوب {min_windows}) — الثبات "
            "يُقاس بالتكرار، ونافذتان أو ثلاث لا تقول شيئاً عن التكرار")

    # هامش ضئيل: ربح خارج العينة لا يغطّي تكلفة الصفقة نفسها.
    # (لا نرفضه تلقائياً لأن العمولة تختلف بين المنصّات، لكن نُبرزه)
    if result.test_r > 0 and result.test_r < 0.1:
        result.thin = True
        result.reasons.append(
            f"⚠️ هامش ضئيل: خارج العينة {result.test_r:+.3f}R — قريب من الصفر "
            "وربما لا يغطّي عمولة الذهاب والعودة")

    # ── الدلالة: على مستوى **النوافذ** لا الصفقات ──
    # تنبيه: تكرار قيمة واحدة لصنع عيّنة يُنتج تشتّتاً صفرياً أي دلالة
    # زائفة. نقيس إذن توزّع عوائد النوافذ نفسها بعتبة مصحّحة (بونفيروني).
    total_candidates = sum(len(variants) for _n, _s, variants in CANDIDATES)
    z = bonferroni_z(total_candidates)
    if len(window_rs) >= 3:
        result.window_stats = measure(window_rs, min_trades=3, z=z)
        if result.window_stats.is_losing:
            result.reasons.append(
                f"❌ عوائد النوافذ سالبة إحصائياً "
                f"({result.window_stats.expectancy_r:+.3f}R · بين "
                f"{result.window_stats.lower_r:+.3f}R و "
                f"{result.window_stats.upper_r:+.3f}R)")

    blocking = [r for r in result.reasons if r.startswith("❌")]
    result.accepted = (not blocking
                       and result.trades >= min_trades
                       and result.test_r > 0
                       and result.windows >= min_windows
                       and result.consistency >= 0.6)
    if result.accepted:
        result.reasons.append(
            f"✅ مقبولة: {result.trades} صفقة · خارج العينة {result.test_r:+.3f}R · "
            f"ثبات {result.consistency * 100:.0f}%")
    return result


# ═══════════════════════ التقرير ═══════════════════════
def _params_text(params: dict) -> str:
    return "، ".join(f"{key.split('.')[-1]}={value}" for key, value in params.items())


def report(results: list[Result], *, min_trades: int, folds: int,
           elapsed: float = 0.0, min_windows: int = MIN_WINDOWS,
           synthetic: bool = True, baselines: list[Result] | None = None) -> None:
    line = "─" * 74
    print(f"\n{line}")
    print(f"  🧪 مختبر الاستراتيجيات — القبول: {min_trades}+ صفقة · ثبات ≥ 60%"
          f" · {min_windows}+ نوافذ")
    print(line)

    results = sorted(results, key=lambda r: r.score, reverse=True)
    print(f"\n  {'المرشّح':<16}{'صفقات':>7}{'داخل':>9}{'خارج':>9}"
          f"{'الثبات':>9}   القرار")
    for item in results:
        print(f"  {item.name:<16}{item.trades:>7}{item.train_r:>+9.3f}"
              f"{item.test_r:>+9.3f}"
              f"{(f'{item.consistency * 100:.0f}%' if item.windows else '—'):>9}"
              f"   {'✅' if item.accepted else '❌'}")

    print("\n  ── التفصيل ──")
    for item in results:
        print(f"\n  {item.name} — {_params_text(item.params)}")
        if item.windows:
            print(f"     الثبات: {item.positive_windows}/{item.windows} "
                  f"نوافذ رابحة · متوسط {item.mean_window_r:+.3f}R")
        for reason in item.reasons:
            print(f"     {reason}")

    if baselines:
        print("\n  ── المرجع: استراتيجيتاك الحاليتان (نفس البيانات) ──")
        for item in baselines:
            print(f"  {item.name:<16}{item.trades:>7}{item.train_r:>+9.3f}"
                  f"{item.test_r:>+9.3f}"
                  f"{(f'{item.consistency * 100:.0f}%' if item.windows else '—'):>9}"
                  f"   {(f'{item.windows} نوافذ' if item.windows else '—')}")

    winners = [r for r in results if r.accepted]
    print(f"\n{line}")
    if winners:
        print(f"  🏆 {len(winners)} مرشّح صمد:")
        for item in winners:
            print(f"     • {item.name}: {_params_text(item.params)}")
            print(f"       /strategy {item.strategy}")
        if any(item.thin for item in winners):
            print("\n  ⚠️ بعض الفائزين بهامش ضئيل — راجع سطر «هامش ضئيل» أعلاه"
                  "\n     قبل أن تتداول به.")
        if synthetic:
            print("\n  ⚠️ تذكّر: بيانات اصطناعية. أعد التشغيل بـ --csv على"
                  "\n     شموعك الحقيقية قبل الاعتماد.")
    else:
        print("  ⛔ **لم يصمد أي مرشّح.**")
        print("     هذا خبر جيّد: أفضل من أن تتداول استراتيجية تبدو رابحة")
        print("     داخل العينة وتنهار خارجها.")
        print("     المعنى: المشكلة في **الإشارة نفسها** لا في معاملاتها.")
    if elapsed:
        print(f"\n  الزمن: {elapsed:.0f} ثانية")
    print(f"{line}\n")


# ═══════════════════════ الواجهة ═══════════════════════
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="مختبر الاستراتيجيات")
    parser.add_argument("--bars", type=int, default=1200)
    parser.add_argument("--series", type=int, default=4)
    parser.add_argument("--split", type=float, default=0.7)
    parser.add_argument("--folds", type=int, default=8,
                        help="نوافذ المشي للأمام (أكثر ⇒ حكم أدقّ على الثبات)")
    parser.add_argument("--min-trades", type=int, default=80,
                        help="أدنى عدد صفقات لقبول المرشّح")
    parser.add_argument("--min-consistency", type=float, default=0.6)
    parser.add_argument("--min-windows", type=int, default=MIN_WINDOWS,
                        help=f"أدنى نوافذ لقياس الثبات (الافتراضي {MIN_WINDOWS})")
    parser.add_argument("--baseline", action="store_true",
                        help="أضف استراتيجيتَيك الحاليتَين مرجعاً للمقارنة")
    parser.add_argument("--delay", type=int, default=1)
    parser.add_argument("--regime", default="mixed",
                        choices=("trend", "range", "mixed"))
    parser.add_argument("--synthetic", action="store_true", default=True)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--only", default="",
                        help="اختبر عائلة واحدة فقط (بالاسم أو بالمعرّف)")
    parser.add_argument("--csv", nargs="*", default=[],
                        help="ملف/ملفات CSV حقيقية: time,open,high,low,close")
    parser.add_argument("--json", default="", help="احفظ النتيجة الكاملة في JSON")
    args = parser.parse_args(argv)

    series: list[Candles] = []
    if args.csv:
        for item in args.csv:
            candles = load_csv(item)
            series.append(candles)
            print(f"  قرأنا {Path(item).name}: {len(candles)} شمعة")
    else:
        for index in range(args.series):
            regime = args.regime if args.regime != "mixed" else (
                "trend", "range")[index % 2]
            series.append(synthetic_series(args.bars, seed=args.seed + index * 17,
                                           regime=regime))

    def _selected(item: tuple) -> bool:
        """`--only` يقبل اسم العرض أو مفتاح الاستراتيجية."""
        if not args.only:
            return True
        needle = args.only.strip().lower()
        return needle in (item[0].strip().lower(), item[1].strip().lower())

    total = sum(len(v) for item in CANDIDATES if _selected(item) for v in [item[2]])
    total_bars = sum(len(c) for c in series)
    source = (f"{len(series)} ملف CSV · {total_bars} شمعة (بياناتك)"
              if args.csv else
              f"{args.series} سلسلة × {args.bars} شمعة · نظام: {args.regime}")
    print(f"\n  البيانات: {source}")
    if not args.csv:
        print("  ⚠️ اصطناعية — للتحقّق من الأداة فقط، لا يُستنتج منها")
    print(f"  المرشّحون: {total} · الشروط: {args.min_trades}+ صفقة،"
          f" ثبات ≥ {args.min_consistency * 100:.0f}%،"
          f" {args.min_windows}+ نوافذ")
    print(f"  (تصحيح بونفيروني: {total} مرشّحاً ⇒ عتبة أعلى)")

    started = time.time()
    results: list[Result] = []
    done = 0
    for name, strategy, variants in CANDIDATES:
        if not _selected((name, strategy, variants)):
            continue
        for params in variants:
            results.append(evaluate_candidate(
                name, strategy, params, series,
                min_trades=args.min_trades, folds=args.folds,
                split=args.split, entry_delay=args.delay,
                min_windows=args.min_windows))
            done += 1
            print(f"    … {done}/{total}", flush=True)

    baselines = []
    if args.baseline:
        for name, strategy in BASELINES:
            baselines.append(evaluate_candidate(
                name, strategy, {}, series,
                min_trades=args.min_trades, folds=args.folds,
                split=args.split, entry_delay=args.delay,
                min_windows=args.min_windows))

    report(results, min_trades=args.min_trades, folds=args.folds,
           elapsed=time.time() - started, min_windows=args.min_windows,
           synthetic=not args.csv, baselines=baselines)

    if args.json:
        import json
        payload = [{
            "name": r.name, "strategy": r.strategy, "params": r.params,
            "trades": r.trades, "train_r": r.train_r, "test_r": r.test_r,
            "consistency": r.consistency, "windows": r.windows,
            "accepted": r.accepted, "reasons": r.reasons, "score": r.score,
        } for r in results]
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  💾 حفظنا النتيجة في {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
