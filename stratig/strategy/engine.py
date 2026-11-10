"""محرك الاستراتيجية: يجمع إشارات المؤشرات ويصدر قراراً واحداً."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..data import Candles, NAN
from ..utils import esc
from .indicators import BUY, SELL, IndicatorResult, rsi_signal, williams_r_signal


@dataclass
class Decision:
    symbol: str
    side: Optional[str] = None        # buy | sell | None
    price: float = NAN
    timeframe: str = ""
    rsi: Optional[IndicatorResult] = None
    willr: Optional[IndicatorResult] = None
    requires_both: bool = True
    notes: list[str] = field(default_factory=list)
    # ── حقول مشتركة بين كل الاستراتيجيات ──
    strategy: str = ""
    lines: list[str] = field(default_factory=list)   # وصف جاهز للعرض (تليجرام)
    sl_distance: float | None = None                 # مسافة الوقف بالسعر (من ATR مثلاً)
    tp_distance: float | None = None                 # مسافة الهدف بالسعر
    stop_loss: float | None = None                   # سعر وقف مطلق
    take_profit: float | None = None                 # سعر هدف مطلق

    @property
    def has_signal(self) -> bool:
        return self.side in (BUY, SELL)

    @property
    def confirming(self) -> int:
        """عدد المؤشرات التي أعطت إشارة في نفس الاتجاه."""
        return sum(
            1
            for ind in (self.rsi, self.willr)
            if ind is not None and ind.side is not None and ind.side == self.side
        )

    def describe(self) -> str:
        if self.lines:                      # الاستراتيجيات الجديدة توفّر وصفها بنفسها
            return "\n".join(self.lines)
        lines = []
        for ind in (self.rsi, self.willr):
            if ind is None:
                continue
            mark = "🔼" if ind.side == BUY else ("🔽" if ind.side == SELL else "➖")
            # سبب المؤشر قد يحتوي على < أو > (مثال: 72.4 < 70) وهذا يكسر HTML تليجرام
            lines.append(f"  {mark} <b>{esc(ind.name)}</b>: {esc(ind.reason)}")
        return "\n".join(lines)


def evaluate(
    candles: Candles, cfg, symbol: str = "", use_closed_candles: bool = True
) -> Decision:
    """يحسب الإشارة لرمز واحد.

    candles: شموع مرتّبة بحيث آخر عنصر = أحدث شمعة
    cfg: كائن Config
    """
    timeframe = str(cfg.get("strategy.timeframe", "15m"))
    require_both = bool(cfg.get("strategy.require_both", True))
    decision = Decision(symbol=symbol, timeframe=timeframe, requires_both=require_both)

    if candles is None or len(candles) == 0:
        decision.notes.append("لا توجد شموع")
        return decision

    data = candles.without_last() if (use_closed_candles and len(candles) > 2) else candles
    if len(data) < 60:
        decision.notes.append("عدد الشموع قليل")
        return decision

    close = list(data.close)
    high = list(data.high)
    low = list(data.low)
    decision.price = data.last_close

    rsi_cfg = cfg.get("strategy.rsi", {}) or {}
    wr_cfg = cfg.get("strategy.williams_r", {}) or {}

    if rsi_cfg.get("enabled", True):
        decision.rsi = rsi_signal(
            close,
            period=int(rsi_cfg.get("period", 14)),
            oversold=float(rsi_cfg.get("oversold", 30)),
            overbought=float(rsi_cfg.get("overbought", 70)),
            lookback=int(rsi_cfg.get("lookback", 3)),
        )
    if wr_cfg.get("enabled", True):
        decision.willr = williams_r_signal(
            high,
            low,
            close,
            lbp=int(wr_cfg.get("lbp", 24)),
            ema_window=int(wr_cfg.get("ema_window", 24)),
            extreme_oversold=float(wr_cfg.get("extreme_oversold", -99.5)),
            extreme_overbought=float(wr_cfg.get("extreme_overbought", -0.5)),
            oversold=float(wr_cfg.get("oversold", -75)),
            overbought=float(wr_cfg.get("overbought", -25)),
        )

    signals = [ind for ind in (decision.rsi, decision.willr) if ind is not None and ind.has_signal]
    if not signals:
        return decision

    buys = [s for s in signals if s.side == BUY]
    sells = [s for s in signals if s.side == SELL]

    if require_both:
        # تأكيد مزدوج: كل المؤشرات المفعّلة يجب أن تتفق (ولا يجوز تعارضها)
        enabled_count = sum(1 for ind in (decision.rsi, decision.willr) if ind is not None)
        if buys and len(buys) == enabled_count:
            decision.side = BUY
        elif sells and len(sells) == enabled_count:
            decision.side = SELL
        elif buys and sells:
            decision.notes.append("المؤشرات متعارضة — لا صفقة")
    else:
        if len(buys) > len(sells):
            decision.side = BUY
        elif len(sells) > len(buys):
            decision.side = SELL
        else:
            decision.notes.append("المؤشرات متعارضة — لا صفقة")

    return decision
