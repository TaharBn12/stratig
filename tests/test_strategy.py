"""اختبارات المؤشرات ومحرك الاستراتيجية."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config  # noqa: E402
from stratig.data import Candles, from_lists  # noqa: E402
from stratig.strategy import evaluate, rsi_signal, williams_r_signal  # noqa: E402
from stratig.strategy import indicators  # noqa: E402


def make_candles(
    sign: int = 1,
    decline: float = 1.0,
    n_dec: int = 100,
    n_steep: int = 20,
    flat: float = 0.05,
    n_flat: int = 5,
    bounce: float = 15.0,
    start: float = 1000.0,
) -> Candles:
    """سلسلة سعرية: هبوط طويل + انحدار حاد + استقرار + ارتداد.

    sign=1  → نمط قاع (إشارة شراء مؤكدة مزدوجة)
    sign=-1 → نمط قمة (إشارة بيع مؤكدة مزدوجة)
    """
    closes: list[float] = []
    price = start
    for _ in range(n_dec):
        price -= decline * sign
        closes.append(price)
    for _ in range(n_steep):
        price -= decline * 4 * sign
        closes.append(price)
    for _ in range(n_flat):
        price -= flat * sign
        closes.append(price)
    price += bounce * sign
    closes.append(price)

    highs = [c + abs(c) * 0.001 for c in closes]
    lows = [c - abs(c) * 0.001 for c in closes]
    return from_lists(closes, highs, lows)


def flat_candles(n: int = 200, price: float = 100.0) -> Candles:
    closes = [price] * n
    return from_lists(closes, [price + 1] * n, [price - 1] * n)


def cfg(**overrides) -> Config:
    return Config(overrides)


# ───────────────────────── RSI ─────────────────────────
def test_rsi_buy_on_oversold_breakout():
    res = rsi_signal(make_candles(sign=1).close, period=14, oversold=30, overbought=70, lookback=3)
    assert res.side == "buy", res.reason
    assert res.value > 30


def test_rsi_sell_on_overbought_breakdown():
    res = rsi_signal(make_candles(sign=-1).close, period=14, oversold=30, overbought=70, lookback=3)
    assert res.side == "sell", res.reason
    assert res.value < 70


def test_rsi_neutral_on_flat_market():
    res = rsi_signal(flat_candles().close)
    assert res.side is None


# ───────────────────── Williams %R ─────────────────────
def test_williams_buy_after_decline():
    data = make_candles(sign=1)
    res = williams_r_signal(data.high, data.low, data.close)
    assert res.side == "buy", res.reason


def test_williams_sell_after_rally():
    data = make_candles(sign=-1)
    res = williams_r_signal(data.high, data.low, data.close)
    assert res.side == "sell", res.reason


# ───────────────────── المحرك ─────────────────────
def test_engine_double_confirmation_buy():
    d = evaluate(make_candles(sign=1), cfg(), symbol="TESTUSDT", use_closed_candles=False)
    assert d.side == "buy"
    assert d.confirming == 2
    assert d.rsi.side == d.willr.side == "buy"


def test_engine_double_confirmation_sell():
    d = evaluate(make_candles(sign=-1), cfg(), symbol="TESTUSDT", use_closed_candles=False)
    assert d.side == "sell"
    assert d.confirming == 2


def test_engine_no_signal_on_flat_market():
    d = evaluate(flat_candles(), cfg(), symbol="FLATUSDT", use_closed_candles=False)
    assert d.side is None


def test_engine_conflict_is_rejected():
    """RSI يقول شراء بينما Williams %R عند قمة (تشبّع شرائي) → لا صفقة."""
    d = evaluate(make_candles(sign=1, bounce=300), cfg(), symbol="MIXUSDT", use_closed_candles=False)
    assert d.rsi.side == "buy"
    assert d.willr.side == "sell"
    assert d.side is None
    assert d.notes


def test_engine_single_indicator_mode():
    cfg_obj = cfg()
    cfg_obj.set("strategy.require_both", False)
    cfg_obj.set("strategy.williams_r.enabled", False)
    d = evaluate(make_candles(sign=1), cfg_obj, symbol="TESTUSDT", use_closed_candles=False)
    assert d.side == "buy"
    assert d.willr is None


def test_engine_ignores_short_history():
    d = evaluate(make_candles(sign=1).slice(0, 10), cfg(), symbol="SHORT", use_closed_candles=False)
    assert d.side is None


def test_use_closed_candles_drops_last_bar():
    data = make_candles(sign=1)
    d_open = evaluate(data, cfg(), symbol="X", use_closed_candles=False)
    d_closed = evaluate(data, cfg(), symbol="X", use_closed_candles=True)
    assert d_open.side == "buy"
    # عند تجاهل آخر شمعة يُحسب السعر من الشمعة قبل الأخيرة
    assert d_closed.price == pytest.approx(data.close[-2])


def test_empty_candles_is_safe():
    d = evaluate(Candles(), cfg(), symbol="EMPTY", use_closed_candles=False)
    assert d.side is None
    assert d.notes


# ─────────── مطابقة الحساب الداخلي لمكتبة ta (إن كانت مثبتة) ───────────
def _maybe_ta():
    try:
        import ta as _ta

        return _ta
    except ImportError:  # المكتبة اختيارية ولم تعد مطلوبة للتشغيل
        return None


def test_native_indicators_match_ta_when_available():
    """تأكيد أن الحساب الداخلي يطابق مكتبة ta (إن وُجدت على الجهاز)."""
    ta_mod = _maybe_ta()
    if ta_mod is None:
        pytest.skip("مكتبة ta غير مثبتة (اختيارية)")
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        pytest.skip("pandas غير مثبتة")

    data = make_candles(sign=1, n_dec=150)
    close = pd.Series(data.close)
    high = pd.Series(data.high)
    low = pd.Series(data.low)

    def maxdiff(a, b):
        diff = (pd.Series(a).reset_index(drop=True) - pd.Series(b).reset_index(drop=True)).abs()
        return float(diff.dropna().max())

    assert maxdiff(indicators.rsi(data.close, 14), ta_mod.momentum.RSIIndicator(close, window=14).rsi()) < 1e-9
    assert maxdiff(
        indicators.williams_r(data.high, data.low, data.close, 24),
        ta_mod.momentum.WilliamsRIndicator(high, low, close, lbp=24).williams_r(),
    ) < 1e-9

    # EMA يُحسب على القيم الصالحة فقط (بعد إسقاط NaN) في الحالتين
    w = [v for v in indicators.williams_r(data.high, data.low, data.close, 24) if v == v]
    t_w = ta_mod.momentum.WilliamsRIndicator(high, low, close, lbp=24).williams_r().dropna().reset_index(drop=True)
    assert maxdiff(indicators.ema(w, 24), ta_mod.trend.ema_indicator(t_w, window=24)) < 1e-9
