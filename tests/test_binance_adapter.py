"""اختبارات محوّل Binance باستخدام عميل وهمي (بدون اتصال بالإنترنت)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.exchanges.base import ExchangeError  # noqa: E402
from stratig.exchanges.binance_futures import BinanceFutures  # noqa: E402

EXCHANGE_INFO = {
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
                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "20"},
            ],
        },
        {
            "symbol": "ETHUSDT",
            "status": "TRADING",
            "quoteAsset": "USDT",
            "contractType": "PERPETUAL",
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"},
                {"filterType": "MIN_NOTIONAL", "notional": "20"},
            ],
        },
        {
            "symbol": "BTCUSDT_250328",
            "status": "TRADING",
            "quoteAsset": "USDT",
            "contractType": "CURRENT_QUARTER",   # عقد ربعي — يجب استبعاده
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "filters": [],
        },
    ]
}

TICKERS = [
    {"symbol": "BTCUSDT", "quoteVolume": "1000"},
    {"symbol": "ETHUSDT", "quoteVolume": "5000"},
    {"symbol": "BTCUSDT_250328", "quoteVolume": "99999"},
]


class FakeClient:
    """يحاكي binance.um_futures.UMFutures ويسجّل كل نداء."""

    def __init__(self, price: float = 30000.0, fail_stop_loss: bool = False):
        self.price = price
        self.fail_stop_loss = fail_stop_loss
        self.calls: list[tuple] = []
        self.amounts = {"BTCUSDT": "0", "ETHUSDT": "-2"}   # positionAmt لكل رمز

    # بيانات السوق
    def exchange_info(self):
        return EXCHANGE_INFO

    def ticker_24hr_price_change(self):
        return TICKERS

    def mark_price(self, symbol=None, **kwargs):
        return {"symbol": symbol, "markPrice": str(self.price)}

    def klines(self, symbol, interval, limit=500, **kwargs):
        # Binance: الأقدم أولاً
        return [[1000 + i * 60_000, "10", "11", "9", "10.5", "100", "1000"] for i in range(limit)]

    # الحساب
    def balance(self, **kwargs):
        return [
            {"asset": "USDT", "balance": "1000.0", "availableBalance": "950.0", "crossUnPnl": "5.0"},
            {"asset": "BNB", "balance": "1.0", "availableBalance": "1.0", "crossUnPnl": "0"},
        ]

    def get_position_risk(self, **kwargs):
        def row(symbol, amt, entry, mark, lev, margin, pnl="0"):
            return {"symbol": symbol, "positionAmt": amt, "entryPrice": entry,
                    "markPrice": mark, "unRealizedProfit": pnl, "leverage": lev,
                    "marginType": margin}
        return [
            row("BTCUSDT", self.amounts["BTCUSDT"], "30000", "30000", "10", "isolated"),
            row("ETHUSDT", self.amounts["ETHUSDT"], "2000", "1900", "5", "cross", pnl="200"),
        ]

    def get_income_history(self, **kwargs):
        self.calls.append(("get_income_history", kwargs))
        return [{"income": "1.5"}, {"income": "-0.5"}]

    # الأوامر
    def get_position_mode(self, **kwargs):
        return {"dualSidePosition": False}

    def change_leverage(self, symbol, leverage, **kwargs):
        self.calls.append(("change_leverage", symbol, leverage))

    def change_margin_type(self, symbol, marginType, **kwargs):
        self.calls.append(("change_margin_type", symbol, marginType))

    def new_order(self, symbol, side, type, **kwargs):
        self.calls.append(("new_order", symbol, side, type, kwargs))
        if self.fail_stop_loss and type == "STOP_MARKET":
            raise RuntimeError("boom")
        if type == "MARKET" and not kwargs.get("reduceOnly"):
            # فتح صفقة جديدة: نسجّل الكمية حتى يراها get_position_risk
            qty = float(kwargs.get("quantity", 0))
            self.amounts[symbol] = f"{qty}" if side == "BUY" else f"{-qty}"
        if type == "MARKET" and kwargs.get("reduceOnly"):
            self.amounts[symbol] = "0"
        return {"orderId": 12345, "avgPrice": "0", "status": "FILLED"}

    def query_order(self, symbol, orderId, **kwargs):
        self.calls.append(("query_order", symbol, orderId))
        return {"orderId": orderId, "avgPrice": str(self.price)}

    def cancel_open_orders(self, symbol, **kwargs):
        self.calls.append(("cancel_open_orders", symbol))

    def reset_positions(self):
        self.amounts = {"BTCUSDT": "0", "ETHUSDT": "-2"}


def make_exchange(**kwargs) -> BinanceFutures:
    ex = BinanceFutures("key", "secret", testnet=True)
    ex.client = FakeClient(**kwargs)
    return ex


# ═══════════════════════ البيانات ═══════════════════════
def test_symbol_filters_parsed():
    ex = make_exchange()
    info = ex.symbol_info("BTCUSDT")
    assert info.price_precision == 2
    assert info.qty_precision == 3
    assert info.step_size == 0.001
    assert info.min_notional == 20.0
    assert info.tick_size == pytest.approx(0.1)


def test_usdt_symbols_filters_and_ranks_by_volume():
    ex = make_exchange()
    symbols = ex.usdt_symbols(top_n=10)
    assert "BTCUSDT_250328" not in symbols      # العقود الربعيه مستبعدة
    assert symbols[0] == "ETHUSDT"              # الأعلى حجماً أولاً


def test_usdt_symbols_excludes_blocked():
    ex = make_exchange()
    assert ex.usdt_symbols(top_n=10, exclude=("ETHUSDT",)) == ["BTCUSDT"]


def test_klines_are_oldest_first():
    ex = make_exchange()
    df = ex.klines("BTCUSDT", "15m", 10)
    assert len(df) == 10
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume", "Turnover"]
    assert df.index[0] < df.index[-1]           # آخر صف = أحدث شمعة


def test_balance_parses_usdt():
    bal = make_exchange().balance()
    assert bal.total == 1000.0
    assert bal.available == 950.0
    assert bal.unrealized == 5.0


def test_positions_only_open_ones():
    positions = make_exchange().positions()
    assert [p.symbol for p in positions] == ["ETHUSDT"]
    assert positions[0].side == "sell"           # positionAmt سالب = شورت
    assert positions[0].size == 2
    assert positions[0].notional == 3800.0
    assert positions[0].roe_pct == pytest.approx(200 / (3800 / 5) * 100)


def test_recent_pnl_sums_income():
    ex = make_exchange()
    assert ex.recent_pnl(limit=2) == 1.0
    assert ex.recent_pnl(limit=2, since_ms=1700000000000) == 1.0
    assert ("get_income_history",) [0] in [c[0] for c in ex.client.calls]


# ═══════════════════════ التنفيذ ═══════════════════════
def test_open_market_places_entry_tp_and_sl():
    ex = make_exchange()
    result = ex.open_market("BTCUSDT", "buy", 60, 0.012, 0.009, leverage=10, margin_mode="isolated")

    kinds = [c for c in ex.client.calls if c[0] == "new_order"]
    assert [c[3] for c in kinds] == ["MARKET", "TAKE_PROFIT_MARKET", "STOP_MARKET"]
    assert kinds[0][4]["quantity"] == "0.002"            # 60/30000 = 0.002
    assert kinds[1][4]["stopPrice"] == "30360.00"        # +1.2%
    assert kinds[2][4]["stopPrice"] == "29730.00"        # -0.9%
    assert kinds[1][4]["closePosition"] == "true"
    assert result.qty == 0.002
    assert result.price == 30000.0
    assert result.tp_price == pytest.approx(30360.0)
    assert result.sl_price == pytest.approx(29730.0)

    assert ("change_margin_type", "BTCUSDT", "ISOLATED") in ex.client.calls
    assert ("change_leverage", "BTCUSDT", 10) in ex.client.calls


def test_open_market_short_side_prices():
    ex = make_exchange()
    ex.open_market("BTCUSDT", "sell", 60, 0.012, 0.009)
    orders = [c for c in ex.client.calls if c[0] == "new_order"]
    assert orders[0][2] == "SELL"
    assert orders[1][4]["stopPrice"] == "29640.00"       # TP تحت السعر للشورت
    assert orders[2][4]["stopPrice"] == "30270.00"       # SL فوق السعر للشورت


def test_min_notional_is_enforced():
    ex = make_exchange()
    ex.open_market("BTCUSDT", "buy", 5, 0.012, 0.009, min_notional=20)
    order = [c for c in ex.client.calls if c[0] == "new_order"][0]
    assert order[4]["quantity"] == "0.001"      # 5 USDT أقل من الحد الأدنى → تُرفع الكمية


def test_dry_run_does_not_send_orders():
    ex = make_exchange()
    ex.dry_run = True
    result = ex.open_market("BTCUSDT", "buy", 60, 0.012, 0.009)
    assert result.simulated is True
    assert not [c for c in ex.client.calls if c[0] == "new_order"]


def test_missing_stop_loss_triggers_emergency_close():
    ex = make_exchange(fail_stop_loss=True)
    with pytest.raises(ExchangeError):
        ex.open_market("BTCUSDT", "buy", 60, 0.012, 0.009)
    # يجب أن يلغي الأوامر ويغلق الصفقة اضطرارياً
    assert ("cancel_open_orders", "BTCUSDT") in ex.client.calls
    closes = [c for c in ex.client.calls if c[0] == "new_order" and c[4].get("reduceOnly") == "true"]
    assert closes, "لم يتم الإغلاق الاضطراري"


def test_close_position_uses_reduce_only():
    ex = make_exchange()
    result = ex.close_position("ETHUSDT")
    assert result is not None
    assert result.qty == 2
    assert ("cancel_open_orders", "ETHUSDT") in ex.client.calls
    order = [c for c in ex.client.calls if c[0] == "new_order"][0]
    assert order[2] == "BUY"                    # إغلاق شورت = شراء
    assert order[4]["reduceOnly"] == "true"


def test_close_position_without_position():
    ex = make_exchange()
    assert ex.close_position("BTCUSDT") is None


def test_invalid_side_raises():
    ex = make_exchange()
    with pytest.raises(ExchangeError):
        ex.open_market("BTCUSDT", "sideways", 60, 0.01, 0.01)
