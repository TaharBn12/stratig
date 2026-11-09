"""بوت تليجرام — تحكم يدوي كامل بالاستراتيجية.

سير العمل في الوضع اليدوي (الافتراضي):
    فحص دوري → إشارة (RSI + Williams %R متفقان) → رسالة بأزرار
    → أنت تضغط ✅ فتح  أو  ❌ تجاهل
"""
from __future__ import annotations

import asyncio
import logging
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
from ..services.notifier import TelegramNotifier
from ..services.trader import Trader
from . import formatters as fmt

log = logging.getLogger(__name__)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 الحالة"), KeyboardButton("💰 الرصيد")],
        [KeyboardButton("📈 الصفقات"), KeyboardButton("💹 الأرباح")],
        [KeyboardButton("🔍 فحص الآن"), KeyboardButton("⚙️ الإعدادات")],
        [KeyboardButton("⏸ إيقاف المسح"), KeyboardButton("▶️ تشغيل المسح")],
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
    "⚙️ الإعدادات": "settings",
    "⏸ إيقاف المسح": "pause",
    "▶️ تشغيل المسح": "resume",
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
    "interval": ("scanner.interval_seconds", "int", "مدة الفحص بالثواني — مثال: 120"),
    "ttl": ("scanner.signal_ttl_seconds", "int", "مدة صلاحية الإشارة بالثواني — مثال: 900"),
    "cooldown": ("scanner.cooldown_seconds", "int", "فترة السمومية لكل رمز بالثواني — مثال: 1800"),
    "maxpos": ("risk.max_positions", "int", "أقصى عدد صفقات مفتوحة — مثال: 5"),
    "topn": ("scanner.top_n", "int", "عدد الرموز المفحوصة — مثال: 40"),
    "minnotional": ("risk.min_notional", "float", "أدنى قيمة للصفقة بالـ USDT — مثال: 20"),
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
        log.info("تم إيقاف البوت")

    def _startup_text(self) -> str:
        net = "تيستنت 🧪" if self.trader.exchange.testnet else "حقيقي 🔴"
        mode = "يدوي (بانتظار تأكيدك)" if not self.trader.is_auto else "تلقائي"
        return "\n".join(
            [
                "🚀 <b>بوت Stratig يعمل الآن</b>",
                "",
                f"المنصة: <code>{fmt.esc(self.trader.exchange.name)}</code> — {net}",
                f"الاستراتيجية: RSI + Williams %R (تأكيد مزدوج: {self.cfg.get('strategy.require_both')})",
                f"الإطار الزمني: {self.cfg.get('strategy.timeframe')}",
                f"وضع التنفيذ: {mode}",
                f"الفحص: كل {self.cfg.get('scanner.interval_seconds')} ثانية",
                "",
                "اضغط 🔍 فحص الآن لتفحص السوق فوراً، أو ❔ مساعدة لكل الأوامر.",
            ]
        )

    # ═══════════════════ المهمة الدورية ═══════════════════
    def _schedule_scan(self) -> None:
        jq = self.app.job_queue
        if jq is None:
            return
        for job in jq.get_jobs_by_name("scanner"):
            job.schedule_removal()
        jq.run_repeating(
            self._scan_job,
            interval=max(30, int(self.cfg.get("scanner.interval_seconds", 120))),
            first=10,
            name="scanner",
        )

    async def _scan_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            await self.trader.notify_expired()
            await self.trader.scan_once()
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
        extra = ""
        if self.trader.is_auto:
            extra = "\n(الوضع التلقائي: تم فتح الصفقات إن وُجدت)"
        elif found:
            extra = "\n👇 راجع الإشارات بالأعلى واضغط ✅ أو ❌"
        await msg.edit_text(
            f"✅ انتهى الفحص — {self.trader.last_scan_symbols} رمز، "
            f"{len(found)} إشارة جديدة، {self.trader.last_scan_duration:.1f} ثانية.{extra}",
            parse_mode=ParseMode.HTML,
        )

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
            "topn": lambda v: 1 <= int(v) <= 200 or "عدد الرموز بين 1 و 200",
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

        return True, (
            f"✅ تم التعديل\n<b>{key}</b>: <code>{old}</code> ← <code>{value}</code>"
            + ("\n🔁 تمت إعادة جدولة الفحص." if key == "interval" else "")
        )

    # ── /symbols ──
    @restricted
    async def _symbols(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        source = str(self.cfg.get("scanner.symbols_source", "auto")).lower()
        symbols = self.trader.symbols()
        shown = ", ".join(symbols[:40]) + (" …" if len(symbols) > 40 else "")
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 تلقائي (أعلى الرموز نشاطاً)", callback_data="sym:auto")],
                [
                    InlineKeyboardButton("➕ إضافة رمز", callback_data="sym:add"),
                    InlineKeyboardButton("➖ حذف رمز", callback_data="sym:del"),
                ],
            ]
        )
        await self._reply(
            update,
            f"📋 <b>قائمة الرموز</b> ({len(symbols)} رمز — المصدر: {source})\n\n<code>{fmt.esc(shown)}</code>",
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
            "scan": self._scan,
            "settings": self._settings,
            "pause": self._pause,
            "resume": self._resume,
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
            if action == "auto":
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
