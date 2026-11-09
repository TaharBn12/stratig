"""تنسيق الرسائل بالعربية (HTML لتليجرام)."""
from __future__ import annotations

import time
from datetime import datetime

from ..exchanges.base import Balance, Position
from ..utils import esc, num  # noqa: F401  (يُستخدمان داخل القوالب)

AR_BUY = "شراء 🟢"
AR_SELL = "بيع 🔴"


def ago(ts: float | None) -> str:
    if not ts:
        return "—"
    seconds = int(time.time() - ts)
    if seconds < 60:
        return f"منذ {seconds} ثانية"
    if seconds < 3600:
        return f"منذ {seconds // 60} دقيقة"
    if seconds < 86400:
        return f"منذ {seconds // 3600} ساعة"
    return f"منذ {seconds // 86400} يوم"


def side_ar(side: str) -> str:
    return AR_BUY if str(side).lower() == "buy" else AR_SELL


def status_text(st: dict) -> str:
    state = "🟢 يعمل" if st["running"] else "⏸ موقوف"
    mode_ar = "تلقائي (بدون تأكيد)" if st["mode"] == "auto" else "يدوي (بتأكيدك)"
    net = "تيستنت 🧪" if st["testnet"] else "حقيقي 🔴"
    lines = [
        "📊 <b>حالة البوت</b>",
        "",
        f"الحالة: {state}",
        f"المنصة: <code>{esc(st['exchange'])}</code> — {net}",
        f"وضع التنفيذ: {mode_ar}",
        f"المحاكاة: {'مفعّلة 🧪' if st['dry_run'] else 'معطّلة'}",
        "",
        f"آخر فحص: {ago(st['last_scan'])} ({st['last_scan_duration']:.1f} ث)",
        f"عدد الرموز المفحوصة: {st['symbols']}",
        f"إشارات بانتظار التأكيد: <b>{st['pending']}</b>",
        "",
        f"إشارات: {st['stats']['signals']} | صفقات مفتوحة: {st['stats']['opened']} | مغلقة: {st['stats']['closed']}",
        f"صفقات اليوم: {st['trades_today']}",
        f"ربح اليوم: <b>{st['pnl_today']:+.4f} USDT</b>",
    ]
    if st.get("last_error"):
        lines += ["", f"⚠️ آخر خطأ: <code>{esc(st['last_error'])}</code>"]
    return "\n".join(lines)


def balance_text(bal: Balance, exchange: str, testnet: bool) -> str:
    net = "تيستنت (أموال وهمية)" if testnet else "حقيقي"
    return "\n".join(
        [
            f"💰 <b>الرصيد — {esc(exchange)} ({net})</b>",
            "",
            f"الإجمالي: <b>{bal.total:.3f} USDT</b>",
            f"المتاح: {bal.available:.3f} USDT",
            f"غير المحقق: {bal.unrealized:+.3f} USDT",
        ]
    )


def positions_text(positions: list[Position], empty_msg: str = "لا توجد صفقات مفتوحة.") -> str:
    if not positions:
        return "📈 " + empty_msg
    total_pnl = sum(p.pnl for p in positions)
    lines = [f"📈 <b>الصفقات المفتوحة ({len(positions)})</b>", ""]
    for p in positions:
        arrow = "🟢" if p.side == "buy" else "🔴"
        lines += [
            f"{arrow} <code>{esc(p.symbol)}</code> — {side_ar(p.side)} ×{p.leverage:g}",
            f"   الكمية: <code>{p.size}</code> | الدخول: <code>{p.entry_price}</code> | الآن: <code>{p.mark_price}</code>",
            f"   الربح: <b>{p.pnl:+.4f} USDT</b> ({p.roe_pct:+.2f}%)",
        ]
    lines += ["", f"المجموع غير المحقق: <b>{total_pnl:+.4f} USDT</b>"]
    return "\n".join(lines)


def pnl_text(today: float, recent: float) -> str:
    return "\n".join(
        [
            "💹 <b>ملخص الأرباح</b>",
            "",
            f"ربح اليوم (UTC): <b>{today:+.4f} USDT</b>",
            f"آخر 50 صفقة مغلقة: {recent:+.4f} USDT",
        ]
    )


def settings_text(cfg) -> str:
    g = cfg.get
    symbols_src = "تلقائي (أعلى الرموز نشاطاً)" if str(
        g("scanner.symbols_source", "auto")
    ).lower() == "auto" else "قائمة يدوية"
    return "\n".join(
        [
            "⚙️ <b>الإعدادات الحالية</b>",
            "",
            f"المنصة: <code>{esc(g('exchange.name'))}</code> | تيستنت: {g('exchange.testnet')}",
            f"الإطار الزمني: {g('strategy.timeframe')} | شموع مكتملة: {g('strategy.use_closed_candles')}",
            f"تأكيد مزدوج (RSI + W%R): {g('strategy.require_both')}",
            f"RSI: فترة {g('strategy.rsi.period')} | بيعي {g('strategy.rsi.oversold')} | شرائي {g('strategy.rsi.overbought')}",
            f"W%R: فترة {g('strategy.williams_r.lbp')} | EMA {g('strategy.williams_r.ema_window')}",
            "",
            f"حجم الصفقة: {float(g('trade.qty_usdt', 0)):g} USDT | رافعة: {g('trade.leverage')}x | هامش: {g('trade.margin_mode')}",
            f"جني الأرباح: {float(g('trade.take_profit_pct', 0)) * 100:g}% | وقف الخسارة: {float(g('trade.stop_loss_pct', 0)) * 100:g}%",
            "",
            f"أقصى صفقات: {g('risk.max_positions')} | حد أدنى للصفقة: {float(g('risk.min_notional', 0)):g} USDT",
            f"فحص كل: {g('scanner.interval_seconds')} ث | مدة الإشارة: {int(g('scanner.signal_ttl_seconds', 0)) // 60} د",
            f"فترة السمومية: {int(g('scanner.cooldown_seconds', 0)) // 60} د | مصدر الرموز: {symbols_src}",
            "",
            f"وضع التنفيذ: {g('execution.mode')} | محاكاة: {g('safety.dry_run')}",
        ]
    )


def help_text() -> str:
    return "\n".join(
        [
            "🤖 <b>أوامر بوت Stratig</b>",
            "",
            "📊 /status — حالة البوت والإحصائيات",
            "💰 /balance — الرصيد",
            "📈 /positions — الصفقات المفتوحة (مع أزرار إغلاق)",
            "💹 /pnl — الأرباح",
            "🔍 /scan — فحص السوق الآن",
            "⚙️ /settings — عرض الإعدادات",
            "✏️ /set — تعديل إعداد (قائمة تفاعلية)",
            "   مثال: <code>/set tp 0.02</code>",
            "📋 /symbols — إدارة قائمة الرموز",
            "⏸ /pause  ▶️ /resume — إيقاف/تشغيل الفحص التلقائي",
            "🔒 /close BTCUSDT — إغلاق صفقة",
            "🔒 /closeall — إغلاق كل الصفقات",
            "🆔 /id — معرف محادثتك",
            "❔ /help — هذه الرسالة",
            "",
            "<i>في الوضع اليدوي: يرسل البوت الإشارة ثم تضغط ✅ للفتح أو ❌ للتجاهل.</i>",
        ]
    )
