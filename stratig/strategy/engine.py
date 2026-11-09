"""محرك الاستراتيجية: يجمع إشارات المؤشرات ويصدر قراراً واحداً."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .indicators import BUY, SELL, IndicatorResult, rsi_signal, williams_r_signal


@dataclass
class Decision:
    symbol: str
    side: Optional[str] = None        # buy | sell | None
    price: float = 0.0
    timeframe: str = ""
    rsi: Optional[IndicatorResult] = None
    willr: Optional[IndicatorResult] = None
    requires_both: bool = True
    notes: list[str] = field(default_factory=list)

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
        lines = []
        for ind in (self.rsi, self.willr):
            if ind is None:
                continue
            mark = "🔼" if ind.side == BUY else ("🔽" if ind.side == SELL else "➖")
            lines.append(f"  {mark} <b>{ind.name}</b>: {ind.reason}")
        return "\n".join(lines)


def evaluate(df: pd.DataFrame, cfg, symbol: str = "", use_closed_candles: bool = True) -> Decision:
    """يحسب الإشارة لرمز واحد.

    df: شموع مرتبة بحيث آخر صف = أحدث شمعة
    cfg: كائن Config
    """
    timeframe = str(cfg.get("strategy.timeframe", "15m"))
    require_both = bool(cfg.get("strategy.require_both", True))
    decision = Decision(symbol=symbol, timeframe=timeframe, requires_both=require_both)

    if df is None or df.empty:
        decision.notes.append("لا توجد شموع")
        return decision

    data = df.iloc[:-1] if (use_closed_candles and len(df) > 2) else df
    if len(data) < 60:
        decision.notes.append("عدد الشموع قليل")
        return decision

    close = data["Close"].astype(float)
    high = data["High"].astype(float)
    low = data["Low"].astype(float)
    decision.price = float(close.iloc[-1])

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
