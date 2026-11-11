"""اختبارات فلاتر جودة الإشارة — منطق خالص."""
from __future__ import annotations

import math
import random
import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.strategy.filters import (  # noqa: E402
    apply_filters,
    mtf_ok,
    regime_ok,
    volatility_ok,
)
from stratig.strategy.indicators import adx, atr_pct  # noqa: E402


class FakeDecision:
    def __init__(self, side="buy"):
        self.side = side
        self.notes: list[str] = []
        self.lines: list[str] = []

    @property
    def has_signal(self) -> bool:
        return self.side in ("buy", "sell")


# ═══════════════════════ ADX ═══════════════════════
def _trend_candles(n: int = 80, slope: float = 0.5):
    closes = [100.0 + i * slope for i in range(n)]
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]
    return highs, lows, closes


def test_adx_high_in_strong_trend():
    highs, lows, closes = _trend_candles()
    values, plus_di, minus_di = adx(highs, lows, closes, 14)
    assert values[-1] > 40, values[-1]
    assert plus_di[-1] > minus_di[-1]        # +DI فوق −DI في اتجاه صاعد


def test_adx_di_reverses_in_downtrend():
    highs, lows, closes = _trend_candles(slope=-0.5)
    values, plus_di, minus_di = adx(highs, lows, closes, 14)
    assert minus_di[-1] > plus_di[-1]


def test_adx_low_on_random_walk():
    """القيمة المرجعية: سير عشوائي يعطي ADX ≈ 15-25."""
    random.seed(5)
    samples = []
    for _ in range(60):
        closes = [100.0]
        for _ in range(120):
            closes.append(closes[-1] * (1 + random.gauss(0, 0.004)))
        highs = [c * 1.002 for c in closes]
        lows = [c * 0.998 for c in closes]
        values, _p, _m = adx(highs, lows, closes, 14)
        if not math.isnan(values[-1]):
            samples.append(values[-1])
    assert 10 < statistics.fmean(samples) < 30, statistics.fmean(samples)


def test_atr_pct_is_relative_to_price():
    highs, lows, closes = _trend_candles()
    value = atr_pct(highs, lows, closes, 14)
    assert 0 < value < 0.05


# ═══════════════════════ فلتر نظام السوق ═══════════════════════
def test_regime_off_allows_everything():
    assert regime_ok(10.0, "off").allowed
    assert regime_ok(60.0, "off").allowed


def test_regime_trend_rejects_flat_market():
    verdict = regime_ok(12.0, "trend", trend_min=25)
    assert verdict.allowed is False and "بلا اتجاه" in verdict.reason


def test_regime_trend_allows_strong_market():
    assert regime_ok(35.0, "trend", trend_min=25).allowed is True


def test_regime_range_rejects_strong_trend():
    """`rsi_williams` تخسر في الاتجاه — الفلتر يحميها هنا."""
    verdict = regime_ok(45.0, "range", range_max=20)
    assert verdict.allowed is False and "متّجه" in verdict.reason


def test_regime_range_allows_flat_market():
    assert regime_ok(15.0, "range", range_max=20).allowed is True


def test_regime_tolerates_missing_adx():
    assert regime_ok(float("nan"), "trend").allowed is True


# ═══════════════════════ فلتر الإطار الأعلى ═══════════════════════
def test_mtf_disabled_allows_everything():
    assert mtf_ok("buy", 90.0, 100.0, enabled=False).allowed


def test_mtf_blocks_buy_below_higher_average():
    verdict = mtf_ok("buy", 95.0, 100.0, enabled=True, timeframe="1h")
    assert verdict.allowed is False and "يعاكس" in verdict.reason


def test_mtf_blocks_sell_above_higher_average():
    assert mtf_ok("sell", 105.0, 100.0, enabled=True).allowed is False


def test_mtf_allows_aligned_trades():
    assert mtf_ok("buy", 105.0, 100.0, enabled=True).allowed is True
    assert mtf_ok("sell", 95.0, 100.0, enabled=True).allowed is True


# ═══════════════════════ فلتر التقلّب ═══════════════════════
def test_volatility_rejects_dead_market():
    verdict = volatility_ok(0.0005, min_pct=0.003)
    assert verdict.allowed is False and "ساكن" in verdict.reason


def test_volatility_rejects_wild_market():
    verdict = volatility_ok(0.08, max_pct=0.02)
    assert verdict.allowed is False and "هائج" in verdict.reason


def test_volatility_accepts_normal_range():
    assert volatility_ok(0.008, min_pct=0.003, max_pct=0.02).allowed is True


def test_volatility_disabled_by_default():
    assert volatility_ok(0.0001).allowed is True


# ═══════════════════════ التطبيق على القرار ═══════════════════════
def test_filters_cancel_the_signal_and_explain_why():
    decision = FakeDecision("buy")
    allowed = apply_filters(
        decision, adx_value=12.0, regime="trend", trend_min=25,
    )
    assert allowed is False
    assert decision.side is None
    assert any("بلا اتجاه" in note for note in decision.notes)
    assert any("مرفوض" in line for line in decision.lines)


def test_filters_annotate_quality_when_passing():
    decision = FakeDecision("buy")
    allowed = apply_filters(
        decision, adx_value=35.0, regime="trend", trend_min=25,
        atr_percent=0.008, vol_min=0.003, vol_max=0.02,
    )
    assert allowed is True and decision.side == "buy"
    assert any("الجودة" in line for line in decision.lines)
    assert any("ADX" in line for line in decision.lines)


def test_all_filters_disabled_never_block():
    decision = FakeDecision("sell")
    assert apply_filters(decision, adx_value=5.0, atr_percent=0.0001) is True
    assert decision.side == "sell"
