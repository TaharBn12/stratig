"""اختبارات الإعدادات، الأدوات المساعدة، ومحرك التنفيذ مع منصة وهمية."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config, Secrets  # noqa: E402
from stratig.data import make_candles  # noqa: E402
from stratig.exchanges.base import (  # noqa: E402
    Balance,
    ExchangeBase,
    ExchangeError,
    OrderResult,
    Position,
    SymbolInfo,
    fmt_num,
    interval_to_minutes,
    normalize_interval,
    round_step,
)
from stratig.services.notifier import MessageRef, Notifier  # noqa: E402
from stratig.services.trader import STATUS_EXPIRED, STATUS_OPENED, STATUS_SKIPPED, Trader  # noqa: E402
from tests.test_strategy import make_candles as make_signal_candles  # noqa: E402


# ═══════════════════════ أدوات ═══════════════════════
def test_round_step():
    assert round_step(1.23456, 0.001) == 1.234
    assert round_step(0.00019, 0.001) == 0.0
    assert round_step(12.7, 1) == 12.0


def test_intervals():
    assert normalize_interval(15) == "15m"
    assert normalize_interval("1h") == "1h"
    assert interval_to_minutes("15m") == 15
    assert interval_to_minutes("2h") == 120


def test_fmt_num():
    assert fmt_num(0.123456789, 4) == "0.1235"
    assert fmt_num(30000.1, 2) == "30000.10"


def test_make_klines_order():
    # Bybit: الأحدث أولاً (300 ثم 200 ثم 100) → نعكس ليصبح الأخير هو الأحدث
    newest_first = [[300, "3", "3", "3", "3", "1", "1"],
                    [200, "2", "2", "2", "2", "1", "1"],
                    [100, "1", "1", "1", "1", "1", "1"]]
    candles = make_candles(newest_first, reverse=True)
    assert candles.close == [1.0, 2.0, 3.0]
    # Binance: الأقدم أولاً → بدون عكس
    candles2 = make_candles(list(reversed(newest_first)), reverse=False)
    assert candles2.close == [1.0, 2.0, 3.0]
    assert candles2.times[0] < candles2.times[-1]


def test_make_candles_handles_empty_and_short_rows():
    assert len(make_candles([])) == 0
    full = make_candles([[1000, "10", "11", "9", "10.5", "100", "1000"]])
    assert full.times == [1000.0]
    assert full.open == [10.0]
    assert full.high == [11.0]
    assert full.low == [9.0]
    assert full.close == [10.5]
    assert full.volume == [100.0]
    assert full.turnover == [1000.0]
    # صف ناقص الأعمدة: تُستكمل بأصفار بدل الانهيار
    short = make_candles([[1, "10", "11", "9"]])
    assert short.open == [10.0]
    assert short.close == [0.0]


# ═══════════════════════ الإعدادات ═══════════════════════
def test_config_defaults_and_set(tmp_path):
    cfg = Config({}, path=tmp_path / "config.toml")
    assert cfg.get("exchange.name") == "binance"
    assert cfg.get("strategy.rsi.period") == 14
    cfg.set("trade.take_profit_pct", 0.02)
    cfg.save()
    loaded = Config.load(tmp_path / "config.toml")
    assert loaded.get("trade.take_profit_pct") == 0.02


def test_config_get_default_for_missing_path():
    cfg = Config({})
    assert cfg.get("does.not.exist", "fallback") == "fallback"


def test_secrets_reads_env(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "TELEGRAM_BOT_TOKEN=123:ABC\n"
        "TELEGRAM_CHAT_IDS=111,222\n"
        "EXCHANGE=binance\n"
        "TESTNET=true\n"
        "BINANCE_TESTNET_API_KEY=key\n"
        "BINANCE_TESTNET_API_SECRET=secret\n",
        encoding="utf-8",
    )
    sec = Secrets.from_env(env)
    assert sec.telegram_token == "123:ABC"
    assert sec.chat_ids == [111, 222]
    key, secret = sec.creds("binance", True)
    assert key == "key" and secret == "secret"


def test_config_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("EXCHANGE", "bybit")
    monkeypatch.setenv("TESTNET", "false")
    cfg = Config.load(tmp_path / "missing.toml", tmp_path / "missing.env")
    assert cfg.get("exchange.name") == "bybit"
    assert cfg.get("exchange.testnet") is False


# ═══════════════════════ منصة وهمية ═══════════════════════
class FakeExchange(ExchangeBase):
    def __init__(self, symbols=("AAAUSDT",), df=None, positions=None):
        self.name = "fake-testnet"
        self.testnet = True
        self.symbols = list(symbols)
        self.df = df if df is not None else make_signal_candles(sign=1)
        self._positions = list(positions or [])
        self.calls: list[tuple] = []
        self.closed: list[str] = []
        self.pnl = 0.0

    def set_positions(self, positions):
        self._positions = list(positions)

    def klines(self, symbol, interval="15m", limit=500):
        return self.df

    def mark_price(self, symbol):
        return float(self.df.close[-1])

    def symbol_info(self, symbol):
        return SymbolInfo(symbol, price_precision=2, qty_precision=3,
                          tick_size=0.01, step_size=0.001, min_qty=0.001, min_notional=5)

    def usdt_symbols(self, top_n=40, exclude=()):
        blocked = set(exclude or ())
        out = [s for s in self.symbols if s not in blocked]
        return out[:top_n] if top_n and top_n > 0 else out

    def balance(self):
        return Balance(total=1000.0, available=900.0, unrealized=0.0)

    def positions(self):
        return self._positions

    def recent_pnl(self, limit=50, since_ms=None):
        return self.pnl

    def open_market(self, symbol, side, qty_usdt, tp_pct, sl_pct, leverage=10,
                    margin_mode="isolated", tp_trigger="mark_price", min_notional=0.0):
        self.calls.append((symbol, side, qty_usdt, tp_pct, sl_pct, leverage, margin_mode))
        price = self.mark_price(symbol)
        if self.dry_run:                      # محاكاة: لا صفقة ولا أمر
            return OrderResult(symbol=symbol, side=side, qty=qty_usdt / price, price=price,
                               tp_price=price * (1 + tp_pct), sl_price=price * (1 - sl_pct),
                               notional=qty_usdt, simulated=True)
        self._positions.append(Position(symbol=symbol, side=side, size=qty_usdt / price,
                                        entry_price=price, mark_price=price))
        return OrderResult(symbol=symbol, side=side, qty=qty_usdt / price, price=price,
                           tp_price=price * (1 + tp_pct), sl_price=price * (1 - sl_pct),
                           notional=qty_usdt)

    def close_position(self, symbol):
        self.closed.append(symbol)
        self._positions = [p for p in self._positions if p.symbol != symbol]
        return OrderResult(symbol=symbol, side="sell", qty=1.0, price=self.mark_price(symbol))


def make_trader(tmp_path, **overrides):
    data = {
        "strategy": {"use_closed_candles": False},
        "scanner": {"symbols_source": "manual", "manual_symbols": ["AAAUSDT"]},
    }
    for key, value in overrides.items():
        section, name = key.split("__", 1)
        data.setdefault(section, {})[name] = value
    cfg = Config(data, path=tmp_path / "config.toml")
    ex = FakeExchange()
    return Trader(cfg, ex), ex


# ═══════════════════════ المحرك التنفيذي ═══════════════════════
def test_manual_flow_open(tmp_path):
    trader, ex = make_trader(tmp_path)
    found = asyncio.run(trader.scan_once())
    assert len(found) == 1
    sig = found[0]
    assert sig.side == "buy"
    assert sig.is_pending
    assert not ex.calls, "الوضع اليدوي لا يجب أن يفتح صفقة تلقائياً"

    result = asyncio.run(trader.open_signal(sig.id))
    assert result is not None
    assert len(ex.calls) == 1
    assert sig.status == STATUS_OPENED
    assert trader.stats["opened"] == 1
    assert trader.trades_today == 1


def test_manual_flow_skip(tmp_path):
    trader, ex = make_trader(tmp_path)
    sig = asyncio.run(trader.scan_once())[0]
    assert asyncio.run(trader.skip_signal(sig.id)) is True
    assert sig.status == STATUS_SKIPPED
    assert not ex.calls


def test_auto_mode_opens_immediately(tmp_path):
    trader, ex = make_trader(tmp_path, execution__mode="auto")
    asyncio.run(trader.scan_once())
    assert len(ex.calls) == 1


def test_cooldown_and_pending_prevent_duplicates(tmp_path):
    trader, ex = make_trader(tmp_path)
    first = asyncio.run(trader.scan_once())
    assert len(first) == 1

    # لا تتكرر الإشارة ما دامت معلّقة أو الرمز في فترة السمومية
    assert asyncio.run(trader.scan_once()) == []

    asyncio.run(trader.skip_signal(first[0].id))
    assert asyncio.run(trader.scan_once()) == []       # ما زال في فترة السمومية

    trader.cooldown.clear()
    third = asyncio.run(trader.scan_once())
    assert len(third) == 1
    assert third[0].id != first[0].id


def test_open_position_blocks_new_signal(tmp_path):
    trader, ex = make_trader(tmp_path)
    ex.set_positions([Position(symbol="AAAUSDT", side="buy", size=1, entry_price=100, mark_price=100)])
    assert asyncio.run(trader.scan_once()) == []


def test_max_positions_stops_scan(tmp_path):
    trader, ex = make_trader(tmp_path, risk__max_positions=1)
    ex.set_positions([Position(symbol="BBBUSDT", side="buy", size=1, entry_price=100, mark_price=100)])
    assert asyncio.run(trader.scan_once()) == []
    assert trader.last_scan_symbols == 0   # خرج مبكراً قبل جلب القائمة


def test_signal_expires(tmp_path):
    trader, ex = make_trader(tmp_path, scanner__signal_ttl_seconds=1)
    sig = asyncio.run(trader.scan_once())[0]
    time.sleep(1.1)
    assert trader.expire_signals()[0].id == sig.id
    assert sig.status == STATUS_EXPIRED
    assert asyncio.run(trader.open_signal(sig.id)) is None
    assert not ex.calls


def test_paused_scanner_does_nothing(tmp_path):
    trader, ex = make_trader(tmp_path, scanner__autostart=False)
    assert asyncio.run(trader.scan_once()) == []
    assert trader.stats["scans"] == 0
    # الفحص اليدوي يعمل رغم الإيقاف
    assert len(asyncio.run(trader.scan_once(manual=True))) == 1


def test_close_symbol_and_close_all(tmp_path):
    trader, ex = make_trader(tmp_path)
    ex.set_positions([Position(symbol="AAAUSDT", side="buy", size=1, entry_price=100, mark_price=100)])
    asyncio.run(trader.close_symbol("AAAUSDT"))
    assert ex.closed == ["AAAUSDT"]

    ex.set_positions([Position(symbol="XUSDT", side="sell", size=1, entry_price=1, mark_price=1)])
    assert asyncio.run(trader.close_all()) == 1
    assert ex.closed == ["AAAUSDT", "XUSDT"]


def test_daily_trade_limit(tmp_path):
    trader, ex = make_trader(tmp_path, risk__daily_max_trades=1)
    sig = asyncio.run(trader.scan_once())[0]
    asyncio.run(trader.open_signal(sig.id))
    trader.cooldown.clear()
    assert asyncio.run(trader.scan_once()) == []


def test_daily_loss_limit_blocks(tmp_path):
    trader, ex = make_trader(tmp_path, risk__daily_max_loss_usdt=10)
    ex.pnl = -25.0
    assert asyncio.run(trader.scan_once()) == []


def test_symbol_management(tmp_path):
    trader, _ = make_trader(tmp_path)
    trader.add_symbol("LTCUSDT")
    assert "LTCUSDT" in trader.symbols()
    trader.remove_symbol("LTCUSDT")
    assert "LTCUSDT" not in trader.symbols()
    assert trader.cfg.get("scanner.symbols_source") == "manual"


def test_status_snapshot(tmp_path):
    trader, _ = make_trader(tmp_path)
    st = trader.status()
    assert st["exchange"] == "fake-testnet"
    assert st["mode"] == "manual"
    assert st["pending"] == 0
    assert st["stats"]["scans"] == 0


# ═══════════════════════ فحص كل العملات ═══════════════════════
def test_available_symbols_ignores_top_n(tmp_path):
    trader, ex = make_trader(tmp_path, scanner__symbols_source="auto", scanner__top_n=2)
    ex.symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    assert trader.symbols() == ["AAAUSDT", "BBBUSDT"]      # محدود بـ top_n
    assert trader.available_symbols() == ex.symbols         # الكل بدون حد


def test_scan_all_uses_provided_symbols(tmp_path):
    trader, ex = make_trader(tmp_path)
    ex.symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    found = asyncio.run(trader.scan_once(manual=True, symbols=ex.symbols))
    assert len(found) == 3                                  # كل الرموز تعطي إشارة
    assert {s.symbol for s in found} == set(ex.symbols)
    assert trader.last_scan_symbols == 3


def test_scan_all_respects_symbols_argument_even_when_paused(tmp_path):
    trader, ex = make_trader(tmp_path, scanner__autostart=False)
    found = asyncio.run(trader.scan_once(manual=True, symbols=["AAAUSDT"]))
    assert len(found) == 1


def test_max_signals_per_scan_caps_results(tmp_path):
    trader, ex = make_trader(tmp_path, scanner__max_signals_per_scan=2)
    ex.symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    trader.cooldown.clear()
    found = asyncio.run(trader.scan_once(manual=True, symbols=ex.symbols))
    assert len(found) == 2


def test_scan_stops_at_max_positions_without_extra_requests(tmp_path):
    """العدّ يتم محلياً: لا يُطلب get_positions عند كل رمز."""
    trader, ex = make_trader(tmp_path, risk__max_positions=2, execution__mode="auto")
    ex.symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    calls = {"positions": 0}
    original = ex.positions

    def counting():
        calls["positions"] += 1
        return original()

    ex.positions = counting
    found = asyncio.run(trader.scan_once(manual=True, symbols=ex.symbols))
    assert len(found) == 2                       # توقف عند max_positions
    assert calls["positions"] <= 2               # طلب واحد في البداية (وليس 3)


# ═══════════════════════ مصدر قائمة الرموز ═══════════════════════
def test_symbols_source_property(tmp_path):
    trader, ex = make_trader(tmp_path, scanner__symbols_source="manual")
    assert trader.symbols_source == "manual"

    trader.cfg.set("scanner.symbols_source", "auto")
    trader.cfg.set("scanner.top_n", 40)
    assert trader.symbols_source == "auto"

    trader.cfg.set("scanner.top_n", 0)
    assert trader.symbols_source == "all"


def test_empty_manual_list_falls_back_to_all(tmp_path):
    """قائمة يدوية فارغة لا تعني 'فحص صفر رموز'."""
    trader, ex = make_trader(tmp_path, scanner__symbols_source="manual",
                            scanner__manual_symbols=[])
    ex.symbols = ["AAAUSDT", "BBBUSDT"]
    assert trader.symbols() == ["AAAUSDT", "BBBUSDT"]


def test_use_auto_symbols_all_sets_topn_zero(tmp_path):
    trader, ex = make_trader(tmp_path, scanner__symbols_source="manual", scanner__top_n=40)
    trader.use_auto_symbols(all_symbols=True)
    assert trader.cfg.get("scanner.symbols_source") == "auto"
    assert trader.cfg.get("scanner.top_n") == 0
    assert trader.symbols_source == "all"


def test_add_symbol_to_tiny_manual_list_keeps_others(tmp_path):
    """الإضافة إلى قائمة يدوية شبه فارغة يجب ألا تحذف بقية السوق."""
    trader, ex = make_trader(tmp_path, scanner__symbols_source="manual",
                            scanner__manual_symbols=["AAAUSDT"])
    ex.symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    trader.add_symbol("DDDUSDT")
    current = trader.symbols()
    assert "DDDUSDT" in current
    assert len(current) >= 3


def test_scan_records_source(tmp_path):
    trader, ex = make_trader(tmp_path)
    asyncio.run(trader.scan_once(manual=True))
    assert trader.last_scan_source == "manual"
    ex.symbols = ["AAAUSDT", "BBBUSDT"]
    asyncio.run(trader.scan_once(manual=True, all_symbols=True))
    assert trader.last_scan_source == "all"


def test_signal_text_shows_real_execution_when_dry_run_off(tmp_path):
    """رسالة الإشارة يجب أن تقول صراحةً أن الأمر سيُرسل فعلياً."""
    trader, ex = make_trader(tmp_path)
    sig = asyncio.run(trader.scan_once())[0]
    text = trader._signal_text(sig)
    assert "محاكاة" not in text
    assert "أمر حقيقي" in text and ex.name in text


def test_signal_text_warns_when_dry_run_on(tmp_path):
    trader, ex = make_trader(tmp_path, safety__dry_run=True)
    sig = asyncio.run(trader.scan_once())[0]
    assert "محاكاة" in trader._signal_text(sig)


def test_opened_text_confirms_real_order(tmp_path):
    """بعد الفتح: 'أُمر حقيقي أُرسل' بدل 'محاكاة'."""
    trader, ex = make_trader(tmp_path)
    sig = asyncio.run(trader.scan_once())[0]
    asyncio.run(trader.open_signal(sig.id))
    text = trader._opened_text(sig)
    assert "محاكاة" not in text
    assert "أُمر حقيقي أُرسل" in text


def test_opened_text_marks_simulation(tmp_path):
    trader, ex = make_trader(tmp_path)
    ex.dry_run = True
    sig = asyncio.run(trader.scan_once())[0]
    asyncio.run(trader.open_signal(sig.id))
    assert "محاكاة" in trader._opened_text(sig)


def test_on_timeframe_changed_clears_cooldown(tmp_path):
    trader, ex = make_trader(tmp_path)
    trader.cooldown["AAAUSDT"] = time.time() + 1800
    cleared = trader.on_timeframe_changed()
    assert cleared == 1
    assert trader.cooldown == {}


def test_total_kline_failure_is_reported_once(tmp_path):
    """"فشل كل الرموز" يجب أن يُبلَّغ عنه بدل الصمت (إطار مرفوض مثلاً)."""
    trader, ex = make_trader(tmp_path)

    class RecordingNotifier(Notifier):
        def __init__(self):
            self.messages: list[str] = []

        async def send(self, text, buttons=None, chat_id=None):
            self.messages.append(text)
            return MessageRef()

    trader.notifier = RecordingNotifier()

    def boom(symbol, interval="15m", limit=500):
        raise ExchangeError("Invalid interval")

    ex.klines = boom
    asyncio.run(trader.scan_once())              # فحص تلقائي (غير يدوي)
    assert any("تعذّر جلب الشموع" in m for m in trader.notifier.messages)

    count = len(trader.notifier.messages)
    asyncio.run(trader.scan_once())
    assert len(trader.notifier.messages) == count      # مرّة واحدة فقط


def test_timeframe_is_read_per_scan(tmp_path):
    trader, ex = make_trader(tmp_path)
    seen: list[str] = []
    original = ex.klines

    def spy(symbol, interval="15m", limit=500):
        seen.append(interval)
        return original(symbol, interval, limit)

    ex.klines = spy
    asyncio.run(trader.scan_once())
    assert seen and seen[0] == "15m"
    trader.cfg.set("strategy.timeframe", "1h")
    trader.on_timeframe_changed()          # يمسح السمومية (كما يفعل /set tf)
    trader.pending.clear()
    asyncio.run(trader.scan_once())
    assert "1h" in seen
