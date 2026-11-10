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
    min_candles: int = 60          # أقل عدد شموع تحتاجه الاستراتيجية لتعمل


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


def resolve(key: Optional[str] = None) -> tuple[Strategy, str]:
    """(الاستراتيجية، رسالة خطأ) — الصرامة تبدأ من هنا.

    بخلاف `get` الذي يرجع استراتيجية بديلة **بصمت**، هذه الدالة تُبلغك إن كان
    المطلوب غير معروف، حتى لا يعمل البوت باستراتيجية ظنّاً وأنت تظن غيرها.
    """
    if not _REGISTRY:
        raise LookupError("لا توجد أي استراتيجية مسجّلة")
    if key and key in _REGISTRY:
        return _REGISTRY[key], ""
    fallback = next(iter(_REGISTRY.values()))
    if key:
        return fallback, f'الاستراتيجية "{key}" غير معروفة'
    return fallback, "لم تُحدَّد استراتيجية في الإعدادات"


VALID_EXIT_MODES = ("percent", "atr")


def check_config(cfg) -> list[str]:
    """يتحقق من اتساق إعدادات الاستراتيجية ويُصلحها. يُرجع تحذيرات جاهزة للعرض.

    الصرامة تعني: ما دمتَ اخترتَ استراتيجية، تُطبَّق **كاملة** — منطقُها
    ومخارجُها. أي تعارض يُصلَّح ويُبلَّغ عنه بدل أن يُهمَل بصمت.
    """
    warnings: list[str] = []
    requested = cfg.get("strategy.name")
    strategy, error = resolve(requested)
    if error:
        cfg.set("strategy.name", strategy.key)
        warnings.append(f"{error} — تم استخدام {strategy.key}. المتاحة: {', '.join(names())}")

    follow = bool(cfg.get("exit.follow_strategy", True))
    mode = str(cfg.get("exit.mode", "percent") or "percent").lower()
    if mode not in VALID_EXIT_MODES:
        warnings.append(
            f'وضع الخروج "{mode}" غير معروف — تم استخدام "{strategy.exit_mode}"'
        )
        cfg.set("exit.mode", strategy.exit_mode)
    elif follow and mode != strategy.exit_mode:
        warnings.append(
            f"⚠️ وضع الخروج <code>{mode}</code> لا يطابق استراتيجية "
            f"<code>{strategy.key}</code> — طُبِّق <code>{strategy.exit_mode}</code> "
            "لأن الاستراتيجية تُطبَّق كاملة. لتجاوز ذلك: "
            "<code>/set follow_exit false</code>"
        )
        cfg.set("exit.mode", strategy.exit_mode)

    try:
        candles = int(cfg.get("strategy.candles", 500))
    except (TypeError, ValueError):
        candles = 500
    if candles < strategy.min_candles:
        warnings.append(
            f"⚠️ عدد الشموع المطلوب ({candles}) أقل مما تحتاجه "
            f"<code>{strategy.key}</code> ({strategy.min_candles}) — لن تصدر أي إشارة. "
            f"صحّحه بـ <code>/set candles {strategy.min_candles * 4}</code>"
        )
    return warnings


# ─────────────────── تسجيل الاستراتيجيات المضمّنة ───────────────────
from . import engine, scalping_i   # noqa: E402

register(
    Strategy(
        key="rsi_williams",
        title="RSI + Williams %R (الأصلية)",
        description="تأكيد مزدوج: اختراق RSI من تشبّع + تقاطع Williams %R مع EMA.",
        exit_mode="percent",
        evaluate=engine.evaluate,
        source="الاستراتيجية الافتراضية في المشروع",
        min_candles=engine.MIN_CANDLES,
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
        min_candles=scalping_i.MIN_CANDLES,
    )
)

__all__ = [
    "Strategy",
    "register",
    "get",
    "resolve",
    "check_config",
    "VALID_EXIT_MODES",
    "names",
    "all_strategies",
    "evaluate",
    "is_supported",
]
