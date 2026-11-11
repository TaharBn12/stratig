"""اختبارات مختبر الاستراتيجيات + الاستراتيجيات المرشّحة الأربع."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.data import Candles                          # noqa: E402
from scripts import lab as labmod                         # noqa: E402
from stratig.strategy import lab                          # noqa: E402
from stratig.strategy.registry import (                   # noqa: E402
    all_strategies,
    get,
    is_supported,
)
from scripts.backtest import synthetic_series             # noqa: E402


def _candles(rows) -> Candles:
    n = len(rows)
    return Candles([float(i) for i in range(n)],
                   [float(r[0]) for r in rows],
                   [float(r[1]) for r in rows],
                   [float(r[2]) for r in rows],
                   [float(r[3]) for r in rows],
                   [1.0] * n)


def _rising(n: int = 60, step: float = 1.0, start: float = 100.0) -> Candles:
    rows = []
    price = start
    for _ in range(n):
        rows.append((price, price * 1.002, price * 0.998, price))
        price += step
    return _candles(rows)


def _falling(n: int = 60, step: float = 1.0, start: float = 200.0) -> Candles:
    rows = []
    price = start
    for _ in range(n):
        rows.append((price, price * 1.002, price * 0.998, price))
        price -= step
    return _candles(rows)


def _flat(n: int = 60, price: float = 100.0) -> Candles:
    return _candles([(price, price * 1.001, price * 0.999, price)] * n)


# ═══════════════════════ التسجيل ═══════════════════════
def test_all_four_candidates_are_registered():
    keys = {s.key for s in all_strategies()}
    for key in (lab.MEAN_REVERSION_Z, lab.RSI_REVERSION,
                lab.DONCHIAN_BREAKOUT, lab.EMA_MOMENTUM):
        assert key in keys
        assert is_supported(key)


def test_original_strategies_are_untouched():
    """الجديد مضاف فقط — الأصليتان تبقيان كما هما."""
    assert get("rsi_williams").exit_mode == "percent"
    assert get("scalping_i").exit_mode == "atr"
    assert get("rsi_williams").key == "rsi_williams"


def test_candidates_use_atr_exits():
    for key in (lab.MEAN_REVERSION_Z, lab.RSI_REVERSION,
                lab.DONCHIAN_BREAKOUT, lab.EMA_MOMENTUM):
        assert get(key).exit_mode == "atr"


def test_lab_exit_modes_are_known_to_the_optimizer():
    from scripts.optimize import EXIT_MODE

    for key in (lab.MEAN_REVERSION_Z, lab.RSI_REVERSION,
                lab.DONCHIAN_BREAKOUT, lab.EMA_MOMENTUM):
        assert EXIT_MODE.get(key) == "atr", key


# ═══════════════════════ 1) ارتداد المتوسط ═══════════════════════
def test_z_score_buys_a_deep_dip():
    rows = [(100.0, 100.1, 99.9, 100.0)] * 30
    rows.append((100.0, 100.1, 88.0, 90.0))          # هبوط حاد
    decision = lab.evaluate_z(_candles(rows), None, use_closed_candles=False)
    assert decision.side == "buy"
    assert decision.sl_distance and decision.sl_distance > 0


def test_z_score_sells_a_spike():
    rows = [(100.0, 100.1, 99.9, 100.0)] * 30
    rows.append((100.0, 112.0, 99.9, 110.0))         # قفزة حادة
    decision = lab.evaluate_z(_candles(rows), None, use_closed_candles=False)
    assert decision.side == "sell"


def test_z_score_stays_flat_near_the_mean():
    """تذبذب ضعيف حول المتوسط ⇒ لا صفقة (المتوسط وحده لا يكفي)."""
    rows = []
    for i in range(40):
        price = 100.0 + (0.05 if i % 2 else 0.0)
        rows.append((price, price * 1.001, price * 0.999, price))
    decision = lab.evaluate_z(_candles(rows), None, use_closed_candles=False)
    assert decision.side is None
    assert any("متوسطه" in note for note in decision.notes)


def test_z_score_skips_a_dead_market():
    """سلسلة ثابتة تماماً: الانحراف المعياري صفر ⇒ لا إشارة ولا قسمة على صفر."""
    decision = lab.evaluate_z(_flat(40), None, use_closed_candles=False)
    assert decision.side is None
    assert any("الانحراف" in note for note in decision.notes)


def test_z_score_attaches_stop_and_target_prices():
    rows = [(100.0, 100.5, 99.5, 100.0)] * 30
    rows.append((100.0, 100.5, 88.0, 90.0))
    decision = lab.evaluate_z(_candles(rows), None, use_closed_candles=False)
    assert decision.side == "buy"
    assert decision.stop_loss < decision.price < decision.take_profit


def test_z_score_needs_enough_candles():
    decision = lab.evaluate_z(_flat(5), None, use_closed_candles=False)
    assert decision.side is None
    assert any("شموع" in note for note in decision.notes)


# ═══════════════════════ 2) ارتداد RSI ═══════════════════════
def test_rsi_reversion_buys_oversold():
    decision = lab.evaluate_rsi(_falling(60), None, use_closed_candles=False)
    assert decision.side == "buy"


def test_rsi_reversion_sells_overbought():
    decision = lab.evaluate_rsi(_rising(60), None, use_closed_candles=False)
    assert decision.side == "sell"


def test_rsi_reversion_ignores_the_middle():
    rows = []
    price = 100.0
    for i in range(60):
        price += 0.05 if i % 2 else -0.05          # تذبذب بلا اتجاه
        rows.append((price, price * 1.001, price * 0.999, price))
    decision = lab.evaluate_rsi(_candles(rows), None, use_closed_candles=False)
    assert decision.side is None
    assert any("محايد" in note for note in decision.notes)


def test_rsi_reversion_skips_a_dead_market():
    """سوق ميّت (إغلاقات متطابقة) ⇒ RSI = 100 ⇒ يجب ألا يُصدر «بيع» وهمياً."""
    decision = lab.evaluate_rsi(_flat(60), None, use_closed_candles=False)
    assert decision.side is None
    assert any("ثابت" in note for note in decision.notes)


# ═══════════════════════ 3) اختراق دونشيان ═══════════════════════
def test_donchian_buys_a_new_high():
    rows = [(100.0, 101.0, 99.0, 100.0)] * 30
    rows.append((100.0, 103.0, 99.5, 102.5))         # كسر القمة
    decision = lab.evaluate_donchian(_candles(rows), None, use_closed_candles=False)
    assert decision.side == "buy"


def test_donchian_sells_a_new_low():
    rows = [(100.0, 101.0, 99.0, 100.0)] * 30
    rows.append((100.0, 99.5, 96.0, 96.5))           # كسر القاع
    decision = lab.evaluate_donchian(_candles(rows), None, use_closed_candles=False)
    assert decision.side == "sell"


def test_donchian_excludes_the_current_candle_from_the_channel():
    """الشمعة الحالية لا تدخل في حساب القناة وإلا كسرت نفسها دائماً."""
    rows = [(100.0, 101.0, 99.0, 100.0)] * 30
    rows.append((100.0, 100.9, 99.1, 100.5))          # داخل القناة
    decision = lab.evaluate_donchian(_candles(rows), None, use_closed_candles=False)
    assert decision.side is None


# ═══════════════════════ 4) زخم EMA ═══════════════════════
def test_momentum_buys_an_uptrend():
    decision = lab.evaluate_momentum(_rising(60), None, use_closed_candles=False)
    assert decision.side == "buy"


def test_momentum_sells_a_downtrend():
    decision = lab.evaluate_momentum(_falling(60), None, use_closed_candles=False)
    assert decision.side == "sell"


def test_momentum_ignores_a_flat_market():
    decision = lab.evaluate_momentum(_flat(60), None, use_closed_candles=False)
    assert decision.side is None


# ═══════════════════════ شروط القبول في المختبر ═══════════════════════
def _patch(monkeypatch, results):
    """يجعل _run يُرجع النتائج بالترتيب: تدريب، اختبار، ثم النوافذ."""
    queue = list(results)

    def fake(series, strategy, params, entry_delay=1, horizon=60):
        if queue:
            return queue.pop(0)
        return {"trades": 0, "expectancy_r": 0.0, "win_rate": 0.0, "total_r": 0.0}

    monkeypatch.setattr(labmod, "_run", fake)
    monkeypatch.setattr(labmod, "split_candles", lambda c, r: (c, c))
    monkeypatch.setattr(labmod, "fold_windows",
                        lambda c, folds: [(c, c)] * (len(results) - 2))


def test_accepts_a_stable_winner(monkeypatch):
    _patch(monkeypatch, [
        {"trades": 100, "expectancy_r": 0.50},        # تدريب
        {"trades": 50, "expectancy_r": 0.30},         # اختبار
        {"trades": 20, "expectancy_r": 0.20},         # نوافذ
        {"trades": 20, "expectancy_r": 0.40},
        {"trades": 20, "expectancy_r": -0.10},
        {"trades": 20, "expectancy_r": 0.25},
        {"trades": 20, "expectancy_r": 0.35},
    ])
    result = labmod.evaluate_candidate("اختبار", "rsi_reversion", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.accepted is True
    assert result.trades == 150
    assert result.consistency == 0.8          # 4 من 5
    assert any("مقبولة" in r for r in result.reasons)


def test_rejects_too_few_trades(monkeypatch):
    _patch(monkeypatch, [
        {"trades": 30, "expectancy_r": 1.0},
        {"trades": 20, "expectancy_r": 1.0},
        {"trades": 10, "expectancy_r": 1.0},
        {"trades": 10, "expectancy_r": 1.0},
        {"trades": 10, "expectancy_r": 1.0},
    ])
    result = labmod.evaluate_candidate("قليل", "rsi_reversion", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.accepted is False
    assert any("صفقة فقط" in r for r in result.reasons)


def test_rejects_negative_out_of_sample(monkeypatch):
    """الدرس الأهم: ربح داخل العينة لا يكفي."""
    _patch(monkeypatch, [
        {"trades": 200, "expectancy_r": 0.80},       # داخل: ممتاز
        {"trades": 100, "expectancy_r": -0.20},      # خارج: خاسر
        {"trades": 20, "expectancy_r": 0.30},
        {"trades": 20, "expectancy_r": 0.30},
        {"trades": 20, "expectancy_r": 0.30},
        {"trades": 20, "expectancy_r": 0.30},
    ])
    result = labmod.evaluate_candidate("مبالغ", "rsi_reversion", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.accepted is False
    assert any("خارج العينة" in r for r in result.reasons)


def test_rejects_low_consistency_even_with_positive_oos(monkeypatch):
    """+0.459R خارج العينة بثبات 42% ⇒ مرفوض (هذا حدث فعلاً)."""
    _patch(monkeypatch, [
        {"trades": 200, "expectancy_r": 0.50},
        {"trades": 100, "expectancy_r": 0.459},
        {"trades": 20, "expectancy_r": 0.90},
        {"trades": 20, "expectancy_r": -0.30},
        {"trades": 20, "expectancy_r": -0.20},
        {"trades": 20, "expectancy_r": -0.10},
        {"trades": 20, "expectancy_r": 0.05},
    ])
    result = labmod.evaluate_candidate("غير ثابت", "donchian_breakout", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.accepted is False
    assert any("الثبات" in r for r in result.reasons)
    assert result.consistency == pytest.approx(0.4)


def test_rejects_windows_that_are_statistically_negative(monkeypatch):
    _patch(monkeypatch, [
        {"trades": 200, "expectancy_r": 0.10},
        {"trades": 100, "expectancy_r": 0.05},
        {"trades": 20, "expectancy_r": -1.0},
        {"trades": 20, "expectancy_r": -1.0},
        {"trades": 20, "expectancy_r": -1.0},
        {"trades": 20, "expectancy_r": -1.0},
    ])
    result = labmod.evaluate_candidate("نوافذ سالبة", "ema_momentum", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.accepted is False
    assert any("النوافذ" in r for r in result.reasons)


def test_score_prefers_stability_over_a_lucky_number(monkeypatch):
    """الثبات × التوقع: مرشّح ثابت يتقدّم على آخر محظوظ."""
    stable = labmod.Result(name="ثابت", strategy="a", params={},
                           trades=200, test_r=0.20, consistency=1.0)
    lucky = labmod.Result(name="محظوظ", strategy="b", params={},
                          trades=200, test_r=0.60, consistency=0.2)
    assert stable.score > lucky.score


def test_report_handles_no_winners(capsys):
    results = [labmod.Result(name="x", strategy="a", params={"k": 1},
                             trades=10, reasons=["❌ صفقة فقط"])]
    labmod.report(results, min_trades=80, folds=4)
    out = capsys.readouterr().out
    assert "لم يصمد أي مرشّح" in out


def test_candidates_cover_both_regime_hypotheses():
    """التنوّع مطلوب: ارتداد (نطاق) + اختراق وزخم (اتجاه)."""
    strategies = {strategy for _name, strategy, _v in labmod.CANDIDATES}
    assert lab.MEAN_REVERSION_Z in strategies
    assert lab.RSI_REVERSION in strategies
    assert lab.DONCHIAN_BREAKOUT in strategies
    assert lab.EMA_MOMENTUM in strategies


# ═══════════════════════════ بيانات حقيقية من CSV ═══════════════════════════

def _csv_text(n: int = 100, with_header: bool = True) -> str:
    lines = ["time,open,high,low,close,volume"] if with_header else []
    for i in range(n):
        base = 100.0 + i * 0.5
        lines.append(f"1700000000000,{base},{base + 1},{base - 1},{base + 0.25},1000")
    return "\n".join(lines) + "\n"


def test_load_csv_reads_candles_in_order(tmp_path):
    path = tmp_path / "BTCUSDT-1h.csv"
    path.write_text(_csv_text(120), encoding="utf-8")
    candles = labmod.load_csv(path)
    assert len(candles) == 120
    assert candles.close[0] < candles.close[-1]        # تصاعدي: الأقدم أولاً
    assert candles.high[0] >= candles.close[0] >= candles.low[0]


def test_load_csv_works_without_a_header(tmp_path):
    path = tmp_path / "no-header.csv"
    path.write_text(_csv_text(80, with_header=False), encoding="utf-8")
    assert len(labmod.load_csv(path)) == 80


def test_load_csv_skips_blank_lines_and_bom(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text("﻿" + _csv_text(90) + "\n\n", encoding="utf-8")
    assert len(labmod.load_csv(path)) == 90


def test_load_csv_rejects_a_sample_that_is_too_small(tmp_path):
    path = tmp_path / "tiny.csv"
    path.write_text(_csv_text(5), encoding="utf-8")
    with pytest.raises(ValueError, match="60"):
        labmod.load_csv(path)


def test_main_runs_on_real_csv_and_writes_json(tmp_path, capsys):
    """الطريق المقصود فعلاً: بيانات المستخدم، لا بيانات المولّد."""
    path = tmp_path / "BTCUSDT-1h.csv"
    path.write_text(_csv_text(400), encoding="utf-8")
    out = tmp_path / "lab.json"
    code = labmod.main(["--csv", str(path), "--folds", "3",
                        "--min-trades", "5", "--json", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "بياناتك" in printed                       # يوضّح مصدر البيانات
    assert "اصطناعية" not in printed
    assert out.exists()


def test_main_labels_synthetic_data_as_non_conclusive(capsys):
    labmod.main(["--synthetic", "--bars", "200", "--series", "1", "--folds", "2"])
    assert "اصطناعية" in capsys.readouterr().out


def test_only_accepts_the_display_name_or_the_key(capsys):
    """`--only` يعمل بالعربية وبالمعرّف الإنجليزي."""
    labmod.main(["--synthetic", "--bars", "200", "--series", "1", "--folds", "2",
                 "--only", "donchian_breakout"])
    assert "المرشّحون: 3" in capsys.readouterr().out
    labmod.main(["--synthetic", "--bars", "200", "--series", "1", "--folds", "2",
                 "--only", "اختراق دونشيان"])
    assert "المرشّحون: 3" in capsys.readouterr().out


# ═══════════════ شرط النوافذ + تحذير الهامش الضئيل ═══════════════

def test_rejects_a_winner_measured_on_too_few_windows(monkeypatch):
    """3 نوافذ لا تقيس التكرار: ثبات «2 من 3» قرعة، لا دليل.

    هذا بالضبط ما ظهر على بيانات ONE الحقيقية (381 شمعة، 3 نوافذ):
    مرشّح بهامش +0.018R كان سيُقبل لولا هذا الشرط.
    """
    _patch(monkeypatch, [
        {"trades": 100, "expectancy_r": 0.40},   # تدريب
        {"trades": 100, "expectancy_r": 0.02},   # اختبار (هامش ضئيل)
        {"trades": 20, "expectancy_r": 0.30},    # 3 نوافذ فقط
        {"trades": 20, "expectancy_r": 0.25},
        {"trades": 20, "expectancy_r": -0.10},
    ])
    result = labmod.evaluate_candidate("قليل النوافذ", "ema_momentum", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.windows == 3
    assert result.accepted is False
    assert any("نوافذ فقط" in r for r in result.reasons)


def test_flags_a_thin_margin_without_rejecting_it(monkeypatch):
    """هامش خارج العينة قريب من الصفر ⇒ ⚠️ تحذير لا ❌ رفض (بلا عمولة هنا)."""
    _patch(monkeypatch, [
        {"trades": 100, "expectancy_r": 0.40},
        {"trades": 100, "expectancy_r": 0.018},        # +0.018R = ضجيج
        {"trades": 20, "expectancy_r": 0.20},
        {"trades": 20, "expectancy_r": 0.25},
        {"trades": 20, "expectancy_r": 0.15},
        {"trades": 20, "expectancy_r": 0.10},
        {"trades": 20, "expectancy_r": 0.05},
    ])
    result = labmod.evaluate_candidate("هامش ضئيل", "ema_momentum", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4, fee_pct=0.0)
    assert result.accepted is True
    assert result.thin is True
    assert any("هامش ضئيل" in r for r in result.reasons)


def test_fee_is_shown_but_not_subtracted_twice(monkeypatch):
    """المُشغّل يخصم العمولة أصلاً ⇒ خصمها هنا again يكون **خصماً مزدوجاً**.

    خطأ وقعنا فيه فعلاً: `scripts/backtest.run` يخصم FEE_PCT من كل صفقة،
    ثم خصمناها مرة ثانية في المختبر — فظهرت استراتيجيات خاسرة وهي رابحة.
    """
    _patch(monkeypatch, [
        {"trades": 100, "expectancy_r": 0.40},
        {"trades": 100, "expectancy_r": 0.018},
        {"trades": 20, "expectancy_r": 0.20},
        {"trades": 20, "expectancy_r": 0.25},
        {"trades": 20, "expectancy_r": 0.15},
        {"trades": 20, "expectancy_r": 0.10},
        {"trades": 20, "expectancy_r": 0.05},
    ])
    result = labmod.evaluate_candidate("عمولة", "ema_momentum", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.fee_r > 0                       # تُحسب وتُعرض
    assert result.net_r == result.test_r          # ولا تُخصم مرتين
    assert not any("بعد العمولة" in r for r in result.reasons)


def test_the_runner_already_deducts_fees_and_slippage():
    """التوقع من المُشغّل صافٍ من العمولة، والانزلاق يزيد التكلفة."""
    from scripts.backtest import run
    from scripts.optimize import base_config

    candles = synthetic_series(1200, seed=5, regime="mixed")
    plain = run(candles, base_config("ema_momentum"), "ema_momentum", False, 1)
    slipped = run(candles, base_config("ema_momentum"), "ema_momentum", False, 1,
                  slippage_pct=0.002)
    assert plain["trades"] and slipped["trades"]
    assert slipped["expectancy_r"] < plain["expectancy_r"]
    assert slipped["cost_r"] > plain["cost_r"]
    assert len(plain["r_list"]) == plain["trades"]      # لكل صفقة عائدها


def test_a_bounded_window_gives_the_same_result_faster():
    """كل المؤشرات نافذية ⇒ تقييم آخر 400 شمعة يكفي (نتائج متطابقة)."""
    from scripts.backtest import run
    from scripts.optimize import base_config

    candles = synthetic_series(1500, seed=7, regime="mixed")
    for key in ("ema_momentum", "scalping_i"):
        full = run(candles, base_config(key), key, False, 1)
        quick = run(candles, base_config(key), key, False, 1, window=400)
        assert full["trades"] == quick["trades"]
        assert abs(full["expectancy_r"] - quick["expectancy_r"]) < 1e-9


def test_a_huge_margin_is_not_flagged_as_thin(monkeypatch):
    _patch(monkeypatch, [
        {"trades": 100, "expectancy_r": 0.40},
        {"trades": 100, "expectancy_r": 0.60},
        {"trades": 20, "expectancy_r": 0.20},
        {"trades": 20, "expectancy_r": 0.25},
        {"trades": 20, "expectancy_r": 0.15},
        {"trades": 20, "expectancy_r": 0.10},
        {"trades": 20, "expectancy_r": 0.05},
    ])
    result = labmod.evaluate_candidate("هامش واضح", "ema_momentum", {},
                                       [synthetic_series(200, seed=1)],
                                       min_trades=80, folds=4)
    assert result.accepted is True and result.thin is False


def test_baseline_prints_the_current_strategies_as_reference(tmp_path, capsys):
    """--baseline: هل الجديد أفضل مما تستعمله اليوم على نفس البيانات؟"""
    rows = ["time,open,high,low,close,volume"]
    for i in range(400):
        base = 100.0 + i * 0.01
        rows.append(f"1700000000000,{base},{base + 0.5},{base - 0.5},{base + 0.2},1000")
    path = tmp_path / "ref.csv"
    path.write_text("\n".join(rows), encoding="utf-8")

    labmod.main(["--csv", str(path), "--folds", "8", "--min-trades", "5",
                 "--baseline"])
    out = capsys.readouterr().out
    assert "المرجع" in out and "الحالية" in out


# ═══════════════════════════ تكلفة الصفقة ═══════════════════════════

def test_fee_drag_is_zero_when_no_fee():
    series = [synthetic_series(300, seed=3)]
    assert labmod.fee_drag_r(series, "ema_momentum", {}, fee_pct=0.0) == 0.0
    assert labmod.fee_drag_r([], "ema_momentum", {}) == 0.0


def test_a_wider_stop_means_a_smaller_fee_in_r():
    """العمولة بوحدة R تتناقص كلما اتّسع الوقف: fee_r = 2×العمولة ÷ بُعد الوقف."""
    series = [synthetic_series(400, seed=3)]
    narrow = labmod.fee_drag_r(series, "ema_momentum",
                               {"strategy.ema_momentum.sl_coef": 1.0})
    wide = labmod.fee_drag_r(series, "ema_momentum",
                             {"strategy.ema_momentum.sl_coef": 4.0})
    assert 0 < wide < narrow
    assert abs(wide - narrow / 4) < narrow * 0.01      # علاقة عكسية بالضبط


def test_fee_drag_uses_the_strategy_defaults_when_params_are_empty():
    """إن لم تُعطَ معاملات، نقرأ الافتراضي من config — لا نخترع رقماً."""
    series = [synthetic_series(400, seed=3)]
    value = labmod.fee_drag_r(series, "donchian_breakout", {})
    manual = labmod.fee_drag_r(series, "donchian_breakout",
                               {"strategy.donchian_breakout.sl_coef": 2.0,
                                "strategy.donchian_breakout.atr_length": 14})
    assert abs(value - manual) < 1e-9
