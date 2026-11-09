"""اختبارات المؤشرات ومحرك الاستراتيجية."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config  # noqa: E402
from stratig.strategy import evaluate, rsi_signal, williams_r_signal  # noqa: E402
from stratig.strategy import indicators  # noqa: E402


def make_df(sign: int = 1, decline: float = 1.0, n_dec: int = 100, n_steep: int = 20,
            flat: float = 0.05, n_flat: int = 5, bounce: float = 15.0, start: float = 1000.0):
    """سلسلة سعرية: هبوط طويل + انحدار حاد + استقرار + ارتداد.

    sign=1  → نمط قاع (إشارة شراء مؤكدة مزدوجة)
    sign=-1 → نمط قمة (إشارة بيع مؤكدة مزدوجة)
    """
    closes = []
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

    close = pd.Series(closes)
    high = close + close.abs() * 0.001
    low = close - close.abs() * 0.001
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1.0, "Turnover": 1.0}
    )


def flat_df(n: int = 200, price: float = 100.0) -> pd.DataFrame:
    close = pd.Series([price] * n)
    return pd.DataFrame(
        {
            "Open": close, "High": close + 1, "Low": close - 1,
            "Close": close, "Volume": 1.0, "Turnover": 1.0,
        }
    )


def cfg(**overrides) -> Config:
    return Config(overrides)


# ───────────────────────── RSI ─────────────────────────
def test_rsi_buy_on_oversold_breakout():
    res = rsi_signal(make_df(sign=1)["Close"], period=14, oversold=30, overbought=70, lookback=3)
    assert res.side == "buy", res.reason
    assert res.value > 30


def test_rsi_sell_on_overbought_breakdown():
    res = rsi_signal(make_df(sign=-1)["Close"], period=14, oversold=30, overbought=70, lookback=3)
    assert res.side == "sell", res.reason
    assert res.value < 70


def test_rsi_neutral_on_flat_market():
    res = rsi_signal(flat_df()["Close"])
    assert res.side is None


# ───────────────────── Williams %R ─────────────────────
def test_williams_buy_after_decline():
    df = make_df(sign=1)
    res = williams_r_signal(df["High"], df["Low"], df["Close"])
    assert res.side == "buy", res.reason


def test_williams_sell_after_rally():
    df = make_df(sign=-1)
    res = williams_r_signal(df["High"], df["Low"], df["Close"])
    assert res.side == "sell", res.reason


# ───────────────────── المحرك ─────────────────────
def test_engine_double_confirmation_buy():
    d = evaluate(make_df(sign=1), cfg(), symbol="TESTUSDT", use_closed_candles=False)
    assert d.side == "buy"
    assert d.confirming == 2
    assert d.rsi.side == d.willr.side == "buy"


def test_engine_double_confirmation_sell():
    d = evaluate(make_df(sign=-1), cfg(), symbol="TESTUSDT", use_closed_candles=False)
    assert d.side == "sell"
    assert d.confirming == 2


def test_engine_no_signal_on_flat_market():
    d = evaluate(flat_df(), cfg(), symbol="FLATUSDT", use_closed_candles=False)
    assert d.side is None


def test_engine_conflict_is_rejected():
    """RSI يقول شراء بينما Williams %R عند قمة (تشبّع شرائي) → لا صفقة."""
    df = make_df(sign=1, decline=1.0, bounce=300)   # ارتداد عنيف إلى قمة النطاق
    d = evaluate(df, cfg(), symbol="MIXUSDT", use_closed_candles=False)
    assert d.rsi.side == "buy"
    assert d.willr.side == "sell"
    assert d.side is None
    assert d.notes


def test_engine_single_indicator_mode():
    cfg_obj = cfg()
    cfg_obj.set("strategy.require_both", False)
    cfg_obj.set("strategy.williams_r.enabled", False)
    d = evaluate(make_df(sign=1), cfg_obj, symbol="TESTUSDT", use_closed_candles=False)
    assert d.side == "buy"
    assert d.willr is None


def test_engine_ignores_short_history():
    d = evaluate(make_df(sign=1).iloc[:10], cfg(), symbol="SHORT", use_closed_candles=False)
    assert d.side is None


def test_use_closed_candles_drops_last_bar():
    df = make_df(sign=1)
    d_open = evaluate(df, cfg(), symbol="X", use_closed_candles=False)
    d_closed = evaluate(df, cfg(), symbol="X", use_closed_candles=True)
    assert d_open.side == "buy"
    # الشمعة الأخيرة (الارتداد نفسُه) هي مصدر الإشارة، فعند تجاهلها تتغيّر النتيجة
    assert d_closed.price == pytest.approx(float(df["Close"].iloc[-2]))


# ───────────── مطابقة الحساب الداخلي لمكتبة ta (إن كانت مثبتة) ─────────────
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

    df = make_df(sign=1, n_dec=150)
    close, high, low = df["Close"], df["High"], df["Low"]

    assert (indicators.rsi(close, 14) - ta_mod.momentum.RSIIndicator(close, window=14).rsi()).abs().max() < 1e-9
    assert (indicators.williams_r(high, low, close, 24)
            - ta_mod.momentum.WilliamsRIndicator(high, low, close, lbp=24).williams_r()).abs().max() < 1e-9

    w = indicators.williams_r(high, low, close, 24).dropna()
    assert (indicators.ema(w, 24) - ta_mod.trend.ema_indicator(w, window=24).dropna()).abs().max() < 1e-9
