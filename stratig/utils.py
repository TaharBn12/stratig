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
