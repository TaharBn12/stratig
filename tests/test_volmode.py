"""اختبارات `/set volmode` — مبدّل السوق المتقلّب والهادئ.

العتبات **مقيسة على بيانات حقيقية** (5 عملات × 15m × 60 يوماً)، لا مُخمَّنة.
هذه الاختبارات تثبّت أن ما يراه المستخدم هو ما يطبّقه البوت فعلاً.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from stratig.bot.telegram_bot import (
    SET_KEYS,
    VOL_BASE_15M,
    TelegramBot,
    volatility_preset,
)
from stratig.config import Config
from stratig.utils import timeframe_minutes


@pytest.fixture
def bot(tmp_path):
    """كائن بحدّه الأدنى: الدالّة تستخدم self.cfg فقط."""
    path = tmp_path / "config.toml"
    path.write_text("[strategy]\ntimeframe = '15m'\n", encoding="utf-8")
    cfg = Config.load(str(path), str(tmp_path / ".env.missing"))
    return SimpleNamespace(cfg=cfg)


# ═══════════════════════ الأمر معرّف ═══════════════════════

def test_volmode_is_a_known_command():
    assert "volmode" in SET_KEYS
    path, kind, _hint = SET_KEYS["volmode"]
    assert path == "strategy.volatility_mode"
    assert kind == "choice:off,calm,volatile,band"


def test_volmode_path_exists_in_config():
    cfg = Config({})
    assert cfg.get("strategy.volatility_mode") == "off"


# ═══════════════════════ العتبات ═══════════════════════

def test_off_disables_both_thresholds():
    assert volatility_preset("off", "15m") == (0.0, 0.0)
    assert volatility_preset("off", "1h") == (0.0, 0.0)


def test_calm_sets_only_a_ceiling():
    low, high = volatility_preset("calm", "15m")
    assert low == 0.0          # بلا حد أدنى
    assert high > 0            # سقف يمنع الهائج


def test_volatile_sets_only_a_floor():
    low, high = volatility_preset("volatile", "15m")
    assert low > 0             # أرضية تمنع الساكن
    assert high == 0           # بلا سقف


def test_band_spans_the_middle():
    """الترتيب المقيس: p25 < p40 < p60 < p75 ⇒ band يحيط بالوضعين."""
    b_low, b_high = volatility_preset("band", "15m")
    _, c_high = volatility_preset("calm", "15m")
    v_low, _ = volatility_preset("volatile", "15m")
    assert b_low < c_high < v_low < b_high


def test_calm_and_volatile_never_overlap():
    """الأهم: الوضعان **منفصلان** بلا تقاطع — وإلا لَـما كانا وضعين.

    الهادئ يقبل ما دون p40، والمتقلّب ما فوق p60: بينهما فجوة (p40←p60)
    فلا توجد شمعة يقبلها الوضعان معاً.
    """
    for tf in ("5m", "15m", "1h", "4h"):
        calm_low, calm_high = volatility_preset("calm", tf)
        vol_low, _vol_high = volatility_preset("volatile", tf)
        assert calm_low == 0.0 and calm_high > 0
        assert calm_high < vol_low, f"{tf}: تداخل بين الوضعين"


def test_unknown_mode_falls_back_to_off():
    assert volatility_preset("غلط", "15m") == (0.0, 0.0)


# ═══════════════════════ القياس على الإطار ═══════════════════════

def test_thresholds_grow_with_timeframe():
    """1h أكثر تقلّباً من 15m ⇒ عتبته أعلى (وهذا كل سبب وجود الأمر)."""
    for mode in ("calm", "volatile", "band"):
        low15, high15 = volatility_preset(mode, "15m")
        low60, high60 = volatility_preset(mode, "1h")
        assert (low60 + high60) > (low15 + high15), mode


def test_scaling_follows_square_root_of_time():
    """التقلّب ∝ √الزمن — تحقّقنا منه على البيانات بخطأ 5.8%."""
    for mode in ("calm", "volatile", "band"):
        low15, high15 = volatility_preset(mode, "15m")
        low60, high60 = volatility_preset(mode, "1h")
        assert math.isclose(low60, low15 * 2, rel_tol=1e-3)
        assert math.isclose(high60, high15 * 2, rel_tol=1e-3)


def test_thresholds_work_for_unmeasured_timeframes():
    """بفضل √الزمن تعمل العتبات على 5m و 4h بلا قياس جديد."""
    for tf in ("5m", "30m", "4h", "1d"):
        low, high = volatility_preset("band", tf)
        assert low > 0 and high > low, tf


def test_thresholds_are_sane_on_extremes():
    """1m صغير جداً و1M ضخم — لا نريد أصفاراً ولا قيماً منفجرة."""
    low, high = volatility_preset("band", "1m")
    assert 0 < low < 0.01
    low, high = volatility_preset("band", "1M")
    assert high < 1.0                      # أقل من 100% تقلّب شهري


def test_base_values_match_measured_data():
    """خط الأساس = النسب المقيسة فعلاً (لا أرقام مخترعة)."""
    # مقيسة على 1,105 قياس حقيقي لـ ATR% (وايلدر 14) على 15m
    assert VOL_BASE_15M["calm"][1] == pytest.approx(0.00318, abs=1e-5)      # p40
    assert VOL_BASE_15M["volatile"][0] == pytest.approx(0.00394, abs=1e-5)  # p60
    assert VOL_BASE_15M["band"][0] == pytest.approx(0.00264, abs=1e-5)      # p25
    assert VOL_BASE_15M["band"][1] == pytest.approx(0.00476, abs=1e-5)      # p75


# ═══════════════════════ التطبيق الفعلي ═══════════════════════

def test_applying_volatile_sets_floor_and_enables_quality(bot):
    message = TelegramBot._apply_volmode(bot, "volatile",
                                         "strategy.volatility_mode", "off")
    low, high = volatility_preset("volatile", "15m")
    assert bot.cfg.get("strategy.volatility_min_pct") == low
    assert bot.cfg.get("strategy.volatility_max_pct") == high
    # الفخّ الأخطر: بلا quality تُتجاهل العتبتان بصمت
    assert bot.cfg.get("strategy.quality_enabled") is True
    assert "quality" in message


def test_applying_calm_sets_ceiling(bot):
    TelegramBot._apply_volmode(bot, "calm", "strategy.volatility_mode", "off")
    low, high = volatility_preset("calm", "15m")
    assert bot.cfg.get("strategy.volatility_min_pct") == low
    assert bot.cfg.get("strategy.volatility_max_pct") == high


def test_off_does_not_force_quality(bot):
    """إيقاف الفلتر قرارك — لا نفعّل quality فوق إرادتك."""
    TelegramBot._apply_volmode(bot, "off", "strategy.volatility_mode", "calm")
    assert bot.cfg.get("strategy.quality_enabled") is False
    assert bot.cfg.get("strategy.volatility_max_pct") == 0.0


def test_applies_thresholds_for_current_timeframe(bot):
    """العتبات تُقاس على الإطار الفعلي لا على 15m دائماً."""
    bot.cfg.set("strategy.timeframe", "1h")
    TelegramBot._apply_volmode(bot, "volatile", "strategy.volatility_mode", "off")
    low_1h, _ = volatility_preset("volatile", "1h")
    low_15m, _ = volatility_preset("volatile", "15m")
    applied = bot.cfg.get("strategy.volatility_min_pct")
    assert applied == low_1h
    assert applied != low_15m
    assert "1h" in TelegramBot._apply_volmode(
        bot, "volatile", "strategy.volatility_mode", "volatile")


def test_message_shows_values_and_warns_about_timeframe_change(bot):
    message = TelegramBot._apply_volmode(bot, "band",
                                         "strategy.volatility_mode", "off")
    assert "0." in message            # الأرقام المعروضة
    assert "/set tf" in message       # تنبيه إعادة الحساب عند تغيير الإطار


def test_values_are_persisted(bot, tmp_path):
    TelegramBot._apply_volmode(bot, "volatile", "strategy.volatility_mode", "off")
    saved = Config.load(str(tmp_path / "config.toml"),
                        str(tmp_path / ".env.missing"))
    assert saved.get("strategy.volatility_min_pct") > 0
    assert saved.get("strategy.quality_enabled") is True


# ═══════════════════════ أداة الإطار ═══════════════════════

@pytest.mark.parametrize("tf,minutes", [("5m", 5), ("15m", 15), ("1h", 60),
                                        ("4h", 240), ("1d", 1440)])
def test_timeframe_minutes(tf, minutes):
    assert timeframe_minutes(tf) == minutes


def test_timeframe_minutes_bad_input_defaults_to_15():
    assert timeframe_minutes("غلط") == 15
    assert timeframe_minutes("") == 15
