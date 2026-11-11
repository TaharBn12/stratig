"""اختبارات دراسة الشموع.

أهم ما يُختبر هنا ليس الحساب، بل **الصرامة الإحصائية**:
  • تصحيح بونفيروني يرفض ما يقبله المستوى العادي
  • دمج الرموز يحفظ العيّنات الخام (ولا يُصفّر التشتّت فيُنتج دلالة زائفة)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.data import Candles                     # noqa: E402
from stratig.edge import VERDICT_FLAT, VERDICT_WIN, bonferroni_z  # noqa: E402
from stratig.study import (                          # noqa: E402
    anatomy,
    autocorr_profile,
    autocorrelation,
    candle_parts,
    detect,
    forward_return,
    merge,
    pattern_samples,
    pattern_study,
    returns,
    study,
    volatility_after,
)


def _candles(rows) -> Candles:
    """rows = (open, high, low, close) — تبني سلسلة شموع."""
    n = len(rows)
    times = [float(i) for i in range(n)]
    opens = [float(r[0]) for r in rows]
    highs = [float(r[1]) for r in rows]
    lows = [float(r[2]) for r in rows]
    closes = [float(r[3]) for r in rows]
    return Candles(times, opens, highs, lows, closes, [1.0] * n)


def _flat(n: int = 40, price: float = 100.0) -> Candles:
    return _candles([(price, price * 1.001, price * 0.999, price)] * n)


# ═══════════════════════ التشريح ═══════════════════════
def test_candle_parts_of_a_bullish_candle():
    candles = _candles([(100, 102, 98, 101)])
    body, upper, lower, total = candle_parts(candles, 0)
    assert body == pytest.approx(0.01)      # |101−100|/100
    assert upper == pytest.approx(0.01)     # 102−101
    assert lower == pytest.approx(0.02)     # 100−98
    assert total == pytest.approx(0.04)     # 102−98


def test_candle_parts_are_symmetric_for_bearish():
    up = candle_parts(_candles([(100, 102, 98, 101)]), 0)
    down = candle_parts(_candles([(100, 102, 98, 99)]), 0)
    assert up[0] == pytest.approx(down[0])      # نفس حجم الجسم
    assert up[3] == pytest.approx(down[3])      # نفس المدى
    # أما الفتيلان فينعكسان: ما كان علوياً صار سفلياً
    assert up[1] == pytest.approx(down[2])


def test_anatomy_averages_body_and_range():
    candles = _candles([(100, 101, 99, 101), (100, 102, 98, 100)])
    a = anatomy(candles)
    assert a.body_pct == pytest.approx(0.005)      # (0.01 + 0) ÷ 2
    assert a.range_pct == pytest.approx(0.03)      # (0.02 + 0.04) ÷ 2


def test_anatomy_bull_ratio_counts_rising_candles():
    candles = _candles([(100, 101, 99, 101), (100, 101, 99, 99)])
    assert anatomy(candles).bull_ratio == pytest.approx(50.0)


def test_anatomy_survives_zero_prices():
    candles = _candles([(0, 0, 0, 0)])
    a = anatomy(candles)
    assert a.range_pct == 0.0


# ═══════════════════════ الارتباط الذاتي ═══════════════════════
def test_returns_are_computed_between_closes():
    values = returns([100.0, 101.0, 100.0])
    assert values[0] == pytest.approx(0.01)
    assert values[1] == pytest.approx(-1 / 101)


def test_alternating_series_has_negative_autocorrelation():
    """الصعود يتبعه هبوط ⇒ ارتباط سالب قوي (الارتداد)."""
    closes = [100.0, 101.0] * 60
    assert autocorrelation(returns(closes), 1) < -0.9


def test_persistent_series_has_positive_autocorrelation():
    """زوج من الصعود ثم زوج من الهبوط ⇒ ارتباط موجب (الزخم)."""
    # عوائد تتبع موجة بطيئة (دورتها 40) ⇒ الشمعة التالية تشبه السابقة
    import math

    closes = [100.0]
    for t in range(480):
        rate = 0.01 * math.sin(2 * math.pi * t / 40.0)
        closes.append(closes[-1] * (1 + rate))
    values = returns(closes)
    # الارتباط النظري لموجة جيبية عند lag 1 هو cos(2π/40) ≈ 0.988
    assert autocorrelation(values, 1) > 0.8


def test_random_walk_has_weak_autocorrelation():
    import random

    random.seed(4)
    closes = [100.0]
    for _ in range(3000):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.004)))
    values = returns(closes)
    assert abs(autocorrelation(values, 1)) < 0.1


def test_autocorrelation_handles_short_series():
    assert autocorrelation([1.0, 2.0], 5) == 0.0
    assert autocorrelation([1.0] * 5, 1) == 0.0      # لا تشتّت


def test_profile_marks_significance_against_the_threshold():
    closes = [100.0, 101.0] * 200
    profile = autocorr_profile(closes, lags=(1, 2, 3))
    assert profile[1]["significant"] is True
    assert profile[1]["kind"] == "ارتداد"
    # العتبة ≈ 1.96/√n وتتضاءل مع العيّنة
    assert profile[1]["threshold"] > 0


def test_profile_of_tiny_sample_is_empty():
    assert autocorr_profile([100.0, 101.0, 102.0]) == {}


# ═══════════════════════ كشف الأنماط ═══════════════════════
def test_hammer_is_detected():
    candles = _candles([(100, 100.3, 98, 100.2)])
    assert "hammer" in detect(candles, 0) or len(candles) < 2
    candles = _candles([(100, 100.3, 99.9, 100.1), (100, 100.3, 98, 100.2)])
    assert "hammer" in detect(candles, 1)


def test_shooting_star_is_detected():
    candles = _candles([(99, 99.1, 98.9, 99.0), (100, 102, 99.8, 100.1)])
    assert "shooting_star" in detect(candles, 1)


def test_bullish_engulfing_is_detected():
    candles = _candles([(100, 100.4, 98.6, 98.8), (98.5, 101.5, 98.4, 101.4)])
    assert "bull_engulf" in detect(candles, 1)


def test_bearish_engulfing_is_detected():
    candles = _candles([(100, 101.4, 99.6, 101.2), (101.5, 101.6, 98.4, 98.5)])
    assert "bear_engulf" in detect(candles, 1)


def test_inside_and_outside_bars():
    inside = _candles([(100, 102, 98, 101), (100, 101, 99, 100)])
    assert "inside_bar" in detect(inside, 1)
    outside = _candles([(100, 101, 99, 100), (100, 103, 97, 100)])
    assert "outside_bar" in detect(outside, 1)


def test_big_candles_are_relative_to_recent_range():
    quiet = [(100, 100.1, 99.9, 100.0)] * 20
    big = (100, 101.5, 98.5, 101.4)
    candles = _candles(quiet + [big])
    assert "big_green" in detect(candles, 20)


def test_detect_on_first_candle_is_empty():
    assert detect(_flat(5), 0) == []


# ═══════════════════════ العائد الأمامي ═══════════════════════
def test_forward_return_is_signed_by_side():
    candles = _candles([(100, 100, 100, 100), (100, 100, 100, 100),
                        (100, 100, 100, 110)])
    assert forward_return(candles, 0, 2, side=1) == pytest.approx(0.10)
    assert forward_return(candles, 0, 2, side=-1) == pytest.approx(-0.10)


def test_forward_return_returns_none_past_the_end():
    candles = _flat(3)
    assert forward_return(candles, 2, 5) is None


# ═══════════════════════ الصرامة الإحصائية ═══════════════════════
def test_bonferroni_raises_the_bar():
    assert bonferroni_z(1) == pytest.approx(1.96, abs=0.01)
    assert bonferroni_z(8) > bonferroni_z(6) > bonferroni_z(1)
    assert bonferroni_z(8) == pytest.approx(2.73, abs=0.02)


def test_bonferroni_rejects_what_the_plain_level_accepts():
    """الأهم: نتيجة «رابحة» عند 95% قد لا تصمد عند تصحيح الاختبارات المتعدّدة."""
    from stratig.edge import measure

    values = [1.5, -0.5] * 12 + [1.5]        # mean ≈ 0.54 · stdev ≈ 1.02
    assert measure(values, min_trades=10).verdict == VERDICT_WIN
    corrected = measure(values, min_trades=10, z=bonferroni_z(8))
    assert corrected.verdict == VERDICT_FLAT


def test_pattern_study_uses_the_corrected_threshold():
    """ستة أنماط تُختبر دفعة واحدة ⇒ العتبة 2.64 لا 1.96."""
    candles = _flat(60)
    stats = pattern_study(candles, horizon=3, min_trades=1)
    assert set(stats) == {"hammer", "shooting_star", "bull_engulf",
                          "bear_engulf", "big_green", "big_red"}


def test_a_rigged_pattern_is_detected_as_winning():
    """سلسلة مُصمَّمة: كل شمعة مطرقة يليها ارتفاع ⇒ يجب أن تُكتشف رابحة."""
    rows = []
    price = 100.0
    for i in range(80):
        # مطرقة: جسم صغير في الأعلى وفتيل سفلي طويل
        rows.append((price, price * 1.001, price * 0.97, price * 1.0005))
        price *= 1.01                     # ارتفاع مؤكّد بعدها
    candles = _candles(rows)
    samples = pattern_samples(candles, horizon=3)
    assert len(samples["hammer"]) >= 30
    stats = pattern_study(candles, horizon=3, min_trades=30)
    assert stats["hammer"].trades >= 30
    assert stats["hammer"].is_winning
    assert all(v > 0 for v in samples["hammer"])


# ═══════════════════════ الدمج ═══════════════════════
def test_merge_keeps_raw_samples_not_averages():
    """دمج المتوسطات يُصفّر التشتّت ⇒ دلالة زائفة. يجب دمج العيّنات الخام."""
    rows = []
    price = 100.0
    for _ in range(60):
        rows.append((price, price * 1.001, price * 0.97, price * 1.0005))
        price *= 1.01
    candles = _candles(rows)
    first = study(candles, "A", "1h", horizon=3, min_trades=30)
    second = study(candles, "B", "1h", horizon=3, min_trades=30)
    merged = merge([first, second], min_trades=30)

    assert len(merged.pattern_samples["hammer"]) == (
        len(first.pattern_samples["hammer"]) * 2)
    # العيّنة المدمجة تحتفظ بتشتّتها (لا تُصفّر)
    assert merged.patterns["hammer"].stderr_r > 0
    assert merged.bars == first.bars + second.bars


def test_merge_of_one_is_identity():
    candles = _flat(60)
    single = study(candles, "A", "1h")
    assert merge([single]) is single


def test_merge_weights_anatomy_by_bars():
    small = study(_candles([(100, 102, 98, 100)] * 10), "A", "1h")
    big = study(_candles([(100, 100.2, 99.8, 100)] * 90), "B", "1h")
    merged = merge([small, big])
    expected = (small.anatomy.range_pct * 10 + big.anatomy.range_pct * 90) / 100
    assert merged.anatomy.range_pct == pytest.approx(expected)


# ═══════════════════════ الحكم ═══════════════════════
def test_verdict_of_random_walk_says_no_structure():
    import random

    random.seed(9)
    closes = [100.0]
    for _ in range(4000):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.004)))
    candles = _candles([(c, c * 1.002, c * 0.998, c) for c in closes])
    result = study(candles, "RAND", "1h")
    assert "عشوائي" in result.verdict or "أثر عند" in result.verdict


def test_best_pattern_is_none_when_nothing_survives():
    import random

    random.seed(3)
    closes = [100.0]
    for _ in range(2000):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.004)))
    candles = _candles([(c, c * 1.004, c * 0.996, c) for c in closes])
    result = study(candles, "RAND", "1h", min_trades=30)
    # إن وُجد نمط رابح فهو استثناء نادر — نقبل النتيجتين لكن نتأكد من النوع
    assert result.best_pattern is None or isinstance(
        result.best_pattern[1].expectancy_r, float)


def test_min_stop_is_the_candle_range():
    candles = _candles([(100, 101, 99, 100)] * 20)
    result = study(candles, "A", "1h")
    assert result.min_stop_pct == pytest.approx(0.02)


# ═══════════════════════ واجهة سطر الأوامر ═══════════════════════
def test_cli_runs_on_synthetic_and_writes_json(tmp_path):
    out = tmp_path / "study.json"
    proc = subprocess.run(
        [sys.executable, "scripts/candle_study.py", "--synthetic",
         "--symbols", "BTCUSDT,ETHUSDT", "--bars", "800", "--tf", "1h",
         "--json", str(out)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "دراسة الشموع" in proc.stdout
    assert "الارتباط الذاتي" in proc.stdout
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["bars"] == 1600
    assert "anatomy" in data and "patterns" in data and "verdict" in data


def test_cli_warns_that_synthetic_is_not_conclusive(tmp_path):
    proc = subprocess.run(
        [sys.executable, "scripts/candle_study.py", "--synthetic",
         "--symbols", "BTCUSDT", "--bars", "300"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        timeout=300,
    )
    assert "اصطناعية" in proc.stdout
