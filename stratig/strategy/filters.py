"""فلاتر جودة الإشارة — تقلّل عدد الإشارات وتُبقي الأفضل.

الهدف: «إشارات كثيرة لكن ضعيفة». الفلاتر لا تُغيّر منطق أي استراتيجية،
بل تعمل **بعد** حساب الإشارة فترفض ما لا يستوفي شروط الجودة.

ثلاثة فلاتر، كلها اختيارية ومُعطّلة افتراضياً:

1. **نظام السوق (ADX)** — أهمّها. قياسنا أثبت:
       `rsi_williams` في سوق متّجه ‎−0.50R‎ · في سوق جانبي ‎+0.18R‎
   إذن: اسمح لها في الجانبي only، واسمح لاستراتيجيات الاتجاه في المتّجه only.

2. **تأكيد إطار أعلى (MTF)** — لا تشترِ في هبوط الإطار الأعلى.
   الإشارة على 15m، والتأكيد من 1h: اشترِ فقط إن كان سعر 1h فوق EMA 50.

3. **التقلّب (ATR%)** — استبعد الساكن (لا يتحرك) والهائج (خطر).

المنطق كله خالص (بلا منصة) ليسهل اختباره.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

NAN = float("nan")

REGIME_OFF = "off"
REGIME_TREND = "trend"
REGIME_RANGE = "range"


@dataclass
class FilterVerdict:
    allowed: bool
    reason: str = ""        # سبب الرفض (أو "") للعرض في رسالة الإشارة
    note: str = ""          # معلومة مفيدة تُعرض حتى عند القبول (ADX، ATR%…)


# ═══════════════════════ 1) نظام السوق ═══════════════════════
def regime_ok(
    adx_value: float,
    mode: str = REGIME_OFF,
    trend_min: float = 25.0,
    range_max: float = 20.0,
) -> FilterVerdict:
    """هل نظام السوق مناسب؟ (قياس ADX بلا جهة)."""
    mode = str(mode or REGIME_OFF).lower()
    if mode == REGIME_OFF:
        return FilterVerdict(True, "", "")
    if adx_value != adx_value:                       # NaN
        return FilterVerdict(True, "", "ADX غير متاح")
    note = f"ADX {adx_value:.0f}"
    if mode == REGIME_TREND:
        if adx_value < trend_min:
            return FilterVerdict(
                False,
                f"السوق بلا اتجاه (ADX {adx_value:.0f} < {trend_min:g}) — "
                "الاستراتيجية تحتاج اتجاهاً",
                note,
            )
        return FilterVerdict(True, "", note)
    if mode == REGIME_RANGE:
        if adx_value > range_max:
            return FilterVerdict(
                False,
                f"السوق متّجه بقوة (ADX {adx_value:.0f} > {range_max:g}) — "
                "الاستراتيجية تحتاج تذبذباً",
                note,
            )
        return FilterVerdict(True, "", note)
    return FilterVerdict(True, "", note)


# ═══════════════════════ 2) تأكيد الإطار الأعلى ═══════════════════════
def mtf_ok(
    side: str,
    higher_close: float,
    higher_ema: float,
    enabled: bool = False,
    timeframe: str = "1h",
) -> FilterVerdict:
    """الإطار الأعلى يؤكّد جهة الصفقة؟

    شراء: سعر الإطار الأعلى فوق متوسطه · بيع: تحته.
    القاعدة الشهيرة: «اتّبع التيار، لا تعاكسه».
    """
    if not enabled:
        return FilterVerdict(True, "", "")
    if not higher_close or not higher_ema:
        return FilterVerdict(True, "", "MTF غير متاح")
    aligned = higher_close >= higher_ema if side == "buy" else higher_close <= higher_ema
    note = f"MTF {timeframe}: {'فوق' if higher_close >= higher_ema else 'تحت'} المتوسط"
    if aligned:
        return FilterVerdict(True, "", note)
    return FilterVerdict(
        False,
        f"الإطار الأعلى ({timeframe}) يعاكس الصفقة — "
        f"السعر {'تحت' if side == 'buy' else 'فوق'} متوسطه",
        note,
    )


# ═══════════════════════ 3) التقلّب ═══════════════════════
def volatility_ok(
    atr_percent: float,
    min_pct: float = 0.0,
    max_pct: float = 0.0,
) -> FilterVerdict:
    """هل التقلّب مناسب؟ ساكن جداً = بلا حركة · هائج جداً = خطر."""
    if atr_percent != atr_percent or atr_percent <= 0:   # NaN أو صفر
        return FilterVerdict(True, "", "التقلّب غير متاح")
    note = f"تقلّب {atr_percent * 100:.2f}%"
    if min_pct and atr_percent < min_pct:
        return FilterVerdict(
            False,
            f"السعر ساكن (تقلّب {atr_percent * 100:.2f}% < {min_pct * 100:.2f}%) — "
            "لن يبلغ الهدف",
            note,
        )
    if max_pct and atr_percent > max_pct:
        return FilterVerdict(
            False,
            f"السوق هائج (تقلّب {atr_percent * 100:.2f}% > {max_pct * 100:.2f}%) — "
            "المخاطرة أعلى من المخطّط",
            note,
        )
    return FilterVerdict(True, "", note)


# ═══════════════════════ التطبيق ═══════════════════════
def apply_filters(
    decision,
    *,
    adx_value: float = NAN,
    regime: str = REGIME_OFF,
    trend_min: float = 25.0,
    range_max: float = 20.0,
    mtf_enabled: bool = False,
    mtf_timeframe: str = "1h",
    higher_close: float = 0.0,
    higher_ema: float = 0.0,
    atr_percent: float = NAN,
    vol_min: float = 0.0,
    vol_max: float = 0.0,
) -> bool:
    """يطبّق الفلاتر الثلاثة على القرار. يُرجع True إن سُمح به.

    عند الرفض: يُفرّغ `decision.side` ويضيف السبب إلى `notes` و`lines`.
    عند القبول: يضيف معلومات الجودة إلى `lines` ليراها المستخدم.
    """
    checks = (
        regime_ok(adx_value, regime, trend_min, range_max),
        mtf_ok(decision.side, higher_close, higher_ema, mtf_enabled, mtf_timeframe),
        volatility_ok(atr_percent, vol_min, vol_max),
    )
    notes: list[str] = [v.note for v in checks if v.note]
    rejected = [v.reason for v in checks if not v.allowed]

    if rejected:
        decision.side = None
        for reason in rejected:
            decision.notes.append(f"مرفوض: {reason}")
            decision.lines.append(f"  ⛔ <b>مرفوض</b>: {reason}")
        return False

    if notes and decision.has_signal:
        decision.lines.append("  🧪 <b>الجودة</b>: " + " · ".join(notes))
    return True
