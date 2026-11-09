"""حاوية الشموع + عمليات بسيطة — ببايثون خالص (بدون pandas/numpy).

السبب: مكتبتا numpy/pandas مترجَمة بلغة C وتفشل أحياناً على ويندوز
(خطأ DLL load failed) أو مع نسخ بايثون الجديدة. المشروع كله يعمل الآن
بدون أي مكتبة مترجَمة.
"""
from __future__ import annotations

from dataclasses import dataclass, field

NAN = float("nan")


@dataclass
class Candles:
    """شموع مرتّبة زمنياً بحيث **آخر عنصر = أحدث شمعة**."""

    times: list[float] = field(default_factory=list)
    open: list[float] = field(default_factory=list)
    high: list[float] = field(default_factory=list)
    low: list[float] = field(default_factory=list)
    close: list[float] = field(default_factory=list)
    volume: list[float] = field(default_factory=list)
    turnover: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.close)

    def __bool__(self) -> bool:
        return len(self.close) > 0

    @property
    def last_close(self) -> float:
        return self.close[-1] if self.close else NAN

    def slice(self, start: int | None = None, stop: int | None = None) -> "Candles":
        """نسخة مقطوعة (مثل df.iloc[start:stop])."""
        window = slice(start, stop)
        return Candles(
            times=self.times[window],
            open=self.open[window],
            high=self.high[window],
            low=self.low[window],
            close=self.close[window],
            volume=self.volume[window],
            turnover=self.turnover[window],
        )

    def without_last(self) -> "Candles":
        """بدون آخر شمعة (تُستخدم عند use_closed_candles)."""
        if len(self) <= 1:
            return self
        return self.slice(0, len(self) - 1)

    def __repr__(self) -> str:  # pragma: no cover
        if not self:
            return "<Candles فارغة>"
        return f"<Candles {len(self)} شمعة, آخر إغلاق {self.last_close}>"


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return NAN


def make_candles(raw, reverse: bool = False) -> Candles:
    """بناء Candles من مصفوفة المنصة.

    reverse=True  ← المنصة تعيد الأحدث أولاً (مثل Bybit)
    reverse=False ← المنصة تعيد الأقدم أولاً (مثل Binance)

    النتيجة في الحالتين: آخر عنصر = أحدث شمعة.
    """
    rows = list(raw or [])
    if reverse:
        rows = rows[::-1]

    times: list[float] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    turnovers: list[float] = []

    for row in rows:
        values = [_to_float(item) for item in row[:7]]
        while len(values) < 7:
            values.append(0.0)
        time_, open_, high_, low_, close_, volume_, turnover_ = values
        times.append(time_)
        opens.append(open_)
        highs.append(high_)
        lows.append(low_)
        closes.append(close_)
        volumes.append(volume_)
        turnovers.append(turnover_)

    return Candles(times, opens, highs, lows, closes, volumes, turnovers)


def from_lists(
    close: list[float],
    high: list[float] | None = None,
    low: list[float] | None = None,
    open_: list[float] | None = None,
) -> Candles:
    """بناء شموع من قوائم (مفيد للاختبارات والبيانات الاصطناعية)."""
    high = list(high) if high is not None else list(close)
    low = list(low) if low is not None else list(close)
    open_ = list(open_) if open_ is not None else list(close)
    return Candles(
        times=[float(i) for i in range(len(close))],
        open=open_,
        high=high,
        low=low,
        close=list(close),
        volume=[0.0] * len(close),
        turnover=[0.0] * len(close),
    )
