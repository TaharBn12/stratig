"""اختبارات مُحسِّن المعاملات — أهمها أن الحماية من المبالغة تعمل فعلاً."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import optimize as opt                    # noqa: E402
from scripts.backtest import synthetic_series          # noqa: E402
from stratig.config import Config                      # noqa: E402


def _cfg(name: str = "scalping_i") -> Config:
    return opt.base_config(name)


# ═══════════════════════ التقسيم ═══════════════════════
def test_split_keeps_chronological_order():
    series = synthetic_series(300, seed=1, regime="trend")
    train, test = opt.split_candles(series, 0.7)
    assert len(train) + len(test) == len(series)
    assert len(train) < len(series) and len(test) > 0
    # التدريب هو **الأول** زمنياً، والاختبار ما بعده
    assert train.close[-1] == series.close[len(train) - 1]
    assert test.close[0] == series.close[len(train)]


def test_split_respects_the_ratio():
    series = synthetic_series(1000, seed=2, regime="range")
    train, _test = opt.split_candles(series, 0.8)
    assert abs(len(train) / len(series) - 0.8) < 0.02


def test_fold_windows_are_sequential_and_disjoint():
    series = synthetic_series(600, seed=3, regime="trend")
    windows = opt.fold_windows(series, 3)
    assert len(windows) >= 2
    previous_end = 0
    for train, test in windows:
        assert len(train) > 0 and len(test) > 0
        assert len(train) >= previous_end        # التدريب ينمو مع الزمن
        previous_end = len(train)


# ═══════════════════════ التقييم ═══════════════════════
def test_evaluate_aggregates_over_series():
    train, _ = opt.split_candles(synthetic_series(400, seed=4, regime="trend"), 0.7)
    result = opt.evaluate([train], _cfg(), "scalping_i", {})
    assert "trades" in result and "expectancy_r" in result
    if result["trades"]:
        assert -5 < result["expectancy_r"] < 5


def test_evaluate_returns_zero_when_no_trades():
    result = opt.evaluate([], _cfg(), "scalping_i", {})
    assert result == {"trades": 0, "expectancy_r": 0.0,
                      "win_rate": 0.0, "total_r": 0.0}


def test_evaluate_applies_the_parameters():
    """تغيير معامل واحد على الأقل يجب أن يُغيّر النتيجة."""
    train, _ = opt.split_candles(synthetic_series(500, seed=5, regime="trend"), 0.7)
    base = opt.evaluate([train], _cfg("rsi_williams"), "rsi_williams", {})
    tuned = opt.evaluate([train], _cfg("rsi_williams"), "rsi_williams",
                         {"trade.stop_loss_pct": 0.02})
    assert base != tuned


def test_scalping_uses_atr_exits_so_sl_coef_matters():
    """sl_coef لا يُؤثّر إلا مع exit.mode=atr — وإلا فالبحث بلا معنى."""
    assert opt.EXIT_MODE["scalping_i"] == "atr"
    cfg = opt.base_config("scalping_i")
    assert cfg.get("exit.mode") == "atr"
    train, _ = opt.split_candles(synthetic_series(600, seed=3, regime="trend"), 0.7)
    base = opt.evaluate([train], cfg, "scalping_i", {})
    tuned = opt.evaluate([train], cfg, "scalping_i",
                         {"strategy.scalping_i.sl_coef": 0.4})
    assert base["trades"] > 0          # السلسلة تُنتج إشارات فعلاً
    assert base != tuned


# ═══════════════════════ البحث ═══════════════════════
def test_sample_params_picks_one_value_per_key():
    import random

    grid = {"a": [1, 2, 3], "b": [10, 20]}
    for seed in range(10):
        params = opt.sample_params(grid, random.Random(seed))
        assert set(params) == {"a", "b"}
        assert params["a"] in (1, 2, 3) and params["b"] in (10, 20)


def _fake_evaluate(scores: dict[float, dict]):
    """بديل سريع للتقييم الحقيقي: التوقع دالة في قيمة المعامل."""
    def fake(series, base_cfg, strategy_key, params, **kwargs):
        key = params.get("strategy.scalping_i.sl_coef", 0.0)
        return scores.get(key, {"trades": 0, "expectancy_r": 0.0,
                                "win_rate": 0.0, "total_r": 0.0})
    return fake


def test_search_ranks_by_out_of_sample_not_in_sample(monkeypatch):
    """الاختبار الأهم: الأفضلية لما صمد خارج العينة."""
    # داخل العينة: 0.9 هو الأجمل · خارجها: 0.9 يخسر و1.5 يربح
    scores = {
        0.9: {"trades": 30, "expectancy_r": 0.90, "win_rate": 50.0, "total_r": 27},
        1.5: {"trades": 30, "expectancy_r": 0.40, "win_rate": 50.0, "total_r": 12},
    }
    train_scores = dict(scores)
    test_scores = {
        0.9: {"trades": 30, "expectancy_r": -0.30, "win_rate": 40.0, "total_r": -9},
        1.5: {"trades": 30, "expectancy_r": 0.35, "win_rate": 50.0, "total_r": 10},
    }

    calls = {"n": 0}

    def fake(series, base_cfg, strategy_key, params, **kwargs):
        key = params.get("strategy.scalping_i.sl_coef", 0.0)
        source = test_scores if calls["n"] >= 2 else train_scores
        calls["n"] += 1
        return source.get(key, {"trades": 0, "expectancy_r": 0.0,
                                "win_rate": 0.0, "total_r": 0.0})

    monkeypatch.setattr(opt, "evaluate", fake)
    trains = [synthetic_series(120, seed=1)]
    tests = [synthetic_series(120, seed=2)]
    ranked = opt.search(trains, tests, _cfg(), "scalping_i",
                        {"strategy.scalping_i.sl_coef": [0.9, 1.5]},
                        trials=2, min_trades=5, top_k=2)
    assert ranked
    assert ranked[0].params["strategy.scalping_i.sl_coef"] == 1.5
    assert ranked[0].test_r == 0.35


def test_search_drops_candidates_with_too_few_trades(monkeypatch):
    monkeypatch.setattr(
        opt, "evaluate",
        _fake_evaluate({1.0: {"trades": 3, "expectancy_r": 5.0,
                              "win_rate": 100.0, "total_r": 15}}))
    ranked = opt.search([synthetic_series(120, seed=1)],
                        [synthetic_series(120, seed=2)], _cfg(), "scalping_i",
                        {"strategy.scalping_i.sl_coef": [1.0]},
                        trials=1, min_trades=20)
    assert ranked == []          # 3 صفقات = رقم بلا معنى


# ═══════════════════ الحماية من المبالغة ═══════════════════
def test_overfit_is_detected_when_out_of_sample_is_negative():
    cand = opt.Candidate(params={"a": 1}, train_r=0.8, test_r=-0.2,
                         train_trades=50, test_trades=30)
    assert cand.is_overfit is True
    assert cand.retention == 0.0


def test_overfit_is_detected_when_most_of_the_edge_disappears():
    cand = opt.Candidate(params={"a": 1}, train_r=1.0, test_r=0.2,
                         train_trades=50, test_trades=30)
    assert cand.is_overfit is True          # احتفظ بـ 20% فقط
    assert cand.retention == pytest.approx(0.2)


def test_good_candidate_is_not_flagged():
    cand = opt.Candidate(params={"a": 1}, train_r=0.5, test_r=0.42,
                         train_trades=50, test_trades=30)
    assert cand.is_overfit is False
    assert cand.retention == pytest.approx(0.84)


def test_walk_forward_flags_inconsistent_results(monkeypatch):
    """رابحة في نافذة من أربع = غير ثابتة."""
    values = [0.5, -0.3, -0.2, -0.4]
    state = {"i": 0}

    def fake(series, base_cfg, strategy_key, params, **kwargs):
        value = values[state["i"] % len(values)]
        state["i"] += 1
        return {"trades": 20, "expectancy_r": value, "win_rate": 50.0,
                "total_r": 4.0}

    monkeypatch.setattr(opt, "evaluate", fake)
    result = opt.walk_forward([synthetic_series(600, seed=1)], _cfg(),
                              "scalping_i", {}, folds=3)
    assert result["folds"] >= 2
    assert result["consistent"] is False


def test_walk_forward_accepts_consistent_results(monkeypatch):
    def fake(series, base_cfg, strategy_key, params, **kwargs):
        return {"trades": 20, "expectancy_r": 0.3, "win_rate": 50.0,
                "total_r": 6.0}

    monkeypatch.setattr(opt, "evaluate", fake)
    result = opt.walk_forward([synthetic_series(600, seed=1)], _cfg(),
                              "scalping_i", {}, folds=3)
    assert result["consistent"] is True
    assert result["positive"] == result["folds"]


# ═══════════════════════ الوصفة ═══════════════════════
def test_recipe_uses_telegram_set_names():
    cand = opt.Candidate(params={
        "strategy.scalping_i.sl_coef": 1.2,
        "strategy.scalping_i.backcandles": 7,
        "trade.stop_loss_pct": 0.01,
    })
    lines = opt.recipe(cand)
    assert "/set sisl 1.2" in lines
    assert "/set sibc 7" in lines
    assert "/set sl 0.01" in lines


def test_recipe_falls_back_to_the_last_path_segment():
    cand = opt.Candidate(params={"strategy.unknown_param": 3})
    assert opt.recipe(cand) == ["/set unknown_param 3"]


def test_every_grid_key_has_a_set_command():
    """كل معامل في شبكة البحث يجب أن يكون قابلاً للتطبيق من تليجرام."""
    from stratig.bot.telegram_bot import SET_KEYS

    paths = {name for name, _kind, _desc in
             ((v[0], v[1], v[2]) for v in SET_KEYS.values())}
    for strategy, grid in opt.GRIDS.items():
        for path in list(grid) + list(opt.EXIT_GRID):
            assert path in paths, f"لا يوجد أمر /set للمسار {path} ({strategy})"


def test_every_set_name_in_recipe_matches_a_real_path():
    from stratig.bot.telegram_bot import SET_KEYS

    for path, name in opt.SET_NAME.items():
        assert name in SET_KEYS, name
        assert SET_KEYS[name][0] == path, (name, SET_KEYS[name][0], path)


# ═══════════════════════ من البداية للنهاية ═══════════════════════
def test_end_to_end_search_runs():
    series = [synthetic_series(300, seed=9, regime="trend")]
    trains, tests = [], []
    for candles in series:
        train, test = opt.split_candles(candles, 0.7)
        trains.append(train)
        tests.append(test)
    ranked = opt.search(trains, tests, _cfg(), "scalping_i",
                        {"strategy.scalping_i.sl_coef": [0.9, 1.1, 1.4]},
                        trials=3, min_trades=1, top_k=2)
    assert isinstance(ranked, list)
    for cand in ranked:
        assert isinstance(cand.params, dict)
        assert isinstance(cand.test_r, float)
