"""اختبار قاطع: هل يحلّل البوت بيانات حقيقية من المنصة أم بيانات اصطناعية؟

هذا الاختبار يعترض طبقة HTTP الخاصة بمكتبة بينانس ويتأكد أن:
1) المحرّك يطلب الشموع فعلياً من عميل المنصة (client.klines)
2) لا توجد أي بيانات اصطناعية في مسار التشغيل الفعلي (main.py)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config  # noqa: E402
from stratig.exchanges.binance_futures import BinanceFutures  # noqa: E402
from stratig.services.trader import Trader  # noqa: E402


class RecordingClient:
    """عميل وهمي يسجّل الطلبات بدل إرسالها للإنترنت."""

    def __init__(self, close_price: float = 30000.0):
        self.close_price = close_price
        self.requests: list[tuple] = []

    def klines(self, symbol, interval, limit=500, **kwargs):
        self.requests.append(("klines", symbol, interval, limit))
        # صف يبدأ بالوقت ثم O/H/L/C/V/Turnover — كما ترجعه بينانس
        return [
            [1_700_000_000_000 + i * 900_000, "10", "11", "9", str(self.close_price), "100", "1000"]
            for i in range(limit)
        ]

    def mark_price(self, symbol=None, **kwargs):
        return {"markPrice": str(self.close_price)}

    def ticker_24hr_price_change(self):
        return [{"symbol": "BTCUSDT", "quoteVolume": "1000"}]

    def exchange_info(self):
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "pricePrecision": 2,
                    "quantityPrecision": 3,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "20"},
                    ],
                }
            ]
        }

    def get_position_risk(self, **kwargs):
        return []

    def balance(self, **kwargs):
        return [{"asset": "USDT", "balance": "1000", "availableBalance": "900", "crossUnPnl": "0"}]


def test_runtime_fetches_candles_from_exchange_client():
    """المحرّك يجب أن يطلب الشموع من عميل المنصة فعلياً."""
    exchange = BinanceFutures("key", "secret", testnet=True)
    client = RecordingClient()
    exchange.client = client

    cfg = Config(
        {"scanner": {"symbols_source": "manual", "manual_symbols": ["BTCUSDT"]}},
        path=Path("config.toml"),
    )
    trader = Trader(cfg, exchange)
    asyncio.run(trader.scan_once(manual=True))

    assert client.requests, "لم يتم طلب أي شموع من المنصة!"
    kind, symbol, interval, limit = client.requests[0]
    assert kind == "klines"
    assert symbol == "BTCUSDT"
    assert interval == cfg.get("strategy.timeframe")
    assert limit == cfg.get("strategy.candles")
    assert trader.last_scan_symbols == 1


def test_strategy_reads_values_returned_by_exchange():
    """القيم التي تُحلَّل هي نفسها القادمة من المنصة (لا تُستبدل)."""
    exchange = BinanceFutures("key", "secret", testnet=True)
    client = RecordingClient(close_price=1234.5)
    exchange.client = client

    candles = exchange.klines("BTCUSDT", "15m", 500)
    assert len(candles) == 500
    assert candles.close[-1] == 1234.5          # نفس السعر الذي أعادته المنصة
    assert candles.times[-1] > candles.times[0]  # مرتّبة تصاعدياً


def test_no_synthetic_data_in_runtime_modules():
    """لا يجوز أن يستورد مسار التشغيل أي باني بيانات اصطناعية."""
    import stratig.data as data
    import stratig.services.trader as trader_mod
    import stratig.strategy.engine as engine_mod

    sources = []
    for module in (trader_mod, engine_mod):
        src = Path(module.__file__).read_text(encoding="utf-8")
        sources.append(src)

    for src in sources:
        assert "from_lists" not in src
        assert "synthetic" not in src.lower()

    # الباني الاصطناعي موجود فقط كأداة للاختبارات والعرض التوضيحي
    assert hasattr(data, "from_lists")


def test_demo_script_is_the_only_place_using_synthetic_exchange():
    """المنصة الوهمية (DemoExchange) لا تُستخدم إلا في سكربت العرض."""
    demo = Path("scripts/demo_scan.py").read_text(encoding="utf-8")
    assert "DemoExchange" in demo
    for runtime_file in ("main.py", "stratig/services/trader.py", "stratig/bot/telegram_bot.py"):
        src = Path(runtime_file).read_text(encoding="utf-8")
        assert "DemoExchange" not in src, f"{runtime_file} يستخدم منصة وهمية!"
        assert "demo_scan" not in src
