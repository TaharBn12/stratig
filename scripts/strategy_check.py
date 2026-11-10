"""يعرض قيم مؤشرات الاستراتيجية الحالية على بيانات حقيقية — للتحقق اليدوي.

    .venv\\Scripts\\python.exe scripts\\strategy_check.py BTCUSDT      (ويندوز)
    .venv/bin/python scripts/strategy_check.py BTCUSDT                (لينكس/ماك)
    .venv/bin/python scripts/strategy_check.py BTCUSDT --strategy scalping_i

يطبع كل مؤشر (EMA، بولينجر، ATR، RSI) وقيمته على آخر الشموع، ثم الإشارة
الناتجة وأسعار الوقف والهدف — لتقارنها مع TradingView سطراً بسطر.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stratig.config import Config, Secrets  # noqa: E402
from stratig.exchanges import build_exchange  # noqa: E402
from stratig.strategy.registry import all_strategies, get as get_strategy  # noqa: E402
from stratig.strategy.scalping_i import Params, ema_signal  # noqa: E402
from stratig.strategy.indicators import atr, bbands, ema, rsi  # noqa: E402

LINE = "═" * 70


def show(name: str, values: list[float], count: int = 3) -> None:
    text = []
    for offset in range(count, 0, -1):
        index = len(values) - offset
        if index < 0:
            continue
        value = values[index]
        text.append("—" if math.isnan(value) else f"{value:.6g}")
    print(f"  {name:<24} {'  '.join(text)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="فحص مؤشرات الاستراتيجية على بيانات حقيقية")
    parser.add_argument("symbol", nargs="?", default="")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--candles", type=int, default=0)
    args = parser.parse_args(argv)

    config = Config.load()
    secrets = Secrets.from_env()

    if args.strategy:
        config.set("strategy.name", args.strategy)
    strategy = get_strategy(config.get("strategy.name"))
    timeframe = str(config.get("strategy.timeframe", "15m"))
    limit = args.candles or int(config.get("strategy.candles", 500))

    print(LINE)
    print(f"  فحص الاستراتيجية: {strategy.title}")
    print(LINE)
    print(f"\n  المعرّف: {strategy.key}")
    print(f"  المصدر: {strategy.source}")
    print(f"  المخارج: {strategy.exit_mode}")

    try:
        exchange = build_exchange(config, secrets)
    except Exception as err:
        print(f"\n❌ {err}")
        return 1

    symbol = (args.symbol or "").strip().upper()
    if not symbol:
        try:
            symbol = (exchange.usdt_symbols(top_n=1) or ["BTCUSDT"])[0]
        except Exception:
            symbol = "BTCUSDT"

    try:
        candles = exchange.klines(symbol, timeframe, limit)
    except Exception as err:
        print(f"\n❌ تعذّر جلب الشموع لـ {symbol}: {err}")
        return 1

    print(f"\n  الرمز: {symbol} | الإطار: {timeframe} | عدد الشموع: {len(candles)}")

    if strategy.key == "scalping_i":
        params = Params(config)
        close = list(candles.close)
        high = list(candles.high)
        low = list(candles.low)

        slow = ema(close, params.ema_slow)
        fast = ema(close, params.ema_fast)
        lower, middle, upper = bbands(close, params.bb_length, params.bb_std, ddof=params.bb_ddof)
        atr_values = atr(high, low, close, params.atr_length, mode=params.atr_mode)
        rsi_values = rsi(close, params.rsi_length)
        index = len(close) - 1

        print(f"\n{LINE}")
        print("  المؤشرات (آخر 3 شموع)")
        print(LINE)
        show(f"EMA_fast ({params.ema_fast})", fast)
        show(f"EMA_slow ({params.ema_slow})", slow)
        show(f"BBL ({params.bb_length}, {params.bb_std:g})", lower)
        show(f"BBM", middle)
        print(f"  {'BBU':<24}", end="")
        print("  ".join(
            "—" if math.isnan(upper[len(upper) - o]) else f"{upper[len(upper) - o]:.6g}"
            for o in range(3, 0, -1)
        ))
        show(f"ATR ({params.atr_length})", atr_values)
        show(f"RSI ({params.rsi_length})", rsi_values)
        print(f"  {'Close':<24}", end="")
        print("  ".join(f"{close[len(close) - o]:.6g}" for o in range(3, 0, -1)))

        trend = ema_signal(fast, slow, index, params.backcandles)
        print(f"\n{LINE}")
        print("  الإشارة")
        print(LINE)
        print(f"\n  اتجاه EMA (آخر {params.backcandles} شموع قبل الحالية): "
              f"{ {2: 'صاعد (2)', 1: 'هابط (1)', 0: 'محايد (0)'}[trend] }")
        print(f"  الشمعة الحالية: الإغلاق {close[index]:.6g} | "
              f"الحد السفلي {lower[index]:.6g} | الحد العلوي {upper[index]:.6g}")

    decision = strategy.evaluate(
        candles, config, symbol=symbol,
        use_closed_candles=bool(config.get("strategy.use_closed_candles", True)),
    )
    print(f"\n  القرار: {decision.side or 'لا صفقة'}")
    if decision.lines:
        print()
        for line in decision.lines:
            print(f"  {line}")
    if decision.notes:
        print(f"\n  ملاحظات: {', '.join(decision.notes)}")
    if decision.stop_loss and decision.take_profit:
        price = decision.price
        print(f"\n  سعر الدخول : {price:.6g}")
        print(f"  وقف الخسارة: {decision.stop_loss:.6g}  (‑{abs(price - decision.stop_loss):.6g})")
        print(f"  جني الأرباح: {decision.take_profit:.6g}  (+{abs(decision.take_profit - price):.6g})")
        if decision.sl_distance:
            ratio = (decision.tp_distance or 0) / decision.sl_distance
            print(f"  العائد:المخاطرة = {ratio:.2f} : 1")

    print(f"\n{LINE}")
    print("  الاستراتيجيات المتاحة")
    print(LINE)
    for item in all_strategies():
        print(f"  • {item.key:<14} {item.title}")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
