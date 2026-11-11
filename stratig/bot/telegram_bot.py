"""بوت تليجرام — تحكم يدوي كامل بالاستراتيجية.

سير العمل في الوضع اليدوي (الافتراضي):
    فحص دوري → إشارة (RSI + Williams %R متفقان) → رسالة بأزرار
    → أنت تضغط ✅ فتح  أو  ❌ تجاهل
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import Config, Secrets
from ..strategy.registry import (
    all_strategies,
    get as get_strategy,
    is_supported as is_supported_strategy,
)
from ..utils import ALLOWED_TIMEFRAMES, is_supported_timeframe, normalize_timeframe
from ..services.notifier import TelegramNotifier
from ..services.trader import Trader
from . import formatters as fmt

log = logging.getLogger(__name__)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 الحالة"), KeyboardButton("💰 الرصيد")],
        [KeyboardButton("📈 الصفقات"), KeyboardButton("💹 الأرباح")],
        [KeyboardButton("🔍 فحص الآن"), KeyboardButton("🌐 فحص كل العملات")],
        [KeyboardButton("⚙️ الإعدادات"), KeyboardButton("❔ مساعدة")],
        [KeyboardButton("⏸ إيقاف المسح"), KeyboardButton("▶️ تشغيل المسح")],
        [KeyboardButton("🔴 تنفيذ حقيقي"), KeyboardButton("🧪 محاكاة")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

TEXT_COMMANDS = {
    "📊 الحالة": "status",
    "💰 الرصيد": "balance",
    "📈 الصفقات": "positions",
    "💹 الأرباح": "pnl",
    "🔍 فحص الآن": "scan",
    "🌐 فحص كل العملات": "scanall",
    "⚙️ الإعدادات": "settings",
    "⏸ إيقاف المسح": "pause",
    "▶️ تشغيل المسح": "resume",
    "🔴 تنفيذ حقيقي": "live",
    "🧪 محاكاة": "dryrun",
    "📉 إحصائياتي": "stats",
    "📊 مقياس الميزة": "edge",
    "🌐 لوحة التحكم": "dashboard",
    "❔ مساعدة": "help",
}

# key: (مسار في config.toml، نوع القيمة، وصف للمستخدم)
SET_KEYS: dict[str, tuple[str, str, str]] = {
    "tp": ("trade.take_profit_pct", "float", "جني الأرباح — مثال: 0.02 أو 2%"),
    "sl": ("trade.stop_loss_pct", "float", "وقف الخسارة — مثال: 0.01 أو 1%"),
    "qty": ("trade.qty_usdt", "float", "حجم الصفقة بالـ USDT — مثال: 50"),
    "lev": ("trade.leverage", "int", "الرافعة المالية — مثال: 10"),
    "margin": ("trade.margin_mode", "choice:isolated,cross", "نوع الهامش"),
    "tf": ("strategy.timeframe", "str", "الإطار الزمني — مثال: 15m أو 1h"),
    "strategy": ("strategy.name", "choice:rsi_williams,scalping_i", "الاستراتيجية المستخدمة"),
    "exit": ("exit.mode", "choice:percent,atr", "مخارج الصفقة: نسب ثابتة أم ATR"),
    "follow_exit": ("exit.follow_strategy", "bool",
                    "الصرامة: مخارج الاستراتيجية تطغى على exit.mode (true / false)"),
    "strict": ("exit.strict", "bool",
               "الصرامة: ارفض فتح صفقة بمخارج لا تنتمي للاستراتيجية (true / false)"),
    "drift": ("execution.max_entry_drift", "float",
              "أقصى انحراف مسموح عن سعر الإشارة كنسبة من الوقف (1.0 = وقف كامل)"),
    "block_stale": ("execution.block_stale_entry", "bool",
                    "ارفض الدخول المتأخّر بدل التحذير فقط (true / false)"),
    "edge": ("edge.enabled", "bool", "مقياس الميزة في /edge"),
    "edgegate": ("edge.gate", "bool", "منع التداول عند ثبوت الخسارة إحصائياً"),
    "edgemin": ("edge.min_trades", "int", "أدنى صفقات قبل إصدار حكم — 30"),
    "edgelook": ("edge.lookback", "int", "0 = كل الصفقات، وإلا آخر N صفقة"),
    "webenable": ("web.enabled", "bool", "لوحة التحكم على جهازك"),
    "webport": ("web.port", "int", "منفذ لوحة التحكم — مثال: 8000"),
    "webtoken": ("web.token", "str", "رمز حماية اللوحة (فارغ = بلا حماية)"),
    "supabase": ("supabase.enabled", "bool", "رفع البيانات إلى Supabase"),
    "supabaseurl": ("supabase.url", "str", "رابط مشروع Supabase"),
    "supabasekey": ("supabase.key", "str", "المفتاح السرّي لـ Supabase"),
    "botid": ("supabase.bot_id", "str", "معرّف البوت في Supabase"),
    "quality": ("strategy.quality_enabled", "bool", "فلاتر الجودة: نظام السوق + MTF + تقلّب"),
    "regime": ("strategy.regime", "choice:off,trend,range",
               "نظام السوق المسموح: off = الكل · trend = اتجاهي فقط · range = جانبي فقط"),
    "adxlen": ("strategy.adx_length", "int", "فترة ADX — مثال: 14"),
    "adxmin": ("strategy.adx_trend_min", "float", "أدنى ADX لاعتبار السوق متّجهاً — 25"),
    "adxmax": ("strategy.adx_range_max", "float", "أقصى ADX لاعتبار السوق جانبياً — 20"),
    "mtf": ("strategy.mtf_enabled", "bool", "تأكيد الإطار الأعلى قبل الدخول"),
    "mtftf": ("strategy.mtf_timeframe", "str", "الإطار الأعلى للتأكيد — مثال: 1h"),
    "mtfema": ("strategy.mtf_ema_period", "int", "فترة متوسط الإطار الأعلى — 50"),
    "volmin": ("strategy.volatility_min_pct", "float", "أدنى تقلّب مسموح (ATR%) — مثال: 0.003"),
    "volmax": ("strategy.volatility_max_pct", "float", "أقصى تقلّب مسموح (ATR%) — مثال: 0.02"),
    # ── معاملات الاستراتيجيات (يفيدها مُحسِّن المعاملات) ──
    "sislow": ("strategy.scalping_i.ema_slow", "int", "scalping_i: EMA بطيء — 50"),
    "sifast": ("strategy.scalping_i.ema_fast", "int", "scalping_i: EMA سريع — 30"),
    "sirsilen": ("strategy.scalping_i.rsi_length", "int", "scalping_i: فترة RSI — 10"),
    "sibb": ("strategy.scalping_i.bb_length", "int", "scalping_i: فترة بولينجر — 15"),
    "sibbstd": ("strategy.scalping_i.bb_std", "float", "scalping_i: انحراف بولينجر — 1.5"),
    "siatr": ("strategy.scalping_i.atr_length", "int", "scalping_i: فترة ATR — 7"),
    "sibc": ("strategy.scalping_i.backcandles", "int", "scalping_i: شموع النظر للخلف — 7"),
    "sisl": ("strategy.scalping_i.sl_coef", "float", "scalping_i: معامل الوقف — 1.1"),
    "sitp": ("strategy.scalping_i.tp_sl_ratio", "float", "scalping_i: نسبة الهدف للوقف — 1.5"),
    "rsiper": ("strategy.rsi.period", "int", "rsi_williams: فترة RSI — 14"),
    "rsios": ("strategy.rsi.oversold", "float", "rsi_williams: تشبّع بيعي — 30"),
    "rsiob": ("strategy.rsi.overbought", "float", "rsi_williams: تشبّع شرائي — 70"),
    "rsilook": ("strategy.rsi.lookback", "int", "rsi_williams: شموع النظر للخلف — 3"),
    "wper": ("strategy.williams_r.lbp", "int", "rsi_williams: فترة وليامز — 24"),
    "wos": ("strategy.williams_r.oversold", "float", "rsi_williams: وليامز تشبّع بيعي — -75"),
    "wob": ("strategy.williams_r.overbought", "float", "rsi_williams: وليامز تشبّع شرائي — -25"),
    "wema": ("strategy.williams_r.ema_window", "int", "rsi_williams: نافذة تنعيم وليامز — 24"),
    "trend": ("strategy.trend_filter", "choice:off,ema",
              "فلتر الاتجاه: off = حرفي · ema = ارفض الإشارات عكس الاتجاه العام"),
    "trendperiod": ("strategy.trend_period", "int", "فترة EMA لفلتر الاتجاه — مثال: 200"),
    "interval": ("scanner.interval_seconds", "int", "مدة الفحص بالثواني — مثال: 120"),
    "ttl": ("scanner.signal_ttl_seconds", "int", "مدة صلاحية الإشارة بالثواني — مثال: 900"),
    "cooldown": ("scanner.cooldown_seconds", "int", "فترة السمومية لكل رمز بالثواني — مثال: 1800"),
    "maxpos": ("risk.max_positions", "int", "أقصى عدد صفقات مفتوحة — مثال: 5"),
    "topn": ("scanner.top_n", "int", "عدد الرموز المفحوصة — 0 = كل العملات"),
    "maxsig": ("scanner.max_signals_per_scan", "int", "أقصى إشارات في الفحص الواحد — مثال: 5"),
    "minnotional": ("risk.min_notional", "float", "أدنى قيمة للصفقة بالـ USDT — مثال: 20"),
    "sizing": ("risk.sizing", "choice:fixed,risk",
               "حجم الصفقة: fixed = ثابت · risk = خسارة ثابتة = نسبة من الرصيد"),
    "riskpct": ("risk.risk_per_trade_pct", "float",
                "نسبة المخاطرة من الرصيد لكل صفقة — مثال: 0.01 (1%)"),
    "maxqty": ("risk.max_qty_usdt", "float", "أقصى قيمة للصفقة بالـ USDT (0 = بلا حد)"),
    "maxtrades": ("risk.max_trades_per_hour", "int", "أقصى صفقات في الساعة (0 = بلا حد)"),
    "mingap": ("risk.min_gap_seconds", "int", "فاصل إلزامي بين صفقتين بالثواني"),
    "maxlosses": ("risk.max_consecutive_losses", "int",
                  "قاطع: أوقف التداول بعد كم خسارة متتالية (0 = معطّل)"),
    "pauseloss": ("risk.pause_after_losses_seconds", "int", "مدة الإيقاف بالثواني بعد القاطع"),
    "mode": ("execution.mode", "choice:manual,auto", "وضع التنفيذ"),
    "dryrun": ("safety.dry_run", "bool", "المحاكاة (لا تُرسل أوامر حقيقية)"),
    "both": ("strategy.require_both", "bool", "التأكيد المزدوج (RSI + Williams %R)"),
}


def restricted(func):
    """يمنع غير المصرّح لهم من استخدام البوت."""

    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        uid = user.id if user else None
        if not self._is_allowed(uid):
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"🚫 غير مصرّح لك باستخدام هذا البوت.\nمعرفك: <code>{uid}</code>",
                    parse_mode=ParseMode.HTML,
                )
            log.warning("محاولة وصول مرفوضة من %s", uid)
            return None
        return await func(self, update, context, *args, **kwargs)

    return wrapper


class TelegramBot:
    def __init__(self, secrets: Secrets, config: Config, trader: Trader):
        self.secrets = secrets
        self.cfg = config
        self.trader = trader
        self.allowed = set(secrets.chat_ids or [])
        self.known: set[int] = set(secrets.chat_ids or [])
        self._scan_task = None          # حلقة فحص احتياطية عند غياب JobQueue
        self._scan_lock = None          # يُنشأ داخل حلقة الأحداث
        self.app = (
            ApplicationBuilder()
            .token(secrets.telegram_token)
            .post_init(self._post_init)
            .post_stop(self._post_stop)
            .build()
        )
        self._register()

    # ═══════════════════ إذن الوصول ═══════════════════
    def _is_allowed(self, uid: int | None) -> bool:
        if uid is None:
            return False
        return not self.allowed or uid in self.allowed

    def _remember(self, uid: int) -> None:
        """عند عدم وجود قائمة بيضاء: نضيف كل من يبدأ البوت لقائمة الإشعارات."""
        if uid and uid not in self.known:
            self.known.add(uid)
            if hasattr(self.trader.notifier, "chat_ids"):
                self.trader.notifier.chat_ids = list(self.known)
            log.info("تم تسجيل المستخدم %s لاستقبال الإشعارات", uid)

    # ═══════════════════ التسجيل ═══════════════════
    def _register(self) -> None:
        h = self.app.add_handler
        for cmd, fn in (
            ("start", self._start),
            ("help", self._help),
            ("id", self._id),
            ("status", self._status),
            ("balance", self._balance),
            ("positions", self._positions),
            ("pnl", self._pnl),
            ("scan", self._scan),
            ("scanall", self._scan_all),
            ("data", self._data),
            ("protect", self._protect),
            ("live", self._live),
            ("dryrun", self._dry_run_mode),
            ("real", self._live),
            ("reload", self._reload),
            ("strategy", self._strategy),
            ("tf", self._timeframe),
            ("stats", self._stats),
            ("dashboard", self._dashboard),
            ("edge", self._edge),
            ("settings", self._settings),
            ("set", self._set),
            ("symbols", self._symbols),
            ("pause", self._pause),
            ("resume", self._resume),
            ("close", self._close),
            ("closeall", self._closeall),
        ):
            h(CommandHandler(cmd, fn))
        h(MessageHandler(filters.TEXT & ~filters.COMMAND, self._text))
        h(CallbackQueryHandler(self._callback))
        self.app.add_error_handler(self._on_error)

    async def _post_init(self, app) -> None:
        # صرامة: تحقّق من اتساق الإعدادات مع الاستراتيجية قبل أول فحص
        for note in self.trader.validate_strategy_config():
            log.warning("إعدادات الاستراتيجية: %s", note.replace("<code>", "").replace("</code>", ""))
        self.trader.attach_notifier(TelegramNotifier(app.bot, list(self.known)))
        self._schedule_scan()
        if not self.known:
            log.warning(
                "لم يتم ضبط TELEGRAM_CHAT_IDS — أرسل /start للبوت من حسابك "
                "ليتمكّن من إرسال الإشارات إليك."
            )
        if self.cfg.get("telegram.notify_startup", True) and self.known:
            for cid in self.known:
                try:
                    await app.bot.send_message(
                        chat_id=cid,
                        text=self._startup_text(),
                        parse_mode=ParseMode.HTML,
                        reply_markup=MAIN_KEYBOARD,
                    )
                except TelegramError as err:
                    log.warning("تعذّر إرسال رسالة الترحيب: %s", err)
        log.info("✅ البوت جاهز — %s (%s)", self.trader.exchange.name,
                 "تيستنت" if self.trader.exchange.testnet else "حقيقي")

    async def _post_stop(self, app) -> None:  # pragma: no cover
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            self._scan_task = None
        log.info("تم إيقاف البوت")

    def _startup_text(self) -> str:
        net = "تيستنت 🧪" if self.trader.exchange.testnet else "حقيقي 🔴"
        mode = "يدوي (بانتظار تأكيدك)" if not self.trader.is_auto else "تلقائي"
        if bool(self.cfg.get("safety.dry_run", False)):
            exec_line = ("التنفيذ: 🧪 <b>محاكاة</b> — لن تُرسل أي أوامر "
                         "(للتنفيذ الحقيقي: /live)")
        else:
            exec_line = "التنفيذ: 🔴 <b>أوامر حقيقية</b> تُرسل إلى المنصة"
        strategy = self.trader.strategy
        exit_ar = "ATR" if strategy.exit_mode == "atr" else "نسب ثابتة"
        warnings = list(getattr(self.trader, "strategy_warnings", []))
        return "\n".join(
            [
                "🚀 <b>بوت Stratig يعمل الآن</b>",
                "",
                f"المنصة: <code>{fmt.esc(self.trader.exchange.name)}</code> — {net}",
                f"الاستراتيجية: <code>{fmt.esc(strategy.key)}</code> — {fmt.esc(strategy.title)}",
                f"المخارج: {exit_ar}",
                f"الإطار الزمني: <code>{fmt.esc(self.cfg.effective_timeframe())}</code>",
                f"وضع التنفيذ: {mode}",
                exec_line,
                f"الفحص: كل {self.cfg.get('scanner.interval_seconds')} ثانية",
            ]
            + (["", "⚠️ <b>تحذيرات الاتساق</b>"] + [f"  • {w}" for w in warnings] if warnings else [])
            + [
                "",
                "اضغط 🔍 فحص الآن لتفحص السوق فوراً، أو ❔ مساعدة لكل الأوامر.",
            ]
        )

    # ═══════════════════ المهمة الدورية ═══════════════════
    def _schedule_scan(self) -> None:
        jq = self.app.job_queue
        if jq is None:
            # لا توجد JobQueue (لم تُثبّت apscheduler) → نستخدم حلقة داخلية
            log.warning(
                "JobQueue غير متاحة — سيتم استخدام حلقة فحص داخلية. "
                "للميزة الكاملة ثبّت: pip install \"python-telegram-bot[job-queue]\""
            )
            if self._scan_task is None or self._scan_task.done():
                self._scan_task = asyncio.create_task(self._scan_loop())
            return

        for job in jq.get_jobs_by_name("scanner"):
            job.schedule_removal()
        jq.run_repeating(
            self._scan_job,
            interval=max(30, int(self.cfg.get("scanner.interval_seconds", 120))),
            first=10,
            name="scanner",
            # قفلنا الداخلي (self._scan_lock) يمنع تراكب دورتين فعلياً؛
            # هذه الإعدادات تمنع تحذير apscheduler المزعج عند تجاوز مدة الفحص.
            job_kwargs={"max_instances": 3, "coalesce": True, "misfire_grace_time": 60},
        )
        log.info("تم جدولة الفحص التلقائي كل %s ثانية",
                 self.cfg.get("scanner.interval_seconds", 120))

    async def _scan_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._run_scan_cycle()

    async def _scan_loop(self) -> None:
        """بديل عن JobQueue: حلقة فحص داخلية تعمل في الخلفية."""
        log.info("تم تشغيل حلقة الفحص الداخلية")
        while True:
            try:
                interval = max(30, int(self.cfg.get("scanner.interval_seconds", 120)))
                await asyncio.sleep(interval)
                if not self.trader.running:
                    continue
                await self._run_scan_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # الحلقة يجب ألا تسقط البوت أبداً
                log.exception("خطأ في حلقة الفحص الداخلية: %s", err)
                await asyncio.sleep(30)

    def _get_scan_lock(self):
        if self._scan_lock is None:      # يُنشأ داخل حلقة الأحداث لتجنّب ربطه بحلقة أخرى
            self._scan_lock = asyncio.Lock()
        return self._scan_lock

    def _reload_config_if_changed(self) -> None:
        """يلتقط التعديلات اليدوية على config.toml أثناء عمل البوت."""
        if not self.cfg.reload():
            return
        log.info("🔁 تم تحديث الإعدادات من %s", self.cfg.path)
        exchange = getattr(self.trader, "exchange", None)
        if exchange is not None:
            exchange.dry_run = bool(self.cfg.get("safety.dry_run", False))
        self.trader.invalidate_symbols()
        self._schedule_scan()

    async def _run_scan_cycle(self) -> None:
        lock = self._get_scan_lock()
        if lock.locked():
            log.info("تخطّي دورة الفحص: الدورة السابقة لم تنتهِ بعد")
            return
        async with lock:
            try:
                self._reload_config_if_changed()
            except Exception as err:
                log.warning("تعذّرت إعادة قراءة الإعدادات: %s", err)
            try:
                await self.trader.notify_expired()
                await self.trader.manage_positions()   # تعادل / متحرك / إغلاق
                await self.trader.scan_once()
                await asyncio.to_thread(self.trader.push_to_supabase)
            except Exception as err:  # مهمة دورية يجب ألا تسقط البوت
                log.exception("خطأ في مهمة الفحص: %s", err)

    # ═══════════════════ الأوامر ═══════════════════
    async def _reply(self, update: Update, text: str, keyboard=None, **kwargs):
        return await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
            **kwargs,
        )

    @restricted
    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._remember(update.effective_user.id)
        await self._reply(update, self._startup_text(), MAIN_KEYBOARD)

    @restricted
    async def _help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._reply(update, fmt.help_text())

    @restricted
    async def _id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._reply(
            update,
            f"🆔 معرفك: <code>{update.effective_user.id}</code>\n"
            f"ضعه في <code>TELEGRAM_CHAT_IDS</code> داخل ملف .env",
        )

    @restricted
    async def _status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        st = await asyncio.to_thread(self.trader.status)
        await self._reply(update, fmt.status_text(st))

    @restricted
    async def _balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = await self._reply(update, "⏳ جارٍ جلب الرصيد…")
        try:
            bal = await self._to_thread(self.trader.exchange.balance)
            await msg.edit_text(
                fmt.balance_text(bal, self.trader.exchange.name, self.trader.exchange.testnet),
                parse_mode=ParseMode.HTML,
            )
        except Exception as err:
            await msg.edit_text(f"❌ تعذّر جلب الرصيد:\n<code>{fmt.esc(str(err))}</code>",
                                parse_mode=ParseMode.HTML)

    @restricted
    async def _positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = await self._reply(update, "⏳ جارٍ جلب الصفقات…")
        try:
            positions = await self._to_thread(self.trader.exchange.positions)
        except Exception as err:
            await msg.edit_text(f"❌ تعذّر جلب الصفقات:\n<code>{fmt.esc(str(err))}</code>",
                                parse_mode=ParseMode.HTML)
            return
        keyboard = None
        if positions:
            keyboard = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(f"🔒 إغلاق {p.symbol}", callback_data=f"pos:{p.symbol}:ask")]
                    for p in positions[:10]
                ]
                + [[InlineKeyboardButton("🔒 إغلاق الكل", callback_data="closeall:ask")]]
            )
        await msg.edit_text(fmt.positions_text(positions), parse_mode=ParseMode.HTML,
                            reply_markup=keyboard)

    @restricted
    async def _pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = await self._reply(update, "⏳ جارٍ حساب الأرباح…")
        try:
            today = await self._to_thread(self.trader.daily_realized_pnl)
            recent = await self._to_thread(self.trader.exchange.recent_pnl, 50)
            await msg.edit_text(fmt.pnl_text(today, recent), parse_mode=ParseMode.HTML)
        except Exception as err:
            await msg.edit_text(f"❌ تعذّر حساب الأرباح:\n<code>{fmt.esc(str(err))}</code>",
                                parse_mode=ParseMode.HTML)

    @restricted
    async def _scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = await self._reply(update, "🔍 جارٍ فحص السوق…")
        found = await self.trader.scan_once(manual=True)
        await msg.edit_text(await self._scan_summary(found), parse_mode=ParseMode.HTML)

    async def _scan_summary(self, found) -> str:
        """ملخص نتيجة الفحص + تنبيه إن كانت القائمة صغيرة جداً."""
        source_names = {"manual": "قائمة يدوية", "auto": "أعلى الرموز نشاطاً", "all": "كل العملات"}
        source = source_names.get(self.trader.last_scan_source, "—")
        lines = [
            "✅ <b>انتهى الفحص</b>",
            "",
            f"الرموز المفحوصة: <b>{self.trader.last_scan_symbols}</b>",
            f"المصدر: {source}",
            f"الإشارات الجديدة: <b>{len(found)}</b>",
            f"المدة: {self.trader.last_scan_duration:.1f} ثانية",
        ]
        if self.trader.is_auto:
            lines.append("\n<i>الوضع التلقائي: تم فتح الصفقات إن وُجدت</i>")
        elif found:
            lines.append("\n👇 راجع الإشارات بالأعلى واضغط ✅ أو ❌")

        if self.trader.last_scan_symbols <= 3:
            lines += [
                "",
                "⚠️ <b>عدد الرموز المفحوصة قليل جداً!</b>",
                "السبب غالباً: القائمة اليدوية تحتوي رمزاً واحداً.",
                "اضغط الزر بالأسفل لفحص كل العملات، أو أرسل /symbols لإدارة القائمة.",
            ]
        return "\n".join(lines)

    @restricted
    async def _scan_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """فحص كل العملات المتاحة على المنصة (بدون حد top_n)."""
        msg = await self._reply(update, "🌐 جارٍ جلب كل الرموز المتاحة…")
        try:
            all_symbols = await self._to_thread(self.trader.available_symbols)
        except Exception as err:
            await msg.edit_text(f"❌ تعذّر جلب الرموز:\n<code>{fmt.esc(str(err))}</code>",
                                parse_mode=ParseMode.HTML)
            return

        total = len(all_symbols)
        delay = float(self.cfg.get("scanner.request_delay", 0.2) or 0)
        eta = int(total * delay)
        await msg.edit_text(
            f"🌐 جارٍ فحص <b>كل العملات</b>: {total} رمز\n"
            f"⏱ الوقت المتوقع: نحو {eta} ثانية…",
            parse_mode=ParseMode.HTML,
        )

        found = await self.trader.scan_once(manual=True, symbols=all_symbols)

        extra = ""
        if self.trader.is_auto:
            extra = "\n(الوضع التلقائي: تم فتح الصفقات إن وُجدت)"
        elif found:
            extra = "\n👇 راجع الإشارات بالأعلى واضغط ✅ أو ❌"
        await msg.edit_text(
            f"✅ انتهى فحص <b>كل العملات</b>\n"
            f"الرموز المفحوصة: {total}\n"
            f"الإشارات الجديدة: {len(found)}\n"
            f"المدة: {self.trader.last_scan_duration:.1f} ثانية{extra}",
            parse_mode=ParseMode.HTML,
        )

    @restricted
    async def _data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """يعرض مصدر البيانات: هل الشموع حقيقية من المنصة أم محاكاة؟"""
        msg = await self._reply(update, "🔎 جارٍ التحقق من مصدر البيانات…")
        trader = self.trader
        exchange = trader.exchange
        symbol = (trader.symbols() or ["BTCUSDT"])[0]
        try:
            candles = await self._to_thread(exchange.klines, symbol,
                                            str(self.cfg.get("strategy.timeframe", "15m")), 10)
            price = await self._to_thread(exchange.mark_price, symbol)
        except Exception as err:
            await msg.edit_text(f"❌ تعذّر الاتصال بالمنصة:\n<code>{fmt.esc(str(err))}</code>",
                                parse_mode=ParseMode.HTML)
            return

        last_ts = candles.times[-1] / 1000
        age = (time.time() - last_ts) / 60
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(last_ts))
        url = getattr(exchange, "api_url", None) or "—"

        lines = [
            "🔎 <b>مصدر البيانات</b>",
            "",
            f"المنصة: <code>{fmt.esc(exchange.name)}</code>",
            f"الرابط: <code>{fmt.esc(str(url))}</code>",
            f"الشبكة: {'تيستنت (أموال وهمية)' if exchange.testnet else 'حقيقي 🔴'}",
            f"المحاكاة: {'مُفعّلة — لا تُرسل أوامر 🧪' if self.cfg.get('safety.dry_run') else 'معطّلة — تُرسل أوامر'}",
            "",
            f"آخر شمعة <code>{fmt.esc(symbol)}</code>:",
            f"  الوقت (UTC): {stamp}",
            f"  الإغلاق: <code>{fmt.num(candles.close[-1])}</code>",
            f"  السعر الآن: <code>{fmt.num(price)}</code>",
            f"  عمرها: {age:.1f} دقيقة",
            "",
            "✅ <b>الشموع حقيقية</b> — مأخوذة مباشرة من API المنصة.",
            "❌ لا تُستخدم أي بيانات اصطناعية في التشغيل الفعلي.",
        ]
        if exchange.testnet:
            lines += ["", "ℹ️ الأسعار من السوق التجريبي لBinance، والأموال وهمية."]
        drift = getattr(exchange, "time_sync", None)
        if drift is not None:
            lines += ["", f"🕒 التوقيت: {fmt.esc(drift.describe())}"]
        if age > 90:
            lines += ["", "⚠️ آخر شمعة قديمة — تحقّق من اتصال الإنترنت."]
        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)

    @restricted
    async def _protect(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """يتحقق أن لكل صفقة مفتوحة وقف خسارة وجني أرباح مسجَّلين في المنصة."""
        msg = await self._reply(update, "🛡 جارٍ فحص حماية الصفقات…")
        exchange = self.trader.exchange

        try:
            positions = await self._to_thread(exchange.positions)
        except Exception as err:
            await msg.edit_text(f"❌ تعذّر جلب الصفقات:\n<code>{fmt.esc(str(err))}</code>",
                                parse_mode=ParseMode.HTML)
            return

        algos: list = []
        has_algo = callable(getattr(exchange, "open_algo_orders", None))
        if has_algo:
            try:
                algos = await self._to_thread(exchange.open_algo_orders)
            except Exception as err:
                log.warning("تعذّر جلب الأوامر الشرطية: %s", err)

        by_symbol: dict = {}
        for order in algos:
            if not isinstance(order, dict):
                continue
            otype = str(order.get("orderType") or order.get("type") or "")
            by_symbol.setdefault(str(order.get("symbol")), set()).add(otype)

        if not positions:
            await msg.edit_text("📈 لا توجد صفقات مفتوحة — لا شيء لفحصه. ✅",
                                parse_mode=ParseMode.HTML)
            return

        lines = ["🛡 <b>حماية الصفقات المفتوحة</b>", ""]
        unprotected = 0
        for pos in positions:
            types = by_symbol.get(pos.symbol, set())
            has_sl = bool(types & {"STOP_MARKET", "STOP"})
            has_tp = bool(types & {"TAKE_PROFIT_MARKET", "TAKE_PROFIT"})
            if not has_sl:
                unprotected += 1
            lines += [
                f"{'🟢' if pos.side == 'buy' else '🔴'} <code>{fmt.esc(pos.symbol)}</code> "
                f"×{pos.leverage:g}",
                f"   وقف الخسارة: {'✅' if has_sl else '❌ <b>غير موجود</b>'}"
                f" | جني الأرباح: {'✅' if has_tp else '—'}",
            ]

        lines += [""]
        if unprotected:
            lines += [
                f"❌ <b>{unprotected} صفقة بلا وقف خسارة!</b>",
                "أغلقها يدوياً من المنصة، أو أرسل /closeall.",
            ]
        else:
            lines += ["✅ كل صفقة مفتوحة عليها وقف خسارة مسجَّل في المنصة."]
        if has_algo:
            lines += ["", f"<i>الأوامر الشرطية المفتوحة: {len(algos)} "
                          "(تُقرأ من نقطة Algo /fapi/v1/openAlgoOrders)</i>"]
        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)

    @restricted
    async def _live(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/live — تفعيل التنفيذ الحقيقي: كل تأكيد يُرسل أمراً فعلياً للمنصة."""
        await self._reply(update, self._toggle_dry_run(False))

    @restricted
    async def _dry_run_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/dryrun — وضع المحاكاة: تحليل حقيقي بلا أي أوامر."""
        await self._reply(update, self._toggle_dry_run(True))

    def _toggle_dry_run(self, dry: bool) -> str:
        """يبدّل وضع المحاكاة فوراً (بدون إعادة تشغيل) ويحفظه في config.toml."""
        self.cfg.set("safety.dry_run", bool(dry))
        try:
            self.cfg.save()
            saved = "✅ حُفظ في config.toml"
        except Exception as err:  # pragma: no cover
            log.warning("تعذّر حفظ الإعدادات: %s", err)
            saved = "⚠️ لم يُحفظ في الملف (سيعود بعد إعادة التشغيل)"

        exchange = getattr(self.trader, "exchange", None)
        synced = ""
        if exchange is not None:
            exchange.dry_run = bool(dry)          # تطبيق فوري على كائن المنصة
            synced = "وطُبّق فوراً على جلسة المنصة"

        net = "تيستنت 🧪 (أموال وهمية)" if (exchange is None or exchange.testnet) else "حقيقي 🔴"

        if dry:
            return "\n".join(
                [
                    "🧪 <b>وضع المحاكاة مُفعّل</b>",
                    "",
                    "لن تُرسل <b>أي أوامر</b> إلى المنصة.",
                    "الإشارات والتحليل يعملان بشكل حقيقي، لكن التنفيذ وهمي.",
                    "",
                    f"{saved} {synced}".strip(),
                    "",
                    "للتنفيذ الحقيقي: /live  (أو /set dryrun false)",
                ]
            )
        return "\n".join(
            [
                "🔴 <b>التنفيذ الحقيقي مُفعّل</b>",
                "",
                f"الشبكة: {net}",
                "عند ضغط ✅ على أي إشارة يُرسل البوت أمراً <b>فعلياً</b> إلى المنصة،",
                "مع وقف خسارة وجني أرباح تلقائيين.",
                "",
                f"{saved} {synced}".strip(),
            ]
        )

    @restricted
    async def _timeframe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/tf 5m — اختصار لتغيير الإطار الزمني."""
        args = context.args or []
        if not args:
            await self._reply(update, self._timeframe_text())
            return
        ok, message = self._apply_setting("tf", args[0])
        await self._reply(update, message)

    def _timeframe_text(self) -> str:
        current = str(self.cfg.get("strategy.timeframe", "15m"))
        pending = sum(1 for s in self.trader.cooldown.values() if s > time.time())
        return "\n".join(
            [
                "⏱ <b>الإطار الزمني</b>",
                "",
                f"الحالي: <code>{fmt.esc(current)}</code>",
                f"رموز داخل فترة السمومية: {pending}",
                "",
                "للتغيير: <code>/tf 5m</code> أو <code>/set tf 1h</code>",
                f"المسموح: <code>{'  '.join(ALLOWED_TIMEFRAMES)}</code>",
                "",
                "<i>تغيير الإطار يمسح فترة السمومية تلقائياً ليظهر أثره في الفحص القادم.</i>",
            ]
        )

    @restricted
    async def _reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/reload — إعادة قراءة config.toml من القرص (للتعديلات اليدوية)."""
        changed = self.cfg.reload()
        if not changed:
            await self._reply(
                update,
                f"ℹ️ لا تغييرات في <code>{fmt.esc(str(self.cfg.path))}</code>\n"
                "للتعديل من تليجرام استخدم /set أو /tf",
            )
            return
        exchange = getattr(self.trader, "exchange", None)
        if exchange is not None:
            exchange.dry_run = bool(self.cfg.get("safety.dry_run", False))
        self.trader.invalidate_symbols()
        self._schedule_scan()
        await self._reply(
            update,
            "🔁 <b>تم تحديث الإعدادات من الملف</b>\n\n"
            f"الإطار الزمني: <code>{fmt.esc(str(self.cfg.get('strategy.timeframe')))}</code>\n"
            f"المحاكاة: <code>{self.cfg.get('safety.dry_run')}</code>\n"
            f"مدة الفحص: <code>{self.cfg.get('scanner.interval_seconds')}</code> ثانية",
        )

    def _switch_strategy(self, key: str) -> str:
        """يبدّل الاستراتيجية فوراً (مع وضع الخروج المناسب لها) — بصرامة."""
        strategy = get_strategy(key)
        previous = self.cfg.get("strategy.name")
        self.cfg.set("strategy.name", strategy.key)
        self.cfg.set("exit.mode", strategy.exit_mode)
        try:
            self.cfg.save()
            saved = "✅ حُفظ في config.toml"
        except Exception as err:  # pragma: no cover
            log.warning("تعذّر حفظ الإعدادات: %s", err)
            saved = "⚠️ لم يُحفظ في الملف"

        cleared = self.trader.on_timeframe_changed()   # يمسح السمومية ليظهر أثرها فوراً
        self.trader.invalidate_symbols()
        mode_ar = "ATR (حسب الاستراتيجية)" if strategy.exit_mode == "atr" else "نسب ثابتة"
        return "\n".join(
            [
                "🧠 <b>تم تغيير الاستراتيجية</b>",
                "",
                f"<code>{fmt.esc(str(previous))}</code> ← <b>{fmt.esc(strategy.key)}</b>",
                fmt.esc(strategy.title),
                "",
                f"مخارج الصفقة: {mode_ar}",
                f"مُسحت السمومية عن {cleared} رمزاً — تُستخدم في الفحص القادم.",
            ]
            + [f"🔒 <b>صرامة</b>: {note}" for note in self.trader.validate_strategy_config()]
            + [saved]
        )

    async def _show_switched(self, query, text: str) -> None:
        """يعرض نتيجة التبديل: يحاول تعديل الرسالة، وإن رفض تليجرام يرسل رسالة جديدة.

        تليجرام يمنع تعديل رسالة مضى عليها أكثر من 48 ساعة (أو إن لم تتغيّر)،
        فيبدو الزر وكأنه «لا يعمل» — لذا نرسل رسالة جديدة بدلاً من الصمت.
        """
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML)
            return
        except Exception as err:  # pragma: no cover - يعتمد على حالة الرسالة
            log.debug("تعذّر تعديل الرسالة، سأرسل رسالة جديدة: %s", err)
        try:
            await query.answer("✅ تم تغيير الاستراتيجية", show_alert=True)
        except Exception:  # pragma: no cover
            pass
        message = getattr(query, "message", None)
        if message is not None:
            await message.reply_text(text, parse_mode=ParseMode.HTML)

    @restricted
    async def _strategy(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/strategy — عرض الاستراتيجيات أو التبديل بينها."""
        args = context.args or []
        if args:
            key = str(args[0]).strip().lower()
            if not is_supported_strategy(key):
                allowed = ", ".join(item.key for item in all_strategies())
                await self._reply(
                    update, f"❌ استراتيجية غير معروفة. المتاحة: <code>{fmt.esc(allowed)}</code>"
                )
                return
            await self._reply(update, self._switch_strategy(key))
            return
        await self._reply(update, self._strategy_text(), self._strategy_keyboard())

    def _strategy_text(self) -> str:
        current = get_strategy(self.cfg.get("strategy.name"))
        follow = bool(self.cfg.get("exit.follow_strategy", True))
        strict = bool(self.cfg.get("exit.strict", True))
        lines = [
            "🧠 <b>الاستراتيجيات</b>",
            "",
            f"الحالية: <code>{fmt.esc(current.key)}</code> — {fmt.esc(current.title)}",
            f"المخارج: {'ATR' if current.exit_mode == 'atr' else 'نسب ثابتة'}",
            f"الصرامة: {'🔒 مُفعّلة' if (follow and strict) else '🔓 مخفّفة'} "
            f"(تتبع الاستراتيجية: {follow} | رفض المخارج الدخيلة: {strict})",
            "",
        ]
        for item in all_strategies():
            mark = "▶️" if item.key == current.key else "▫️"
            lines += [
                f"{mark} <code>{fmt.esc(item.key)}</code> — {fmt.esc(item.title)}",
                f"   {fmt.esc(item.description)}",
            ]
        warnings = list(getattr(self.trader, "strategy_warnings", []))
        if warnings:
            lines += ["", "⚠️ <b>تحذيرات الاتساق</b>"] + [f"  • {w}" for w in warnings]
        lines += ["", "<i>للتبديل: /strategy scalping_i أو اضغط الزر أدناه.</i>"]
        return "\n".join(lines)

    def _strategy_keyboard(self) -> InlineKeyboardMarkup:
        current = get_strategy(self.cfg.get("strategy.name"))
        rows = [
            [InlineKeyboardButton(f"🧠 {item.title}", callback_data=f"strat:{item.key}")]
            for item in all_strategies()
            if item.key != current.key
        ]
        return InlineKeyboardMarkup(rows)

    @restricted
    async def _stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/stats — إحصائياتك الحقيقية من سجل الصفقات."""
        await self._reply(
            update,
            fmt.stats_text(self.trader.journal, self.trader.rate, self.trader.breaker),
        )

    @restricted
    async def _dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/dashboard — رابط لوحة التحكم (محلياً أو على Vercel)."""
        dash = getattr(self.trader, "dashboard", None)
        lines = []
        if dash is not None:
            lines.append("🖥 <b>لوحة التحكم المحلية</b>:")
            lines.append("<code>" + fmt.esc(dash.url) + "</code>")
            lines.append("افتحها من متصفح على نفس الجهاز.")
        else:
            lines.append(
                "⚠️ اللوحة المحلية مُعطّلة. فعّلها بـ "
                "<code>/set webenable true</code> ثم أعد تشغيل البوت."
            )
        if bool(self.cfg.get("supabase.enabled", False)):
            lines.append(
                "☁️ الرفع إلى Supabase <b>مُفعّل</b> — افتح لوحة Vercel من أي مكان."
            )
        else:
            lines.append(
                "☁️ للوصول من هاتفك: فعّل <code>supabase.enabled</code> في config.toml."
            )
        await self._reply(update, "\n\n".join(lines))

    @restricted
    async def _edge(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/edge — هل استراتيجيتك رابحة إحصائياً؟ (فترة ثقة 95%)."""
        await self._reply(update, fmt.edge_text(self.trader.edge_report()))

    @restricted
    async def _settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._reply(update, fmt.settings_text(self.cfg))

    # ── /set ──
    @restricted
    async def _set(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if len(args) >= 2:
            ok, message = self._apply_setting(args[0].lower(), " ".join(args[1:]))
            await self._reply(update, message)
            return
        if len(args) == 1:
            key = args[0].lower()
            if key not in SET_KEYS:
                await self._reply(update, f"❌ إعداد غير معروف: <code>{fmt.esc(key)}</code>")
                return
            context.user_data["await"] = key
            await self._reply(update, f"✏️ أرسل القيمة الجديدة لـ <b>{key}</b>:\n{SET_KEYS[key][2]}")
            return
        await self._reply(update, "⚙️ اختر الإعداد الذي تريد تعديله:", self._settings_keyboard())

    def _settings_keyboard(self) -> InlineKeyboardMarkup:
        keys = list(SET_KEYS)
        rows = [
            [InlineKeyboardButton(k, callback_data=f"set:{k}") for k in keys[i : i + 4]]
            for i in range(0, len(keys), 4)
        ]
        return InlineKeyboardMarkup(rows)

    def _apply_setting(self, key: str, raw: str) -> tuple[bool, str]:
        """يطبّق قيمة جديدة ويحفظها في config.toml."""
        if key not in SET_KEYS:
            return False, f"❌ إعداد غير معروف: {fmt.esc(key)}"
        path, kind, hint = SET_KEYS[key]
        text = str(raw).strip()

        try:
            if kind.startswith("choice:"):
                options = kind.split(":", 1)[1].split(",")
                if text.lower() not in options:
                    return False, f"❌ القيمة يجب أن تكون أحد: {', '.join(options)}"
                value: object = text.lower()
            elif kind == "bool":
                value = text.lower() in ("1", "true", "yes", "on", "نعم", "مفعّل")
            elif kind == "int":
                value = int(float(text))
            elif kind == "float":
                value = float(text.replace("%", "")) / 100 if text.endswith("%") else float(text)
            else:
                value = text.lower() if key == "tf" else text
        except (TypeError, ValueError):
            return False, f"❌ قيمة غير صالحة. {hint}"

        if key == "tf":
            # 5 / 5min / 5M / 1h → 5m / 1h … ورفض ما لا تقبله المنصة
            normalized = normalize_timeframe(value)
            if not is_supported_timeframe(normalized):
                allowed = "  ".join(ALLOWED_TIMEFRAMES)
                return False, (
                    f"❌ إطار زمني غير مدعوم: <code>{fmt.esc(text)}</code>\n"
                    f"المسموح: <code>{allowed}</code>"
                )
            value = normalized

        # تحققات إضافية
        checks = {
            "lev": lambda v: 1 <= int(v) <= 125 or "الرافعة بين 1 و 125",
            "tp": lambda v: 0 < float(v) < 1 or "جني الأرباح بين 0 و 1 (مثال 0.02)",
            "sl": lambda v: 0 < float(v) < 1 or "وقف الخسارة بين 0 و 1 (مثال 0.01)",
            "qty": lambda v: float(v) > 0 or "حجم الصفقة يجب أن يكون أكبر من صفر",
            "interval": lambda v: int(v) >= 30 or "مدة الفحص 30 ثانية على الأقل",
            "ttl": lambda v: int(v) >= 60 or "مدة الإشارة 60 ثانية على الأقل",
            "cooldown": lambda v: int(v) >= 0 or "قيمة غير صالحة",
            "maxpos": lambda v: 1 <= int(v) <= 50 or "أقصى صفقات بين 1 و 50",
            "topn": lambda v: 0 <= int(v) <= 2000 or "عدد الرموز بين 0 و 2000 (0 = الكل)",
            "maxsig": lambda v: 1 <= int(v) <= 50 or "أقصى إشارات بين 1 و 50",
        }
        if key in checks:
            result = checks[key](value)
            if result is not True:
                return False, f"❌ {result}"

        old = self.cfg.get(path)
        self.cfg.set(path, value)
        self.cfg.save()

        if key == "interval":
            self._schedule_scan()
        if key == "topn":
            self.trader.invalidate_symbols()
        if key == "dryrun":
            # مهم: تطبيق فوري على كائن المنصة، وإلا تبقى الأوامر محاكاة حتى إعادة التشغيل
            exchange = getattr(self.trader, "exchange", None)
            if exchange is not None:
                exchange.dry_run = bool(value)
        if key == "strategy":
            return True, self._switch_strategy(str(value))
        if key in ("exit", "follow_exit", "strict", "candles"):
            # صرامة: المخارج تتبع الاستراتيجية المختارة — أي تعارض يُصلح ويُبلَّغ
            notes = self.trader.validate_strategy_config()
            if notes:
                self.cfg.save()
                return True, (
                    f"✅ تم التعديل\n<b>{key}</b>: <code>{fmt.esc(str(old))}</code>"
                    f" ← <code>{fmt.esc(str(self.cfg.get(path)))}</code>\n\n"
                    + "\n".join(f"🔒 {note}" for note in notes)
                )
        if key == "tf":
            # السمومية القديمة كانت تمنع ظهور إشارات الإطار الجديد لمدة 30 دقيقة
            cleared = self.trader.on_timeframe_changed()
            self.trader.invalidate_symbols()
            note = (f"\n⏱ الإطار الزمني الآن <b>{fmt.esc(str(value))}</b>"
                    f" — مُسحت السمومية عن {cleared} رمزاً، ويُستخدم في الفحص القادم.")
            return True, (
                f"✅ تم التعديل\n<b>tf</b>: <code>{fmt.esc(str(old))}</code>"
                f" ← <code>{fmt.esc(str(value))}</code>" + note
            )

        note = "\n🔁 تمت إعادة جدولة الفحص." if key == "interval" else ""
        if key == "dryrun":
            note = "\n🧪 الأوامر الآن محاكاة فقط." if value else (
                "\n🔴 الأوامر الآن <b>حقيقية</b> وتُرسل إلى المنصة فوراً."
            )
        return True, (
            f"✅ تم التعديل\n<b>{key}</b>: <code>{old}</code> ← <code>{value}</code>" + note
        )

    # ── /symbols ──
    @restricted
    async def _symbols(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        source = str(self.cfg.get("scanner.symbols_source", "auto")).lower()
        symbols = self.trader.symbols()
        shown = ", ".join(symbols[:40]) + (" …" if len(symbols) > 40 else "")
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🌐 فحص كل العملات تلقائياً", callback_data="sym:all")],
                [InlineKeyboardButton("🔄 تلقائي (أعلى الرموز نشاطاً)", callback_data="sym:auto")],
                [
                    InlineKeyboardButton("➕ إضافة رمز", callback_data="sym:add"),
                    InlineKeyboardButton("➖ حذف رمز", callback_data="sym:del"),
                ],
            ]
        )
        total = "؟"
        try:
            total = str(len(await self._to_thread(self.trader.available_symbols)))
        except Exception:
            pass
        await self._reply(
            update,
            f"📋 <b>قائمة الرموز</b>\n"
            f"المفحوصة حالياً: {len(symbols)} من {total} رمز متاح على المنصة\n"
            f"المصدر: {source}\n\n<code>{fmt.esc(shown)}</code>",
            keyboard,
        )

    @restricted
    async def _pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.trader.running = False
        await self._reply(update, "⏸ تم إيقاف الفحص التلقائي.\nيمكنك الفحص يدوياً عبر 🔍 فحص الآن.")

    @restricted
    async def _resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.trader.running = True
        await self._reply(
            update, f"▶️ تم تشغيل الفحص التلقائي (كل {self.cfg.get('scanner.interval_seconds')} ثانية)."
        )

    @restricted
    async def _close(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await self._reply(update, "استخدم: <code>/close BTCUSDT</code>")
            return
        symbol = args[0].strip().upper()
        msg = await self._reply(update, f"⏳ جارٍ إغلاق {fmt.esc(symbol)}…")
        result = await self.trader.close_symbol(symbol)
        if result is None:
            await msg.edit_text(f"ℹ️ لا توجد صفقة مفتوحة على {fmt.esc(symbol)}",
                                parse_mode=ParseMode.HTML)

    @restricted
    async def _closeall(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        positions = await self._to_thread(self.trader.exchange.positions)
        if not positions:
            await self._reply(update, "ℹ️ لا توجد صفقات مفتوحة.")
            return
        await self._reply(
            update,
            f"⚠️ هل تريد إغلاق كل الصفقات ({len(positions)})؟",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ نعم، أغلق الكل", callback_data="closeall:yes"),
                        InlineKeyboardButton("❌ إلغاء", callback_data="closeall:no"),
                    ]
                ]
            ),
        )

    # ═══════════════════ النصوص ═══════════════════
    @restricted
    async def _text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (update.effective_message.text or "").strip()

        awaiting = context.user_data.pop("await", None)
        if awaiting:
            if awaiting == "__add_symbol__":
                self.trader.add_symbol(text)
                await self._reply(update, f"➕ تمت إضافة <code>{fmt.esc(text.upper())}</code> للقائمة اليدوية.")
                return
            if awaiting == "__del_symbol__":
                self.trader.remove_symbol(text)
                await self._reply(update, f"➖ تم حذف <code>{fmt.esc(text.upper())}</code> من القائمة اليدوية.")
                return
            ok, message = self._apply_setting(awaiting, text)
            await self._reply(update, message)
            return

        cmd = TEXT_COMMANDS.get(text)
        if not cmd:
            await self._reply(update, "❔ لم أفهم. اكتب /help لعرض الأوامر.")
            return
        handler = {
            "status": self._status,
            "balance": self._balance,
            "positions": self._positions,
            "pnl": self._pnl,
            "stats": self._stats,
            "dashboard": self._dashboard,
            "edge": self._edge,
            "scan": self._scan,
            "scanall": self._scan_all,
            "settings": self._settings,
            "pause": self._pause,
            "resume": self._resume,
            "live": self._live,
            "dryrun": self._dry_run_mode,
            "help": self._help,
        }[cmd]
        await handler(update, context)

    # ═══════════════════ الأزرار ═══════════════════
    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        uid = update.effective_user.id if update.effective_user else None
        if not self._is_allowed(uid):
            await query.answer("🚫 غير مصرّح لك.", show_alert=True)
            return

        data = (query.data or "").split(":")
        kind = data[0]

        # ── تبديل الاستراتيجية ──
        if kind == "strat" and len(data) == 2:
            if not is_supported_strategy(data[1]):
                await query.answer("❌ استراتيجية غير معروفة", show_alert=True)
                return
            await self._show_switched(query, self._switch_strategy(data[1]))
            return

        # ── إشارات ──
        if kind == "sig" and len(data) == 3:
            _, sid, action = data
            if action == "open":
                await query.edit_message_text("⏳ جارٍ إرسال الأمر…")
                result = await self.trader.open_signal(sid)
                if result is None:
                    await query.edit_message_text(
                        "❌ لم يتم فتح الصفقة (انتهت الإشارة أو حدث خطأ — راجع اللوج)."
                    )
            elif action == "skip":
                await self.trader.skip_signal(sid)
            elif action == "info":
                sig = self.trader.pending.get(sid)
                if sig and sig.decision:
                    rsi = sig.decision.rsi
                    wr = sig.decision.willr
                    rsi_txt = f"{rsi.value:.1f}" if rsi else "—"
                    wr_txt = f"{wr.value:.1f}" if wr else "—"
                    await query.answer(
                        f"{sig.symbol}\nRSI: {rsi_txt}\nWilliams %R: {wr_txt}",
                        show_alert=True,
                    )
                else:
                    await query.answer("الإشارة لم تعد متاحة", show_alert=True)
            return

        # ── إغلاق صفقة ──
        if kind == "pos" and len(data) == 3:
            _, symbol, action = data
            if action == "ask":
                await query.edit_message_text(
                    f"⚠️ إغلاق صفقة <code>{fmt.esc(symbol)}</code>؟",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("✅ نعم", callback_data=f"pos:{symbol}:yes"),
                                InlineKeyboardButton("❌ لا", callback_data=f"pos:{symbol}:no"),
                            ]
                        ]
                    ),
                )
            elif action == "yes":
                await query.edit_message_text(f"⏳ جارٍ إغلاق {fmt.esc(symbol)}…", parse_mode=ParseMode.HTML)
                await self.trader.close_symbol(symbol)
            elif action == "no":
                await query.edit_message_text("تم الإلغاء.")
            return

        # ── إغلاق الكل ──
        if kind == "closeall" and len(data) == 2:
            action = data[1]
            if action == "ask":
                await query.edit_message_text(
                    "⚠️ إغلاق <b>كل</b> الصفقات؟",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("✅ نعم، أغلق الكل", callback_data="closeall:yes"),
                                InlineKeyboardButton("❌ إلغاء", callback_data="closeall:no"),
                            ]
                        ]
                    ),
                )
            elif action == "yes":
                await query.edit_message_text("⏳ جارٍ إغلاق كل الصفقات…")
                count = await self.trader.close_all()
                await query.edit_message_text(f"🔒 تم إغلاق {count} صفقة.")
            elif action == "no":
                await query.edit_message_text("تم الإلغاء.")
            return

        # ── الإعدادات ──
        if kind == "set" and len(data) == 2:
            key = data[1]
            if key not in SET_KEYS:
                await query.answer("إعداد غير معروف", show_alert=True)
                return
            path, kind_type, hint = SET_KEYS[key]
            if kind_type.startswith("choice:") or kind_type == "bool":
                options = (
                    kind_type.split(":", 1)[1].split(",")
                    if kind_type.startswith("choice:")
                    else ["true", "false"]
                )
                await query.edit_message_text(
                    f"⚙️ <b>{key}</b> — القيمة الحالية: <code>{self.cfg.get(path)}</code>\n{hint}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(opt, callback_data=f"setv:{key}:{opt}")
                                for opt in options
                            ]
                        ]
                    ),
                )
            else:
                context.user_data["await"] = key
                await query.edit_message_text(f"✏️ أرسل القيمة الجديدة لـ <b>{key}</b>:\n{hint}",
                                              parse_mode=ParseMode.HTML)
            return

        if kind == "setv" and len(data) == 3:
            _, key, value = data
            ok, message = self._apply_setting(key, value)
            await query.edit_message_text(message, parse_mode=ParseMode.HTML)
            return

        # ── الرموز ──
        if kind == "sym" and len(data) == 2:
            action = data[1]
            if action == "all":
                self.trader.use_auto_symbols(all_symbols=True)
                count = await self._to_thread(lambda: len(self.trader.available_symbols()))
                await query.edit_message_text(
                    f"🌐 تم التبديل إلى <b>فحص كل العملات</b> ({count} رمز).\n"
                    f"سيبدأ من الفحص التلقائي القادم — أو اضغط 🌐 فحص كل العملات الآن.",
                    parse_mode=ParseMode.HTML,
                )
            elif action == "auto":
                self.trader.use_auto_symbols()
                await query.edit_message_text("🔄 تم التبديل إلى القائمة التلقائية (أعلى الرموز نشاطاً).")
            elif action == "add":
                context.user_data["await"] = "__add_symbol__"
                await query.edit_message_text("✏️ أرسل رمز الصفقة (مثال: BTCUSDT)")
            elif action == "del":
                context.user_data["await"] = "__del_symbol__"
                await query.edit_message_text("✏️ أرسل الرمز الذي تريد حذفه (مثال: BTCUSDT)")
            return

        await query.answer("أمر غير معروف", show_alert=True)

    # ═══════════════════ مساعدات ═══════════════════
    async def _to_thread(self, func, *args):
        return await asyncio.to_thread(func, *args)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("خطأ غير متوقع: %s", context.error)
        try:
            if isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text(
                    f"⚠️ حدث خطأ: <code>{fmt.esc(str(context.error))}</code>", parse_mode=ParseMode.HTML
                )
        except Exception:  # pragma: no cover
            pass

    # ═══════════════════ التشغيل ═══════════════════
    def run(self) -> None:
        log.info("جارٍ تشغيل البوت…")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
