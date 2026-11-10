"""الاستراتيجية الأولى — 01_Strategy_Scalping_Modified_I (تُطبَّق حرفياً).

هذه الاستراتيجية منقولة **سطراً بسطر** من دفتر Jupyter
`01_Strategy_Scalping_Modified_I` مع الحفاظ على كل الثوابت والمنطق:

المؤشرات (كانت pandas_ta، والآن حساب خالص ببايثون بدون أي مكتبة مجمَّعة):
    EMA_slow   = ta.ema(Close, length=50)
    EMA_fast   = ta.ema(Close, length=30)
    RSI        = ta.rsi(Close, length=10)          # محسوب للعرض فقط
    BBANDS     = ta.bbands(Close, length=15, std=1.5)
    ATR        = ta.atr(High, Low, Close, length=7)

EMA Signal (من الدفتر):
    start = max(0, current_candle - backcandles)   # backcandles = 7
    end   = current_candle                          # حصري → آخر 7 شموع قبل الحالية
    if   all(EMA_fast < EMA_slow): return 1         # اتجاه هابط
    elif all(EMA_fast > EMA_slow): return 2         # اتجاه صاعد
    else:                          return 0

Total Signal (من الدفتر):
    ema_signal == 2 and Close <= BBL  →  2 = شراء (long)
    ema_signal == 1 and Close >= BBU  →  1 = بيع (short)
    غير ذلك                           →  0
    (فلتر RSI معطّل في الدفتر نفسه — سطوره معلَّقة — فبقي معطّلاً هنا)

الخروج (من صنف MyStrat في الدفتر):
    slatr      = slcoef * ATR            (slcoef = 1.1)
    اتجاه شراء:  SL = Close - slatr      |  TP = Close + slatr * TPSLRatio
    اتجاه بيع:   SL = Close + slatr      |  TP = Close - slatr * TPSLRatio
    TPSLRatio = 1.5  →  العائد : المخاطرة = 1.5 : 1

ملاحظة عن حجم الصفقة: الدفتر يستخدم `mysize = 3000` وحدة في الاختبار الخلفي،
أما البوت فيستخدم `trade.qty_usdt` (قيمة بالدولار) — الحجم إداري لا يغيّر الإشارة.
"""
from __future__ import annotations

import math

from ..data import Candles, NAN
from ..utils import esc
from .engine import BUY, SELL, Decision
from .indicators import atr, bbands, ema, rsi

KEY = "scalping_i"

# ═══════════════════ الثوابت من الدفتر (لا تُغيَّر) ═══════════════════
EMA_SLOW = 50
EMA_FAST = 30
RSI_LENGTH = 10
BB_LENGTH = 15
BB_STD = 1.5
BB_DDOF = 1          # سلوك pandas_ta التلقائي (عينة: N-1)
ATR_LENGTH = 7
BACKCANDLES = 7
SL_COEF = 1.1        # slcoef
TPSL_RATIO = 1.5     # TPSLRatio
MYSIZE = 3000        # للاختبار الخلفي فقط (مرجعي)

# الدفتر: signal==2 → self.buy  |  signal==1 → self.sell
BUY_SIGNAL = 2
SELL_SIGNAL = 1


class Params:
    """يقرأ المعاملات من الإعدادات مع الحفاظ على ثوابت الدفتر كقيم افتراضية."""

    def __init__(self, cfg=None) -> None:
        section = (cfg.get(f"strategy.{KEY}", {}) if cfg else {}) or {}
        get = section.get

        def pick(name: str, default, cast):
            try:
                value = get(name, default)
                return cast(value) if value is not None else default
            except (TypeError, ValueError):
                return default

        self.ema_slow = pick("ema_slow", EMA_SLOW, int)
        self.ema_fast = pick("ema_fast", EMA_FAST, int)
        self.rsi_length = pick("rsi_length", RSI_LENGTH, int)
        self.bb_length = pick("bb_length", BB_LENGTH, int)
        self.bb_std = pick("bb_std", BB_STD, float)
        self.bb_ddof = pick("bb_ddof", BB_DDOF, int)
        self.atr_length = pick("atr_length", ATR_LENGTH, int)
        self.atr_mode = str(get("atr_mode", "rma") or "rma")
        self.backcandles = pick("backcandles", BACKCANDLES, int)
        self.sl_coef = pick("sl_coef", SL_COEF, float)
        self.tp_sl_ratio = pick("tp_sl_ratio", TPSL_RATIO, float)


# ═══════════════════ منطق الدفتر كما هو ═══════════════════
def ema_signal(
    ema_fast: list[float],
    ema_slow: list[float],
    current_candle: int,
    backcandles: int = BACKCANDLES,
) -> int:
    """1 = اتجاه هابط · 2 = اتجاه صاعد · 0 = بلا اتجاه واضح.

    النطاق [current_candle - backcandles, current_candle) — أي **لا** يدخل
    الشمعة الحالية، تماماً كما في `df_slice.iloc[start:end]` في الدفتر.
    """
    start = max(0, current_candle - backcandles)
    end = current_candle
    if end <= start:
        return 0
    rows = range(start, end)
    if all(ema_fast[i] < ema_slow[i] for i in rows):
        return 1
    if all(ema_fast[i] > ema_slow[i] for i in rows):
        return 2
    return 0


def total_signal(
    close: list[float],
    lower: list[float],
    upper: list[float],
    ema_fast: list[float],
    ema_slow: list[float],
    current_candle: int,
    backcandles: int = BACKCANDLES,
) -> int:
    """2 = شراء · 1 = بيع · 0 = لا إشارة (نفس شفرة الدفتر)."""
    trend = ema_signal(ema_fast, ema_slow, current_candle, backcandles)
    if trend == BUY_SIGNAL and close[current_candle] <= lower[current_candle]:
        return BUY_SIGNAL
    if trend == SELL_SIGNAL and close[current_candle] >= upper[current_candle]:
        return SELL_SIGNAL
    return 0


def evaluate(
    candles: Candles, cfg=None, symbol: str = "", use_closed_candles: bool = True
) -> Decision:
    """يحسب إشارة الاستراتيجية لرمز واحد."""
    params = Params(cfg)
    timeframe = str(cfg.get("strategy.timeframe", "15m")) if cfg else "15m"
    decision = Decision(symbol=symbol, timeframe=timeframe, strategy=KEY)

    if candles is None or len(candles) == 0:
        decision.notes.append("لا توجد شموع")
        return decision

    data = candles.without_last() if (use_closed_candles and len(candles) > 2) else candles
    needed = max(params.ema_slow, params.bb_length, params.atr_length) + params.backcandles + 5
    if len(data) < needed:
        decision.notes.append(f"عدد الشموع قليل (يحتاج {needed})")
        return decision

    close = list(data.close)
    high = list(data.high)
    low = list(data.low)

    ema_slow_values = ema(close, params.ema_slow)
    ema_fast_values = ema(close, params.ema_fast)
    lower, middle, upper = bbands(
        close, params.bb_length, params.bb_std, ddof=params.bb_ddof
    )
    atr_values = atr(high, low, close, params.atr_length, mode=params.atr_mode)
    rsi_values = rsi(close, params.rsi_length)

    index = len(close) - 1                     # الشمعة الحالية
    signal = total_signal(
        close, lower, upper, ema_fast_values, ema_slow_values, index, params.backcandles
    )
    trend = ema_signal(ema_fast_values, ema_slow_values, index, params.backcandles)

    price = data.last_close
    decision.price = price

    current_atr = atr_values[index] if index < len(atr_values) else NAN
    if math.isnan(current_atr) or current_atr <= 0:
        decision.notes.append("ATR غير متاح")
        return decision

    sl_distance = params.sl_coef * current_atr
    tp_distance = sl_distance * params.tp_sl_ratio
    decision.sl_distance = sl_distance
    decision.tp_distance = tp_distance

    trend_ar = {2: "صاعد 🟢", 1: "هابط 🔴"}.get(trend, "محايد ➖")
    decision.lines = [
        f"  {'🔼' if trend == 2 else ('🔽' if trend == 1 else '➖')} <b>EMA {params.ema_fast}/{params.ema_slow}</b>: {trend_ar}",
        f"  📊 <b>بولينجر ({params.bb_length}, {params.bb_std:g})</b>: "
        f"السعر {esc(f'{price:.6g}')} | سفلي {esc(f'{lower[index]:.6g}')} | علوي {esc(f'{upper[index]:.6g}')}",
        f"  📏 <b>ATR {params.atr_length}</b>: {esc(f'{current_atr:.6g}')}",
        f"  🎯 <b>RSI {params.rsi_length}</b>: {esc(f'{rsi_values[index]:.1f}' if not math.isnan(rsi_values[index]) else '—')} (للعرض فقط)",
    ]

    if signal == BUY_SIGNAL:
        decision.side = BUY
        decision.stop_loss = price - sl_distance
        decision.take_profit = price + tp_distance
        decision.lines.append(
            f"  ✅ <b>الإشارة: شراء</b> (اتجاه صاعد + إغلاق ≤ الحد السفلي)"
        )
    elif signal == SELL_SIGNAL:
        decision.side = SELL
        decision.stop_loss = price + sl_distance
        decision.take_profit = price - tp_distance
        decision.lines.append(
            f"  ✅ <b>الإشارة: بيع</b> (اتجاه هابط + إغلاق ≥ الحد العلوي)"
        )
    else:
        decision.lines.append("  ➖ لا إشارة")
    return decision


# ═══════════════════ وصف للعرض ═══════════════════
DESCRIPTION = (
    "EMA 30/50 + بولينجر (15, 1.5) + ATR 7 — "
    "شراء عند اتجاه صاعد وإغلاق تحت الحد السفلي، وبيع عند اتجاه هابط وإغلاق فوق الحد العلوي. "
    "وقف = 1.1 × ATR، وهدف = 1.5 × الوقف."
)

TITLE = "Scalping Modified I (الدفتر الأول)"
