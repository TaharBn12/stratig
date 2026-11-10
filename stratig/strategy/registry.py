"""سجل الاستراتيجيات — يسمح بالتبديل بينها من تليجرام بدون إعادة تشغيل.

كل استراتيجية تُسجَّل بمعرّف (key) وتوفّر:
    key        : المعرّف في config.toml (strategy.name)
    title      : اسم مقروء بالعربية
    description: سطر شرح
    exit_mode  : "percent" أو "atr" — يُطبَّق تلقائياً عند اختيارها
    evaluate() : الدالة التي تُصدر القرار
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..data import Candles


@dataclass
class Strategy:
    key: str
    title: str
    description: str
    exit_mode: str                 # percent | atr
    evaluate: Callable[..., object]
    source: str = ""


_REGISTRY: dict[str, Strategy] = {}


def register(strategy: Strategy) -> Strategy:
    _REGISTRY[strategy.key] = strategy
    return strategy


def get(key: Optional[str]) -> Strategy:
    """استراتيجية بالمعرّف، أو الأولى إن كان المعرّف غير معروف."""
    if key and key in _REGISTRY:
        return _REGISTRY[key]
    if _REGISTRY:
        return next(iter(_REGISTRY.values()))
    raise LookupError("لا توجد أي استراتيجية مسجّلة")


def names() -> list[str]:
    return list(_REGISTRY)


def all_strategies() -> list[Strategy]:
    return list(_REGISTRY.values())


def evaluate(key: Optional[str], candles: Candles, cfg, symbol: str = "",
             use_closed_candles: bool = True):
    """يُشغّل الاستراتيجية المطلوبة على الشموع."""
    return get(key).evaluate(candles, cfg, symbol=symbol, use_closed_candles=use_closed_candles)


def is_supported(key: Optional[str]) -> bool:
    return bool(key) and key in _REGISTRY


# ─────────────────── تسجيل الاستراتيجيات المضمّنة ───────────────────
from . import scalping_i          # noqa: E402
from .engine import evaluate as _rsi_williams_evaluate  # noqa: E402

register(
    Strategy(
        key="rsi_williams",
        title="RSI + Williams %R (الأصلية)",
        description="تأكيد مزدوج: اختراق RSI من تشبّع + تقاطع Williams %R مع EMA.",
        exit_mode="percent",
        evaluate=_rsi_williams_evaluate,
        source="الاستراتيجية الافتراضية في المشروع",
    )
)

register(
    Strategy(
        key=scalping_i.KEY,
        title=scalping_i.TITLE,
        description=scalping_i.DESCRIPTION,
        exit_mode="atr",
        evaluate=scalping_i.evaluate,
        source="01_Strategy_Scalping_Modified_I.ipynb — مطبَّقة حرفياً",
    )
)

__all__ = [
    "Strategy",
    "register",
    "get",
    "names",
    "all_strategies",
    "evaluate",
    "is_supported",
]
