"""دراسة حقيقية للشموع — على **بيانات السوق الحقيقية** لا الاصطناعية.

    python scripts/candle_study.py --symbols BTCUSDT,ETHUSDT --tf 1h --bars 5000
    python scripts/candle_study.py --synthetic            # تجربة بلا إنترنت

لماذا البيانات الحقيقية؟
    مولّد البيانات الاصطناعية في `backtest.py` يبني النطاق الجانبي
    كعملية **مرتدّة إلى المتوسط** بالبناء (`drift = log(anchor/price) × 0.02`)،
    أي أنه يُكافئ استراتيجيات الارتداد ميكانيكياً. كل نتيجة عليه متحيّزة.

ماذا تجيب الدراسة؟
    1. الارتباط الذاتي: هل السوق يرتدّ أم يستمرّ أم يسير عشوائياً؟
    2. تشريح الشمعة: أصغر وقف ممكن قبل أن يبتلعه الضجيج
    3. الأنماط: هل لأي نمط شمعة قيمة؟ (مع تصحيح بونفيروني)

ملاحظة: يجلب من نقطة Binance **العامة** للبيانات (`fapi.binance.com`) فلا
تحتاج مفاتيح — لأن الدراسة تريد بيانات السوق الحقيقي لا التيستنت.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.data import Candles                       # noqa: E402
from stratig.study import (                            # noqa: E402
    DIRECTIONAL_PATTERNS,
    PATTERN_TITLES,
    bonferroni_z as _unused,                           # noqa: F401
    merge,
    study,
)
from stratig.edge import bonferroni_z                  # noqa: E402
from scripts.backtest import synthetic_series          # noqa: E402

KLINES = "https://fapi.binance.com/fapi/v1/klines"
TESTNET_KLINES = "https://testnet.binancefuture.com/fapi/v1/klines"
MAX_LIMIT = 1500


# ═══════════════════════ جلب البيانات ═══════════════════════
def fetch_klines(symbol: str, interval: str, bars: int,
                 testnet: bool = False, verbose: bool = True) -> Candles:
    """يجلب شموعاً حقيقية من نقطة Binance العامة (بلا مفاتيح)."""
    base = TESTNET_KLINES if testnet else KLINES
    rows: list[list] = []
    end: int | None = None
    remaining = int(bars)

    while remaining > 0:
        limit = min(MAX_LIMIT, remaining)
        params = f"symbol={symbol.upper()}&interval={interval}&limit={limit}"
        if end:
            params += f"&endTime={end}"
        url = f"{base}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                chunk = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise SystemExit(
                f"❌ تعذّر جلب {symbol} ({err.code}). تأكد من الرمز والإطار.")
        except Exception as err:
            raise SystemExit(
                f"❌ تعذّر الاتصال بـ Binance: {err}\n"
                "   (الدراسة تحتاج إنترنت — أو جرّب --synthetic للتجربة)")
        if not chunk:
            break
        rows = list(chunk) + rows
        remaining -= len(chunk)
        end = int(chunk[0][0]) - 1
        if len(chunk) < limit:
            break
        time.sleep(0.25)                    # احترام حدود المعدّل

    if not rows:
        raise SystemExit(f"❌ لا توجد شموع لـ {symbol}")

    times = [float(row[0]) for row in rows]
    opens = [float(row[1]) for row in rows]
    highs = [float(row[2]) for row in rows]
    lows = [float(row[3]) for row in rows]
    closes = [float(row[4]) for row in rows]
    vols = [float(row[5]) for row in rows]
    if verbose:
        print(f"  ✅ {symbol}: {len(rows)} شمعة")
    return Candles(times, opens, highs, lows, closes, vols)


# ═══════════════════════ التقرير ═══════════════════════
def _pct(value: float) -> str:
    return f"{value * 100:.4f}%"


def report(result, horizon: int, min_trades: int, elapsed: float = 0.0) -> None:
    line = "─" * 74
    print(f"\n{line}")
    print(f"  🔬 دراسة الشموع — {result.symbol or '?'} · {result.timeframe or '?'}"
          f" · {result.bars} شمعة")
    print(line)

    # ── 1) التشريح ──
    a = result.anatomy
    print("\n  1) تشريح الشمعة (كنسبة من سعرها)")
    print(f"     الجسم          {_pct(a.body_pct)}")
    print(f"     الفتيل العلوي  {_pct(a.upper_wick_pct)}")
    print(f"     الفتيل السفلي  {_pct(a.lower_wick_pct)}")
    print(f"     المدى الكامل   {_pct(a.range_pct)}")
    print(f"     نسبة الصاعدة   {a.bull_ratio:.1f}%")
    print(f"     ⚠️ وقف أضيق من المدى الكامل ({_pct(a.range_pct)}) يبتلعه"
          " ضجيج شمعة واحدة")

    # ── 2) الارتباط الذاتي ──
    print("\n  2) الارتباط الذاتي للعوائد — هل السوق يرتدّ أم يستمرّ؟")
    print(f"     {'الفاصل':<8}{'القيمة':>10}{'العتبة':>10}   {'الدلالة':<10}النوع")
    for lag, info in sorted(result.autocorr.items()):
        mark = "مهم ✅" if info["significant"] else "—"
        print(f"     lag {lag:<4}{info['value']:>+10.4f}{info['threshold']:>10.4f}"
              f"   {mark:<10}{info['kind']}")
    print(f"\n     الحكم: {result.verdict}")

    # ── 3) الأنماط ──
    print(f"\n  3) اختبار الأنماط (العائد بعد {horizon} شموع · "
          f"بتصحيح بونفيروني z={bonferroni_z(len(DIRECTIONAL_PATTERNS)):.2f})")
    print(f"     {'النمط':<26}{'عدد':>6}{'العائد':>11}{'النجاح':>8}   الحكم")
    rows = [(n, s) for n, s in result.patterns.items()]
    rows.sort(key=lambda kv: kv[1].expectancy_r, reverse=True)
    for name, stats in rows:
        title = PATTERN_TITLES.get(name, name)
        if stats.trades == 0:
            print(f"     {title:<26}{0:>6}{'—':>11}{'—':>8}   —")
            continue
        flag = {"رابحة": "✅", "خاسرة": "⛔", "غير حاسمة": "⚖️",
                "لا بيانات كافية": "…"}.get(stats.verdict, "•")
        print(f"     {title:<26}{stats.trades:>6}{stats.expectancy_r * 100:>+10.4f}%"
              f"{stats.win_rate:>7.1f}%   {flag} {stats.verdict}")

    best = result.best_pattern
    if best:
        name, stats = best
        print(f"\n     🏆 أقوى نمط: {PATTERN_TITLES.get(name, name)} — "
              f"{stats.trades} صفقة · {stats.expectancy_r * 100:+.4f}% "
              f"· بين {stats.lower_r * 100:+.4f}% و {stats.upper_r * 100:+.4f}%")
    else:
        print("\n     ❌ لا نمط واحد صمد أمام تصحيح بونفيروني.")

    # ── 4) التقلّب ──
    if result.volatility:
        print("\n  4) التقلّب بعد الأنماط بلا جهة")
        for name, info in result.volatility.items():
            ratio = info["ratio"]
            flag = "⚡ تقلّب أعلى" if ratio > 1.15 else (
                "😴 تقلّب أقل" if ratio < 0.85 else "≈ كالمعتاد")
            print(f"     {PATTERN_TITLES.get(name, name):<26}"
                  f"{info['count']:>6}   ×{ratio:.2f}   {flag}")

    # ── الخلاصة ──
    print(f"\n{line}")
    print("  📌 الخلاصة")
    print(f"     • {result.verdict}")
    print(f"     • أصغر وقف معقول ≈ {_pct(result.min_stop_pct)} "
          "(مدى الشمعة الواحدة)")
    if best:
        name, stats = best
        print(f"     • النمط الوحيد المدعوم إحصائياً: "
              f"{PATTERN_TITLES.get(name, name)}")
        print("       (تذكّر: العائد المذكور **إجمالي** — اطرح عمولة الدخول"
              " والخروج قبل الحكم)")
    else:
        print("     • لا يوجد نمط شمعة مدعوم إحصائياً على هذه البيانات.")
        print("       الاستراتيجية يجب أن تعتمد على **النظام** (اتجاه/نطاق)")
        print("       و**إدارة المخاطر**، لا على شكل الشمعة.")
    if elapsed:
        print(f"\n  الزمن: {elapsed:.1f} ثانية")
    print(f"{line}\n")


# ═══════════════════════ الواجهة ═══════════════════════
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="دراسة حقيقية للشموع")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT")
    parser.add_argument("--tf", default="1h")
    parser.add_argument("--bars", type=int, default=5000)
    parser.add_argument("--horizon", type=int, default=3,
                        help="بعد كم شمعة نقيس العائد؟")
    parser.add_argument("--min-trades", type=int, default=30)
    parser.add_argument("--testnet", action="store_true",
                        help="استخدم بيانات التيستنت (غير مُستحسن للدراسة)")
    parser.add_argument("--synthetic", action="store_true",
                        help="بيانات اصطناعية للتجربة بلا إنترنت")
    parser.add_argument("--regime", default="range", choices=("trend", "range", "mixed"))
    parser.add_argument("--json", default="", help="احفظ النتيجة في ملف JSON")
    args = parser.parse_args(argv)

    started = time.time()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    if args.synthetic:
        print("\n  ⚠️ بيانات اصطناعية — للتحقّق من الأداة فقط، "
              "ولا يصحّ الاستنتاج منها.")
        results = []
        for index, symbol in enumerate(symbols):
            regime = args.regime if args.regime != "mixed" else (
                "trend", "range")[index % 2]
            candles = synthetic_series(args.bars, seed=11 + index * 7, regime=regime)
            results.append(study(candles, symbol, args.tf, args.horizon,
                                 args.min_trades))
    else:
        print(f"\n  جلب شموع حقيقية من Binance ({args.tf})…")
        results = []
        for symbol in symbols:
            candles = fetch_klines(symbol, args.tf, args.bars, args.testnet)
            results.append(study(candles, symbol, args.tf, args.horizon,
                                 args.min_trades))

    merged = merge(results, args.min_trades) if len(results) > 1 else results[0]
    report(merged, args.horizon, args.min_trades, time.time() - started)

    if args.json:
        payload = {
            "symbol": merged.symbol,
            "timeframe": merged.timeframe,
            "bars": merged.bars,
            "anatomy": merged.anatomy.__dict__,
            "autocorr": merged.autocorr,
            "patterns": {name: stats.__dict__
                         for name, stats in merged.patterns.items()},
            "volatility": merged.volatility,
            "verdict": merged.verdict,
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  💾 حُفظت النتيجة في {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
