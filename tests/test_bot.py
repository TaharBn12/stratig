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
    for expected in ("start", "status", "scan", "scanall", "set", "closeall", "data", "protect"):
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


def test_protect_reports_unprotected_positions():
    """/protect يكشف الصفقات التي بلا وقف خسارة على المنصة."""
    from stratig.exchanges.base import Position

    bot, trader, exchange = make_bot()
    exchange.set_positions([
        Position(symbol="AAAUSDT", side="buy", size=0.001, entry_price=30000.0,
                 mark_price=30100.0, leverage=10),
    ])

    edits: list[str] = []

    class FakeMsg:
        async def edit_text(self, text, **kwargs):
            edits.append(text)

    class Update:
        class effective_message:
            @staticmethod
            async def reply_text(text, **kwargs):
                return FakeMsg()

    asyncio.run(bot._protect.__wrapped__(bot, Update(), None))
    assert edits and "AAAUSDT" in edits[0]
    assert "\u274c" in edits[0]              # بلا وقف خسارة → تحذير


def test_protect_reports_no_positions():
    bot, _, exchange = make_bot()
    exchange.set_positions([])

    edits: list[str] = []

    class FakeMsg:
        async def edit_text(self, text, **kwargs):
            edits.append(text)

    class Update:
        class effective_message:
            @staticmethod
            async def reply_text(text, **kwargs):
                return FakeMsg()

    asyncio.run(bot._protect.__wrapped__(bot, Update(), None))
    assert edits and "لا توجد صفقات" in edits[0]


# ═══════════════════════ المحاكاة مقابل التنفيذ الحقيقي ═══════════════════════
def make_bot_with_config(tmp_path, dry: bool = True):
    cfg = Config({}, path=tmp_path / "config.toml")
    cfg.set("scanner.symbols_source", "manual")
    cfg.set("scanner.manual_symbols", ["AAAUSDT"])
    cfg.set("safety.dry_run", dry)
    exchange = FakeExchange(symbols=("AAAUSDT",), df=make_candles(sign=1))
    exchange.dry_run = dry
    trader = Trader(cfg, exchange)
    bot = TelegramBot(Secrets(telegram_token="123:FAKE", chat_ids=[1]), cfg, trader)
    return bot, trader, exchange


def test_live_disables_simulation_immediately(tmp_path):
    """/live يجب أن يوقف المحاكاة فوراً على كائن المنصة بدون إعادة تشغيل."""
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=True)
    assert exchange.dry_run is True

    text = bot._toggle_dry_run(False)

    assert bot.cfg.get("safety.dry_run") is False
    assert exchange.dry_run is False            # الأهم: يُطبَّق فوراً
    assert "التنفيذ الحقيقي" in text
    assert (tmp_path / "config.toml").exists()  # وحُفظ في الملف


def test_dryrun_enables_simulation(tmp_path):
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    text = bot._toggle_dry_run(True)
    assert bot.cfg.get("safety.dry_run") is True
    assert exchange.dry_run is True
    assert "محاكاة" in text


def test_set_dryrun_false_applies_to_exchange(tmp_path):
    """/set dryrun false كان يحفظ الإعداد دون تطبيقه على الجلسة — عُولج."""
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=True)
    ok, message = bot._apply_setting("dryrun", "false")
    assert ok is True
    assert exchange.dry_run is False
    assert "حقيقية" in message


def test_startup_text_states_execution_mode(tmp_path):
    bot, _, _ = make_bot_with_config(tmp_path, dry=True)
    assert "محاكاة" in bot._startup_text()
    bot.cfg.set("safety.dry_run", False)
    assert "أوامر حقيقية" in bot._startup_text()


# ═══════════════════════ الإطار الزمني ═══════════════════════
def test_set_tf_normalizes_aliases(tmp_path):
    """/set tf 5min يجب أن يُفهم كـ 5m."""
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    ok, message = bot._apply_setting("tf", "5min")
    assert ok is True
    assert bot.cfg.get("strategy.timeframe") == "5m"
    assert "5m" in message


def test_set_tf_accepts_bare_number(tmp_path):
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    ok, _ = bot._apply_setting("tf", "15")
    assert ok is True
    assert bot.cfg.get("strategy.timeframe") == "15m"


def test_set_tf_rejects_unsupported(tmp_path):
    """إطار مرفوض يجب أن يُرفض فوراً برسالة واضحة بدل صمت المنصة."""
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    ok, message = bot._apply_setting("tf", "7m")
    assert ok is False
    assert "غير مدعوم" in message
    assert bot.cfg.get("strategy.timeframe") != "7m"


def test_set_tf_clears_cooldown_so_new_tf_applies(tmp_path):
    """السمومية كانت تخفي أثر تغيير الإطار لمدة 30 دقيقة."""
    import time as _time

    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    trader.cooldown["AAAUSDT"] = _time.time() + 1800
    ok, message = bot._apply_setting("tf", "5m")
    assert ok is True
    assert trader.cooldown == {}
    assert "السمومية" in message


def test_scan_uses_current_timeframe(tmp_path):
    """الفحص يقرأ الإطار من الإعدادات عند كل رمز (لا يُخزَّن عند الإقلاع)."""
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    seen: list[str] = []
    exchange.klines = lambda symbol, interval="15m", limit=500: (seen.append(interval), exchange.df)[1]
    bot.cfg.set("strategy.timeframe", "1h")
    asyncio.run(trader.scan_once())
    assert seen and seen[0] == "1h"


def test_reload_picks_up_manual_file_edit(tmp_path):
    """تعديل config.toml يدوياً يجب أن يظهر بـ /reload أو تلقائياً."""
    cfg = Config({"strategy": {"timeframe": "15m"}}, path=tmp_path / "config.toml")
    cfg.save()
    assert cfg.reload() is False                 # لا تغيير بعد

    text = (tmp_path / "config.toml").read_text(encoding="utf-8").replace("15m", "5m")
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    import os
    os.utime(tmp_path / "config.toml", (9_000_000_000, 9_000_000_000))

    assert cfg.reload() is True
    assert cfg.get("strategy.timeframe") == "5m"


def test_reload_keeps_pinned_values(tmp_path):
    """--dry-run يجب ألا يُلغى بإعادة تحميل الملف."""
    cfg = Config({"safety": {"dry_run": False}}, path=tmp_path / "config.toml")
    cfg.save()
    cfg.pin("safety.dry_run", True)
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    (tmp_path / "config.toml").write_text(text + "\n", encoding="utf-8")
    import os
    os.utime(tmp_path / "config.toml", (9_000_000_001, 9_000_000_001))
    assert cfg.reload() is True
    assert cfg.get("safety.dry_run") is True


def test_scan_cycle_reloads_config_automatically(tmp_path):
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    bot.cfg.save()
    (tmp_path / "config.toml").write_text(
        (tmp_path / "config.toml").read_text(encoding="utf-8")
        .replace('timeframe = "15m"', 'timeframe = "5m"'),
        encoding="utf-8",
    )
    import os
    os.utime(tmp_path / "config.toml", (9_000_000_002, 9_000_000_002))
    asyncio.run(bot._run_scan_cycle())
    assert bot.cfg.get("strategy.timeframe") == "5m"


# ═══════════════════════ تبديل الاستراتيجية ═══════════════════════
def test_switch_strategy_is_immediate(tmp_path):
    """/strategy scalping_i يجب أن يبدّل المنطق ووضع المخارج فوراً."""
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    assert trader.strategy_key == "rsi_williams"

    text = bot._switch_strategy("scalping_i")

    assert bot.cfg.get("strategy.name") == "scalping_i"
    assert bot.cfg.get("exit.mode") == "atr"        # وضع الخروج يتبع الاستراتيجية
    assert trader.strategy_key == "scalping_i"
    assert "scalping_i" in text


def test_switch_strategy_back_to_original_restores_percent(tmp_path):
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    bot._switch_strategy("scalping_i")
    bot._switch_strategy("rsi_williams")
    assert bot.cfg.get("exit.mode") == "percent"


def test_set_strategy_key_works(tmp_path):
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    ok, message = bot._apply_setting("strategy", "scalping_i")
    assert ok is True
    assert trader.strategy_key == "scalping_i"
    assert "scalping_i" in message


def test_set_strategy_rejects_unknown(tmp_path):
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    ok, message = bot._apply_setting("strategy", "martingale")
    assert ok is False
    assert trader.strategy_key == "rsi_williams"


def test_strategy_command_lists_all(tmp_path):
    bot, trader, exchange = make_bot_with_config(tmp_path, dry=False)
    text = bot._strategy_text()
    assert "rsi_williams" in text and "scalping_i" in text
