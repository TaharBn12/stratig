"""اختبار أمامي (walk-forward) لكل الاستراتيجيات على شموع حقيقية.

    .venv\\Scripts\\python.exe scripts\\backtest.py
    .venv\\Scripts\\python.exe scripts\\backtest.py --symbols BTCUSDT,ETHUSDT --bars 1500
    .venv\\Scripts\\python.exe scripts\\backtest.py --strategy scalping_i --tf 15m
    .venv\\Scripts\\python.exe scripts\\backtest.py --synthetic        (بدون إنترنت)

السؤال الذي يجيب عنه: **هل الإشارة مقلوبة؟** «أعطاني شراء فهبط، وأعطاني بيعاً فصعد».

يقيس لكل استراتيجية:
  • متوسط العائد الأمامي بعد كل إشارة (شراء يجب أن يكون موجباً، وبيع سالباً)
  • نسبة النجاح مع الوقف والهدف الحقيقيين للاستراتيجية
  • التوقع (Expectancy) بوحدة R — إن كان سالباً بقوة فالإشارة **مقلوبة**
  • نفس القياس على إشارات **معكوسة** عمداً — للمقارنة (إن كان المعكوس أفضل
    فهناك خلل في الاتجاه فعلاً)
  • أثر تأخير الدخول: أداء الدخول عند الإغلاق / الشمعة التالية / بعد 3 شموع

لا يستخدم أي بيانات مستقبلية: عند كل شمعة i يُحسب القرار من الشموع 0..i فقط،
ثم يُنفَّذ الدخول على **افتتاح** الشمعة i+1.
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stratig.config import Config, Secrets  # noqa: E402
from stratig.data import Candles  # noqa: E402
from stratig.strategy.registry import (  # noqa: E402
    all_strategies,
    evaluate as registry_evaluate,
    get as get_strategy,
)

LINE = "═" * 74
FEE_PCT = 0.0005          # 0.05% taker — تُدفع عند الدخول والخروج


# ═══════════════════════ بيانات ═══════════════════════
def synthetic_series(n: int = 1500, seed: int = 11, regime: str = "trend") -> Candles:
    """سلسلة اصطناعية بنظام محدّد.

    trend : اتجاهات قوية كل 120 شمعة (مثل أسواق العملات الرقمية)
    range : تذبذب جانبي مع ارتداد (سوق بلا اتجاه)
    mixed : نصف ونصف
    """
    random.seed(seed)
    price = 30000.0
    drift = 0.0
    anchor = price
    times, opens, highs, lows, closes, vols = [], [], [], [], [], []
    for i in range(n):
        if regime == "trend":
            if i % 120 == 0:                   # نظام اتجاهي يتغيّر كل 120 شمعة
                drift = random.uniform(-0.0012, 0.0012)
        elif regime == "range":                # ارتداد نحو المتوسط
            drift = (math.log(anchor / price)) * 0.02
        else:
            if i % 240 < 120:
                if i % 120 == 0:
                    drift = random.uniform(-0.0012, 0.0012)
            else:
                drift = (math.log(anchor / price)) * 0.02
        vol = abs(random.gauss(0, 0.004)) + 0.0012
        open_ = price
        price *= (1 + drift + random.gauss(0, vol))
        close = price
        high = max(open_, close) * (1 + abs(random.gauss(0, vol * 0.5)))
        low = min(open_, close) * (1 - abs(random.gauss(0, vol * 0.5)))
        times.append(float(i))
        opens.append(open_)
        highs.append(high)
        lows.append(low)
        closes.append(close)
        vols.append(1.0)
    return Candles(times, opens, highs, lows, closes, vols)


def real_series(symbol: str, tf: str, bars: int, cfg: Config, secrets: Secrets):
    from stratig.exchanges import build_exchange

    exchange = build_exchange(cfg, secrets)
    return exchange.klines(symbol, tf, max(bars, 600))


# ═══════════════════════ المحاكاة ═══════════════════════
def exits_for(decision, cfg, side: str, price: float) -> tuple[float, float]:
    """(وقف، هدف) كنسب مئوية من سعر الدخول — حسب الاستراتيجية."""
    tp_pct = float(cfg.get("trade.take_profit_pct", 0.012))
    sl_pct = float(cfg.get("trade.stop_loss_pct", 0.009))
    mode = str(cfg.get("exit.mode", "percent")).lower()
    if mode == "atr" and decision.sl_distance and price:
        sl_pct = decision.sl_distance / price
        tp_pct = (decision.tp_distance or decision.sl_distance * 1.5) / price
    return sl_pct, tp_pct


def simulate(candles: Candles, side: str, entry: float, sl_pct: float,
             tp_pct: float, start: int, horizon: int = 60) -> tuple[str, float]:
    """يتتبع الشموع بعد الدخول: أيٌّ يُلمس أولاً؟ يُرجع (النتيجة، العائد بنسبة R)."""
    if side == "buy":
        tp = entry * (1 + tp_pct)
        sl = entry * (1 - sl_pct)
    else:
        tp = entry * (1 - tp_pct)
        sl = entry * (1 + sl_pct)
    for i in range(start, min(len(candles), start + horizon)):
        high, low = candles.high[i], candles.low[i]
        hit_sl = (low <= sl) if side == "buy" else (high >= sl)
        hit_tp = (high >= tp) if side == "buy" else (low <= tp)
        if hit_sl and hit_tp:
            return "sl", -1.0          # شمعة واحدة لمست الاثنين → نفترض الأسوأ
        if hit_sl:
            return "sl", -1.0
        if hit_tp:
            return "tp", tp_pct / sl_pct
    last = candles.close[min(len(candles) - 1, start + horizon - 1)]
    raw = (last - entry) / entry * (1 if side == "buy" else -1)
    return "open", raw / sl_pct


def forward_return(candles: Candles, side: str, entry_price: float,
                   start: int, bars: int) -> float:
    """العائد بعد `bars` شموع — بلا وقف ولا هدف (مقياس الاتجاه الصرف)."""
    end = min(len(candles) - 1, start + bars)
    last = candles.close[end]
    change = (last - entry_price) / entry_price
    return change if side == "buy" else -change


def run(candles: Candles, cfg: Config, strategy_key: str, use_closed: bool = False,
        entry_delay: int = 1, inverted: bool = False, horizon: int = 60) -> dict:
    """يمشي على الشموع ويجمع إشارات الاستراتيجية — بلا أي نظرة للمستقبل."""
    strategy = get_strategy(strategy_key)
    fwd3, trades, sides = [], [], []
    min_bars = strategy.min_candles + 5

    for i in range(min_bars, len(candles) - entry_delay - 1):
        window = candles.slice(0, i + 1)
        decision = registry_evaluate(      # يمرّ عبر السجل (ومعه فلتر الاتجاه)
            strategy.key, window, cfg, symbol="BT", use_closed_candles=use_closed
        )
        if not decision.has_signal:
            continue
        side = decision.side
        if inverted:
            side = "sell" if side == "buy" else "buy"
        # delay=0 → الدخول عند **إغلاق** شمعة الإشارة (أسرع دخول ممكن في الواقع)
        # delay=n → الدخول عند افتتاح الشمعة n بعدها (تأخّر n شمعة)
        entry = candles.close[i] if entry_delay == 0 else candles.open[i + entry_delay]
        sl_pct, tp_pct = exits_for(decision, cfg, side, entry)
        if sl_pct <= 0:
            continue
        outcome, r = simulate(candles, side, entry, sl_pct, tp_pct,
                              i + max(entry_delay, 1), horizon)
        sl_pct_net = sl_pct + 2 * FEE_PCT / 1.0        # تكلفة تقريبية من مسافة الوقف
        trades.append(r - (2 * FEE_PCT) / sl_pct)
        fwd3.append(forward_return(candles, side, entry, i + entry_delay, 3))
        sides.append(side)

    if not trades:
        return {"trades": 0}

    wins = [t for t in trades if t > 0]
    mean_fwd = statistics.fmean(fwd3) if fwd3 else 0.0
    return {
        "trades": len(trades),
        "win_rate": 100.0 * len(wins) / len(trades),
        "expectancy_r": statistics.fmean(trades),
        "total_r": sum(trades),
        "fwd3": mean_fwd,
        "fwd3_buy": statistics.fmean([f for f, s in zip(fwd3, sides) if s == "buy"])
        if any(s == "buy" for s in sides) else 0.0,
        "fwd3_sell": statistics.fmean([f for f, s in zip(fwd3, sides) if s == "sell"])
        if any(s == "sell" for s in sides) else 0.0,
        "buy": sides.count("buy"),
        "sell": sides.count("sell"),
        "rr": (tp_pct / sl_pct) if sl_pct else 0.0,
        "fee_r": (2 * FEE_PCT) / sl_pct,
    }


def show(name: str, result: dict) -> None:
    if not result.get("trades"):
        print(f"  {name:<34} — لا إشارات كافية")
        return
    flag = "✅" if result["expectancy_r"] > 0 else "❌"
    print(
        f"  {flag} {name:<32} صفقات={result['trades']:<4} "
        f"نجاح={result['win_rate']:5.1f}%  "
        f"توقع={result['expectancy_r']:+.3f}R  "
        f"المجموع={result['total_r']:+7.2f}R"
    )
    print(
        f"     {'':<32} عائد 3 شموع: بعد شراء {result['fwd3_buy']*100:+.3f}% | "
        f"بعد بيع {result['fwd3_sell']*100:+.3f}%"
    )
    rr = result.get("rr", 0.0)
    fee = result.get("fee_r", 0.0)
    if rr:
        breakeven = 100.0 / (1.0 + rr)
        print(
            f"     {'':<32} عائد:مخاطرة={rr:.2f} · نجاح التعادل={breakeven:.0f}% · "
            f"تكلفة العمولة={fee:.2f}R"
        )
        if fee > 0.2:
            print(
                f"     {'':<32} ⚠️  العمولة تأكل {fee/1:.0%} من مسافة الوقف — "
                "الوقف ضيّق جداً لهذا الإطار"
            )


def verdict(normal: dict, inverted: dict) -> str:
    if not normal.get("trades"):
        return "  ⚠️  لا إشارات كافية للحكم — زد عدد الشموع أو جدّد البيانات."
    lines = []
    buy_ok = normal["fwd3_buy"] > 0
    sell_ok = normal["fwd3_sell"] > 0
    if buy_ok and sell_ok:
        lines.append("  ✅ الاتجاه سليم: بعد الشراء يميل السعر صعوداً وبعد البيع هبوطاً.")
    elif not buy_ok and not sell_ok:
        lines.append(
            "  ❌ **الإشارة مقلوبة**: بعد الشراء يهبط السعر وبعد البيع يصعد.\n"
            "     هذا يعني انعكاساً في منطق الاتجاه — بلّغ عنه فوراً."
        )
    else:
        lines.append(
            "  ⚠️  الاتجاه سليم جزئياً: " +
            ("الشراء يعمل والبيع لا." if buy_ok else "البيع يعمل والشراء لا.")
        )
    if inverted.get("trades"):
        if inverted["expectancy_r"] > normal["expectancy_r"] + 0.02:
            lines.append(
                f"  ❌ الإشارات **المعكوسة** أفضل ({inverted['expectancy_r']:+.3f}R "
                f"مقابل {normal['expectancy_r']:+.3f}R) — الخلل في الاتجاه مؤكّد."
            )
        else:
            lines.append("  ✅ الإشارات المعكوسة أسوأ — لا يوجد انعكاس في الاتجاه.")
    if normal["expectancy_r"] < 0 and inverted.get("trades") and \
            inverted["expectancy_r"] <= normal["expectancy_r"] + 0.02:
        lines.append(
            "  ⚠️  التوقع سالب لكن بلا انعكاس — السبب على الأرجح: تأخير الدخول،\n"
            "     أو حجم هدف/وقف لا يناسب الإطار، أو سوق بلا اتجاه."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="اختبار أمامي لكل الاستراتيجيات")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--tf", default="15m")
    parser.add_argument("--bars", type=int, default=1500)
    parser.add_argument("--delay", type=int, default=1, help="تأخير الدخول بالشموع (0/1/3)")
    parser.add_argument("--synthetic", action="store_true", help="بيانات اصطناعية بلا إنترنت")
    parser.add_argument("--series", type=int, default=3, help="عدد السلاسل الاصطناعية")
    parser.add_argument("--regime", default="trend", choices=("trend", "range", "mixed"),
                        help="نظام السوق الاصطناعي: اتجاهي / جانبي / مختلط")
    parser.add_argument("--trend-filter", action="store_true",
                        help="فعّل فلتر الاتجاه (strategy.trend_filter=ema)")
    parser.add_argument("--quality", action="store_true",
                        help="فعّل فلاتر الجودة (ADX/تقلّب)")
    parser.add_argument("--adx-regime", default="", choices=("", "trend", "range"),
                        help="نظام السوق المسموح مع --quality")
    args = parser.parse_args(argv)

    cfg = Config.load()
    if args.trend_filter:
        cfg.set("strategy.trend_filter", "ema")
        print("  فلتر الاتجاه: مُفعّل (EMA 200)")
    if args.quality:
        cfg.set("strategy.quality_enabled", True)
        if args.adx_regime:
            cfg.set("strategy.regime", args.adx_regime)
        print(f"  فلاتر الجودة: مُفعّلة (نظام: {args.adx_regime or 'الكل'})")
    keys = [args.strategy] if args.strategy else [s.key for s in all_strategies()]

    print(LINE)
    print("  اختبار أمامي — هل الإشارة مقلوبة؟")
    print(LINE)
    print(f"\n  الإطار: {args.tf} | تأخير الدخول: {args.delay} شمعة | "
          f"العمولة: {FEE_PCT*100:.2f}% لكل جهة")

    series = []
    if args.synthetic:
        print(f"  البيانات: اصطناعية ({args.series} سلسلة، نظام: {args.regime})")
        total = max(1, args.series)
        series = [
            (f"SYNTH-{k+1}", synthetic_series(args.bars, seed=11 + 17 * k, regime=args.regime))
            for k in range(total)
        ]
    else:
        secrets = Secrets.from_env()
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        for symbol in symbols:
            try:
                candles = real_series(symbol, args.tf, args.bars, cfg, secrets)
                if len(candles) > 200:
                    series.append((symbol, candles))
                    print(f"  ✅ {symbol}: {len(candles)} شمعة")
                else:
                    print(f"  ⚠️  {symbol}: {len(candles)} شمعة فقط — تُخطّى")
            except Exception as err:
                print(f"  ❌ {symbol}: {err}")
    if not series:
        print("\n  لا توجد بيانات. استخدم --synthetic أو تحقّق من المفاتيح.")
        return 1

    original = cfg.get("strategy.name")
    for key in keys:
        cfg.set("strategy.name", key)
        strategy = get_strategy(key)
        cfg.set("exit.mode", strategy.exit_mode)
        print(f"\n{LINE}\n  🧠 {strategy.title} ({key})\n{LINE}")

        agg = {"n": 0, "win": 0.0, "r": 0.0, "buy": 0.0, "sell": 0.0, "trades": 0}
        inv = {"n": 0, "r": 0.0, "trades": 0}
        for name, candles in series:
            normal = run(candles, cfg, key, entry_delay=args.delay)
            if normal.get("trades"):
                agg["n"] += 1
                agg["trades"] += normal["trades"]
                agg["win"] += normal["win_rate"]
                agg["r"] += normal["expectancy_r"]
                agg["buy"] += normal["fwd3_buy"]
                agg["sell"] += normal["fwd3_sell"]
            inverted = run(candles, cfg, key, entry_delay=args.delay, inverted=True)
            if inverted.get("trades"):
                inv["n"] += 1
                inv["trades"] += inverted["trades"]
                inv["r"] += inverted["expectancy_r"]
            show(f"{name}", normal)

        if agg["n"]:
            summary = {
                "trades": agg["trades"],
                "win_rate": agg["win"] / agg["n"],
                "expectancy_r": agg["r"] / agg["n"],
                "total_r": agg["r"],
                "fwd3_buy": agg["buy"] / agg["n"],
                "fwd3_sell": agg["sell"] / agg["n"],
            }
            inverted_summary = {
                "trades": inv["trades"],
                "rr": summary.get("rr", 0.0),
                "fee_r": summary.get("fee_r", 0.0),
                "win_rate": 0.0,
                "expectancy_r": (inv["r"] / inv["n"]) if inv["n"] else 0.0,
                "total_r": inv["r"],
                "fwd3_buy": 0.0,
                "fwd3_sell": 0.0,
            }
            if not inv["n"]:
                inverted_summary = {"trades": 0}
            print(f"\n  ── الملخص ({agg['n']} سلسلة) ──")
            show("الإجمالي", summary)
            show("الإشارات المعكوسة (للمقارنة)", inverted_summary)
            print()
            print(verdict(summary, inverted_summary))

        # أثر تأخير الدخول
        print(f"\n  ── أثر تأخير الدخول ({series[0][0]}) ──")
        for delay in (0, 1, 3, 6):
            result = run(series[0][1], cfg, key, entry_delay=delay)
            if result.get("trades"):
                label = {0: "عند إغلاق شمعة الإشارة", 1: "افتتاح الشمعة التالية",
                         3: "بعد 3 شموع", 6: "بعد 6 شموع"}[delay]
                show(label, result)

    cfg.set("strategy.name", original)
    print(f"\n{LINE}")
    print("  ملاحظة: سلسلة عشوائية بلا اتجاه تُعطي توقعاً ≈ 0 — هذا طبيعي.")
    print("  المهم ألا يكون التوقع سالباً بقوة، ولا يكون المعكوس أفضل من الأصلي.")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
