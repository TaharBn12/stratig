"""اختبارات استراتيجية 01_Strategy_Scalping_Modified_I — مطابقة للدفتر حرفياً.

تحقّق هذه الاختبارات أن المنطق منقول كما هو:
- نافذة EMA هي [current-7, current) — **لا** تشمل الشمعة الحالية
- الشراء = اتجاه صاعد + إغلاق ≤ الحد السفلي · البيع = هابط + إغلاق ≥ العلوي
- الوقف = 1.1 × ATR · الهدف = 1.5 × الوقف
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config  # noqa: E402
from stratig.data import Candles  # noqa: E402
from stratig.strategy.indicators import atr, bbands, ema, rsi  # noqa: E402
from stratig.strategy.registry import all_strategies, get, is_supported, names  # noqa: E402
from stratig.strategy.scalping_i import (  # noqa: E402
    BACKCANDLES,
    BUY_SIGNAL,
    SELL_SIGNAL,
    SL_COEF,
    TPSL_RATIO,
    evaluate,
    ema_signal,
    total_signal,
)

# ═══════════════════════ EMA Signal ═══════════════════════
def test_ema_signal_uptrend():
    fast = [2.0] * 20
    slow = [1.0] * 20
    assert ema_signal(fast, slow, 10, 7) == 2


def test_ema_signal_downtrend():
    fast = [1.0] * 20
    slow = [2.0] * 20
    assert ema_signal(fast, slow, 10, 7) == 1


def test_ema_signal_excludes_current_candle():
    """النافذة [i-7, i) — الشمعة الحالية لا تُحسب (iloc[start:end] في الدفتر)."""
    fast = [2.0] * 20
    slow = [1.0] * 20
    fast[12] = 0.0                       # الشمعة الحالية مخالفة
    assert ema_signal(fast, slow, 12, 7) == 2     # لا تُرى بعد
    assert ema_signal(fast, slow, 13, 7) == 0     # تدخل النافذة → اختلاط


def test_ema_signal_mixed_is_zero():
    fast = [2.0] * 20
    slow = [1.0] * 20
    fast[8] = 0.0
    assert ema_signal(fast, slow, 10, 7) == 0


def test_ema_signal_start_clamped_at_zero():
    fast = [2.0] * 5
    slow = [1.0] * 5
    assert ema_signal(fast, slow, 2, 7) == 2      # max(0, 2-7) = 0


# ═══════════════════════ Total Signal ═══════════════════════
def _flat(value: float, size: int = 30) -> list[float]:
    return [value] * size


def test_total_signal_buy_when_uptrend_and_close_below_lower():
    close = _flat(100.0)
    close[-1] = 90.0                     # إغلاق تحت الحد السفلي
    assert total_signal(close, _flat(95.0), _flat(105.0), _flat(2.0), _flat(1.0), 29, 7) == BUY_SIGNAL


def test_total_signal_sell_when_downtrend_and_close_above_upper():
    close = _flat(100.0)
    close[-1] = 110.0                    # إغلاق فوق الحد العلوي
    assert total_signal(close, _flat(95.0), _flat(105.0), _flat(1.0), _flat(2.0), 29, 7) == SELL_SIGNAL


def test_total_signal_none_when_price_inside_bands():
    close = _flat(100.0)
    assert total_signal(close, _flat(95.0), _flat(105.0), _flat(2.0), _flat(1.0), 29, 7) == 0


def test_total_signal_none_when_trend_missing():
    close = _flat(100.0)
    close[-1] = 90.0
    # اتجاه محايد (متساويان) → لا إشارة حتى مع لمس الحد السفلي
    assert total_signal(close, _flat(95.0), _flat(105.0), _flat(1.0), _flat(1.0), 29, 7) == 0


# ═══════════════════════ المخارج من ATR ═══════════════════════
def _candles(closes: list[float], spread: float = 1.0) -> Candles:
    size = len(closes)
    return Candles(
        times=list(range(size)),
        open=list(closes),
        high=[c + spread for c in closes],
        low=[c - spread for c in closes],
        close=list(closes),
        volume=[1.0] * size,
    )


def _trend(direction: float, size: int = 200) -> list[float]:
    """اتجاه ثابت (EMA السريع فوق/تحت البطيء طوال الطريق) ثم شمعة حادة."""
    return [100.0 * ((1 + 0.003 * direction) ** i) for i in range(size)]


def test_evaluate_buy_exits_follow_atr():
    """وقف = 1.1 × ATR تحت السعر · هدف = 1.5 × الوقف فوقه."""
    closes = _trend(+1)
    closes.append(closes[-1] * 0.90)              # هبوط حاد يلمس الحد السفلي
    cfg = Config({}, path=Path("config.toml"))
    cfg.set("strategy.name", "scalping_i")
    cfg.set("strategy.use_closed_candles", False)

    decision = evaluate(_candles(closes), cfg, symbol="XUSDT", use_closed_candles=False)
    assert decision.side == "buy", decision.notes
    # المسافة نفسها = slcoef × ATR(7) تماماً كما في صنف MyStrat
    expected_atr = atr(
        [c + 1.0 for c in closes], [c - 1.0 for c in closes], closes, 7, mode="rma"
    )[-1]
    assert decision.sl_distance == pytest.approx(SL_COEF * expected_atr, rel=1e-9)
    assert decision.sl_distance and decision.tp_distance
    assert decision.tp_distance == pytest.approx(decision.sl_distance * TPSL_RATIO)
    assert decision.stop_loss == pytest.approx(decision.price - decision.sl_distance)
    assert decision.take_profit == pytest.approx(decision.price + decision.tp_distance)


def test_evaluate_sell_exits_follow_atr():
    closes = _trend(-1)
    closes.append(closes[-1] * 1.10)              # صعود حاد يلمس الحد العلوي
    cfg = Config({}, path=Path("config.toml"))
    cfg.set("strategy.use_closed_candles", False)

    decision = evaluate(_candles(closes), cfg, symbol="XUSDT", use_closed_candles=False)
    assert decision.side == "sell", decision.notes
    assert decision.stop_loss == pytest.approx(decision.price + decision.sl_distance)
    assert decision.take_profit == pytest.approx(decision.price - decision.tp_distance)


def test_evaluate_needs_enough_candles():
    cfg = Config({}, path=Path("config.toml"))
    decision = evaluate(_candles([100.0] * 20), cfg, use_closed_candles=False)
    assert decision.side is None
    assert any("قليل" in note for note in decision.notes)


def test_evaluate_produces_readable_lines():
    cfg = Config({}, path=Path("config.toml"))
    random.seed(5)
    closes = [100.0]
    for _ in range(200):
        closes.append(closes[-1] * (1 + random.uniform(-0.006, 0.006)))
    decision = evaluate(_candles(closes), cfg, use_closed_candles=False)
    text = decision.describe()
    assert "EMA" in text and "ATR" in text and "بولينجر" in text


# ═══════════════════════ السجل ═══════════════════════
def test_registry_lists_both_strategies():
    assert "rsi_williams" in names()
    assert "scalping_i" in names()
    assert is_supported("scalping_i") and not is_supported("unknown")
    assert get("scalping_i").exit_mode == "atr"
    assert get("rsi_williams").exit_mode == "percent"


def test_unknown_key_falls_back_to_first():
    assert get(None).key == "rsi_williams"


def test_each_strategy_has_title_and_description():
    for strategy in all_strategies():
        assert strategy.title and strategy.description and callable(strategy.evaluate)


# ═══════════════════════ تطابق مع pandas (إن توفّر) ═══════════════════════
try:  # pandas اختياري — لا يدخل في requirements (لا تبعيات مجمَّعة)
    import pandas as _pd
except ImportError:  # pragma: no cover
    _pd = None

needs_pandas = pytest.mark.skipif(_pd is None, reason="pandas غير مثبّت (اختياري)")


@needs_pandas
def test_indicators_match_pandas():
    """مقارنة مؤشراتنا الخالصة بـ pandas/pandas_ta على نفس السلسلة."""
    random.seed(42)
    closes = [100.0]
    for _ in range(300):
        closes.append(closes[-1] * (1 + random.uniform(-0.01, 0.01)))
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]

    series = _pd.Series(closes)
    # EMA (adjust=False كما في pandas_ta و ta)
    assert ema(closes, 30)[-1] == pytest.approx(
        series.ewm(span=30, adjust=False).mean().tolist()[-1], rel=1e-9
    )
    SMA = series.rolling(15).mean()
    STD = series.rolling(15).std(ddof=1)          # ddof=1 = سلوك pandas_ta
    lower, middle, upper = bbands(closes, 15, 1.5, ddof=1)
    assert middle[-1] == pytest.approx(SMA.tolist()[-1], rel=1e-9)
    assert lower[-1] == pytest.approx((SMA - 1.5 * STD).tolist()[-1], rel=1e-9)
    assert upper[-1] == pytest.approx((SMA + 1.5 * STD).tolist()[-1], rel=1e-9)

    tr = _pd.concat(
        [
            _pd.Series(highs) - _pd.Series(lows),
            (_pd.Series(highs) - series.shift()).abs(),
            (series.shift() - _pd.Series(lows)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    reference_atr = tr.ewm(alpha=1 / 7, min_periods=7).mean().tolist()   # rma في pandas_ta
    assert atr(highs, lows, closes, 7, mode="rma")[-1] == pytest.approx(
        reference_atr[-1], rel=1e-6
    )


@needs_pandas
def test_full_pipeline_matches_notebook_with_pandas():
    """أقوى اختبار: نشغّل منطق الدفتر كاملاً بـ pandas ونقارنه بنسختنا."""
    random.seed(1234)
    size = 400
    closes = [100.0]
    for _ in range(size):
        closes.append(closes[-1] * (1 + random.uniform(-0.012, 0.012)))
    highs = [c * (1 + abs(random.uniform(0, 0.004))) for c in closes]
    lows = [c * (1 - abs(random.uniform(0, 0.004))) for c in closes]

    series = _pd.Series(closes)
    slow = series.ewm(span=50, adjust=False).mean().tolist()
    fast = series.ewm(span=30, adjust=False).mean().tolist()
    sma15 = series.rolling(15).mean()
    std15 = series.rolling(15).std(ddof=1)
    lower = (sma15 - 1.5 * std15).tolist()
    upper = (sma15 + 1.5 * std15).tolist()

    def ref_ema_signal(i: int, back: int = BACKCANDLES) -> int:
        rows = range(max(0, i - back), i)
        if not len(list(rows)):
            return 0
        if all(fast[j] < slow[j] for j in rows):
            return 1
        if all(fast[j] > slow[j] for j in rows):
            return 2
        return 0

    def ref_total(i: int) -> int:
        if ref_ema_signal(i) == 2 and closes[i] <= lower[i]:
            return 2
        if ref_ema_signal(i) == 1 and closes[i] >= upper[i]:
            return 1
        return 0

    for i in range(60, size):
        assert ema_signal(fast, slow, i, BACKCANDLES) == ref_ema_signal(i)
        assert (
            total_signal(closes, lower, upper, fast, slow, i, BACKCANDLES) == ref_total(i)
        ), f"اختلاف عند الشمعة {i}"
