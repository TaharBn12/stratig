"""اختبارات الإعدادات المُوصى بها.

أهم اختبارين هنا:
  1) التوصيات **لا تلمس معاملات الاستراتيجية أبداً** (الدفتر منقول حرفياً)
  2) كل توصية لها أمر /set حقيقي ومسار موجود في DEFAULT_CONFIG
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig import presets                          # noqa: E402
from stratig.config import DEFAULT_CONFIG, Config    # noqa: E402
from stratig.strategy.registry import all_strategies  # noqa: E402


def _cfg(**overrides) -> Config:
    data: dict = {}
    for key, value in overrides.items():
        section, name = key.split("__", 1)
        data.setdefault(section, {})[name] = value
    return Config(data)


# ═══════════════════ سلامة القائمة ═══════════════════
def test_every_recommendation_points_to_a_real_config_path():
    for rec in presets.RECOMMENDED:
        node = DEFAULT_CONFIG
        for part in rec.path.split("."):
            assert isinstance(node, dict) and part in node, f"مسار غير موجود: {rec.path}"
            node = node[part]


def test_every_recommendation_has_a_real_set_command():
    from stratig.bot.telegram_bot import SET_KEYS

    for rec in presets.RECOMMENDED:
        assert rec.set_key in SET_KEYS, f"لا يوجد /set للتوصية {rec.path}"
        assert SET_KEYS[rec.set_key][0] == rec.path, (
            f"{rec.set_key} يشير إلى {SET_KEYS[rec.set_key][0]} لا {rec.path}")


def test_every_recommendation_has_a_reason():
    for rec in presets.RECOMMENDED:
        assert rec.why.strip(), f"توصية بلا سبب: {rec.path}"


def test_no_duplicate_paths_per_strategy():
    seen: set[tuple[str, str]] = set()
    for rec in presets.RECOMMENDED:
        keys = rec.strategies or ("*",)
        for strategy in keys:
            marker = (rec.path, strategy)
            assert marker not in seen, f"توصية مكرّرة: {rec.path} / {strategy}"
            seen.add(marker)


def test_recommendations_never_touch_strategy_parameters():
    """الأهم: الدفتر منقول حرفياً — معاملاته خط أحمر."""
    forbidden_prefixes = (
        "strategy.scalping_i.",
        "strategy.rsi.period",
        "strategy.williams_r.",
        "exit.atr.",
    )
    for rec in presets.RECOMMENDED:
        for prefix in forbidden_prefixes:
            assert not rec.path.startswith(prefix), (
                f"التوصية {rec.path} تُغيّر معامل استراتيجية — ممنوع")


def test_recommended_values_match_their_types():
    """القيمة المُوصى بها من نفس نوع القيمة الافتراضية."""
    for rec in presets.RECOMMENDED:
        node = DEFAULT_CONFIG
        for part in rec.path.split("."):
            node = node[part]
        if node is None or node == "":
            continue
        assert isinstance(rec.value, type(node)), (
            f"{rec.path}: المُوصى به {rec.value!r} من نوع {type(rec.value).__name__} "
            f"والافتراضي {node!r} من نوع {type(node).__name__}")


# ═══════════════════ الانطباق ═══════════════════
def test_regime_recommendation_follows_the_strategy():
    """rsi_williams ارتدادية ⇒ جانبي · scalping_i اختراقية ⇒ متّجه."""
    for strategy, expected in (("rsi_williams", "range"), ("scalping_i", "trend")):
        cfg = _cfg(strategy__name=strategy)
        found = [r for r in presets.applicable(cfg, strategy)
                 if r.path == "strategy.regime"]
        assert len(found) == 1
        assert found[0].value == expected


def test_percent_exit_recommendations_skip_atr_strategies():
    """sl/tp النسبية لا معنى لها مع مخارج ATR."""
    cfg = _cfg(strategy__name="scalping_i", exit__mode="atr")
    paths = [r.path for r in presets.applicable(cfg, "scalping_i")]
    assert "trade.stop_loss_pct" not in paths
    assert "trade.take_profit_pct" not in paths

    cfg = _cfg(strategy__name="rsi_williams", exit__mode="percent")
    paths = [r.path for r in presets.applicable(cfg, "rsi_williams")]
    assert "trade.stop_loss_pct" in paths


def test_applicable_includes_shared_recommendations():
    cfg = _cfg(strategy__name="scalping_i")
    paths = [r.path for r in presets.applicable(cfg, "scalping_i")]
    for path in ("risk.sizing", "risk.risk_per_trade_pct", "edge.gate",
                 "strategy.quality_enabled", "scanner.signal_ttl_seconds"):
        assert path in paths


# ═══════════════════ الفرق والتطبيق ═══════════════════
def test_diff_reports_old_and_new():
    cfg = _cfg(strategy__name="scalping_i")
    changes = presets.diff(cfg, "scalping_i")
    by_path = {c.rec.path: c for c in changes}
    assert by_path["risk.sizing"].old == "fixed"
    assert by_path["risk.sizing"].new == "risk"
    assert by_path["risk.sizing"].changed is True


def test_apply_changes_the_config_and_returns_undo():
    cfg = _cfg(strategy__name="scalping_i")
    changes, undo = presets.apply(cfg, "scalping_i")
    applied = [c for c in changes if c.changed]
    assert applied
    assert cfg.get("risk.sizing") == "risk"
    assert cfg.get("risk.risk_per_trade_pct") == 0.01
    assert cfg.get("edge.gate") is True
    assert undo["risk.sizing"] == "fixed"


def test_undo_restores_previous_values():
    cfg = _cfg(strategy__name="scalping_i")
    _changes, undo = presets.apply(cfg, "scalping_i")
    restored = presets.restore(cfg, undo)
    assert "risk.sizing" in restored
    assert cfg.get("risk.sizing") == "fixed"
    assert cfg.get("edge.gate") is False


def test_apply_is_idempotent():
    """تطبيق مرتين لا يُغيّر شيئاً في المرة الثانية."""
    cfg = _cfg(strategy__name="scalping_i")
    presets.apply(cfg, "scalping_i")
    changes, _undo = presets.apply(cfg, "scalping_i")
    assert [c for c in changes if c.changed] == []


def test_diff_of_already_applied_shows_no_changes():
    cfg = _cfg(strategy__name="scalping_i")
    presets.apply(cfg, "scalping_i")
    assert [c for c in presets.diff(cfg, "scalping_i") if c.changed] == []


def test_snapshot_only_contains_changed_values():
    cfg = _cfg(strategy__name="scalping_i")
    cfg.set("risk.sizing", "risk")            # مطبَّقة مسبقاً
    changes = presets.diff(cfg, "scalping_i")
    undo = presets.snapshot(cfg, changes)
    assert "risk.sizing" not in undo


# ═══════════════════ العرض ═══════════════════
def test_format_changes_groups_and_marks_applied():
    cfg = _cfg(strategy__name="scalping_i")
    changes = presets.diff(cfg, "scalping_i")
    text = presets.format_changes(changes)
    assert "إدارة المخاطر" in text
    assert "sizing" in text
    assert "مقياس الميزة" in text


def test_format_changes_marks_already_applied():
    cfg = _cfg(strategy__name="scalping_i")
    presets.apply(cfg, "scalping_i")
    text = presets.format_changes(presets.diff(cfg, "scalping_i"))
    assert "مطبَّق مسبقاً" in text


def test_format_renders_booleans_in_arabic():
    cfg = _cfg(strategy__name="scalping_i")
    changes = presets.diff(cfg, "scalping_i")
    text = presets.format_changes(changes)
    gate = [c for c in changes if c.rec.path == "edge.gate"][0]
    assert gate.old is False
    assert "لا" in text


# ═══════════════════ أوامر /set تغطي كل التوصيات ═══════════════════
def _bot():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_bot import make_bot

    bot, _trader, _ex = make_bot()
    return bot


def test_all_recommendations_are_reachable_from_telegram():
    """لكل توصية أمر /set يعمل فعلاً على البوت."""
    from stratig.bot.telegram_bot import SET_KEYS

    bot = _bot()
    for rec in presets.RECOMMENDED:
        assert rec.set_key in SET_KEYS
        ok, message = bot._apply_setting(rec.set_key, str(rec.value))
        assert ok, f"/set {rec.set_key} {rec.value} فشل: {message}"


def test_recommended_command_shows_a_plan_before_applying():
    """/recommended يعرض الخطة ولا يطبّق قبل التأكيد."""
    sent: list[str] = []

    class FakeMsg:
        async def edit_text(self, text, **kwargs):
            sent.append(text)

    class Update:
        class effective_message:
            @staticmethod
            async def reply_text(text, **kwargs):
                sent.append(text)
                return FakeMsg()

    import asyncio
    bot = _bot()
    asyncio.run(bot._recommended.__wrapped__(bot, Update(), _Ctx([])))

    assert sent and "تغيير مقترح" in sent[0]
    assert "sizing" in sent[0]
    # لم يُطبَّق بعد
    assert bot.cfg.get("risk.sizing") == "fixed"


def test_recommended_undo_restores():
    import asyncio

    bot = _bot()
    bot._last_rec_undo = {"risk.sizing": "fixed", "edge.gate": False}
    bot.cfg.set("risk.sizing", "risk")
    bot.cfg.set("edge.gate", True)

    sent: list[str] = []

    class FakeMsg:
        async def edit_text(self, text, **kwargs):
            sent.append(text)

    class Update:
        class effective_message:
            @staticmethod
            async def reply_text(text, **kwargs):
                sent.append(text)
                return FakeMsg()

    asyncio.run(bot._recommended_undo.__wrapped__(bot, Update()))
    assert bot.cfg.get("risk.sizing") == "fixed"
    assert bot.cfg.get("edge.gate") is False
    assert "أُعيدت" in sent[0]


class _Ctx:
    """سياق تليجرام وهمي."""

    def __init__(self, args):
        self.args = args
