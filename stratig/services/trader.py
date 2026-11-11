"""عقل البوت: الفحص الدوري + إدارة الإشارات + التنفيذ اليدوي/التلقائي."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ..config import PROJECT_ROOT, Config
from ..exchanges.base import BUY, SELL, ExchangeBase, OrderResult
from ..web.server import Dashboard
from ..web.snapshot import build_snapshot
from ..web.supabase import SupabaseSync
from ..strategy.filters import apply_filters
from ..strategy.indicators import adx, atr_pct, ema
from ..strategy.engine import Decision
from ..risk import (
    CircuitBreaker,
    Journal,
    RateLimiter,
    Trade,
    plan_protection,
    position_size,
    risk_of,
)
from ..strategy.registry import (
    check_config as check_strategy_config,
    evaluate as strategy_evaluate,
    names as strategy_names,
    resolve as resolve_strategy,
)
from .notifier import Button, MessageRef, Notifier
from ..utils import esc as _esc, num as _num

log = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_OPENED = "opened"
STATUS_SKIPPED = "skipped"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"


@dataclass
class PendingSignal:
    id: str
    symbol: str
    side: str
    price: float
    timeframe: str
    created_at: float
    expires_at: float
    decision: Decision = None  # type: ignore[assignment]
    status: str = STATUS_PENDING
    ref: Optional[MessageRef] = None
    result: Optional[OrderResult] = None
    error: Optional[str] = None

    @property
    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.time())

    @property
    def is_pending(self) -> bool:
        return self.status == STATUS_PENDING


class Trader:
    def __init__(self, config: Config, exchange: ExchangeBase):
        self.cfg = config
        self.exchange = exchange
        self.notifier: Notifier = Notifier()

        self.pending: dict[str, PendingSignal] = {}
        self.cooldown: dict[str, float] = {}
        self.scan_failures: int = 0          # عدد الرموز التي فشل جلب شموعها في آخر فحص
        self._total_failure_notified: bool = False
        self.running: bool = bool(config.get("scanner.autostart", True))

        self.last_scan_source: str = ""      # auto | manual | all
        self.last_scan_at: Optional[float] = None
        self.last_scan_duration: float = 0.0
        self.last_scan_symbols: int = 0
        self.last_error: Optional[str] = None
        self.stats = {"scans": 0, "signals": 0, "opened": 0, "closed": 0, "errors": 0}

        self._lock = asyncio.Lock()
        self._symbols_cache: list[str] = []
        self._symbols_ts = 0.0

        self._day: date = datetime.now(timezone.utc).date()
        self.trades_today = 0
        self.pnl_today = 0.0

        # صرامة الاستراتيجية: أي تعارض بين الإعدادات والاستراتيجية المختارة
        # يُسجَّل هنا ليظهر للمستخدم بدل أن يُهمَل بصمت
        self.strategy_warnings: list[str] = []
        self._strategy_warned = False

        # ═══════════════ إدارة المخاطر ═══════════════
        self.rate = RateLimiter()
        self.breaker = CircuitBreaker()
        journal_path = Path(str(config.get("risk.journal_path", "state/trades.json") or ""))
        if not journal_path.is_absolute():
            journal_path = PROJECT_ROOT / journal_path
        self.journal = Journal(journal_path, limit=int(config.get("risk.journal_limit", 1000)))
        self._risk_reason = ""            # آخر سبب منعه التداول
        # ── لوحة التحكم + الرفع إلى Supabase (اختياريان، معطّلان افتراضياً) ──
        self._supabase = SupabaseSync.from_config(config)
        self._last_push = 0.0
        self._pushed_trades = 0
        self.dashboard = None
        if bool(config.get("web.enabled", False)):
            self._start_dashboard()
        self._last_qty: dict[str, tuple[float, float]] = {}
        self._opened_meta: dict[str, dict] = {}   # بيانات الصفقة لإدارة المخاطر لاحقاً
        self._managed_sl: dict[str, float] = {}   # آخر وقف ضبطناه لكل رمز
        self._sync_risk()

    # ═══════════════════ إعداد ═══════════════════
    # ═══════════════════════ لوحة التحكم ═══════════════════════
    def _start_dashboard(self) -> None:
        """يُشغّل خادم اللوحة في خيط خلفي — لا يوقف البوت إن فشل."""
        self.dashboard = Dashboard(
            self.snapshot,
            host=str(self.cfg.get("web.host", "0.0.0.0")),
            port=int(self.cfg.get("web.port", 8000)),
            token=str(self.cfg.get("web.token", "") or ""),
        )
        if self.dashboard.start():
            log.info("🔎 لوحة التحكم: %s", self.dashboard.url)
        else:
            self.dashboard = None

    def snapshot(self) -> dict:
        """اللقطة الموحّدة — تستخدمها اللوحة المحلية والسحابية."""
        return build_snapshot(self, self.cfg,
                              bot_id=str(self.cfg.get("supabase.bot_id", "default")),
                              live=True)

    def push_to_supabase(self, force: bool = False) -> None:
        """يدفع اللقطة + الصفقات الجديدة — يُستدعى من دورة الفحص."""
        if not self._supabase.enabled:
            return
        now = time.time()
        gap = float(self.cfg.get("supabase.push_interval_seconds", 60) or 60)
        if not force and (now - self._last_push) < gap:
            return
        self._last_push = now
        try:
            snap = self.snapshot()
            self._supabase.push_state(snap)
            rows = snap.get("trades", [])
            if len(rows) > self._pushed_trades:
                new_rows = rows[:len(rows) - self._pushed_trades]
                if self._supabase.push_trades(new_rows):
                    self._pushed_trades = len(rows)
        except Exception as err:  # pragma: no cover
            log.debug("[supabase] تعذّر الرفع: %s", err)

    def attach_notifier(self, notifier: Notifier) -> None:
        self.notifier = notifier

    @property
    def strategy_key(self) -> str:
        """معرّف الاستراتيجية المُستخدمة الآن (من config.toml)."""
        return self.strategy.key

    @property
    def strategy(self):
        """الاستراتيجية المُستخدمة فعلاً — مع تحذير صريح إن كان الاسم غير معروف."""
        strategy, error = resolve_strategy(self.cfg.get("strategy.name"))
        if error and not self._strategy_warned:
            self._strategy_warned = True
            self.strategy_warnings.append(
                f"⚠️ {error} — يعمل البوت الآن بـ <code>{strategy.key}</code>. "
                f"المتاحة: <code>{', '.join(strategy_names())}</code>"
            )
            log.error("%s — تم استخدام %s بدلاً منها", error, strategy.key)
        return strategy

    def _sync_risk(self) -> None:
        """يقرأ إعدادات المخاطر (تُستدعى عند الإقلاع وبعد كل /set)."""
        g = self.cfg.get
        self.rate.max_per_hour = int(g("risk.max_trades_per_hour", 0) or 0)
        self.rate.min_gap_seconds = float(g("risk.min_gap_seconds", 0) or 0)
        self.breaker.max_losses = int(g("risk.max_consecutive_losses", 0) or 0)
        self.breaker.pause_seconds = float(g("risk.pause_after_losses_seconds", 3600) or 0)

    def risk_gate(self, now: float | None = None) -> tuple[bool, str]:
        """بوابة قبل أي فتح: معدّل + قاطع الخسائر. (False, السبب) إن مُنع."""
        self._sync_risk()
        ok, reason = self.breaker.check(now)
        if not ok:
            self._risk_reason = reason
            return False, reason
        ok, reason = self.rate.check(now)
        if not ok:
            self._risk_reason = reason
            return False, reason
        self._risk_reason = ""
        return True, ""

    def sized_qty(self, sl_pct: float, default_qty: float) -> float:
        """حجم الصفقة: ثابت، أو محسوب بحيث تكون الخسارة = risk_pct × الرصيد."""
        mode = str(self.cfg.get("risk.sizing", "fixed") or "fixed").lower()
        if mode != "risk" or sl_pct <= 0:
            return float(default_qty)
        try:
            balance = float(self.exchange.balance().available)
        except Exception as err:  # pragma: no cover
            log.debug("تعذّر جلب الرصيد للحجم الديناميكي: %s", err)
            return float(default_qty)
        qty = position_size(
            balance,
            float(self.cfg.get("risk.risk_per_trade_pct", 0.01) or 0.01),
            sl_pct,
            leverage=int(self.cfg.get("trade.leverage", 10)),
            max_qty=float(self.cfg.get("risk.max_qty_usdt", 0) or 0) or None,
            min_qty=float(self.cfg.get("risk.min_qty_usdt", 0) or 0),
        )
        return qty or float(default_qty)

    def validate_strategy_config(self) -> list[str]:
        """يتحقق من اتساق إعدادات الاستراتيجية ويُصلحها (يُستدعى عند الإقلاع)."""
        warnings = check_strategy_config(self.cfg)
        for note in warnings:
            log.warning("%s", note.replace("<code>", "").replace("</code>", ""))
        self.strategy_warnings = list(dict.fromkeys(self.strategy_warnings + warnings))
        return warnings

    @property
    def mode(self) -> str:
        return str(self.cfg.get("execution.mode", "manual")).lower()

    @property
    def is_auto(self) -> bool:
        return self.mode == "auto"

    # ═══════════════════ الرموز ═══════════════════
    @property
    def symbols_source(self) -> str:
        """مصدر قائمة الرموز: manual | auto | all"""
        source = str(self.cfg.get("scanner.symbols_source", "auto")).lower()
        if source == "manual":
            return "manual"
        return "all" if int(self.cfg.get("scanner.top_n", 40) or 0) == 0 else "auto"

    def symbols(self, force: bool = False) -> list[str]:
        """قائمة الرموز: auto (أعلى نشاطاً / الكل) أو manual (القائمة اليدوية)."""
        source = str(self.cfg.get("scanner.symbols_source", "auto")).lower()
        if source == "manual":
            manual = [s.strip().upper() for s in (self.cfg.get("scanner.manual_symbols") or []) if s]
            if not manual:
                # قائمة يدوية فارغة → لا نفحص شيئاً، نرجع للكل وننبّه
                log.warning("القائمة اليدوية فارغة — سيتم استخدام كل الرموز المتاحة")
                return self.available_symbols()
            return manual
        now = time.time()
        if force or not self._symbols_cache or now - self._symbols_ts > 1800:
            exclude = tuple(str(s).upper() for s in (self.cfg.get("scanner.exclude") or []))
            top_n = int(self.cfg.get("scanner.top_n", 40) or 0)
            self._symbols_cache = self.exchange.usdt_symbols(top_n=top_n, exclude=exclude)
            self._symbols_ts = now
        return self._symbols_cache

    def available_symbols(self) -> list[str]:
        """كل الرموز المتاحة على المنصة (بدون حد top_n)."""
        exclude = tuple(str(s).upper() for s in (self.cfg.get("scanner.exclude") or []))
        return self.exchange.usdt_symbols(top_n=0, exclude=exclude)

    def set_manual_symbols(self, symbols: list[str]) -> None:
        clean = [s.strip().upper() for s in symbols if s and s.strip()]
        self.cfg.set("scanner.manual_symbols", clean)
        self.cfg.set("scanner.symbols_source", "manual")
        self.cfg.save()

    def reset_cooldowns(self) -> int:
        """يمسح فترة السمومية لكل الرموز (مفيد بعد تغيير الإطار الزمني)."""
        count = len(self.cooldown)
        self.cooldown.clear()
        return count

    def on_timeframe_changed(self) -> int:
        """بعد تغيير الإطار الزمني: يمسح السمومية ليُقيَّم السوق فوراً."""
        self._total_failure_notified = False
        return self.reset_cooldowns()

    def invalidate_symbols(self) -> None:
        """يمسح الذاكرة المؤقتة للرموز (يُجبر التحديث في الفحص القادم)."""
        self._symbols_cache = []
        self._symbols_ts = 0.0

    def add_symbol(self, symbol: str) -> None:
        clean = symbol.strip().upper()
        current = list(self.symbols())
        if len(current) <= 1 and str(self.cfg.get("scanner.symbols_source", "auto")).lower() == "manual":
            # القائمة اليدوية شبه فارغة: نبدأ من كل الرموز المتاحة ثم نضيف
            try:
                current = list(self.available_symbols())
            except Exception:
                pass
        if clean not in current:
            current.append(clean)
        self.set_manual_symbols(current)
        self.invalidate_symbols()

    def remove_symbol(self, symbol: str) -> None:
        clean = symbol.strip().upper()
        current = [s for s in self.symbols() if s != clean]
        self.set_manual_symbols(current)
        self.invalidate_symbols()

    def use_auto_symbols(self, all_symbols: bool = False) -> None:
        """الرجوع للقائمة التلقائية؛ all_symbols=True → كل العملات (top_n = 0)."""
        self.cfg.set("scanner.symbols_source", "auto")
        if all_symbols:
            self.cfg.set("scanner.top_n", 0)
        self.cfg.save()
        self.invalidate_symbols()

    # ═══════════════════ حدود المخاطرة ═══════════════════
    def _roll_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self.trades_today = 0
            self.pnl_today = 0.0

    def _daily_blocked(self) -> Optional[str]:
        self._roll_day()
        max_trades = int(self.cfg.get("risk.daily_max_trades", 0) or 0)
        max_loss = float(self.cfg.get("risk.daily_max_loss_usdt", 0) or 0)
        if max_trades and self.trades_today >= max_trades:
            return f"تم الوصول للحد الأقصى للصفقات اليومية ({max_trades})"
        if max_loss:
            realized = self.daily_realized_pnl()
            if realized <= -abs(max_loss):
                return f"تم الوصول للحد الأقصى للخسارة اليومية ({realized:.2f} USDT)"
        return None

    def daily_realized_pnl(self) -> float:
        """الربح المحقق منذ منتصف الليل UTC."""
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            return self.exchange.recent_pnl(
                limit=200, since_ms=int(midnight.timestamp() * 1000)
            )
        except TypeError:  # منصات لا تدعم since_ms
            return self.exchange.recent_pnl(limit=50)
        except Exception as err:
            log.warning("تعذّر حساب الربح اليومي: %s", err)
            return 0.0

    # ═══════════════════ الفحص ═══════════════════
    async def scan_once(
        self,
        manual: bool = False,
        symbols: Optional[list[str]] = None,
        all_symbols: bool = False,
    ) -> list[PendingSignal]:
        """يفحص الرموز ويرجع الإشارات الجديدة.

        symbols     : قائمة مخصّصة للفحص (بدل إعدادات الماسح)
        all_symbols : True = فحص كل الرموز المتاحة على المنصة (يتجاهل top_n)
        """
        if not manual and not self.running:
            return []
        if self._lock.locked():
            log.debug("هناك فحص جارٍ بالفعل — تم التخطي")
            return []

        start = time.time()
        found: list[PendingSignal] = []
        async with self._lock:
            try:
                blocked = self._daily_blocked()
                if blocked:
                    log.info("الفحص موقوف: %s", blocked)
                    if manual:
                        await self.notifier.send(f"⛔ {blocked}")
                    return []

                positions = await asyncio.to_thread(self.exchange.open_position_symbols)
                max_pos = int(self.cfg.get("risk.max_positions", 5))
                if len(positions) >= max_pos:
                    log.info("الحد الأقصى للصفقات المفتوحة (%s) — تم التخطي", max_pos)
                    if manual:
                        await self.notifier.send(
                            f"⛔ لديك {len(positions)} صفقة مفتوحة (الحد: {max_pos})"
                        )
                    return []

                if symbols is None:
                    if all_symbols:
                        symbols = await asyncio.to_thread(self.available_symbols)
                    else:
                        symbols = await asyncio.to_thread(self.symbols)
                if symbols and symbols is not self._symbols_cache:
                    self.last_scan_source = "all" if all_symbols else self.symbols_source
                elif symbols:
                    self.last_scan_source = "all" if all_symbols else self.symbols_source
                self.last_scan_symbols = len(symbols)
                delay = float(self.cfg.get("scanner.request_delay", 0.2) or 0)
                cap = int(self.cfg.get("scanner.max_signals_per_scan", 5) or 0)

                # نعدّ الصفقات محلياً (بدل طلبها من المنصة عند كل رمز — يضاعف الطلبات)
                open_count = len(positions)
                self.scan_failures = 0
                for symbol in symbols:
                    if open_count >= max_pos:
                        break
                    sig = await self._evaluate_symbol(symbol, positions)
                    if sig:
                        found.append(sig)
                        if sig.status == STATUS_OPENED:   # الوضع التلقائي فتحها فوراً
                            open_count += 1
                        if cap and len(found) >= cap:
                            log.info("تم الوصول لحد الإشارات في الفحص الواحد (%s) — توقف", cap)
                            break
                    if delay:
                        await asyncio.sleep(delay)

                if symbols and self.scan_failures >= len(symbols):
                    # فشل كل الرموز = غالباً إطار زمني مرفوض من المنصة
                    await self._report_total_failure(len(symbols))

                self.stats["scans"] += 1
                self.last_scan_at = time.time()
                self.last_error = None
            except Exception as err:
                self.stats["errors"] += 1
                self.last_error = str(err)
                log.exception("خطأ أثناء الفحص: %s", err)
                await self.notifier.send(f"⚠️ خطأ أثناء الفحص:\n<code>{_esc(str(err))}</code>")
            finally:
                self.last_scan_duration = time.time() - start

        self.expire_signals()
        self._prune()

        if manual and not found and bool(self.cfg.get("scanner.notify_no_signal", False)):
            await self.notifier.send("🔍 لا توجد إشارات حالياً.")
        return found

    async def _report_total_failure(self, count: int) -> None:
        """"فشل جلب الشموع لكل الرموز" — السبب الغالب: إطار زمني ترفضه المنصة."""
        timeframe = self.cfg.effective_timeframe()
        message = (
            f"❌ تعذّر جلب الشموع لكل الرموز ({count}) على الإطار "
            f"<code>{_esc(timeframe)}</code>.\n"
            "السبب الغالب: إطار زمني لا تقبله المنصة.\n"
            "أرسل <code>/set tf 15m</code> أو <code>/set tf 5m</code>."
        )
        log.error("فشل جلب الشموع لكل الرموز على الإطار %s", timeframe)
        if not self._total_failure_notified and self.notifier is not None:
            self._total_failure_notified = True
            await self.notifier.send(message)

    async def _evaluate_symbol(self, symbol: str, open_positions: set) -> Optional[PendingSignal]:
        if symbol in open_positions:
            return None
        if any(s.symbol == symbol and s.is_pending for s in self.pending.values()):
            return None
        if time.time() < self.cooldown.get(symbol, 0):
            return None

        timeframe = self.cfg.effective_timeframe()      # صالح للمنصة دائماً
        limit = int(self.cfg.get("strategy.candles", 500))
        use_closed = bool(self.cfg.get("strategy.use_closed_candles", True))
        strategy = self.strategy

        try:
            df = await asyncio.to_thread(self.exchange.klines, symbol, timeframe, limit)
            decision = strategy_evaluate(
                strategy.key, df, self.cfg, symbol=symbol, use_closed_candles=use_closed
            )
        except Exception as err:
            self.scan_failures += 1
            log.debug("[%s] تعذّر الحساب: %s", symbol, err)
            return None

        if not decision.has_signal:
            return None

        if not self._mtf_passes(symbol, decision):
            return None

        # صرامة: القرار يجب أن يكون صادراً من الاستراتيجية المختارة
        # وعلى نفس الإطار المطلوب — وإلا نرفضه بدل تمريره
        if decision.strategy and decision.strategy != strategy.key:
            log.error(
                "[%s] القرار من استراتيجية %s بينما المختارة %s — تم رفض الإشارة",
                symbol, decision.strategy, strategy.key,
            )
            self.stats["errors"] += 1
            return None
        if decision.timeframe and decision.timeframe != timeframe:
            log.error(
                "[%s] القرار على الإطار %s والمطلوب %s — تم رفض الإشارة",
                symbol, decision.timeframe, timeframe,
            )
            self.stats["errors"] += 1
            return None

        ttl = float(self.cfg.get("scanner.signal_ttl_seconds", 900))
        now = time.time()
        sig = PendingSignal(
            id=uuid.uuid4().hex[:8],
            symbol=symbol,
            side=decision.side,  # type: ignore[arg-type]
            price=decision.price,
            timeframe=timeframe,
            created_at=now,
            expires_at=now + ttl,
            decision=decision,
        )
        self.pending[sig.id] = sig
        self.cooldown[symbol] = now + float(self.cfg.get("scanner.cooldown_seconds", 1800))
        self.stats["signals"] += 1

        if self.is_auto:
            await self.open_signal(sig.id, notify_result=True)
        else:
            await self._announce(sig)
        return sig

    # ═══════════════════ إشعار الإشارة ═══════════════════
    def _signal_text(self, sig: PendingSignal) -> str:
        side_ar = "شراء 🟢" if sig.side == BUY else "بيع 🔴"
        arrow = "🔼" if sig.side == BUY else "🔽"
        qty_usdt = float(self.cfg.get("trade.qty_usdt", 50))
        lev = int(self.cfg.get("trade.leverage", 10))
        tp = float(self.cfg.get("trade.take_profit_pct", 0.012)) * 100
        sl = float(self.cfg.get("trade.stop_loss_pct", 0.009)) * 100
        mins = int(sig.remaining // 60)
        lines = [
            f"{arrow} <b>إشارة جديدة</b>",
            "",
            f"الرمز: <code>{_esc(sig.symbol)}</code>",
            f"الاتجاه: <b>{side_ar}</b>",
            f"السعر: <code>{_num(sig.price)}</code>",
            f"الإطار الزمني: {sig.timeframe}",
            "",
            "<b>المؤشرات:</b>",
            sig.decision.describe(),
            "",
            f"الحجم المقترح: {qty_usdt:g} USDT × {lev}x",
            f"الهدف: +{tp:g}% | الوقف: -{sl:g}%",
            f"⏳ تنتهي الإشارة بعد {mins} دقيقة",
        ]
        freshness = self._signal_freshness(sig)
        if freshness:
            lines.append(freshness)
        if bool(self.cfg.get("safety.dry_run", False)):
            lines.append("\n🧪 وضع المحاكاة مفعّل — لن تُرسل أوامر حقيقية")
        else:
            lines.append(f"\n🔴 عند التأكيد يُرسل أمر حقيقي إلى {_esc(self.exchange.name)}")
        return "\n".join(lines)

    def _mtf_passes(self, symbol: str, decision) -> bool:
        """تأكيد الإطار الأعلى — الإشارتان الأخريان (ADX/تقلّب) في السجل.

        معطّل افتراضياً (`strategy.quality_enabled` + `strategy.mtf_enabled`).
        """
        if not bool(self.cfg.get("strategy.quality_enabled", False)):
            return True
        if not bool(self.cfg.get("strategy.mtf_enabled", False)):
            return True
        g = self.cfg.get
        higher_tf = str(g("strategy.mtf_timeframe", "1h") or "1h")
        period = int(g("strategy.mtf_ema_period", 50) or 50)
        try:
            higher = self._resolve_higher(self.cfg.effective_timeframe(), higher_tf)
            htf = self.exchange.klines(symbol, higher, 250)
        except Exception as err:  # pragma: no cover
            log.debug("[%s] تعذّر جلب الإطار الأعلى: %s", symbol, err)
            return True
        if len(htf) < period + 5:
            return True
        return apply_filters(
            decision,
            mtf_enabled=True,
            mtf_timeframe=higher,
            higher_close=htf.last_close,
            higher_ema=ema(list(htf.close), period)[-1],
        )

    @staticmethod
    def _resolve_higher(current: str, requested: str) -> str:
        """إن كان الإطار المطلوب للتأكيد مساوياً للحالي (أو أقل) → نصعده."""
        ladder = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
                  "12h", "1d", "3d", "1w")
        try:
            here = ladder.index(str(current).lower())
        except ValueError:
            return requested
        for step in range(here + 1, len(ladder)):
            if ladder[step] == str(requested).lower():
                return ladder[step]
        return ladder[min(here + 2, len(ladder) - 1)]

    def _signal_freshness(self, sig: "PendingSignal") -> str:
        """/"كم تأخّرت عن سعر الإشارة؟" — الدخول المتأخر يقتل ميزة الإشارة."""
        try:
            current = float(self.exchange.mark_price(sig.symbol))
        except Exception:  # pragma: no cover
            return ""
        if not current or not sig.price:
            return ""
        drift = abs(current - sig.price) / sig.price
        _, sl_pct, _err = self._resolve_exits(sig)
        if sl_pct <= 0:
            return ""
        ratio = drift / sl_pct
        age = int(max(0.0, time.time() - sig.created_at) // 60)
        if ratio < 0.25:
            mark = "🟢 طازجة"
        elif ratio < 0.75:
            mark = "🟡 تأخّرت قليلاً"
        else:
            mark = "🔴 متأخّرة — السعر تحرّك كثيراً عن نقطة الإشارة"
        return (
            f"\n📍 السعر الآن <code>{_num(current)}</code> | انحراف "
            f"{drift * 100:.2f}% ({ratio:.2f}× الوقف) · عمر الإشارة {age} د · {mark}"
        )

    def _stale_entry_error(self, sig: "PendingSignal") -> str:
        """يرفض الدخول إن كان السعر قد تجاوز الإشارة بمقدار يُفقدها ميزتها."""
        limit = float(self.cfg.get("execution.max_entry_drift", 1.0) or 0)
        if limit <= 0:
            return ""
        try:
            current = float(self.exchange.mark_price(sig.symbol))
        except Exception:  # pragma: no cover
            return ""
        if not current or not sig.price:
            return ""
        drift = abs(current - sig.price) / sig.price
        _, sl_pct, _err = self._resolve_exits(sig)
        if sl_pct <= 0:
            return ""
        if drift / sl_pct <= limit:
            return ""
        return (
            f"تحرّك السعر <b>{drift * 100:.2f}%</b> عن سعر الإشارة "
            f"(<code>{limit:g}</code>× الوقف مسموح) — الدخول الآن متأخّر "
            "ويفقد الإشارة ميزتها."
        )

    def _signal_buttons(self, sig: PendingSignal):
        label = "✅ فتح صفقة شراء" if sig.side == BUY else "✅ فتح صفقة بيع"
        return [
            [Button(label, f"sig:{sig.id}:open"), Button("❌ تجاهل", f"sig:{sig.id}:skip")],
            [Button("🔍 تفاصيل", f"sig:{sig.id}:info")],
        ]

    async def _announce(self, sig: PendingSignal) -> None:
        sig.ref = await self.notifier.send(self._signal_text(sig), self._signal_buttons(sig))

    # ═══════════════════ التنفيذ ═══════════════════
    def _exit_percentages(self, sig: "PendingSignal") -> tuple[float, float]:
        """(للتوافق مع الاختبارات القديمة) نسب المخارج، أو (0, 0) إن تعذّر تحديدها."""
        tp_pct, sl_pct, _error = self._resolve_exits(sig)
        return tp_pct, sl_pct

    def _resolve_exits(self, sig: "PendingSignal") -> tuple[float, float, str]:
        """يحدد نسبتي الوقف والهدف — ويرفض إن لم تكن من الاستراتيجية المختارة.

        الصرامة: إن كانت الاستراتيجية تفرض مخارج ATR ولم تُعطِ مسافات،
        نُرجع سبباً صريحاً بدل فتح الصفقة بنسب ثابتة لا تنتمي إليها.
        """
        tp_pct = float(self.cfg.get("trade.take_profit_pct", 0.012))
        sl_pct = float(self.cfg.get("trade.stop_loss_pct", 0.009))
        mode = str(self.cfg.get("exit.mode", "percent")).lower()
        strict = bool(self.cfg.get("exit.strict", True))
        distance = sig.decision.sl_distance if sig.decision else None
        target = sig.decision.tp_distance if sig.decision else None

        if mode != "atr":
            return tp_pct, sl_pct, ""
        if not distance or not sig.price:
            reason = (
                f"الاستراتيجية <code>{_esc(self.strategy_key)}</code> تفرض مخارج ATR "
                "ولم تُحتسب مسافة الوقف — لن تُفتح الصفقة بمخارج لا تنتمي إليها."
            )
            if strict:
                log.error("[%s] %s", sig.symbol, reason)
                return 0.0, 0.0, reason
            log.warning("[%s] تراجع للنسب الثابتة (exit.strict=false)", sig.symbol)
            return tp_pct, sl_pct, ""

        # الاستراتيجية تعطي المسافات بالسعر → نحوّلها إلى نسب من سعر الدخول
        sl_pct = distance / sig.price
        tp_pct = (target or distance * float(
            self.cfg.get("exit.atr.tp_ratio", 1.5))) / sig.price
        log.info(
            "[%s] مخارج ATR: وقف %s (%.4g%%) | هدف %s (%.4g%%)",
            sig.symbol, f"{distance:.6g}", sl_pct * 100, f"{(target or 0):.6g}", tp_pct * 100,
        )
        return tp_pct, sl_pct, ""

    async def open_signal(self, signal_id: str, notify_result: bool = True) -> Optional[OrderResult]:
        sig = self.pending.get(signal_id)
        if sig is None:
            return None
        if not sig.is_pending:
            return sig.result
        if sig.expires_at < time.time():
            sig.status = STATUS_EXPIRED
            await self.notifier.edit(sig.ref, "⌛ انتهت صلاحية هذه الإشارة.", None)
            return None

        blocked = self._daily_blocked()
        if blocked:
            await self.notifier.send(f"⛔ لم يتم فتح {sig.symbol}: {blocked}")
            return None

        stale = self._stale_entry_error(sig)
        if stale:
            if bool(self.cfg.get("execution.block_stale_entry", False)):
                sig.status = STATUS_SKIPPED
                await self.notifier.send(
                    f"⛔ لم يتم فتح <code>{_esc(sig.symbol)}</code>: {stale}\n"
                    "للتجاوز: <code>/set block_stale false</code>"
                )
                return None
            log.warning("[%s] دخول متأخّر: %s", sig.symbol, stale)
            await self.notifier.send(f"⚠️ {stale}\n<i>سأفتحها كما طلبت.</i>")

        allowed, why = self.risk_gate()
        if not allowed:
            await self.notifier.send(f"🛡 {why}")
            log.info("[%s] موقوف بإدارة المخاطر: %s", sig.symbol, why)
            return None

        tp_pct, sl_pct, exit_error = self._resolve_exits(sig)
        if exit_error:
            sig.status = STATUS_FAILED
            sig.error = exit_error
            await self.notifier.send(
                f"⛔ لم يتم فتح <code>{_esc(sig.symbol)}</code>: {exit_error}\n"
                "للتجاوز: <code>/set strict false</code>"
            )
            return None
        qty_usdt = self.sized_qty(sl_pct, float(self.cfg.get("trade.qty_usdt", 50)))
        self._last_qty[sig.symbol] = (qty_usdt, sl_pct)
        try:
            result = await asyncio.to_thread(
                self.exchange.open_market,
                sig.symbol,
                sig.side,
                qty_usdt,
                tp_pct,
                sl_pct,
                int(self.cfg.get("trade.leverage", 10)),
                str(self.cfg.get("trade.margin_mode", "isolated")),
                str(self.cfg.get("trade.tp_trigger", "mark_price")),
                float(self.cfg.get("risk.min_notional", 0) or 0),
            )
        except Exception as err:
            sig.status = STATUS_FAILED
            sig.error = str(err)
            self.stats["errors"] += 1
            log.error("[%s] فشل فتح الصفقة: %s", sig.symbol, err)
            await self.notifier.edit(
                sig.ref,
                f"❌ فشل فتح صفقة {_esc(sig.symbol)}\n<code>{_esc(str(err))}</code>",
                None,
            )
            return None

        sig.status = STATUS_OPENED
        sig.result = result
        self.trades_today += 1
        self.stats["opened"] += 1
        self.rate.record()
        self._opened_meta[sig.symbol] = {
            "side": sig.side,
            "entry": result.price if result else sig.price,
            "sl_dist": sig.decision.sl_distance if sig.decision else None,
            "sl_pct": sl_pct,
            "strategy": self.strategy_key,
            "opened_at": time.time(),
            "tp_price": (result.tp_price if result else None),
        }
        if notify_result:
            await self.notifier.edit(sig.ref, self._opened_text(sig), self._manage_buttons(sig.symbol))
        return result

    def _opened_text(self, sig: PendingSignal) -> str:
        r = sig.result
        side_ar = "شراء 🟢" if sig.side == BUY else "بيع 🔴"
        tag = ("\n🧪 <i>محاكاة — لم تُرسل أمراً حقيقياً</i>" if (r and r.simulated)
               else f"\n🔴 <i>أُمر حقيقي أُرسل إلى {_esc(self.exchange.name)}</i>")
        if not r:
            return f"❌ لا توجد نتيجة لـ {_esc(sig.symbol)}"
        lines = [
            "✅ <b>تم فتح الصفقة</b>",
            "",
            f"الرمز: <code>{_esc(r.symbol)}</code>",
            f"الاتجاه: <b>{side_ar}</b>",
            f"الكمية: <code>{_num(r.qty)}</code>",
            f"السعر: <code>{_num(r.price)}</code>",
            f"القيمة: ≈ {r.notional:.2f} USDT",
        ]
        if r.tp_price:
            lines.append(f"🎯 جني الأرباح: <code>{_num(r.tp_price)}</code>")
        if r.sl_price:
            lines.append(f"🛑 وقف الخسارة: <code>{_num(r.sl_price)}</code>")
        if r.order_id:
            lines.append(f"رقم الأمر: <code>{_esc(str(r.order_id))}</code>")
        lines.append(tag)
        return "\n".join(lines)

    def _manage_buttons(self, symbol: str):
        return [[Button(f"❌ إغلاق {symbol}", f"pos:{symbol}:close")]]

    async def skip_signal(self, signal_id: str) -> bool:
        sig = self.pending.get(signal_id)
        if sig is None or not sig.is_pending:
            return False
        sig.status = STATUS_SKIPPED
        await self.notifier.edit(
            sig.ref, f"🚫 تم تجاهل إشارة {_esc(sig.symbol)} ({sig.side}).", None
        )
        return True

    # ═══════════════════ الإغلاق ═══════════════════
    async def close_symbol(self, symbol: str) -> Optional[OrderResult]:
        symbol = symbol.strip().upper()
        try:
            result = await asyncio.to_thread(self.exchange.close_position, symbol)
        except Exception as err:
            log.error("[%s] فشل الإغلاق: %s", symbol, err)
            await self.notifier.send(f"❌ فشل إغلاق {_esc(symbol)}:\n<code>{_esc(str(err))}</code>")
            return None
        if result is None:
            await self.notifier.send(f"ℹ️ لا توجد صفقة مفتوحة على {_esc(symbol)}")
            return None
        self.stats["closed"] += 1
        pnl = await asyncio.to_thread(self.exchange.recent_pnl, 1)
        self._record_close(symbol, float(pnl or 0.0), result)
        await self.notifier.send(
            f"🔒 <b>تم إغلاق الصفقة</b>\n"
            f"الرمز: <code>{_esc(symbol)}</code>\n"
            f"الكمية: <code>{_num(result.qty)}</code> بسعر ≈ <code>{_num(result.price)}</code>\n"
            f"آخر ربح محقق: <b>{pnl:+.4f} USDT</b>"
        )
        return result

    # ═══════════════ إدارة الصفقات المفتوحة ═══════════════
    async def manage_positions(self) -> int:
        """يفحص الصفقات المفتوحة ويُحسّن وقفها: تعادل / متحرك / إغلاق لانتهاء المدة.

        مُعطّل افتراضياً (`risk.manage_positions`) لأنه يلغي الأوامر الشرطية
        ويعيد وضعها — ميزة متقدّمة لمن يفهم أثرها.
        """
        if not bool(self.cfg.get("risk.manage_positions", False)):
            return 0
        try:
            positions = await asyncio.to_thread(self.exchange.positions)
        except Exception as err:  # pragma: no cover
            log.debug("تعذّر جلب الصفقات للإدارة: %s", err)
            return 0

        changed = 0
        for pos in positions:
            symbol = pos.symbol.upper()
            meta = self._opened_meta.get(symbol)
            if not meta or not pos.entry_price or not pos.mark_price:
                continue                      # صفقة لم يفتحها البوت → لا نتدخّل
            entry = float(meta.get("entry") or pos.entry_price)
            sl_pct = float(meta.get("sl_pct") or 0)
            if sl_pct <= 0:
                continue
            sl_distance = float(meta.get("sl_dist") or 0) or entry * sl_pct
            current_sl = float(self._managed_sl.get(symbol) or 0)
            trail_distance = None
            if bool(self.cfg.get("risk.trailing", False)):
                trail_distance = sl_distance * float(
                    self.cfg.get("risk.trail_distance_mult", 1.0) or 1.0
                )

            plan = plan_protection(
                side=pos.side,
                entry=entry,
                current=pos.mark_price,
                sl_distance=sl_distance,
                current_sl=current_sl or (entry - sl_distance if pos.side == BUY
                                          else entry + sl_distance),
                opened_at=float(meta.get("opened_at") or 0),
                breakeven_after_r=float(self.cfg.get("risk.breakeven_after_r", 1.0) or 0),
                breakeven_offset_pct=float(self.cfg.get("risk.breakeven_offset_pct", 0) or 0),
                trailing=bool(self.cfg.get("risk.trailing", False)),
                trail_distance=trail_distance,
                max_hold_seconds=float(self.cfg.get("risk.max_hold_seconds", 0) or 0),
            )
            if plan.action == "close":
                await self.close_symbol(symbol)
                self._managed_sl.pop(symbol, None)
                changed += 1
            elif plan.action in ("breakeven", "trail") and plan.new_sl:
                await self._apply_stop(symbol, pos.side, plan.new_sl, meta, plan.reason)
                changed += 1
        return changed

    async def _apply_stop(self, symbol: str, side: str, new_sl: float,
                          meta: dict, reason: str) -> None:
        try:
            ok = await asyncio.to_thread(
                self.exchange.replace_protection, symbol, side, new_sl,
                meta.get("tp_price"),
            )
        except Exception as err:  # pragma: no cover
            log.warning("[%s] تعذّر تحديث الوقف: %s", symbol, err)
            return
        if not ok:
            return
        self._managed_sl[symbol] = new_sl
        log.info("[%s] %s → وقف جديد %s", symbol, reason, f"{new_sl:.6g}")
        await self.notifier.send(
            f"🛡 <b>{_esc(reason)}</b>\n"
            f"الرمز: <code>{_esc(symbol)}</code>\n"
            f"الوقف الجديد: <code>{_num(new_sl)}</code>"
        )

    def _record_close(self, symbol: str, pnl: float, result=None) -> None:
        """يسجّل الصفقة في السجل (لإحصائيات /stats) ويُغذّي قاطع الخسائر."""
        meta = self._opened_meta.pop(symbol.upper(), {}) or {}
        sl_dist = meta.get("sl_dist")
        entry = float(meta.get("entry") or (result.price if result else 0.0) or 0.0)
        r_multiple = (pnl / (sl_dist * (result.qty or 1))) if (sl_dist and result and
                                                               result.qty) else 0.0
        if not r_multiple and meta.get("sl_pct") and entry:
            # تقدير بوحدة R من نسبة الوقف (إن لم تُعرف مسافة ATR)
            qty_value = (result.qty or 0) * entry if result else 0.0
            r_multiple = pnl / (qty_value * float(meta["sl_pct"])) if qty_value else 0.0
        self.journal.add(
            Trade(
                symbol=symbol.upper(),
                side=str(meta.get("side") or (result.side if result else "")),
                pnl=float(pnl),
                r_multiple=float(r_multiple),
                opened_at=float(meta.get("opened_at") or time.time()),
                closed_at=time.time(),
                strategy=str(meta.get("strategy") or self.strategy_key),
            )
        )
        self.breaker.record(float(pnl))
        self.pnl_today += float(pnl)

    async def close_all(self) -> int:
        positions = await asyncio.to_thread(self.exchange.positions)
        count = 0
        for pos in positions:
            if await self.close_symbol(pos.symbol):
                count += 1
                await asyncio.sleep(0.4)
        if positions and count == 0:
            await self.notifier.send("ℹ️ لا توجد صفقات لإغلاقها")
        return count

    # ═══════════════════ صيانة ═══════════════════
    def expire_signals(self) -> list[PendingSignal]:
        expired: list[PendingSignal] = []
        now = time.time()
        for sig in list(self.pending.values()):
            if sig.is_pending and sig.expires_at < now:
                sig.status = STATUS_EXPIRED
                expired.append(sig)
        return expired

    async def notify_expired(self) -> None:
        for sig in self.expire_signals():
            await self.notifier.edit(sig.ref, f"⌛ انتهت صلاحية إشارة {_esc(sig.symbol)}.", None)

    def _prune(self, keep: int = 60) -> None:
        """يحذف الإشارات القديمة من الذاكرة."""
        done = [s for s in self.pending.values() if not s.is_pending]
        done.sort(key=lambda s: s.created_at)
        for sig in done[:-keep]:
            self.pending.pop(sig.id, None)

    # ═══════════════════ حالة ═══════════════════
    def status(self) -> dict:
        return {
            "running": self.running,
            "mode": self.mode,
            "exchange": self.exchange.name,
            "testnet": self.exchange.testnet,
            "dry_run": bool(self.cfg.get("safety.dry_run", False)),
            "timeframe": self.cfg.effective_timeframe(),
            "strategy": self.strategy_key,
            "strategy_warnings": list(self.strategy_warnings),
            "last_scan": self.last_scan_at,
            "source": self.last_scan_source or self.symbols_source,
            "last_scan_duration": self.last_scan_duration,
            "symbols": self.last_scan_symbols,
            "pending": sum(1 for s in self.pending.values() if s.is_pending),
            "trades_today": self.trades_today,
            "pnl_today": self.daily_realized_pnl(),
            "stats": dict(self.stats),
            "last_error": self.last_error,
        }



