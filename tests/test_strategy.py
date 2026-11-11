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
from stratig.strategy import scalping_i  # noqa: E402
from stratig.utils import is_supported_timeframe  # noqa: E402


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


# ═══════════════════════ صرامة الاستراتيجية ═══════════════════════
def test_resolve_reports_unknown_strategy():
    """/set strategy مجهول لا يُمرَّر بصمت — بل يُبلَّغ."""
    from stratig.strategy.registry import resolve

    strategy, error = resolve("rsi_williams")
    assert strategy.key == "rsi_williams" and error == ""

    strategy, error = resolve("martingale")
    assert strategy.key == "rsi_williams" and "غير معروفة" in error

    strategy, error = resolve(None)
    assert "لم تُحدَّد" in error


def test_check_config_fixes_exit_mode_mismatch():
    """الاستراتيجية تُطبَّق كاملة: مخارجها تطغى على exit.mode المتعارض."""
    from stratig.strategy.registry import check_config

    cfg = Config({"strategy": {"name": "scalping_i"}, "exit": {"mode": "percent"}},
                 path=Path("config.toml"))
    notes = check_config(cfg)
    assert cfg.get("exit.mode") == "atr"          # صُحِّح
    assert any("لا يطابق" in note for note in notes)


def test_check_config_respects_manual_override():
    """/set follow_exit false = تجاوز واعٍ ولا تحذير."""
    from stratig.strategy.registry import check_config

    cfg = Config(
        {"strategy": {"name": "scalping_i"},
         "exit": {"mode": "percent", "follow_strategy": False}},
        path=Path("config.toml"),
    )
    assert check_config(cfg) == []
    assert cfg.get("exit.mode") == "percent"


def test_check_config_fixes_unknown_strategy_name():
    from stratig.strategy.registry import check_config

    cfg = Config({"strategy": {"name": "خيالية"}}, path=Path("config.toml"))
    notes = check_config(cfg)
    assert cfg.get("strategy.name") == "rsi_williams"
    assert any("غير معروفة" in note for note in notes)


def test_check_config_warns_when_candles_below_minimum():
    """/set candles 30 مع استراتيجية تحتاج 62 = لن تصدر أي إشارة → نُبلّغ."""
    from stratig.strategy.registry import check_config

    cfg = Config({"strategy": {"name": "scalping_i", "candles": 30}},
                 path=Path("config.toml"))
    notes = check_config(cfg)
    assert any("لن تصدر أي إشارة" in note for note in notes)


def test_decision_carries_its_strategy_key():
    """كل استراتيجية توسم قرارها — حتى نرفض أي إشارة من غير المختارة."""
    from stratig.strategy.engine import KEY as RSI_KEY
    from stratig.strategy.scalping_i import KEY as SCALP_KEY

    cfg = Config({}, path=Path("config.toml"))
    candles = make_candles(sign=1)
    assert evaluate(candles, cfg).strategy == RSI_KEY
    assert scalping_i.evaluate(candles, cfg).strategy == SCALP_KEY


# ═══════════════════════ صرامة الإطار الزمني ═══════════════════════
def test_effective_timeframe_never_returns_invalid(tmp_path):
    cfg = Config({}, path=tmp_path / "c.toml")
    for raw in ("4", "5", "15min", "1h", "1M", "1mo", "60", "1440"):
        cfg.set("strategy.timeframe", raw)
        assert is_supported_timeframe(cfg.effective_timeframe()), raw


def test_effective_timeframe_repairs_manual_edit(tmp_path):
    """تعديل config.toml يدوياً أثناء عمل البوت كان يمرّ بصمت."""
    cfg = Config({}, path=tmp_path / "c.toml")
    cfg.set("strategy.timeframe", "zzz")
    assert cfg.effective_timeframe() == "15m"
    assert cfg.get("strategy.timeframe") == "15m"   # ثُبِّت في الإعدادات


def test_reload_repairs_timeframe(tmp_path):
    path = tmp_path / "c.toml"
    cfg = Config({}, path=path)
    path.write_text('[strategy]\ntimeframe = "45m"\n', encoding="utf-8")
    cfg.reload()
    assert is_supported_timeframe(cfg.get("strategy.timeframe"))


# ═══════════════════════ فلتر الاتجاه (اختياري) ═══════════════════════
def _cfg(**over) -> Config:
    return Config(over or {}, path=Path("config.toml"))


def test_trend_filter_off_by_default_keeps_signals():
    """الوضع الحرفي: لا يُرفض أي إشارة."""
    from stratig.strategy.registry import evaluate as reg_evaluate

    candles = make_candles(sign=1)
    decision = reg_evaluate("rsi_williams", candles, _cfg(), use_closed_candles=False)
    # لا نتحقق من وجود إشارة (تعتمد على البيانات) بل من غياب سبب الرفض
    assert not any("عكس الاتجاه" in n for n in decision.notes)


def test_trend_filter_rejects_counter_trend_signals():
    """مع trend_filter=ema تُرفض الإشارة المعاكسة للاتجاه العام."""
    from stratig.strategy.registry import evaluate as reg_evaluate
    from stratig.strategy.indicators import ema

    candles = make_candles(sign=1)
    cfg = _cfg(**{"strategy": {"trend_filter": "ema", "trend_period": 50}})
    decision = reg_evaluate("rsi_williams", candles, cfg, use_closed_candles=False)
    if decision.has_signal:
        level = ema(list(candles.close), 50)[-1]
        price = candles.last_close
        if decision.side == "buy":
            assert price >= level
        else:
            assert price <= level
    else:
        assert any("عكس الاتجاه" in n for n in decision.notes) or decision.side is None


def test_trend_filter_never_inverts_a_signal():
    """الفلتر يرفض فقط — لا يقلب الاتجاه أبداً (مهم: لا انعكاس خفي)."""
    from stratig.strategy.registry import evaluate as reg_evaluate

    candles = make_candles(sign=1)
    plain = reg_evaluate("rsi_williams", candles, _cfg(), use_closed_candles=False)
    filtered = reg_evaluate(
        "rsi_williams", candles,
        _cfg(**{"strategy": {"trend_filter": "ema", "trend_period": 50}}),
        use_closed_candles=False,
    )
    if plain.has_signal and filtered.has_signal:
        assert plain.side == filtered.side


# ═══════════════════════ فلاتر الجودة داخل السجل ═══════════════════════
def test_quality_filters_disabled_by_default():
    from stratig.strategy.registry import evaluate as reg_evaluate

    candles = make_candles(sign=1)
    decision = reg_evaluate("rsi_williams", candles, _cfg(), use_closed_candles=False)
    assert not any("بلا اتجاه" in n or "هائج" in n or "ساكن" in n for n in decision.notes)


def test_quality_filter_blocks_the_losing_regime():
    """`rsi_williams` تخسر في السوق المتّجه — فلتر `range` يمنعها هناك."""
    from stratig.strategy.registry import evaluate as reg_evaluate
    from stratig.strategy.indicators import adx

    candles = make_candles(sign=1)
    values, _p, _m = adx(list(candles.high), list(candles.low), list(candles.close), 14)
    adx_now = values[-1] if values else float("nan")
    cfg = _cfg(**{"strategy": {"quality_enabled": True, "regime": "range",
                               "adx_range_max": 20.0}})
    decision = reg_evaluate("rsi_williams", candles, cfg, use_closed_candles=False)
    if adx_now > 20.0:
        assert decision.side is None
        assert any("متّجه" in note for note in decision.notes)


def test_quality_filters_never_invert_a_signal():
    from stratig.strategy.registry import evaluate as reg_evaluate

    candles = make_candles(sign=1)
    plain = reg_evaluate("rsi_williams", candles, _cfg(), use_closed_candles=False)
    filtered = reg_evaluate(
        "rsi_williams", candles,
        _cfg(**{"strategy": {"quality_enabled": True, "regime": "trend"}}),
        use_closed_candles=False,
    )
    if plain.has_signal and filtered.has_signal:
        assert plain.side == filtered.side


def test_quality_notes_appear_on_accepted_signals():
    from stratig.strategy.registry import evaluate as reg_evaluate

    candles = make_candles(sign=1)
    cfg = _cfg(**{"strategy": {"quality_enabled": True, "regime": "off",
                               "volatility_min_pct": 0.0, "volatility_max_pct": 0.0}})
    decision = reg_evaluate("rsi_williams", candles, cfg, use_closed_candles=False)
    if decision.has_signal:
        assert any("الجودة" in line for line in decision.lines)
