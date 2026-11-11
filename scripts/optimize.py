"""مُحسِّن المعاملات — يبحث عن معاملات أفضل لاستراتيجيتك على بياناتك.

⚠️  القاعدة الذهبية في هذا الملف: **لا تُبدّل المعاملات تلقائياً أبداً.**
هذا السكربت لا يكتب في config.toml — يطبع وصفة `/set` جاهزة لتطبّقها
بيدك بعد أن تقتنع بالأرقام.

لماذا التحقق خارج العينة إلزامي؟
    البحث على 100 تركيبة معاملات على نفس البيانات **سيجد** تركيبة رابحة
    بالمصادفة، حتى على بيانات عشوائية. اختيار الأفضل داخل العينة يعطي
    أرقاماً جميلة على الماضي وخسائر في الحقيقة — وهذا بالضبط ما يسمّى
    المبالغة في الملاءمة (overfitting).

    لذلك: نبحث على **النصف الأول** only، ثم نختبر الفائز على **النصف
    الثاني** الذي لم تره عملية البحث. إن خسر هناك → لا نوصي به.

    ثم نتحقّق بـ **المشي للأمام** (walk-forward): نوافذ متتالية، ندرّب على
    ما قبلها ونختبر على ما بعدها، ونحسب في كم نافذة كان التوقع موجباً.
    المعاملات الجيدة تعمل في **معظم** النوافذ، لا في نافذة واحدة محظوظة.

الاستخدام:
    python scripts/optimize.py --synthetic --bars 900 --series 3
    python scripts/optimize.py --strategy scalping_i --trials 40
    python scripts/optimize.py --folds 4          # تحقّق أقوى
"""
from __future__ import annotations

import argparse
import copy
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config                       # noqa: E402
from stratig.data import Candles                        # noqa: E402
from scripts.backtest import run, synthetic_series      # noqa: E402

# ═════════════════════════ شبكات البحث ═══════════════════════════
# مفاتيح config.toml مع القيم المجرَّبة لكل استراتيجية.
# (القيم الافتراضية تبقى كما هي — هذا البحث **استشاري** فقط.)
GRIDS: dict[str, dict[str, list]] = {
    "scalping_i": {
        "strategy.scalping_i.ema_slow": [30, 50, 70],
        "strategy.scalping_i.ema_fast": [20, 30, 40],
        "strategy.scalping_i.rsi_length": [7, 10, 14],
        "strategy.scalping_i.bb_length": [12, 15, 20],
        "strategy.scalping_i.bb_std": [1.2, 1.5, 2.0],
        "strategy.scalping_i.atr_length": [5, 7, 14],
        "strategy.scalping_i.backcandles": [5, 7, 10],
        "strategy.scalping_i.sl_coef": [0.8, 1.1, 1.5],
        "strategy.scalping_i.tp_sl_ratio": [1.0, 1.5, 2.0],
    },
    "rsi_williams": {
        "strategy.rsi.period": [7, 14, 21],
        "strategy.rsi.oversold": [20, 30, 35],
        "strategy.rsi.overbought": [65, 70, 80],
        "strategy.rsi.lookback": [2, 3, 5],
        "strategy.williams_r.lbp": [14, 24, 30],
        "strategy.williams_r.oversold": [-85, -75, -70],
        "strategy.williams_r.overbought": [-30, -25, -15],
        "strategy.williams_r.ema_window": [14, 24, 30],
    },
}

# معاملات الخروج المشتركة (تؤثّر في كل الاستراتيجيات)
EXIT_GRID: dict[str, list] = {
    "trade.stop_loss_pct": [0.006, 0.009, 0.015],
    "trade.take_profit_pct": [0.008, 0.012, 0.020],
}

# أي وضع مخارج تستخدمه كل استراتيجية؟
#
# مهم: `sl_coef` و`tp_sl_ratio` في scalping_i **لا تُؤثّران إلا** حين يكون
# exit.mode = "atr" (حينها تُستخدم مسافات الاستراتيجية). مع "percent" تُستخدم
# النسب الثابتة وحدها — وأي بحث على sl_coef هناك يجرّب معاملات بلا أثر.
EXIT_MODE: dict[str, str] = {
    "scalping_i": "atr",             # مخارج من ATR الاستراتيجية
    "rsi_williams": "percent",       # نسب ثابتة
    "mean_reversion_z": "atr",       # الاستراتيجيات المرشّحة كلها ATR
    "rsi_reversion": "atr",
    "donchian_breakout": "atr",
    "ema_momentum": "atr",
}

# هل تملك الاستراتيجية نسب خروج خاصة تُغني عن النسب العامة؟
USES_GENERIC_EXITS: dict[str, bool] = {
    "scalping_i": False,        # يملك sl_coef / tp_sl_ratio
    "rsi_williams": True,       # لا يملك → النسب العامة هي مخارجه فعلاً
}


def base_config(strategy_key: str, **overrides) -> Config:
    """إعداد الأساس للبحث — بوضع المخارج الصحيح للاستراتيجية."""
    data: dict = {
        "strategy": {"name": strategy_key, "use_closed_candles": False},
        "exit": {"mode": EXIT_MODE.get(strategy_key, "percent")},
        "trade": {"stop_loss_pct": 0.009, "take_profit_pct": 0.012},
    }
    data.update(overrides)
    return Config(data)


def build_grid(strategy_key: str, *, use_exits: bool = False) -> dict[str, list]:
    """شبكة البحث: معاملات الاستراتيجية + معاملات الخروج إن كانت مؤثّرة."""
    grid = dict(GRIDS.get(strategy_key, {}))
    if use_exits or USES_GENERIC_EXITS.get(strategy_key, False):
        grid.update(EXIT_GRID)
    return grid


@dataclass
class Candidate:
    params: dict[str, float] = field(default_factory=dict)
    train_r: float = 0.0
    train_trades: int = 0
    test_r: float = 0.0
    test_trades: int = 0
    score: float = 0.0

    @property
    def is_overfit(self) -> bool:
        """خسر خارج العينة، أو احتفظ بأقل من نصف توقّعه → مبالغ في ملاءمته."""
        if self.train_r <= 0:
            return True
        if self.test_r <= 0:
            return True
        return self.test_r < 0.5 * self.train_r

    @property
    def retention(self) -> float:
        """كم احتفظ من توقّعه خارج العينة؟ 1.0 = مثالي."""
        if self.train_r <= 0 or self.test_r <= 0:
            return 0.0
        return self.test_r / self.train_r


# ═════════════════════════ التقسيم ═════════════════════════
def split_candles(candles: Candles, ratio: float = 0.7) -> tuple[Candles, Candles]:
    """يقسم السلسلة إلى تدريب (الأول) واختبار (الأخير) — الترتيب الزمني محفوظ."""
    cut = max(60, int(len(candles) * min(max(ratio, 0.3), 0.9)))
    return candles.slice(0, cut), candles.slice(cut, len(candles))


def fold_windows(candles: Candles, folds: int) -> list[tuple[Candles, Candles]]:
    """نوافذ المشي للأمام: درّب على ما قبل النافذة، اختبر عليها."""
    total = len(candles)
    step = max(60, total // max(2, folds))
    windows = []
    start = step
    while start + step <= total:
        windows.append((candles.slice(0, start), candles.slice(start, start + step)))
        start += step
    return windows


# ═════════════════════════ التقييم ═════════════════════════
def evaluate(
    series: list[Candles],
    base_cfg: Config,
    strategy_key: str,
    params: dict[str, float],
    *,
    entry_delay: int = 1,
    use_closed: bool = False,
) -> dict:
    """يقيس تركيبة معاملات على مجموعة سلاسل — يُرجع النتيجة المجمّعة."""
    cfg = copy.deepcopy(base_cfg)
    for key, value in params.items():
        cfg.set(key, value)

    total_r = 0.0
    trades = 0
    win_rates = []
    for candles in series:
        result = run(candles, cfg, strategy_key, use_closed, entry_delay)
        count = int(result.get("trades", 0) or 0)
        if not count:
            continue
        trades += count
        total_r += float(result.get("total_r", 0.0) or 0.0)
        win_rates.append(float(result.get("win_rate", 0.0) or 0.0))

    if not trades:
        return {"trades": 0, "expectancy_r": 0.0, "win_rate": 0.0, "total_r": 0.0}
    return {
        "trades": trades,
        # التوقع = مجموع R ÷ عدد الصفقات (يجمع كل السلاسل بعدد صفقاتها)
        "expectancy_r": total_r / trades,
        "win_rate": statistics.fmean(win_rates) if win_rates else 0.0,
        "total_r": total_r,
    }


def sample_params(grid: dict[str, list], rng: random.Random) -> dict[str, float]:
    """يسحب تركيبة عشوائية واحدة من الشبكة."""
    return {key: rng.choice(values) for key, values in grid.items()}


def search(
    trains: list[Candles],
    tests: list[Candles],
    base_cfg: Config,
    strategy_key: str,
    grid: dict[str, list],
    *,
    trials: int = 30,
    min_trades: int = 20,
    seed: int = 7,
    entry_delay: int = 1,
    use_closed: bool = False,
    top_k: int = 5,
    progress=None,
) -> list[Candidate]:
    """يبحث على بيانات التدريب، ثم يختبر أفضلها على بيانات الاختبار."""
    rng = random.Random(seed)
    scored: list[Candidate] = []

    for index in range(trials):
        params = sample_params(grid, rng)
        result = evaluate(trains, base_cfg, strategy_key, params,
                          entry_delay=entry_delay, use_closed=use_closed)
        if progress:
            progress(index + 1, trials)
        if result["trades"] < min_trades:
            continue                      # تركيبة بلا صفقات كافية = رقم بلا معنى
        scored.append(Candidate(params=params,
                                train_r=result["expectancy_r"],
                                train_trades=result["trades"]))

    if not scored:
        return []

    # الأفضل داخل العينة → نختبره خارجها (هنا تكمن الحماية من المبالغة)
    scored.sort(key=lambda c: c.train_r, reverse=True)
    for cand in scored[:max(1, top_k)]:
        result = evaluate(tests, base_cfg, strategy_key, cand.params,
                          entry_delay=entry_delay, use_closed=use_closed)
        cand.test_r = result["expectancy_r"]
        cand.test_trades = result["trades"]
        # الأفضلية لما صمد خارج العينة، لا لما تألّق داخلها
        cand.score = cand.test_r

    return sorted(scored[:max(1, top_k)], key=lambda c: c.score, reverse=True)


def walk_forward(
    series: list[Candles],
    base_cfg: Config,
    strategy_key: str,
    params: dict[str, float],
    *,
    folds: int = 3,
    entry_delay: int = 1,
    use_closed: bool = False,
) -> dict:
    """يتحقّق من المعاملات على نوافذ زمنية متتالية."""
    per_fold = []
    for candles in series:
        for train, test in fold_windows(candles, folds):
            result = evaluate([test], base_cfg, strategy_key, params,
                              entry_delay=entry_delay, use_closed=use_closed)
            if result["trades"] >= 5:
                per_fold.append(result["expectancy_r"])
    if not per_fold:
        return {"folds": 0, "positive": 0, "mean": 0.0, "consistent": False}
    positive = sum(1 for value in per_fold if value > 0)
    return {
        "folds": len(per_fold),
        "positive": positive,
        "mean": statistics.fmean(per_fold),
        # «ثابت» = رابح في أغلب النوافذ، لا في نافذة محظوظة واحدة
        "consistent": positive / len(per_fold) >= 0.6 and statistics.fmean(per_fold) > 0,
    }


# ═════════════════════════ التقرير ═════════════════════════
# أسماء أوامر /set المقابلة لمسارات config.toml (من SET_KEYS في البوت)
SET_NAME: dict[str, str] = {
    "strategy.scalping_i.ema_slow": "sislow",
    "strategy.scalping_i.ema_fast": "sifast",
    "strategy.scalping_i.rsi_length": "sirsilen",
    "strategy.scalping_i.bb_length": "sibb",
    "strategy.scalping_i.bb_std": "sibbstd",
    "strategy.scalping_i.atr_length": "siatr",
    "strategy.scalping_i.backcandles": "sibc",
    "strategy.scalping_i.sl_coef": "sisl",
    "strategy.scalping_i.tp_sl_ratio": "sitp",
    "strategy.rsi.period": "rsiper",
    "strategy.rsi.oversold": "rsios",
    "strategy.rsi.overbought": "rsiob",
    "strategy.rsi.lookback": "rsilook",
    "strategy.williams_r.lbp": "wper",
    "strategy.williams_r.oversold": "wos",
    "strategy.williams_r.overbought": "wob",
    "strategy.williams_r.ema_window": "wema",
    "trade.stop_loss_pct": "sl",
    "trade.take_profit_pct": "tp",
}


def recipe(cand: Candidate) -> list[str]:
    """وصفة /set جاهزة للنسخ — بلا أي كتابة تلقائية في الإعدادات."""
    lines = []
    for key, value in cand.params.items():
        name = SET_NAME.get(key, key.split(".")[-1])
        lines.append(f"/set {name} {value}")
    return lines


def report(
    best: Candidate,
    baseline: dict,
    wf: dict,
    strategy_key: str,
    *,
    trials: int,
) -> None:
    line = "─" * 68
    print(f"\n{line}\n  مُحسِّن المعاملات — {strategy_key}\n{line}")

    print(f"\n  الأساس (معاملاتك الحالية):")
    print(f"    داخل العينة {baseline.get('train_r', 0):+.3f}R "
          f"({baseline.get('train_trades', 0)} صفقة) · "
          f"خارجها {baseline.get('test_r', 0):+.3f}R "
          f"({baseline.get('test_trades', 0)} صفقة)")

    print(f"\n  أفضل تركيبة بعد {trials} محاولة (مُقاس على {len(best.params)} معاملات):")
    print(f"    داخل العينة  {best.train_r:+.3f}R  ({best.train_trades} صفقة)")
    print(f"    خارج العينة  {best.test_r:+.3f}R  ({best.test_trades} صفقة)  "
          f"← الاحتفاظ {best.retention * 100:.0f}%")

    if wf.get("folds"):
        print(f"\n  المشي للأمام: {wf['positive']}/{wf['folds']} نافذة رابحة · "
              f"متوسط {wf['mean']:+.3f}R")

    print()
    if best.is_overfit:
        print("  ⛔ **لا تُطبّق هذه المعاملات** — مبالغ في ملاءمتها:")
        print("     خسرت (أو فقدت أكثر من نصف توقّعها) على بيانات لم ترها.")
        print("     هذا بالضبط ما يحدث عند اختيار الأفضل داخل العينة.")
        print("     الأفضل: حسّن **الإشارة** أو **نظام السوق**، لا الأرقام.")
        return

    if wf and not wf.get("consistent", True):
        print(f"  ⚠️  تحذير: رابحة في {wf.get('positive', 0)} فقط من "
              f"{wf.get('folds', 0)} نوافذ — نتيجة غير ثابتة.")
        print("     طبّقها بحجم صفقة صغير، وراقب أسبوعاً قبل الاعتماد.")

    print("  ✅ الوصفة (طبّقها بيدك في تليجرام):")
    for command in recipe(best):
        print(f"     {command}")
    print("\n  ثم أعد فحص النتيجة:")
    print(f"     scripts{chr(92)}backtest.py --strategy {strategy_key}")
    print(f"{line}\n")


# ═════════════════════════ الواجهة ═════════════════════════
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="مُحسِّن معاملات ستراتيج")
    parser.add_argument("--strategy", default="scalping_i",
                        choices=sorted(GRIDS), help="الاستراتيجية المطلوب تحسينها")
    parser.add_argument("--trials", type=int, default=30, help="عدد التركيبات المجرَّبة")
    parser.add_argument("--bars", type=int, default=900, help="طول كل سلسلة")
    parser.add_argument("--series", type=int, default=3, help="عدد السلاسل")
    parser.add_argument("--split", type=float, default=0.7,
                        help="نسبة بيانات التدريب (الباقي للتحقق)")
    parser.add_argument("--folds", type=int, default=0,
                        help="نوافذ المشي للأمام (0 = بلا، 3 = مُستحسن)")
    parser.add_argument("--min-trades", type=int, default=20,
                        help="أدنى عدد صفقات لاعتبار التركيبة ذات معنى")
    parser.add_argument("--delay", type=int, default=1, help="تأخير الدخول بالشموع")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--use-exits", action="store_true",
                        help="أدرج معاملات الوقف والهدف في البحث")
    parser.add_argument("--synthetic", action="store_true",
                        default=True, help="بيانات اصطناعية (افتراضي)")
    parser.add_argument("--regime", default="mixed", choices=("trend", "range", "mixed"))
    args = parser.parse_args(argv)

    grid = build_grid(args.strategy, use_exits=args.use_exits)

    rng = random.Random(args.seed)
    series: list[Candles] = []
    for index in range(args.series):
        regime = (args.regime if args.regime != "mixed"
                  else ("trend", "range")[index % 2])
        series.append(synthetic_series(args.bars, seed=args.seed + index,
                                       regime=regime))
    trains = []
    tests = []
    for candles in series:
        train, test = split_candles(candles, args.split)
        trains.append(train)
        tests.append(test)

    base_cfg = base_config(args.strategy)
    exit_mode = EXIT_MODE.get(args.strategy, "percent")
    print(f"  وضع المخارج: {exit_mode}"
          + ("  (مسافات ATR من الاستراتيجية)"
             if exit_mode == "atr" else "  (نسب ثابتة)"))

    print(f"\n  بيانات: {args.series} سلسلة × {args.bars} شمعة · "
          f"نظام: {args.regime}")
    print(f"  البحث: {args.trials} تركيبة على {len(grid)} معاملات · "
          f"التحقق على آخر {100 - int(args.split * 100)}% من كل سلسلة")
    print("  (قد يستغرق دقائق — كل محاولة تُعيد حساب الاستراتيجية شمعة بشمعة)")

    started = time.time()

    def progress(done: int, total: int) -> None:
        if done % 5 == 0 or done == total:
            print(f"    … {done}/{total}", flush=True)

    # الأساس: معاملاتك الحالية قبل أي تغيير — المرجع الذي نُقارن به
    base_train = evaluate(trains, base_cfg, args.strategy, {},
                          entry_delay=args.delay)
    base_test = evaluate(tests, base_cfg, args.strategy, {},
                         entry_delay=args.delay)
    baseline = {"train_r": base_train["expectancy_r"],
                "train_trades": base_train["trades"],
                "test_r": base_test["expectancy_r"],
                "test_trades": base_test["trades"]}

    ranked = search(trains, tests, base_cfg, args.strategy, grid,
                    trials=args.trials, min_trades=args.min_trades,
                    seed=args.seed, entry_delay=args.delay,
                    progress=progress)
    if not ranked:
        print("\n  ⛔ لم تُنتِج أي تركيبة صفقات كافية — قلّل --min-trades "
              "أو زد --bars.")
        return 1

    best = ranked[0]
    wf = {}
    if args.folds and args.folds >= 2:
        wf = walk_forward(series, base_cfg, args.strategy, best.params,
                          folds=args.folds, entry_delay=args.delay)

    report(best, baseline, wf, args.strategy, trials=args.trials)
    print(f"  الزمن: {time.time() - started:.0f} ثانية")
    return 0


if __name__ == "__main__":
    sys.exit(main())
