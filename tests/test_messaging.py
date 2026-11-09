"""اختبارات تنسيق الرسائل (HTML تليجرام) وطبقة الإشعارات.

الخطأ الذي عالجه هذا الملف:
    Can't parse entities: unsupported start tag "" at byte offset 262
وسببه أن وصف المؤشر يحتوي على < أو > بشكل خام، مثال:
    "كسر هابط من تشبّع شرائي (72.4 < 70)"
فيفسّره تليجرام على أنه بداية وسم HTML ويرفض الرسالة كلها.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.services.notifier import MessageRef, TelegramNotifier, strip_tags  # noqa: E402
from stratig.strategy.engine import Decision  # noqa: E402
from stratig.strategy.indicators import IndicatorResult, rsi_signal  # noqa: E402
from stratig.config import Config, Secrets  # noqa: E402
from tests.test_core import FakeExchange  # noqa: E402

ALLOWED_TAGS = re.compile(r"</?(?:b|i|u|s|code|pre|a|tg-spoiler)(?:\s[^>]*)?>", re.I)
ANY_TAG = re.compile(r"<[^>]*>")


def unsupported_tags(text: str) -> list[str]:
    return [t for t in ANY_TAG.findall(text) if not ALLOWED_TAGS.fullmatch(t)]


# ═══════════════════════ وصف القرار ═══════════════════════
def test_describe_escapes_comparison_operators():
    decision = Decision(
        symbol="BTCUSDT",
        rsi=IndicatorResult("RSI", "sell", 72.4, "كسر هابط من تشبّع شرائي (72.4 < 70)"),
        willr=IndicatorResult("W%R", "buy", -95.0, "تشبّع بيعي شديد (-95.0)"),
    )
    text = decision.describe()
    assert "72.4 < 70" not in text          # الرمز الخام يجب أن يختفي
    assert "&lt;" in text
    assert unsupported_tags(text) == []


def test_rsi_reason_with_operator_is_safe_in_html():
    """سبب المؤشر الحقيقي (يحتوي > أو <) يجب ألا يكسر HTML."""
    decline = [100 * (0.97 ** i) for i in range(30)]       # هبوط حاد → تشبّع بيعي
    bounce = [decline[-1] * (1.05 ** i) for i in range(1, 5)]
    result = rsi_signal(decline + bounce, period=14, oversold=30, overbought=70)
    assert result.side == "buy"
    assert ">" in result.reason                            # السبب يحتوي رمز مقارنة خام
    text = Decision(symbol="X", rsi=result).describe()
    assert "&gt;" in text
    assert unsupported_tags(text) == []


def test_strip_tags_removes_markup():
    assert strip_tags("<b>مرحبا</b> <i>يا</i> <&>") == "مرحبا يا <&>"


# ═══════════════════════ طبقة الإشعارات ═══════════════════════
class FakeMessage:
    chat_id = 1
    message_id = 42


class FakeTelegramBot:
    """يرفض أول إرسال بتنسيق HTML ثم يقبل النص العادي."""

    def __init__(self, reject_html: bool = True):
        self.reject_html = reject_html
        self.sent: list[dict] = []
        self.edited: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        if self.reject_html and kwargs.get("parse_mode"):
            from telegram.error import BadRequest

            raise BadRequest("Can't parse entities: unsupported start tag \"\"")
        if not self.reject_html and kwargs.get("parse_mode"):
            # محاكاة رفض لأي سبب آخر (مثل الرسالة غير معدّلة)
            pass
        return FakeMessage()

    async def edit_message_text(self, **kwargs):
        self.edited.append(kwargs)
        if self.reject_html and kwargs.get("parse_mode"):
            from telegram.error import BadRequest

            raise BadRequest("Can't parse entities")
        return FakeMessage()


def make_notifier(reject_html: bool = True):
    from telegram import InlineKeyboardButton

    fake = FakeTelegramBot(reject_html=reject_html)
    notifier = TelegramNotifier(fake, chat_ids=[1])
    return notifier, fake, InlineKeyboardButton


def test_send_falls_back_to_plain_text_when_html_rejected():
    notifier, fake, _ = make_notifier(reject_html=True)
    ref = asyncio.run(notifier.send("🔽 <b>إشارة</b>: RSI 72.4 < 70"))

    assert ref is not None and ref.message_id == 42
    assert len(fake.sent) == 2
    assert fake.sent[0].get("parse_mode") is not None      # المحاولة الأولى بتنسيق HTML
    assert fake.sent[1].get("parse_mode") is None          # الملاذ: نص عادي
    assert fake.sent[1]["text"] == "🔽 إشارة: RSI 72.4 < 70"


def test_send_uses_html_when_accepted():
    notifier, fake, _ = make_notifier(reject_html=False)
    asyncio.run(notifier.send("🔽 <b>إشارة</b>"))
    assert len(fake.sent) == 1
    assert fake.sent[0]["parse_mode"] is not None


def test_edit_falls_back_to_plain_text():
    notifier, fake, _ = make_notifier(reject_html=True)
    asyncio.run(notifier.edit(MessageRef(chat_id=1, message_id=7), "❌ <code>خطأ</code>"))
    assert len(fake.edited) == 2
    assert fake.edited[1]["text"] == "❌ خطأ"


# ═══════════════════════ قفل دورات الفحص ═══════════════════════
def test_scan_cycle_is_skipped_while_previous_runs():
    """دورة فحص ثانية أثناء عمل الأولى تُتخطّى بدل أن تتراكم."""
    from stratig.bot.telegram_bot import TelegramBot
    from stratig.services.trader import Trader
    from tests.test_strategy import make_candles

    cfg = Config({}, path=Path("config.toml"))
    cfg.set("scanner.symbols_source", "manual")
    cfg.set("scanner.manual_symbols", ["AAAUSDT"])
    exchange = FakeExchange(symbols=("AAAUSDT",), df=make_candles(sign=1))
    trader = Trader(cfg, exchange)
    bot = TelegramBot(Secrets(telegram_token="123:FAKE", chat_ids=[1]), cfg, trader)

    started = 0

    async def slow_scan():
        nonlocal started
        started += 1
        await asyncio.sleep(0.05)

    async def scenario():
        bot._get_scan_lock()
        lock = bot._scan_lock
        await lock.acquire()               # نحاكي دورة فحص لا زالت تعمل
        await bot._run_scan_cycle()
        assert started == 0, "يجب تخطّي الدورة المتزامنة"
        lock.release()
        await bot._run_scan_cycle()        # الآن تعمل بشكل طبيعي

    trader.scan_once = slow_scan           # type: ignore[method-assign]
    asyncio.run(scenario())
    assert started == 1
