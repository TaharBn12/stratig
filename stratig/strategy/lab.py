"""استراتيجيات مرشّحة للبحث عن ميزة — تُسجَّل في السجل كأي استراتيجية أخرى.

لماذا أربع عائلات مختلفة؟
    قياسنا أثبت أن كلا الاستراتيجيتين الحاليتين **ارتداديتان** (تعاكسان
    الاتجاه)، فكلتاهما تخسر في السوق المتّجه لنفس السبب. البحث عن ميزة
    يحتاج **تنوّعاً في الفرضيات** لا تكراراً لها:

    ┌──────────────────┬────────────────────┬─────────────────────┐
    │ الاستراتيجية     │ الفرضية            │ نظامها الملائم      │
    ├──────────────────┼────────────────────┼─────────────────────┤
    │ mean_reversion_z │ السعر يعود لمتوسطه │ نطاق جانبي          │
    │ rsi_reversion    │ التشدّد يعقبه ارتداد│ نطاق جانبي          │
    │ donchian_breakout│ الاختراق يستمرّ     │ اتجاه قوي           │
    │ ema_momentum     │ الزخم يستمرّ        │ اتجاه قوي           │
    └──────────────────┴────────────────────┴─────────────────────┘

    الفحص الحاسم: هل أيٌّ منها يصمد على **80+ صفقة** وبثبات بين النوافذ؟
    يجيب عن ذلك `scripts/lab.py` لا هذا الملف.

قاعدة: هذه الاستراتيجيات **مضافة** ولا تُغيّر أي استراتيجية قائمة،
وقيمها الافتراضية لا تُطبَّق تلقائياً — تختارها بـ `/strategy`.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..data import Candles, NAN
from .engine import BUY, SELL, Decision
from .indicators import atr, ema, rolling_std, rsi, sma


# ═══════════════════════ 1) الارتداد إلى المتوسط ═══════════════════════
MEAN_REVERSION_Z = "mean_reversion_z"


@dataclass
class ZParams:
    length: int = 20          # نافذة المتوسط
    entry_z: float = 2.0      # بعد كم انحراف معياري ندخل؟
    exit_z: float = 0.5       # نخرج عند العودة إلى كم؟
    atr_length: int = 14
    sl_coef: float = 1.5      # مسافة الوقف = × ATR
    tp_ratio: float = 1.5     # الهدف = × مسافة الوقف

    @classmethod
    def from_cfg(cls, cfg) -> "ZParams":
        node = (cfg.get("strategy.mean_reversion_z", {}) or {}) if cfg else {}
        g = node.get
        return cls(
            length=int(g("length", 20)),
            entry_z=float(g("entry_z", 2.0)),
            exit_z=float(g("exit_z", 0.5)),
            atr_length=int(g("atr_length", 14)),
            sl_coef=float(g("sl_coef", 1.5)),
            tp_ratio=float(g("tp_ratio", 1.5)),
        )


def evaluate_z(candles: Candles, cfg=None, symbol: str = "",
               use_closed_candles: bool = True) -> Decision:
    """اشترِ عند انخفاض السعر انحرافين تحت متوسطه، وبع عند ارتفاعه فوقه."""
    params = ZParams.from_cfg(cfg)
    timeframe = str(cfg.get("strategy.timeframe", "15m")) if cfg else "15m"
    decision = Decision(symbol=symbol, timeframe=timeframe, strategy=MEAN_REVERSION_Z)

    data = candles.without_last() if (use_closed_candles and len(candles) > 2) else candles
    needed = max(params.length, params.atr_length) + 5
    if candles is None or len(data) < needed:
        decision.notes.append(f"عدد الشموع قليل (يحتاج {needed})")
        return decision

    close = list(data.close)
    index = len(close) - 1
    mean_values = sma(close, params.length)
    std_values = rolling_std(close, params.length, ddof=1)
    mean_now = mean_values[index] if index < len(mean_values) else NAN
    std_now = std_values[index] if index < len(std_values) else NAN

    if mean_now != mean_now or std_now != std_now or std_now <= 0:
        decision.notes.append("لا يمكن حساب الانحراف المعياري")
        return decision

    z = (close[index] - mean_now) / std_now
    decision.price = data.last_close
    decision.lines.append(f"  📐 z-score = {z:+.2f} (المتوسط {params.length})")

    if z <= -params.entry_z:
        decision.side = BUY
        decision.notes.append(f"السعر تحت متوسطه بـ {abs(z):.2f} انحراف ⇒ شراء")
    elif z >= params.entry_z:
        decision.side = SELL
        decision.notes.append(f"السعر فوق متوسطه بـ {z:.2f} انحراف ⇒ بيع")
    else:
        decision.notes.append(
            f"السعر قريب من متوسطه (|z| = {abs(z):.2f} < {params.entry_z}) ⇒ لا صفقة")
        return decision

    _attach_atr_exits(decision, data, params.atr_length,
                      params.sl_coef, params.tp_ratio)
    return decision


# ═══════════════════════ 2) ارتداد RSI ═══════════════════════
RSI_REVERSION = "rsi_reversion"


@dataclass
class RsiParams:
    period: int = 14
    oversold: float = 25.0
    overbought: float = 75.0
    atr_length: int = 14
    sl_coef: float = 1.5
    tp_ratio: float = 1.5

    @classmethod
    def from_cfg(cls, cfg) -> "RsiParams":
        node = (cfg.get("strategy.rsi_reversion", {}) or {}) if cfg else {}
        g = node.get
        return cls(
            period=int(g("period", 14)),
            oversold=float(g("oversold", 25.0)),
            overbought=float(g("overbought", 75.0)),
            atr_length=int(g("atr_length", 14)),
            sl_coef=float(g("sl_coef", 1.5)),
            tp_ratio=float(g("tp_ratio", 1.5)),
        )


def evaluate_rsi(candles: Candles, cfg=None, symbol: str = "",
                 use_closed_candles: bool = True) -> Decision:
    """نسخة أبسط من الأصلية: مؤشر واحد (RSI) بلا تأكيد مزدوج.

    الأصلية نادراً ما تُصدر إشارة (14 صفقة في 4800 شمعة) لأنها تشترط
    اتفاق مؤشرَين. هذه تكتفي بواحد ⇒ عيّنة أكبر ⇒ حكم إحصائي أصدق.
    """
    params = RsiParams.from_cfg(cfg)
    timeframe = str(cfg.get("strategy.timeframe", "15m")) if cfg else "15m"
    decision = Decision(symbol=symbol, timeframe=timeframe, strategy=RSI_REVERSION)

    data = candles.without_last() if (use_closed_candles and len(candles) > 2) else candles
    needed = max(params.period, params.atr_length) + 5
    if candles is None or len(data) < needed:
        decision.notes.append(f"عدد الشموع قليل (يحتاج {needed})")
        return decision

    closes = list(data.close)
    values = rsi(closes, params.period)
    index = len(data) - 1
    value = values[index] if index < len(values) else NAN
    if value != value:
        decision.notes.append("لا يمكن حساب RSI")
        return decision

    # حارس: سلسلة ثابتة تماماً تعطي RSI = 100 (بلا حركة ⇒ لا مكسب ولا خسارة)
    # فتُصدر «بيع» وهمياً. السوق الميّت لا يعطي إشارة.
    window_closes = closes[max(0, index - params.period): index + 1]
    if len(window_closes) > 1 and max(window_closes) - min(window_closes) <= 0:
        decision.notes.append("السعر ثابت تماماً ⇒ RSI بلا معنى")
        return decision

    decision.price = data.last_close
    decision.lines.append(f"  📉 RSI({params.period}) = {value:.1f}")

    if value <= params.oversold:
        decision.side = BUY
        decision.notes.append(f"تشبّع بيعي ({value:.1f} ≤ {params.oversold:g}) ⇒ شراء")
    elif value >= params.overbought:
        decision.side = SELL
        decision.notes.append(f"تشبّع شرائي ({value:.1f} ≥ {params.overbought:g}) ⇒ بيع")
    else:
        decision.notes.append(
            f"RSI في النطاق المحايد ({value:.1f}) ⇒ لا صفقة")
        return decision

    _attach_atr_exits(decision, data, params.atr_length,
                      params.sl_coef, params.tp_ratio)
    return decision


# ═══════════════════════ 3) اختراق دونشيان ═══════════════════════
DONCHIAN_BREAKOUT = "donchian_breakout"


@dataclass
class DonchianParams:
    length: int = 20          # نافذة القناة
    atr_length: int = 14
    sl_coef: float = 2.0
    tp_ratio: float = 2.0     # الاختراقات تحتاج هدفاً أوسع

    @classmethod
    def from_cfg(cls, cfg) -> "DonchianParams":
        node = (cfg.get("strategy.donchian_breakout", {}) or {}) if cfg else {}
        g = node.get
        return cls(
            length=int(g("length", 20)),
            atr_length=int(g("atr_length", 14)),
            sl_coef=float(g("sl_coef", 2.0)),
            tp_ratio=float(g("tp_ratio", 2.0)),
        )


def evaluate_donchian(candles: Candles, cfg=None, symbol: str = "",
                      use_closed_candles: bool = True) -> Decision:
    """اشترِ عند كسر أعلى قمة في N شمعة، وبع عند كسر أدنى قاع.

    عكس الارتداد تماماً: تفترض أن **الاختراق يستمرّ** — أي تعمل حيث
    تخسر الاستراتيجيتان الحاليتان (السوق المتّجه).
    """
    params = DonchianParams.from_cfg(cfg)
    timeframe = str(cfg.get("strategy.timeframe", "15m")) if cfg else "15m"
    decision = Decision(symbol=symbol, timeframe=timeframe, strategy=DONCHIAN_BREAKOUT)

    data = candles.without_last() if (use_closed_candles and len(candles) > 2) else candles
    needed = max(params.length, params.atr_length) + 5
    if candles is None or len(data) < needed:
        decision.notes.append(f"عدد الشموع قليل (يحتاج {needed})")
        return decision

    index = len(data) - 1
    start = max(0, index - params.length)
    high = list(data.high)
    low = list(data.low)
    window_high = max(high[start:index])          # الشمعة الحالية مستثناة
    window_low = min(low[start:index])
    price = data.last_close
    decision.price = price
    decision.lines.append(
        f"  📦 قناة {params.length}: {window_low:.4f} ← → {window_high:.4f}")

    if price > window_high:
        decision.side = BUY
        decision.notes.append(f"كسر أعلى قمة في {params.length} شمعة ⇒ شراء")
    elif price < window_low:
        decision.side = SELL
        decision.notes.append(f"كسر أدنى قاع في {params.length} شمعة ⇒ بيع")
    else:
        decision.notes.append("السعر داخل القناة ⇒ لا صفقة")
        return decision

    _attach_atr_exits(decision, data, params.atr_length,
                      params.sl_coef, params.tp_ratio)
    return decision


# ═══════════════════════ 4) زخم المتوسطات ═══════════════════════
EMA_MOMENTUM = "ema_momentum"


@dataclass
class MomentumParams:
    fast: int = 9
    slow: int = 21
    atr_length: int = 14
    sl_coef: float = 2.0
    tp_ratio: float = 2.0

    @classmethod
    def from_cfg(cls, cfg) -> "MomentumParams":
        node = (cfg.get("strategy.ema_momentum", {}) or {}) if cfg else {}
        g = node.get
        return cls(
            fast=int(g("fast", 9)),
            slow=int(g("slow", 21)),
            atr_length=int(g("atr_length", 14)),
            sl_coef=float(g("sl_coef", 2.0)),
            tp_ratio=float(g("tp_ratio", 2.0)),
        )


def evaluate_momentum(candles: Candles, cfg=None, symbol: str = "",
                      use_closed_candles: bool = True) -> Decision:
    """المتوسط السريع فوق البطيء **والسعر فوقه** ⇒ اشترِ (اتّباع اتجاه)."""
    params = MomentumParams.from_cfg(cfg)
    timeframe = str(cfg.get("strategy.timeframe", "15m")) if cfg else "15m"
    decision = Decision(symbol=symbol, timeframe=timeframe, strategy=EMA_MOMENTUM)

    data = candles.without_last() if (use_closed_candles and len(candles) > 2) else candles
    needed = max(params.fast, params.slow, params.atr_length) + 5
    if candles is None or len(data) < needed:
        decision.notes.append(f"عدد الشموع قليل (يحتاج {needed})")
        return decision

    close = list(data.close)
    index = len(close) - 1
    fast_values = ema(close, params.fast)
    slow_values = ema(close, params.slow)
    fast_now = fast_values[index] if index < len(fast_values) else NAN
    slow_now = slow_values[index] if index < len(slow_values) else NAN
    if fast_now != fast_now or slow_now != slow_now:
        decision.notes.append("لا يمكن حساب المتوسطات")
        return decision

    price = data.last_close
    decision.price = price
    decision.lines.append(
        f"  📈 EMA {params.fast} = {fast_now:.4f} · EMA {params.slow} = {slow_now:.4f}")

    if fast_now > slow_now and price > fast_now:
        decision.side = BUY
        decision.notes.append("ترتيب صاعد والسعر فوق المتوسط السريع ⇒ شراء")
    elif fast_now < slow_now and price < fast_now:
        decision.side = SELL
        decision.notes.append("ترتيب هابط والسعر تحت المتوسط السريع ⇒ بيع")
    else:
        decision.notes.append("لا اتجاه واضح ⇒ لا صفقة")
        return decision

    _attach_atr_exits(decision, data, params.atr_length,
                      params.sl_coef, params.tp_ratio)
    return decision


# ═══════════════════════ مخارج مشتركة ═══════════════════════
def _attach_atr_exits(decision: Decision, data: Candles, atr_length: int,
                      sl_coef: float, tp_ratio: float) -> None:
    """وقف وهدف من ATR — يتكيّفان مع تقلّب الرمز تلقائياً."""
    values = atr(list(data.high), list(data.low), list(data.close), atr_length)
    index = len(data) - 1
    current = values[index] if index < len(values) else NAN
    if current != current or current <= 0:
        decision.notes.append("تعذّر حساب ATR ⇒ بلا مسافات خروج")
        return
    distance = current * sl_coef
    decision.sl_distance = distance
    decision.tp_distance = distance * tp_ratio
    price = decision.price
    if price and price == price:
        if decision.side == BUY:
            decision.stop_loss = price - distance
            decision.take_profit = price + distance * tp_ratio
        else:
            decision.stop_loss = price + distance
            decision.take_profit = price - distance * tp_ratio
    decision.lines.append(
        f"  🎯 وقف {sl_coef:g}×ATR ({distance:.4f}) · هدف {tp_ratio:g}:1")
