"""محرك الاستراتيجيات.

- `engine`     : الاستراتيجية الأصلية (RSI + Williams %R)
- `scalping_i` : استراتيجية الدفتر 01_Strategy_Scalping_Modified_I (حرفياً)
- `registry`   : السجل — منه يختار البوت الاستراتيجية ويبدّلها
                 (يُستورد مباشرة: `from stratig.strategy.registry import get`)
"""
from .engine import Decision, evaluate
from .indicators import IndicatorResult, rsi_signal, williams_r_signal

__all__ = ["evaluate", "Decision", "IndicatorResult", "rsi_signal", "williams_r_signal"]
