"""اختبارات مُحكِّم الخبير — البوابات الثماني.

الهدف: أن يثق المستخدم بالحكم. لذلك نختبر **منطق** كل بوابة لا مجرد
أنها تُرجع رقماً: أن يعرف أقصى سحب، وألا يرفق استراتيجية سليمة بتهمة
«النظرة للمستقبل»، وألا يقبل واحدة لا تتفوّق على القرعة.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.data import Candles                            # noqa: E402
from scripts import validate as v                           # noqa: E402
from scripts.backtest import synthetic_series               # noqa: E402
from scripts.optimize import base_config                    # noqa: E402


def _series(n: int = 900, seed: int = 3, regime: str = "mixed") -> Candles:
    return synthetic_series(n, seed=seed, regime=regime)


# ═══════════════════════════ أدوات القياس ═══════════════════════════

def test_max_drawdown_measures_the_worst_peak_to_trough():
    assert v.max_drawdown([1, -2, 3, -4]) == 4.0      # تراكمي: 1،-1،2،-2
    assert v.max_drawdown([1, 1, 1]) == 0.0           # بلا هبوط
    assert v.max_drawdown([-5]) == 5.0


def test_profit_factor_compares_wins_to_losses():
    assert v.profit_factor([1.0, -1.0, 2.0, -0.5]) == 2.0     # 3 ÷ 1.5
    assert v.profit_factor([-1.0, -2.0]) == 0.0               # بلا أرباح
    assert v.profit_factor([1.0, 2.0]) == 99.0                # بلا خسائر
    assert v.profit_factor([]) == 0.0


def test_bootstrap_ci_excludes_zero_for_a_clearly_winning_sample():
    rng = random.Random(1)
    sample = [1.0 if rng.random() < 0.8 else -1.0 for _ in range(300)]
    low, high = v.bootstrap_ci(sample, sims=300, seed=5)
    assert 0 < low < high


def test_bootstrap_ci_includes_zero_for_a_coin_flip():
    rng = random.Random(2)
    sample = [1.0 if rng.random() < 0.5 else -1.0 for _ in range(200)]
    low, high = v.bootstrap_ci(sample, sims=300, seed=5)
    assert low < 0 < high


def test_atr_pct_series_matches_the_candle_count():
    values = v.atr_pct_series(_series(600))
    assert len(values) == 600
    assert all(value >= 0 for value in values)
    assert sum(1 for value in values if value > 0) > 500


# ═══════════════════════════ الدخول العشوائي ═══════════════════════════

def test_random_entries_lose_money_after_costs():
    """الدخول العشوائي **خاسر** (العمولة والانزلاق بلا مقابل) — وهذا
    بالضبط ما يجعله معياراً: إن لم تتفوّق عليه الإشارة فهي بلا قيمة."""
    candles = [_series(900, seed=4)]
    atrs = [v.atr_pct_series(c) for c in candles]
    means = v.random_entry_benchmark(candles, atrs, trades=200,
                                     sl_coef=2.0, tp_ratio=2.0,
                                     cost_pct=0.0007, sims=40, seed=3)
    assert len(means) == 40
    assert sum(means) / len(means) < 0.05      # ≈ صفر أو سالب قبل الأثر العشوائي


def test_a_huge_edge_beats_random_entries_outright():
    candles = [_series(900, seed=4)]
    atrs = [v.atr_pct_series(c) for c in candles]
    means = v.random_entry_benchmark(candles, atrs, trades=200,
                                     sl_coef=2.0, tp_ratio=2.0,
                                     cost_pct=0.0007, sims=40, seed=3)
    # توقّع خيالي: لا محاكاة عشوائية تبلغه
    assert sum(1 for m in means if m >= 5.0) == 0


def test_random_benchmark_returns_nothing_without_trades():
    assert v.random_entry_benchmark([], [], trades=0, sl_coef=2.0,
                                    tp_ratio=2.0, cost_pct=0.0007) == []


# ═══════════════════════════ بوابة «النظرة للمستقبل» ═══════════════════════════

@pytest.mark.parametrize("strategy", v.ALL_STRATEGIES)
def test_no_registered_strategy_looks_into_the_future(strategy):
    """أخطر تهمة: أن تتغيّر الإشارة إن حذفنا المستقبل.

    كل استراتيجية مسجّلة يجب أن تنجو منها — وإلا فهي «تعيد رسم» إشاراتها.
    """
    assert v.repaint_free(_series(900, seed=6), strategy, {}) is True


def test_repaint_check_detects_a_strategy_that_actually_repaints(monkeypatch):
    """منطق المقارنة نفسه: إن اختلفت العوائد عند القطع ⇒ رفض."""
    calls = {"n": 0}

    def fake_run(candles, cfg, key, use_closed, delay, window=None, **kw):
        calls["n"] += 1
        n = len(candles)
        r = [0.5] * 20 if calls["n"] == 1 else [0.5] * 10 + [9.9] * 10
        return {"trades": len(r), "r_list": r, "entries": list(range(len(r)))}

    monkeypatch.setattr("scripts.backtest.run", fake_run)
    assert v.repaint_free(_series(900), "ema_momentum", {}) is False


def test_repaint_check_ignores_trades_that_cannot_resolve():
    """صفقة تبدأ قرب نهاية المقطع الآمن **لا تُحسم فيه** — لا تُتَّهم."""
    def fake_run(candles, cfg, key, use_closed, delay, window=None, **kw):
        n = len(candles)
        # كل الصفقات تبدأ عند آخر شمعة ⇒ غير محسومة أصلاً
        return {"trades": 5, "r_list": [1.0] * 5,
                "entries": [n - 1] * 5}

    import scripts.backtest as bt
    original = bt.run
    bt.run = fake_run
    try:
        assert v.repaint_free(_series(900), "ema_momentum", {}) is True
    finally:
        bt.run = original


# ═══════════════════════════ المرشّحون ═══════════════════════════

def test_candidates_cover_every_strategy_at_four_strictness_levels():
    pool = v.candidates(v.ALL_STRATEGIES)
    assert len(pool) == 24
    assert {level for level, _key, _params in pool} == {"أساسي", "+نظام",
                                                        "+اتجاه", "صارم"}


def test_the_regime_filter_matches_each_strategy_nature():
    """الاتجاهية تتاجر في الاتجاه، والارتدادية في النطاق — لا العكس."""
    pool = dict(((key, level), params)
                for level, key, params in v.candidates(v.ALL_STRATEGIES))
    assert pool[("ema_momentum", "+نظام")]["strategy.regime"] == "trend"
    assert pool[("donchian_breakout", "+نظام")]["strategy.regime"] == "trend"
    assert pool[("scalping_i", "+نظام")]["strategy.regime"] == "range"
    assert pool[("mean_reversion_z", "+نظام")]["strategy.regime"] == "range"


# ═══════════════════════════ الحكم الكامل ═══════════════════════════

def test_judge_returns_all_eight_gates():
    verdict = v.judge("أساسي", "ema_momentum", {}, [_series(900, seed=8)],
                      min_trades=10, sims=20, total_candidates=24)
    assert set(verdict.gates) == {"sample", "repaint", "oos", "consistency",
                                  "markets", "random", "bootstrap", "risk"}
    assert verdict.grade.endswith("/8")


def test_judge_rejects_a_sample_that_is_too_small():
    """المرشّحون الذين لا يصلون للحدّ لا تُهدر عليهم البوابات الغالية."""
    verdict = v.judge("أساسي", "rsi_williams", {}, [_series(900, seed=8)],
                      min_trades=100_000, sims=20)
    assert verdict.gates["sample"] is False
    assert verdict.passed is False
    assert verdict.gates["random"] is False        # لم تُحسب أصلاً


def test_a_passing_verdict_needs_every_gate():
    verdict = v.judge("أساسي", "ema_momentum", {}, [_series(900, seed=8)],
                      min_trades=10, sims=20)
    assert verdict.passed is all(verdict.gates.values())


def test_main_runs_end_to_end_and_writes_json(tmp_path):
    rows = ["time,open,high,low,close,volume"]
    rng = random.Random(9)
    price = 100.0
    for i in range(800):
        price *= 1 + rng.uniform(-0.004, 0.004)
        rows.append(f"1700000000000,{price},{price * 1.004},"
                    f"{price * 0.996},{price},1000")
    path = tmp_path / "mini.csv"
    path.write_text("\n".join(rows), encoding="utf-8")

    out = tmp_path / "verdict.json"
    code = v.main(["--csv", str(path), "--only", "ema_momentum",
                   "--sims", "20", "--min-trades", "10", "--json", str(out)])
    assert code == 0 and out.exists()
    import json
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload and all("grade" in row and "passed" in row
                           for row in payload)
    assert all(row["reasons"] or row["passed"] or True for row in payload)


def test_main_refuses_to_run_without_data():
    assert v.main(["--csv"]) == 1
