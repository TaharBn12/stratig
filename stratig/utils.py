"""أدوات مشتركة صغيرة (بدون تبعيات داخلية لتجنّب الاستيراد الدائري)."""
from __future__ import annotations


def num(value, digits: int = 8) -> str:
    """رقم مقروء للعرض في الرسائل (بدون أصفار زائدة)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value == 0:
        return "0"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def esc(text) -> str:
    """تهريب رموز HTML قبل الإرسال إلى تليجرام."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ═══════════════════ الإطارات الزمنية ═══════════════════
# الإطارات التي تقبلها منصات العقود (Binance / Bybit) — أي قيمة خارجها
# تُرفض من المنصة، فتفشل كل طلبات الشموع بصمت ولا تظهر أي إشارة.
ALLOWED_TIMEFRAMES: tuple[str, ...] = (
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
)

# مرادفات شائعة يكتبها المستخدم بدل الصيغة الرسمية
_TIMEFRAME_ALIASES: dict[str, str] = {
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m", "30min": "30m",
    "1hour": "1h", "2hour": "2h", "4hour": "4h", "6hour": "6h",
    "8hour": "8h", "12hour": "12h",
    "1day": "1d", "3day": "3d", "1week": "1w", "1month": "1M",
    "60": "1h", "240": "4h", "1440": "1d",
    "1mon": "1M", "1mo": "1M", "1month": "1M",
}


def normalize_timeframe(value, default: str = "15m") -> str:
    """يُوحّد الإطار الزمني إلى صيغة المنصة: 5 / '5min' / '5M' → '5m'.

    `1M` (بحرف كبير) = شهر، و`1m` = دقيقة — Binance تفرّق بينهما.
    يُرجع `default` إن لم يمكن فهم القيمة.
    """
    raw = str(value or "").strip()
    if not raw:
        return default
    if raw == "1M":                                   # الشهر: الإطار الوحيد بحرف M كبير
        return raw
    text = raw.lower()
    if text in _TIMEFRAME_ALIASES:
        return _TIMEFRAME_ALIASES[text]
    if text.isdigit():
        return f"{int(text)}m" if int(text) > 0 else default
    if text.endswith("m") and text[:-1].isdigit():
        return text                      # دقائق — الحرف m صغير دائماً
    unit = text[-1]
    if unit in ("h", "d", "w") and text[:-1].isdigit():
        return text
    if unit == "m" and len(text) > 1 and text[:-1].isdigit():
        return text
    if text.endswith("mo"):              # 1mo → 1M
        return f"{text[:-2]}M" if text[:-2].isdigit() else default
    return default


def is_supported_timeframe(value) -> bool:
    return normalize_timeframe(value, default="") in ALLOWED_TIMEFRAMES
