"""تجربة كاملة بدون مفاتيح ولا إنترنت.

يشغّل دورة فحص واحدة على بيانات اصطناعية ويطبع الرسائل التي
سيرسلها البوت إلى تليجرام بالضبط:

    .venv\Scripts\python.exe scripts\demo_scan.py     (ويندوز)
    .venv/bin/python scripts/demo_scan.py             (لينكس/ماك)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stratig.config import Config  # noqa: E402
from stratig.data import from_lists  # noqa: E402
from stratig.exchanges.base import (  # noqa: E402
    Balance,
    ExchangeBase,
    OrderResult,
    Position,
    SymbolInfo,
)
from stratig.services.notifier import Notifier  # noqa: E402
from stratig.services.trader import Trader  # noqa: E402


def synthetic(sign: int, seed: float = 1000.0):
    """سلسلة سعرية: هبوط طويل + انحدار حاد + استقرار + ارتداد."""
    closes: list[float] = []
    price = seed
    for _ in range(100):
        price -= 1.0 * sign
        closes.append(price)
    for _ in range(20):
        price -= 4.0 * sign
        closes.append(price)
    for _ in range(5):
        price -= 0.05 * sign
        closes.append(price)
    price += 15.0 * sign
    closes.append(price)

    highs = [c + abs(c) * 0.001 for c in closes]
    lows = [c - abs(c) * 0.001 for c in closes]
    return from_lists(closes, highs, lows)


class DemoExchange(ExchangeBase):
    """منصة وهمية تُرجع بيانات اصطناعية."""

    name = "demo-testnet"
    testnet = True

    def __init__(self):
        self.symbols = ["BULLUSDT", "BEARUSDT", "FLATUSDT"]
        self.data = {
            "BULLUSDT": synthetic(1),        # نمط قاع → إشارة شراء
            "BEARUSDT": synthetic(-1),       # نمط قمة → إشارة بيع
            "FLATUSDT": from_lists([100.0] * 200),   # سوق جانبي → لا إشارة
        }

    def klines(self, symbol, interval="15m", limit=500):
        return self.data[symbol]

    def mark_price(self, symbol):
        return float(self.data[symbol].close[-1])

    def symbol_info(self, symbol):
        return SymbolInfo(symbol, 2, 3, 0.01, 0.001, 0.001, 20)

    def usdt_symbols(self, top_n=40, exclude=()):
        return self.symbols[:top_n]

    def balance(self):
        return Balance(1000.0, 950.0, 0.0)

    def positions(self):
        return []

    def recent_pnl(self, limit=50, since_ms=None):
        return 0.0

    def open_market(self, symbol, side, qty_usdt, tp_pct, sl_pct, leverage=10,
                    margin_mode="isolated", tp_trigger="mark_price", min_notional=0.0):
        price = self.mark_price(symbol)
        print(f"   ↳ [منصة وهمية] أمر {side} على {symbol}: {qty_usdt} USDT @ {price:.2f}")
        return OrderResult(
            symbol, side, qty_usdt / price, price,
            tp_price=price * (1 + tp_pct) if side == "buy" else price * (1 - tp_pct),
            sl_price=price * (1 - sl_pct) if side == "buy" else price * (1 + sl_pct),
            notional=qty_usdt, simulated=True,
        )

    def close_position(self, symbol):
        return None


def main() -> int:
    cfg = Config(
        {
            "strategy": {"use_closed_candles": False},
            "scanner": {"symbols_source": "manual",
                        "manual_symbols": ["BULLUSDT", "BEARUSDT", "FLATUSDT"]},
            "safety": {"dry_run": True},
        },
        path=ROOT / "config.toml",
    )
    trader = Trader(cfg, DemoExchange())
    trader.attach_notifier(Notifier())   # يطبع في الطرفية بدل تليجرام

    print("═" * 60)
    print("1) الفحص الأول — نتوقع إشارتين (شراء + بيع)")
    print("═" * 60)
    found = asyncio.run(trader.scan_once(manual=True))
    for sig in found:
        print(f"\n--- إشارة {sig.id}: {sig.symbol} {sig.side} ---")
        print(trader._signal_text(sig))

    print("\n" + "═" * 60)
    print("2) محاكاة ضغطة ✅ فتح على الإشارة الأولى")
    print("═" * 60)
    if found:
        result = asyncio.run(trader.open_signal(found[0].id))
        if result:
            print(trader._opened_text(found[0]))

    print("\n" + "═" * 60)
    print("3) الفحص الثاني — لا يجب أن تتكرر الإشارات (فترة سمومية)")
    print("═" * 60)
    assert asyncio.run(trader.scan_once(manual=True)) == []
    print("✅ لا إشارات مكررة — النظام يعمل بشكل صحيح")
    return 0


if __name__ == "__main__":
    sys.exit(main())
