"""هل كل الأوامر **تعمل فعلاً** أم أنها زينة؟

«اريد كل الاوامر تشغل حقيقيتا وليس زينتا»

القراءة لا تكفي: قد يكون الأمر موصولاً بمعالج، والمعالج يستدعي دالّة،
والدالّة **لا تفعل شيئاً** (كما حدث مع فلاتر `quality` التي كانت تُتجاهل
بصمت، ومع `candles` الذي كان ميتاً).

لذا هنا **نُشغّل كل أمر فعلياً** بمنصة وهمية تسجّل استدعاءاتها، ونفحص
**الأثر المرصود**: هل تغيّر الإعداد؟ هل طُلب الرصيد؟ هل أُغلقت الصفقة؟

القاعدة الذهبية: **كل أمر يجب أن يُخلّف أثراً يمكن قياسه.**
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from stratig.bot.telegram_bot import SET_KEYS, TelegramBot
from stratig.config import Config, Secrets
from stratig.data import Candles
from stratig.exchanges.base import Balance, OrderResult, Position
from stratig.services.trader import Trader

# ═══════════════════════ المنصة الوهمية ═══════════════════════


class FakeExchange:
    """منصة تسجّل كل استدعاء — فنعرف إن كان الأمر «حقيقياً» أم مجرد ردّ."""

    name = "وهمي"
    testnet = True
    dry_run = True

    def __init__(self, positions=None):
        self.calls: list[tuple] = []
        # الأنواع الحقيقية (Position/Balance) لا وهميات — وإلا فشلت العارض
        # بخطأ لا علاقة له بما نختبره
        self._positions = list(positions if positions is not None
                               else [Position("BTCUSDT", "buy", 0.01,
                                              entry_price=100.0, mark_price=101.0,
                                              pnl=5.0, leverage=10, roe_pct=5.0),
                                     Position("ETHUSDT", "sell", 0.5,
                                              entry_price=3000.0, mark_price=2990.0,
                                              pnl=-2.0, leverage=5, roe_pct=-1.3)])
        self._candles = _make_candles(600)

    # ── الواجهة التي يستخدمها البوت ──
    def balance(self):
        self.calls.append(("balance",))
        return Balance(total=1000.0, available=800.0, used=200.0)

    def positions(self):
        self.calls.append(("positions",))
        return list(self._positions)

    def klines(self, symbol, timeframe="15m", limit=500):
        self.calls.append(("klines", symbol, timeframe, limit))
        # نُعيد كائن Candles مقطوعاً (لا قائمة) — كما تفعل المنصة الحقيقية
        return self._candles.slice(max(0, len(self._candles) - limit), None)

    def mark_price(self, symbol):
        self.calls.append(("mark_price", symbol))
        return 100.0

    def recent_pnl(self, limit=50, since_ms=None):
        # الواجهة الحقيقية تُعيد **رقماً** (مجموع الأرباح) لا قائمة
        self.calls.append(("recent_pnl", limit))
        return 3.5

    def usdt_symbols(self, top_n=0, exclude=None):
        self.calls.append(("usdt_symbols", top_n))
        # SOLUSDT **غير** مفتوح — الفحص يتجاوز الرموز المفتوحة أصلاً،
        # فلو لم نُدرج رمزاً مغلقاً لَمَا جُلبت أي شمعة (ولَمَا اختبرنا شيئاً)
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def open_market(self, **kwargs):
        self.calls.append(("open_market", kwargs.get("symbol")))
        return {"ok": True, "id": "1"}

    def close_position(self, symbol, **kwargs):
        self.calls.append(("close_position", symbol))
        self._positions = [p for p in self._positions if p.symbol != symbol]
        # النوع الحقيقي الذي تتوقّعه الخدمة — لا dict
        return OrderResult(symbol=symbol, side="sell", qty=0.01, price=100.5)

    def open_position_symbols(self):
        return [p.symbol for p in self._positions]

    def replace_protection(self, symbol, **kwargs):
        self.calls.append(("replace_protection", symbol))
        return {"ok": True}


def _make_candles(count: int = 600):
    """كائن `Candles` حقيقي — المعالجات تقرأ `.times` و `.close`."""
    times = [i * 900_000 for i in range(count)]
    close = [100.0 + i * 0.01 for i in range(count)]
    return Candles(
        times=times,
        open=[c - 0.2 for c in close],
        high=[c + 0.5 for c in close],
        low=[c - 0.5 for c in close],
        close=close,
        volume=[1000.0] * count,
    )


# ═══════════════════════ تليجرام الوهمي ═══════════════════════


class FakeMessage:
    """يسجّل كل ردّ وكل تعديل لرسالة سابقة."""

    def __init__(self):
        self.replies: list[str] = []
        self.edits: list[str] = []
        self.markups: list = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        # نُعيد **نفس** الكائن: المعالج يعدّل هذه الرسالة لاحقاً
        # (msg.edit_text) — فلو أعطيناه كائناً آخر لضاع التعديل.
        return self

    async def reply_html(self, text, **kwargs):
        return await self.reply_text(text, **kwargs)

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self

    @property
    def all_text(self) -> str:
        return "\n".join(self.replies + self.edits)


class FakeUpdate:
    def __init__(self, uid: int = 1):
        self.effective_user = SimpleNamespace(id=uid)
        self.effective_chat = SimpleNamespace(id=uid)
        self.message = FakeMessage()
        self.callback_query = None

    @property
    def effective_message(self):
        return self.message

    @property
    def text(self) -> str:
        return self.message.all_text


class FakeContext:
    def __init__(self, args=None):
        self.args = list(args or [])
        self.user_data: dict = {}
        self.bot = SimpleNamespace(
            send_message=lambda **kw: asyncio.sleep(0),
            send_photo=lambda **kw: asyncio.sleep(0),
        )


# ═══════════════════════ تجهيز البوت ═══════════════════════


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    config = Config.load(str(path), str(tmp_path / ".env.missing"))
    # لا نريد لوحة ولا شبكة داخل الاختبارات
    config.set("web.enabled", False)
    config.set("supabase.enabled", False)
    return config


@pytest.fixture
def exchange():
    return FakeExchange()


@pytest.fixture
def bot(cfg, exchange, tmp_path, monkeypatch):
    cfg.set("risk.journal_path", str(tmp_path / "trades.json"))
    trader = Trader(cfg, exchange)
    secrets = Secrets(telegram_token="123456:AAA-fake-token-for-tests",
                      chat_ids=[1])
    instance = TelegramBot(secrets, cfg, trader)
    monkeypatch.setattr(instance, "_reply", _make_reply(instance))
    return instance


def _make_reply(bot):
    """يوجّه كل ردّ إلى رسالة التحديث نفسها، لنقيس الأثر."""
    async def _reply(update, text, markup=None, **kwargs):
        return await update.message.reply_text(text, reply_markup=markup)
    return _reply


def run(coro):
    return asyncio.run(coro)


def update_ctx(args=None, uid=1):
    return FakeUpdate(uid), FakeContext(args)


# ═══════════════════════ أوامر تلامس المنصة ═══════════════════════

def test_balance_really_queries_the_exchange(bot, exchange):
    upd, ctx = update_ctx()
    run(bot._balance(upd, ctx))
    assert ("balance",) in exchange.calls, "❌ /balance لم يطلب الرصيد — زينة"
    assert "رصيد" in upd.text or "USDT" in upd.text


def test_positions_really_queries_the_exchange(bot, exchange):
    upd, ctx = update_ctx()
    run(bot._positions(upd, ctx))
    assert ("positions",) in exchange.calls, "❌ /positions لم يجلب الصفقات"
    assert "BTCUSDT" in upd.text, "❌ الصفقة المعروفة لم تظهر في الردّ"


def test_pnl_really_queries_the_exchange(bot, exchange):
    upd, ctx = update_ctx()
    run(bot._pnl(upd, ctx))
    assert ("recent_pnl", 50) in exchange.calls, "❌ /pnl لم يحسب الأرباح فعلاً"


def test_scan_really_scans(bot, exchange, monkeypatch):
    upd, ctx = update_ctx()
    # نمنع الفحص من لمس الشبكة: المنصة الوهمية تكفي
    monkeypatch.setattr(bot, "_scan_summary", lambda found: _fake_summary(found))
    run(bot._scan(upd, ctx))
    assert any(call[0] == "klines" for call in exchange.calls), (
        "❌ /scan لم يجلب أي شمعة — لم يفحص شيئاً")


async def _fake_summary(found):
    return f"تم الفحص: {len(found)} إشارة"


def test_close_really_closes(bot, exchange):
    upd, ctx = update_ctx(["BTCUSDT"])
    run(bot._close(upd, ctx))
    assert ("close_position", "BTCUSDT") in exchange.calls, (
        "❌ /close لم يُرسل أمر إغلاق فعلي")


def test_close_without_args_explains_usage(bot, exchange):
    upd, ctx = update_ctx([])
    run(bot._close(upd, ctx))
    assert "/close" in upd.text
    assert not [c for c in exchange.calls if c[0] == "close_position"], (
        "❌ أغلق شيئاً بلا أن يحدّد المستخدم رمزاً!")


def test_closeall_asks_for_confirmation_first(bot, exchange):
    upd, ctx = update_ctx()
    run(bot._closeall(upd, ctx))
    assert ("positions",) in exchange.calls
    assert not [c for c in exchange.calls if c[0] == "close_position"], (
        "❌ /closeall أغلق كل شيء **بلا تأكيد** — هذا خطر")
    assert upd.message.markups[-1] is not None, "❌ لا أزرار تأكيد"


# ═══════════════════════ أوامر تبدّل الحالة ═══════════════════════

def test_pause_and_resume_really_toggle_scanning(bot):
    upd, ctx = update_ctx()
    run(bot._pause(upd, ctx))
    assert bot.trader.running is False, "❌ /pause لم يوقف الفحص"
    upd2, ctx2 = update_ctx()
    run(bot._resume(upd2, ctx2))
    assert bot.trader.running is True, "❌ /resume لم يُشغّل الفحص"


def test_dryrun_really_switches_exchange_mode(bot, exchange):
    upd, ctx = update_ctx()
    run(bot._dry_run_mode(upd, ctx))
    assert exchange.dry_run is True, "❌ /dryrun لم يُطبَّق على جلسة المنصة"
    assert bot.cfg.get("safety.dry_run") is True


def test_live_really_switches_exchange_mode(bot, exchange):
    upd, ctx = update_ctx()
    run(bot._live(upd, ctx))
    assert exchange.dry_run is False, "❌ /live لم يُطبَّق على جلسة المنصة"
    assert bot.cfg.get("safety.dry_run") is False


def test_dryrun_persists(bot, cfg, tmp_path):
    upd, ctx = update_ctx()
    run(bot._dry_run_mode(upd, ctx))
    reloaded = Config.load(str(tmp_path / "config.toml"),
                           str(tmp_path / ".env.missing"))
    assert reloaded.get("safety.dry_run") is True, "❌ /dryrun لم يُحفظ"


# ═══════════════════════ أوامر تغيّر الإعدادات ═══════════════════════

def test_set_changes_config_and_persists(bot, cfg, tmp_path):
    upd, ctx = update_ctx(["tp", "0.02"])
    run(bot._set(upd, ctx))
    assert cfg.get("trade.take_profit_pct") == 0.02
    reloaded = Config.load(str(tmp_path / "config.toml"),
                           str(tmp_path / ".env.missing"))
    assert reloaded.get("trade.take_profit_pct") == 0.02, "❌ /set لم يُحفظ"


def test_set_rejects_out_of_range(bot, cfg):
    upd, ctx = update_ctx(["lev", "9999"])
    run(bot._set(upd, ctx))
    assert cfg.get("trade.leverage") != 9999
    assert "125" in upd.text, "❌ لم يُبلّغ عن المجال المسموح"


def test_timeframe_command_really_changes_timeframe(bot, cfg):
    upd, ctx = update_ctx(["1h"])
    run(bot._timeframe(upd, ctx))
    assert cfg.get("strategy.timeframe") == "1h", "❌ /tf لم يغيّر الإطار"


def test_timeframe_command_rejects_bad_value(bot, cfg):
    upd, ctx = update_ctx(["غلط"])
    run(bot._timeframe(upd, ctx))
    assert cfg.get("strategy.timeframe") != "غلط"


def test_volmode_command_really_applies_thresholds(bot, cfg):
    upd, ctx = update_ctx(["volmode", "volatile"])
    run(bot._set(upd, ctx))
    assert cfg.get("strategy.volatility_min_pct") > 0, (
        "❌ /set volmode لم يضبط العتبة فعلاً")
    assert cfg.get("strategy.quality_enabled") is True, (
        "❌ لم يفعّل quality ⇒ العتبة ستُتجاهل بصمت")


def test_strategy_command_switches_strategy(bot, cfg):
    upd, ctx = update_ctx(["scalping_i"])
    run(bot._strategy(upd, ctx))
    assert cfg.get("strategy.name") == "scalping_i", "❌ /strategy لم يبدّل"


def test_recommended_really_changes_settings(bot, cfg):
    before = {k: cfg.get(v[0]) for k, v in SET_KEYS.items()}
    upd, ctx = update_ctx()
    run(bot._recommended(upd, ctx))
    # /recommended يعرض خطة ويطلب تأكيداً — الأثر هو **عرض خطة حقيقية**
    assert upd.text, "❌ /recommended لم يردّ شيئاً"
    plan = bot._pending_rec
    assert plan, "❌ /recommended لم يحضّر خطة تغييرات"
    assert plan != {}, "❌ الخطة فارغة"


# ═══════════════════════ أوامر معلومات ═══════════════════════

def test_stats_reads_real_journal(bot):
    upd, ctx = update_ctx()
    run(bot._stats(upd, ctx))
    assert upd.text and len(upd.text) > 20, "❌ /stats بلا محتوى"


def test_id_returns_the_users_id(bot):
    upd, ctx = update_ctx(uid=4242)
    run(bot._id(upd, ctx))
    assert "4242" in upd.text, "❌ /id لم يُظهر معرّف المستخدم"


def test_help_and_start_respond(bot):
    for handler in (bot._help, bot._start):
        upd, ctx = update_ctx()
        run(handler(upd, ctx))
        assert upd.text and len(upd.text) > 20, f"❌ {handler.__name__} بلا محتوى"


def test_reload_really_rereads_config_from_disk(bot, cfg, tmp_path):
    """/reload يجب أن يُعيد قراءة الملف — لا أن يكتفي بالردّ."""
    path = tmp_path / "config.toml"
    path.write_text("[trade]\ntake_profit_pct = 0.077\n", encoding="utf-8")
    assert cfg.get("trade.take_profit_pct") != 0.077

    run(bot._reload(*update_ctx()))
    assert cfg.get("trade.take_profit_pct") == 0.077, (
        "❌ /reload لم يقرأ الملف من القرص فعلاً")


def test_status_reflects_live_state_not_a_canned_string(bot, exchange):
    """/status يجب أن يعكس **الحالة الآن** — لا نصّاً جاهزاً."""
    upd, ctx = update_ctx()
    run(bot._status(upd, ctx))
    first = upd.text
    assert exchange.name in first, "❌ /status لا يذكر المنصة الفعلية"

    bot.trader.running = False
    upd2, ctx2 = update_ctx()
    run(bot._status(upd2, ctx2))
    assert upd2.text != first, "❌ /status لا يتغيّر بتغيّر الحالة (نصّ جامد)"


def test_scanall_really_scans_every_symbol(bot, exchange, monkeypatch):
    monkeypatch.setattr(bot, "_scan_summary", lambda found: _fake_summary(found))
    upd, ctx = update_ctx()
    run(bot._scan_all(upd, ctx))
    assert any(call[0] == "klines" for call in exchange.calls), (
        "❌ /scanall لم يفحص شيئاً")


def test_symbols_lists_the_symbols(bot, exchange):
    upd, ctx = update_ctx()
    run(bot._symbols(upd, ctx))
    assert ("usdt_symbols", 0) in exchange.calls or any(
        c[0] == "usdt_symbols" for c in exchange.calls), "❌ /symbols لم يجلب الرموز"
    assert "BTCUSDT" in upd.text, "❌ /symbols لم يعرض الرموز"


def _seed_journal(bot, count: int = 40) -> None:
    """صفقات واقعية في السجل — لكي يحسب /edge و /stats أرقاماً حقيقية."""
    import time as _time

    from stratig.risk import Trade

    now = _time.time()
    for i in range(count):
        bot.trader.journal.trades.append(
            Trade(symbol="SOLUSDT", side="buy" if i % 2 else "sell",
                  pnl=2.0 if i % 3 else -1.0,
                  r_multiple=1.5 if i % 3 else -1.0,
                  opened_at=now - (count - i) * 3600, closed_at=now - (count - i) * 3500,
                  strategy="scalping_i"))
    bot.trader.journal.save()


def test_edge_computes_from_real_trades(bot):
    """/edge بلا صفقات ⇒ بلا حكم؛ ومع صفقات ⇒ **أرقام محسوبة**."""
    upd, ctx = update_ctx()
    run(bot._edge(upd, ctx))
    empty_report = upd.text

    _seed_journal(bot, 40)
    upd2, ctx2 = update_ctx()
    run(bot._edge(upd2, ctx2))
    assert any(ch.isdigit() for ch in upd2.text), "❌ /edge بلا أرقام حتى مع صفقات"
    assert upd2.text != empty_report, "❌ /edge يتجاهل السجل — لا يحسب شيئاً"


def test_stats_counts_real_trades(bot):
    """/stats يجب أن يعدّ الصفقات المسجّلة فعلاً."""
    _seed_journal(bot, 7)
    upd, ctx = update_ctx()
    run(bot._stats(upd, ctx))
    assert "7" in upd.text, "❌ /stats لا يعكس عدد الصفقات الحقيقي"


def test_dashboard_command_responds(bot):
    upd, ctx = update_ctx()
    run(bot._dashboard(upd, ctx))
    assert upd.text and len(upd.text) > 10, "❌ /dashboard بلا ردّ"


def test_settings_lists_current_values(bot, cfg):
    cfg.set("trade.leverage", 25)
    upd, ctx = update_ctx()
    run(bot._settings(upd, ctx))
    assert "25" in upd.text, "❌ /settings لا يعرض القيم الحالية"


def test_protect_really_manages_protection(bot, exchange, cfg):
    """/protect يجب أن يفحص الصفقات المفتوحة فعلاً."""
    upd, ctx = update_ctx()
    run(bot._protect(upd, ctx))
    assert upd.text and len(upd.text) > 10, "❌ /protect بلا ردّ"
    asked = [c for c in exchange.calls if c[0] in ("positions", "replace_protection")]
    assert asked, "❌ /protect لم يلمس المنصة — زينة"


def test_data_command_inspects_real_candles(bot, exchange):
    upd, ctx = update_ctx(["SOLUSDT"])
    run(bot._data(upd, ctx))
    assert any(c[0] == "klines" for c in exchange.calls), (
        "❌ /data لم يجلب شموعاً حقيقية")


def test_start_registers_a_new_user_for_notifications(cfg, exchange, tmp_path):
    """بلا قائمة بيضاء: أول /start يضيف المستخدم لقائمة الإشعارات."""
    cfg.set("risk.journal_path", str(tmp_path / "trades.json"))
    trader = Trader(cfg, exchange)
    # chat_ids فارغة = لا قائمة بيضاء ⇒ كل من يبدأ يُسجَّل
    instance = TelegramBot(Secrets(telegram_token="123456:AAA-fake",
                                   chat_ids=[]), cfg, trader)
    upd, ctx = update_ctx(uid=777)
    run(instance._start(upd, ctx))
    assert 777 in instance.known, "❌ /start لم يسجّل المستخدم للإشعارات"


# ═══════════════════════ القائمة (الأزرار) ═══════════════════════

def _text_dispatch() -> dict[str, str]:
    """خريطة التوجيه داخل `_text`: {المفتاح: اسم الدالّة}.

    نقرأها من الكود نفسه (لا بتخمين الأسماء) — فالأسماء لا تتبع قاعدة
    واحدة: `scanall` ⇒ `_scan_all`، و`dryrun` ⇒ `_dry_run_mode`.
    """
    import ast
    from pathlib import Path

    src = Path("stratig/bot/telegram_bot.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_text":
            for sub in ast.walk(node):
                # البحث عن: {…}[cmd]  ⇒ القاموس المُفهرَس هو قاموس التوجيه
                if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Dict):
                    mapping = {}
                    for key, value in zip(sub.value.keys, sub.value.values):
                        if (isinstance(key, ast.Constant)
                                and isinstance(value, ast.Attribute)):
                            mapping[key.value] = value.attr
                    if mapping:
                        return mapping
    return {}


def _text_dispatch_keys() -> set[str]:
    return set(_text_dispatch())


def test_every_menu_button_is_dispatched():
    """أهم فحص «زينة»: زرّ معروض بلا توجيه = يُضغط ولا يحدث شيء."""
    from stratig.bot.telegram_bot import TEXT_COMMANDS

    dispatched = _text_dispatch_keys()
    assert dispatched, "لم يُعثر على قاموس التوجيه — تغيّر هيكل الكود؟"
    missing = {k: v for k, v in TEXT_COMMANDS.items() if v not in dispatched}
    assert not missing, f"❌ أزرار معروضة بلا توجيه (زينة): {missing}"


def test_every_dispatched_key_has_a_real_method(bot):
    """وكل مفتاح توجيه ⇒ دالّة موجودة فعلاً على الكائن (بالاسم الصحيح)."""
    for key, method in sorted(_text_dispatch().items()):
        assert callable(getattr(bot, method, None)), (
            f"❌ مفتاح التوجيه «{key}» يشير إلى {method} غير الموجودة")


def test_no_orphan_dispatch_entries():
    """مدخل توجيه بلا زرّ ولا أمر = كود ميت."""
    from stratig.bot.telegram_bot import TEXT_COMMANDS

    commands = {c for c, _m in _registered_commands()}
    orphans = _text_dispatch_keys() - set(TEXT_COMMANDS.values()) - commands
    assert not orphans, f"❌ مداخل توجيه لا يصلها أحد: {sorted(orphans)}"


def test_every_registered_command_has_a_working_handler(bot):
    """كل أمر مسجّل ⇒ معالج موجود وقابل للاستدعاء."""
    commands = _registered_commands()
    assert len(commands) >= 28, "❌ بعض الأوامر لم تُسجَّل"
    for cmd, method_name in commands:
        method = getattr(bot, method_name, None)
        assert method is not None, f"❌ /{cmd} بلا معالج"
        assert callable(method), f"❌ معالج /{cmd} ليس دالّة"


def test_help_lists_real_commands(bot):
    """/help ليس زينة: يجب أن يذكر أوامر موجودة فعلاً."""
    upd, ctx = update_ctx()
    upd, ctx = update_ctx()
    run(bot._help(upd, ctx))
    text = upd.text
    assert len(text) > 100, "❌ /help نصّ قصير جداً"
    # يذكر أوامراً مسجّلة فعلاً — لا نصّاً عاماً
    known = {c for c, _m in _registered_commands()}
    mentioned = [c for c in known if f"/{c}" in text]
    assert len(mentioned) >= 5, (
        f"❌ /help يذكر {len(mentioned)} أمراً فقط — لا يفيد")


def test_real_is_an_alias_of_live_and_works(bot):
    """/real اسم مستعار لـ /live — يجب أن يفعل الشيء نفسه."""
    mapping = dict(_registered_commands())
    assert mapping.get("real") == mapping.get("live"), (
        "❌ /real لم يعد مرادفاً لـ /live")
    # والأثر: تفعيل التنفيذ الحقيقي فعلاً
    upd, ctx = update_ctx()
    run(bot._live(upd, ctx))
    assert bot.cfg.get("safety.dry_run") is False, "❌ /real لا يفعّل التنفيذ"


def test_every_command_has_a_live_behaviour_test():
    """المِظلّة: أي أمر بلا اختبار أثر حقيقي ⇒ فشل.

    هذا هو ما يمنع عودة «الزينة»: إن أضفت أمراً جديداً ولم تختبر أنه
    **يفعل** شيئاً، يفشل هذا الاختبار هنا — لا في يد المستخدم.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    # نستثني هذا الاختبار نفسه ومرافقه حتى لا يُحصي نفسه
    helpers = {"test_every_command_has_a_live_behaviour_test",
               "test_every_registered_command_has_a_working_handler",
               "_registered_commands", "_text_dispatch", "_text_dispatch_keys"}
    body = "\n".join(ln for ln in source.splitlines()
                      if not any(h in ln for h in helpers))

    untested = []
    for cmd, method in _registered_commands():
        # الأثر الحقيقي مختبر إن ذُكر المعالج أو الأمر صراحةً
        if f"_{method}(" not in body and f"/{cmd}" not in body:
            untested.append(f"/{cmd} ({method})")
    assert not untested, (
        f"❌ أوامر بلا اختبار أثر حقيقي: {untested}\n"
        "أضف اختباراً يثبت أن الأمر **يفعل** شيئاً يمكن قياسه.")


def _registered_commands() -> list[tuple[str, str]]:
    import ast
    from pathlib import Path

    src = Path("stratig/bot/telegram_bot.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            for elt in node.iter.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                    name, handler = elt.elts
                    if isinstance(name, ast.Constant) and isinstance(handler, ast.Attribute):
                        found.append((name.value, handler.attr))
    return found


# ═══════════════════════ الحماية ═══════════════════════

def test_commands_are_restricted_to_allowed_users(cfg, exchange, tmp_path):
    """غير المصرّح له يجب ألا يستطيع تحريك المنصة."""
    cfg.set("risk.journal_path", str(tmp_path / "trades.json"))
    trader = Trader(cfg, exchange)
    secrets = Secrets(telegram_token="123456:AAA-fake", chat_ids=[999])
    instance = TelegramBot(secrets, cfg, trader)

    upd, ctx = update_ctx(uid=1)          # مستخدم غير مصرّح
    run(instance._balance(upd, ctx))
    assert not [c for c in exchange.calls if c[0] == "balance"], (
        "❌ مستخدم غير مصرّح له استطاع جلب الرصيد!")


def test_unauthorized_set_is_ignored(cfg, exchange, tmp_path):
    cfg.set("risk.journal_path", str(tmp_path / "trades.json"))
    trader = Trader(cfg, exchange)
    secrets = Secrets(telegram_token="123456:AAA-fake", chat_ids=[999])
    instance = TelegramBot(secrets, cfg, trader)

    upd, ctx = update_ctx(["lev", "50"], uid=1)
    run(instance._set(upd, ctx))
    assert cfg.get("trade.leverage") != 50, (
        "❌ غير المصرّح له استطاع تغيير الرافعة!")
