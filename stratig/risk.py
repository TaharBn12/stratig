"""إدارة المخاطر — منطق خالص (بلا اتصال بالمنصة) ليسهل اختباره.

أربع وحدات مستقلة:

1. `position_size`  — حجم الصفقة بحيث تكون **خسارتك ثابتة** بالدولار مهما اختلف التقلّب
2. `RateLimiter`    — حدّ أقصى لعدد الصفقات في الساعة + فاصل زمني أدنى
3. `CircuitBreaker` — إيقاف تلقائي بعد خسائر متتالية (يمنع «الانتقام من السوق»)
4. `Journal`        — سجل الصفقات: نجاح، توقع، معامل الربح، أقصى سحب

لماذا هذا مهم خصوصاً في **الوضع التلقائي مع إشارات كثيرة**؟
لأن كثرة الصفقات الضعيفة تعني أن الرسوم والانزلاق تتراكم: قياسنا أظهر
نجاحاً 40% مقابل تعادل 40% — أي أن الميزة الإجمالية ≈ صفر قبل الرسوم.
تحديد الحجم وتحديد المعدل هما ما يمنع النزيف قبل تحسين الإشارة نفسها.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

# ═══════════════════════ 1) حجم الصفقة ═══════════════════════


def position_size(
    balance: float,
    risk_pct: float,
    sl_pct: float,
    leverage: int = 10,
    max_qty: float | None = None,
    min_qty: float = 0.0,
) -> float:
    """قيمة الصفقة بالـ USDT بحيث: الخسارة عند الوقف = `risk_pct` × الرصيد.

        القيمة = (الرصيد × نسبة المخاطرة) ÷ نسبة الوقف

    مثال: رصيد 1000، مخاطرة 1%، وقف 0.9% → 1000×0.01 ÷ 0.009 ≈ 1111 USDT
    أي أنك إن ضُرب وقفك تخسر 10 USDT فقط — سواء كان الوقف 0.9% أو 3%.

    يُرجع `max_qty` إن تجاوزته، و`min_qty` إن قلّ عنه، و0 لأي قيمة غير صالحة.
    """
    try:
        balance = float(balance)
        risk_pct = float(risk_pct)
        sl_pct = float(sl_pct)
    except (TypeError, ValueError):
        return 0.0
    if balance <= 0 or risk_pct <= 0 or sl_pct <= 0:
        return 0.0
    risk_amount = balance * risk_pct
    qty = risk_amount / sl_pct
    if max_qty and qty > max_qty:
        qty = float(max_qty)
    if qty < min_qty:
        qty = float(min_qty)
    return qty


def risk_of(qty: float, sl_pct: float, leverage: int = 10) -> float:
    """كم تخسر فعلاً إن ضُرب الوقف (بالـ USDT) — للعرض في رسالة الإشارة."""
    try:
        return float(qty) * float(sl_pct)
    except (TypeError, ValueError):
        return 0.0


# ═══════════════════════ 2) تحديد المعدل ═══════════════════════


@dataclass
class RateLimiter:
    """يمنع «الإفراط في التداول» (overtrading) — أخطر ما في الوضع التلقائي.

    max_per_hour   : أقصى صفقات في الساعة (0 = بلا حد)
    min_gap_seconds: فاصل أدنى بين صفقتين (0 = بلا حد)
    """

    max_per_hour: int = 0
    min_gap_seconds: float = 0.0
    _opened: list[float] = field(default_factory=list)

    def prune(self, now: float | None = None) -> None:
        """يحذف التواريخ الأقدم من ساعة (حتى لا تنمو القائمة بلا حد)."""
        now = time.time() if now is None else now
        self._opened = [t for t in self._opened if now - t < 3600.0]

    def check(self, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        self.prune(now)
        if self.max_per_hour and len(self._opened) >= self.max_per_hour:
            return False, (
                f"⏳ بلغت الحد الأقصى: {self.max_per_hour} صفقة/ساعة — "
                f"انتظر {self._seconds_to_slot(now)}"
            )
        if self._opened and self.min_gap_seconds:
            elapsed = now - max(self._opened)
            if elapsed < self.min_gap_seconds:
                left = self.min_gap_seconds - elapsed
                return False, (
                    f"⏳ فاصل إلزامي بين الصفقات — انتظر {int(left)} ثانية"
                )
        return True, ""

    def _seconds_to_slot(self, now: float) -> str:
        oldest = min(self._opened) if self._opened else now
        left = max(0.0, 3600.0 - (now - oldest))
        return f"{int(left // 60)} دقيقة"

    def record(self, now: float | None = None) -> None:
        self._opened.append(time.time() if now is None else now)
        self.prune(now)

    def remaining(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        self.prune(now)
        return max(0, self.max_per_hour - len(self._opened)) if self.max_per_hour else 99


# ═══════════════════════ 3) قاطع الخسائر المتتالية ═══════════════════════


@dataclass
class CircuitBreaker:
    """يوقف التداول مؤقتاً بعد سلسلة خسائر — يحميك من نفسك في الوضع التلقائي.

    بعد `max_losses` خسارة متتالية → توقف لمدة `pause_seconds`.
    """

    max_losses: int = 0
    pause_seconds: float = 3600.0
    losses: int = 0
    paused_until: float = 0.0

    def check(self, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        if now < self.paused_until:
            left = int(self.paused_until - now)
            return False, (
                f"🛑 موقوف تلقائياً بعد {self.losses} خسارة متتالية — "
                f"يُستأنف بعد {left // 60} دقيقة (أو /resume)"
            )
        return True, ""

    def record(self, pnl: float, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if not self.max_losses:
            return
        if pnl < 0:
            self.losses += 1
            if self.losses >= self.max_losses:
                self.paused_until = now + self.pause_seconds
        elif pnl > 0:
            self.losses = 0

    def resume(self) -> None:
        self.losses = 0
        self.paused_until = 0.0


# ═══════════════════════ 4) سجل الصفقات ═══════════════════════


@dataclass
class Trade:
    symbol: str
    side: str
    pnl: float = 0.0          # بالـ USDT
    r_multiple: float = 0.0   # بوحدة R (الربح ÷ مسافة الوقف)
    opened_at: float = 0.0
    closed_at: float = 0.0
    strategy: str = ""


class Journal:
    """سجل بسيط على القرص — يحسب إحصائياتك الحقيقية من صفقاتك الواقعية."""

    def __init__(self, path: Path | None = None, limit: int = 1000) -> None:
        self.path = Path(path) if path else None
        self.limit = max(10, int(limit))
        self.trades: list[Trade] = []
        if self.path:
            self.load()

    def add(self, trade: Trade) -> None:
        self.trades.append(trade)
        if len(self.trades) > self.limit:
            self.trades = self.trades[-self.limit:]
        self.save()

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.trades = [
            Trade(**{k: v for k, v in item.items() if k in Trade.__dataclass_fields__})
            for item in raw if isinstance(item, dict)
        ][-self.limit:]

    def save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([t.__dict__ for t in self.trades], ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:  # pragma: no cover
            pass

    # ── إحصائيات ──
    @property
    def count(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losses(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl < 0]

    @property
    def win_rate(self) -> float:
        return 100.0 * len(self.wins) / self.count if self.count else 0.0

    @property
    def expectancy_r(self) -> float:
        return sum(t.r_multiple for t in self.trades) / self.count if self.count else 0.0

    @property
    def profit_factor(self) -> float:
        gross = sum(t.pnl for t in self.wins)
        lost = abs(sum(t.pnl for t in self.losses))
        if lost == 0:
            return float("inf") if gross > 0 else 0.0
        return gross / lost

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def max_drawdown(self) -> float:
        """أقصى هبوط في منحنى الرصيد (بالـ USDT)."""
        equity, peak, worst = 0.0, 0.0, 0.0
        for trade in self.trades:
            equity += trade.pnl
            peak = max(peak, equity)
            worst = min(worst, equity - peak)
        return abs(worst)

    def today(self) -> list[Trade]:
        from datetime import datetime, timezone

        day = datetime.now(timezone.utc).date()
        return [
            t for t in self.trades
            if datetime.fromtimestamp(t.closed_at or t.opened_at, timezone.utc).date() == day
        ]


# ═══════════════════════ 5) إدارة الصفقة المفتوحة ═══════════════════════


@dataclass
class ProtectionPlan:
    """ما يجب فعله بالصفقة المفتوحة الآن."""

    action: str = "none"      # none | breakeven | trail | close
    new_sl: float | None = None
    reason: str = ""


def signed_profit(side: str, entry: float, current: float) -> float:
    """الربح بالسعر (موجب = لصالحك) — للبيع على المكشوف كذلك."""
    change = current - entry
    return change if str(side).lower() == "buy" else -change


def plan_protection(
    side: str,
    entry: float,
    current: float,
    sl_distance: float,
    current_sl: float,
    opened_at: float = 0.0,
    now: float | None = None,
    breakeven_after_r: float = 1.0,
    breakeven_offset_pct: float = 0.0,
    trailing: bool = False,
    trail_distance: float | None = None,
    max_hold_seconds: float = 0.0,
) -> ProtectionPlan:
    """يقرّر: لا شيء · نقل الوقف للتعادل · وقف متحرك · إغلاق لانتهاء المدة.

    side          : buy (long) | sell (short)
    sl_distance   : مسافة الوقف الأصلية بالسعر (من ATR أو من النسبة)
    current_sl    : آخر وقف معروف (0 إن لم يُضبط بعد)
    breakeven_after_r: بعد كم R ننقل الوقف إلى نقطة التعادل
    trailing      : تفعيل الوقف المتحرك
    max_hold_seconds : أغلق الصفقة إن تجاوزت هذه المدة (0 = معطّل)

    القاعدة الذهبية: **الوقف يتحرك في اتجاه واحد فقط** — للأعلى في الشراء،
    وللأسفل في البيع. لا يُسمح أبداً بإبعاد الوقف عن السعر.
    """
    now = time.time() if now is None else now
    side = str(side).lower()
    try:
        entry = float(entry)
        current = float(current)
        sl_distance = float(sl_distance or 0)
        current_sl = float(current_sl or 0)
    except (TypeError, ValueError):
        return ProtectionPlan("none", None, "قيم غير صالحة")
    if entry <= 0 or current <= 0 or sl_distance <= 0:
        return ProtectionPlan("none", None, "بيانات ناقصة")

    profit = signed_profit(side, entry, current)
    r_multiple = profit / sl_distance
    better = (lambda a, b: a > b) if side == "buy" else (lambda a, b: a < b)

    # 1) الإغلاق لانتهاء المدة — رأس المال المجمّد خسارة خفية
    if max_hold_seconds and opened_at and (now - opened_at) >= max_hold_seconds:
        return ProtectionPlan(
            "close", None,
            f"⏳ تجاوزت مدة الاحتفاظ القصوى ({int(max_hold_seconds // 60)} دقيقة)",
        )

    candidate = None
    reason = ""
    if trailing:
        distance = float(trail_distance or sl_distance)
        trail_sl = current - distance if side == "buy" else current + distance
        if not current_sl or better(trail_sl, current_sl):
            candidate = trail_sl
            reason = f"وقف متحرك — السعر ربح {r_multiple:.2f}R"
    if breakeven_after_r and r_multiple >= breakeven_after_r:
        offset = float(breakeven_offset_pct or 0.0)
        be = entry * (1 + offset) if side == "buy" else entry * (1 - offset)
        if candidate is None or better(be, candidate):
            if not current_sl or better(be, current_sl):
                candidate = be
                reason = (
                    f"نقل الوقف لنقطة التعادل بعد {r_multiple:.2f}R"
                    + (" (+ العمولة)" if offset else "")
                )

    if candidate is None or (current_sl and not better(candidate, current_sl)):
        return ProtectionPlan("none", None, "")
    return ProtectionPlan("breakeven" if not trailing else "trail", candidate, reason)
