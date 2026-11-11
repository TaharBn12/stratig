"""اختبارات إدارة المخاطر — منطق خالص بلا منصة."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.risk import (  # noqa: E402
    CircuitBreaker,
    Journal,
    RateLimiter,
    Trade,
    plan_protection,
    position_size,
    risk_of,
    signed_profit,
)

# ═══════════════════════ 1) حجم الصفقة ═══════════════════════
def test_position_size_keeps_loss_constant():
    """المخاطرة ثابتة بالدولار مهما اختلف اتساع الوقف."""
    tight = position_size(1000, 0.01, 0.009)     # وقف ضيّق 0.9%
    wide = position_size(1000, 0.01, 0.03)       # وقف واسع 3%
    assert tight > wide                          # حجم أصغر مع وقف أوسع
    assert risk_of(tight, 0.009) == pytest.approx(10.0, rel=1e-6)
    assert risk_of(wide, 0.03) == pytest.approx(10.0, rel=1e-6)


def test_position_size_respects_max_and_min():
    assert position_size(1000, 0.5, 0.009, max_qty=500) == 500
    assert position_size(10, 0.001, 0.009, min_qty=25) == 25


def test_position_size_rejects_bad_input():
    for args in ((0, 0.01, 0.009), (1000, 0, 0.009), (1000, 0.01, 0)):
        assert position_size(*args) == 0.0


# ═══════════════════════ 2) تحديد المعدل ═══════════════════════
def test_rate_limiter_blocks_after_max():
    now = 1_000_000.0
    limiter = RateLimiter(max_per_hour=2)
    for _ in range(2):
        assert limiter.check(now)[0] is True
        limiter.record(now)
    ok, reason = limiter.check(now)
    assert ok is False and "صفقة/ساعة" in reason


def test_rate_limiter_frees_slots_after_an_hour():
    now = 1_000_000.0
    limiter = RateLimiter(max_per_hour=1)
    limiter.record(now)
    assert limiter.check(now)[0] is False
    assert limiter.check(now + 3601)[0] is True


def test_rate_limiter_enforces_minimum_gap():
    now = 1_000_000.0
    limiter = RateLimiter(min_gap_seconds=600)
    limiter.record(now)
    ok, reason = limiter.check(now + 60)
    assert ok is False and "فاصل إلزامي" in reason
    assert limiter.check(now + 601)[0] is True


# ═══════════════════════ 3) قاطع الخسائر المتتالية ═══════════════════════
def test_breaker_pauses_after_consecutive_losses():
    now = 1_000_000.0
    breaker = CircuitBreaker(max_losses=3, pause_seconds=3600)
    breaker.record(-10, now)
    breaker.record(+5, now)          # ربح يصفّر العدّاد
    breaker.record(-10, now)
    breaker.record(-10, now)
    breaker.record(-10, now)
    ok, reason = breaker.check(now)
    assert ok is False and "موقوف تلقائياً" in reason


def test_breaker_resumes_after_pause_and_manually():
    now = 1_000_000.0
    breaker = CircuitBreaker(max_losses=1, pause_seconds=60)
    breaker.record(-10, now)
    assert breaker.check(now)[0] is False
    assert breaker.check(now + 61)[0] is True
    breaker.resume()
    assert breaker.check(now)[0] is True


# ═══════════════════════ 4) إدارة الصفقة المفتوحة ═══════════════════════
def test_no_action_while_trade_is_flat():
    plan = plan_protection("buy", 100, 100.2, 1.0, 99.0, breakeven_after_r=1.0)
    assert plan.action == "none"


def test_breakeven_moves_stop_to_entry():
    plan = plan_protection("buy", 100, 101.2, 1.0, 99.0, breakeven_after_r=1.0)
    assert plan.action == "breakeven"
    assert plan.new_sl == pytest.approx(100.0)


def test_breakeven_includes_fee_buffer_for_short():
    plan = plan_protection("sell", 100, 98.5, 1.0, 101.0, breakeven_after_r=1.0,
                           breakeven_offset_pct=0.001)
    assert plan.action == "breakeven"
    assert plan.new_sl == pytest.approx(99.9)       # أقل من الدخول للبيع


def test_stop_never_moves_against_the_trade():
    """القاعدة الذهبية: الوقف يتقدّم فقط — لا يتراجع أبداً."""
    plan = plan_protection("buy", 100, 102.0, 1.0, current_sl=101.5,
                           trailing=True, trail_distance=5.0)
    assert plan.action == "none"                    # 97 أضعف من 101.5


def test_trailing_follows_the_price_up():
    plan = plan_protection("buy", 100, 110.0, 1.0, current_sl=101.0,
                           trailing=True, trail_distance=1.0)
    assert plan.action == "trail"
    assert plan.new_sl == pytest.approx(109.0)


def test_trailing_for_short_follows_down():
    plan = plan_protection("sell", 100, 90.0, 1.0, current_sl=101.0,
                           trailing=True, trail_distance=1.0)
    assert plan.new_sl == pytest.approx(91.0)


def test_time_based_exit():
    now = 1_000_000.0
    plan = plan_protection("buy", 100, 100.5, 1.0, 99.0,
                           opened_at=now - 7200, now=now, max_hold_seconds=3600)
    assert plan.action == "close" and "مدة الاحتفاظ" in plan.reason


def test_signed_profit_handles_both_directions():
    assert signed_profit("buy", 100, 110) == pytest.approx(10)
    assert signed_profit("sell", 100, 110) == pytest.approx(-10)
    assert signed_profit("sell", 100, 90) == pytest.approx(10)


# ═══════════════════════ 5) السجل والإحصائيات ═══════════════════════
def _journal(tmp_path, results):
    journal = Journal(tmp_path / "trades.json")
    for i, (pnl, r) in enumerate(results):
        journal.add(Trade(symbol="X", side="buy", pnl=pnl, r_multiple=r,
                          opened_at=float(i), closed_at=float(i)))
    return journal


def test_journal_statistics(tmp_path):
    journal = _journal(tmp_path, [(10, 1.5), (-10, -1.0), (10, 1.5), (-10, -1.0)])
    assert journal.count == 4
    assert journal.win_rate == pytest.approx(50.0)
    assert journal.expectancy_r == pytest.approx(0.25)
    assert journal.profit_factor == pytest.approx(1.0)
    assert journal.total_pnl == pytest.approx(0.0)


def test_journal_max_drawdown(tmp_path):
    """الرصيد: 0 → -10 → -30 → -25 ⇒ أقصى هبوط من القمة = 30."""
    journal = _journal(tmp_path, [(-10, -1), (-20, -2), (+5, 0.5)])
    assert journal.max_drawdown == pytest.approx(30.0)


def test_journal_drawdown_recovers_after_new_peak(tmp_path):
    journal = _journal(tmp_path, [(-10, -1), (+20, 2), (-5, -0.5)])
    assert journal.max_drawdown == pytest.approx(10.0)


def test_journal_persists_to_disk(tmp_path):
    path = tmp_path / "trades.json"
    first = Journal(path)
    first.add(Trade(symbol="BTCUSDT", side="buy", pnl=7.0, r_multiple=1.2,
                    opened_at=time.time(), closed_at=time.time()))
    second = Journal(path)
    assert second.count == 1 and second.total_pnl == pytest.approx(7.0)
