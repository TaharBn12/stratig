"""اختبارات مقياس الميزة — أهمها أن الحظ لا يُقرأ ميزة."""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.edge import (                      # noqa: E402
    VERDICT_FLAT,
    VERDICT_LOSS,
    VERDICT_UNKNOWN,
    VERDICT_WIN,
    EdgeStats,
    by_strategy,
    measure,
    measure_trades,
)
from stratig.risk import Trade                  # noqa: E402


def _rs(values):
    """عيّنة عوائد بوحدة R من قائمة قيم."""
    return list(values)


# ═══════════════════════ الأساسيات ═══════════════════════
def test_empty_sample_is_unknown():
    stats = measure([])
    assert stats.verdict == VERDICT_UNKNOWN
    assert stats.trades == 0
    assert stats.expectancy_r == 0.0


def test_nan_values_are_ignored():
    stats = measure([1.0, float("nan"), 2.0], min_trades=2)
    assert stats.trades == 2


def test_expectancy_and_win_rate_are_computed():
    stats = measure([1.0, -1.0, 2.0, -0.5, 1.5], min_trades=2)
    assert stats.trades == 5
    assert stats.expectancy_r == pytest.approx(0.6)
    assert stats.win_rate == pytest.approx(60.0)
    assert stats.total_r == pytest.approx(3.0)


# ═══════════════════════ الحكم ═══════════════════════
def test_strong_consistent_edge_is_winning():
    """30 صفقة كلها +1R → رابحة إحصائياً بلا شك."""
    stats = measure([1.0] * 30)
    assert stats.verdict == VERDICT_WIN
    assert stats.is_winning and not stats.is_losing
    assert stats.should_block is False
    assert stats.lower_r > 0


def test_strong_consistent_loss_is_blocking():
    stats = measure([-1.0] * 30)
    assert stats.verdict == VERDICT_LOSS
    assert stats.is_losing
    assert stats.should_block is True
    assert stats.upper_r < 0


def test_small_sample_is_not_judged():
    """12 صفقة رابحة قد تكون حظاً → لا حكم."""
    stats = measure([1.0] * 12, min_trades=30)
    assert stats.verdict == VERDICT_UNKNOWN
    assert stats.should_block is False        # لا نمنع بلا دليل
    assert stats.expectancy_r == 1.0          # الرقم موجود لكن الحكم معلّق


def test_high_variance_positive_mean_can_be_inconclusive():
    """متوسط موجب لكن تشتّت هائل → الفترة تحتوي الصفر."""
    # +10R واحدة و 29 خسارة صغيرة: المتوسط موجب قليلاً لكن بلا دلالة
    values = [10.0] + [-0.3] * 29
    stats = measure(values, min_trades=30)
    assert stats.expectancy_r > 0
    assert stats.verdict in (VERDICT_FLAT, VERDICT_LOSS)
    assert stats.should_block is False or stats.verdict == VERDICT_LOSS


def test_losing_edge_is_detected_despite_some_winners():
    """خسارة مؤكّدة: كثير من الصفقات كلها حول −0.3R."""
    values = [-0.3] * 40 + [0.5] * 5
    stats = measure(values, min_trades=30)
    assert stats.verdict == VERDICT_LOSS
    assert stats.should_block is True


def test_confidence_interval_contains_the_mean():
    values = [0.5, -0.2, 1.0, -0.7, 0.3, 0.1, -0.4, 0.8] * 6
    stats = measure(values, min_trades=10)
    assert stats.lower_r < stats.expectancy_r < stats.upper_r
    assert stats.stderr_r > 0


def test_more_samples_narrow_the_interval():
    values = [0.4, -0.2, 0.6, -0.3] * 5
    few = measure(values[:12], min_trades=10)
    many = measure(values * 3, min_trades=10)
    assert many.stderr_r < few.stderr_r


# ═══════════════════════ الشرح ═══════════════════════
def test_explain_mentions_the_interval():
    stats = measure([-1.0] * 40)
    assert "فترة الثقة" in stats.explain()
    assert "الصفر" in stats.explain()


def test_explain_for_insufficient_data():
    stats = measure([1.0] * 5, min_trades=30)
    assert "العيّنة" in stats.explain()


def test_explain_for_no_trades():
    assert measure([]).explain() == "لا توجد صفقات مسجّلة بعد"


# ═══════════════════════ مع كائنات Trade ═══════════════════════
def test_measure_trades_reads_r_multiple():
    trades = [Trade("A", "buy", 5.0, 1.2), Trade("B", "sell", -5.0, -1.0)]
    stats = measure_trades(trades, min_trades=1)
    assert stats.trades == 2
    assert stats.expectancy_r == pytest.approx(0.1)


def test_by_strategy_separates_strategies():
    """استراتيجية رابحة وأخرى خاسرة — لا يجوز خلطهما."""
    trades = ([Trade("A", "buy", 1.0, 1.0, strategy="scalping_i")] * 30
              + [Trade("B", "buy", -1.0, -1.0, strategy="rsi_williams")] * 30)
    per = by_strategy(trades, min_trades=30)
    assert per["scalping_i"].is_winning
    assert per["rsi_williams"].is_losing


def test_by_strategy_handles_missing_strategy_field():
    per = by_strategy([Trade("A", "buy", 1.0, 1.0)], min_trades=1)
    assert "غير محدّد" in per


# ═══════════════════════ الاندماج مع المتداول ═══════════════════════
def test_edge_report_groups_by_strategy(make_trader, tmp_path):
    tr, _ex = make_trader(tmp_path, risk__journal_path=str(tmp_path / "t.json"))
    for _ in range(30):
        tr.journal.add(Trade("A", "buy", -1.0, -1.0, strategy="scalping_i"))
    report = tr.edge_report()
    assert report["current"] == tr.strategy_key
    assert report["per_strategy"]["scalping_i"].is_losing
    assert report["gate"] is False


def test_edge_gate_off_by_default(make_trader, tmp_path):
    """البوابة معطّلة افتراضياً — لا نمنع التداول بلا إذنك."""
    tr, _ex = make_trader(tmp_path, risk__journal_path=str(tmp_path / "t.json"))
    for _ in range(40):
        tr.journal.add(Trade("A", "buy", -1.0, -1.0, strategy=tr.strategy_key))
    assert tr.edge_gate() == (True, "")


def test_edge_gate_blocks_a_proven_loser(make_trader, tmp_path):
    tr, _ex = make_trader(tmp_path, risk__journal_path=str(tmp_path / "t.json"),
                          edge__gate=True)
    for _ in range(40):
        tr.journal.add(Trade("A", "buy", -1.0, -1.0, strategy=tr.strategy_key))
    ok, reason = tr.edge_gate()
    assert ok is False
    assert "مقياس الميزة" in reason and "خاسرة" in reason
    # ويظهر عبر بوابة المخاطر العامة أيضاً
    assert tr.risk_gate()[0] is False


def test_edge_gate_lets_a_winner_through(make_trader, tmp_path):
    tr, _ex = make_trader(tmp_path, risk__journal_path=str(tmp_path / "t.json"),
                          edge__gate=True)
    for _ in range(40):
        tr.journal.add(Trade("A", "buy", 1.0, 1.0, strategy=tr.strategy_key))
    assert tr.edge_gate() == (True, "")
    assert tr.risk_gate()[0] is True


def test_edge_gate_ignores_other_strategies(make_trader, tmp_path):
    """خسارة استراتيجية أخرى لا تمنع استراتيجيتك الحالية."""
    tr, _ex = make_trader(tmp_path, risk__journal_path=str(tmp_path / "t.json"),
                          edge__gate=True)
    for _ in range(40):
        tr.journal.add(Trade("A", "buy", -1.0, -1.0, strategy="استراتيجية_أخرى"))
    assert tr.edge_gate() == (True, "")


def test_edge_lookback_limits_the_sample(make_trader, tmp_path):
    tr, _ex = make_trader(tmp_path, risk__journal_path=str(tmp_path / "t.json"),
                          edge__lookback=10)
    for _ in range(40):
        tr.journal.add(Trade("A", "buy", -1.0, -1.0, strategy=tr.strategy_key))
    assert tr.edge_stats(str(tr.strategy_key)).trades == 10
