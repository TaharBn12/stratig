"""اختبارات طبقة البوت (بدون اتصال بتليجرام فعلي)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.bot.telegram_bot import TelegramBot  # noqa: E402
from stratig.config import Config, Secrets  # noqa: E402
from stratig.services.trader import Trader  # noqa: E402
from tests.test_core import FakeExchange  # noqa: E402
from tests.test_strategy import make_candles  # noqa: E402


def make_bot(**overrides):
    data = {
        "strategy": {"use_closed_candles": False},
        "scanner": {"symbols_source": "manual", "manual_symbols": ["AAAUSDT"]},
    }
    for key, value in overrides.items():
        section, name = key.split("__", 1)
        data.setdefault(section, {})[name] = value
    cfg = Config(data, path=Path("config.toml"))
    exchange = FakeExchange(symbols=("AAAUSDT",), df=make_candles(sign=1))
    trader = Trader(cfg, exchange)
    bot = TelegramBot(Secrets(telegram_token="123:FAKE", chat_ids=[1]), cfg, trader)
    return bot, trader, exchange


# ═══════════════════════ صلاحيات الوصول ═══════════════════════
def test_whitelist_allows_only_listed_ids():
    bot, _, _ = make_bot()
    assert bot._is_allowed(1) is True
    assert bot._is_allowed(999) is False
    assert bot._is_allowed(None) is False


def test_empty_whitelist_allows_everyone():
    cfg = Config({}, path=Path("config.toml"))
    trader = Trader(cfg, FakeExchange())
    bot = TelegramBot(Secrets(telegram_token="123:FAKE", chat_ids=[]), cfg, trader)
    assert bot._is_allowed(555) is True


# ═══════════════════════ جدولة الفحص ═══════════════════════
def test_fallback_scan_loop_when_jobqueue_missing():
    """عند غياب JobQueue يجب أن تعمل حلقة فحص داخلية بديلة."""
    bot, _, _ = make_bot()

    async def scenario():
        bot.app._job_queue = None          # محاكاة غياب apscheduler
        bot._schedule_scan()
        assert bot._scan_task is not None
        assert not bot._scan_task.done()
        bot._scan_task.cancel()

    asyncio.run(scenario())


def test_fallback_loop_is_not_duplicated():
    bot, _, _ = make_bot()

    async def scenario():
        bot.app._job_queue = None
        bot._schedule_scan()
        first = bot._scan_task
        bot._schedule_scan()               # استدعاء ثانٍ (تغيير المدة مثلاً)
        assert bot._scan_task is first
        first.cancel()

    asyncio.run(scenario())


def test_run_scan_cycle_scans_market():
    bot, trader, _ = make_bot()
    asyncio.run(bot._run_scan_cycle())
    assert trader.stats["scans"] == 1
    assert trader.last_scan_symbols == 1


# ═══════════════════════ تعديل الإعدادات ═══════════════════════
def test_set_topn_zero_means_all_symbols():
    bot, _, _ = make_bot()
    ok, message = bot._apply_setting("topn", "0")
    assert ok is True
    assert bot.cfg.get("scanner.top_n") == 0
    assert "0" in message


def test_set_topn_rejects_out_of_range():
    bot, _, _ = make_bot()
    ok, message = bot._apply_setting("topn", "5000")
    assert ok is False
    assert bot.cfg.get("scanner.top_n") == 40      # لم يتغيّر


def test_set_maxsig_works():
    bot, _, _ = make_bot()
    ok, _ = bot._apply_setting("maxsig", "10")
    assert ok is True
    assert bot.cfg.get("scanner.max_signals_per_scan") == 10


def test_set_percent_values():
    bot, _, _ = make_bot()
    ok, _ = bot._apply_setting("tp", "2%")
    assert ok is True
    assert bot.cfg.get("trade.take_profit_pct") == 0.02


def test_set_unknown_key():
    bot, _, _ = make_bot()
    ok, message = bot._apply_setting("unknown", "1")
    assert ok is False
    assert "غير معروف" in message


# ═══════════════════════ فحص كل العملات ═══════════════════════
def test_scan_all_uses_every_available_symbol():
    bot, trader, exchange = make_bot(scanner__symbols_source="auto", scanner__top_n=1)
    exchange.symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    assert trader.symbols() == ["AAAUSDT"]                 # مقيَّد بـ top_n
    found = asyncio.run(trader.scan_once(manual=True, symbols=trader.available_symbols()))
    assert len(found) == 3                                  # الفحص الشامل يغطي الكل


def test_commands_registered():
    bot, _, _ = make_bot()
    from telegram.ext import CommandHandler

    commands = {
        command
        for handler in bot.app.handlers[0]
        if isinstance(handler, CommandHandler)
        for command in handler.commands
    }
    for expected in ("start", "status", "scan", "scanall", "set", "closeall"):
        assert expected in commands


# ═══════════════════════ ملخص الفحص والتنبيه ═══════════════════════
def test_scan_summary_warns_when_few_symbols():
    bot, trader, exchange = make_bot()
    exchange.symbols = ["AAAUSDT"]
    found = asyncio.run(trader.scan_once(manual=True))
    summary = asyncio.run(bot._scan_summary(found))
    assert "قليل جداً" in summary
    assert "قائمة يدوية" in summary


def test_scan_summary_normal_case_has_no_warning():
    bot, trader, exchange = make_bot(scanner__symbols_source="auto", scanner__top_n=0)
    exchange.symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    found = asyncio.run(trader.scan_once(manual=True))
    summary = asyncio.run(bot._scan_summary(found))
    assert "قليل جداً" not in summary
    assert "كل العملات" in summary
