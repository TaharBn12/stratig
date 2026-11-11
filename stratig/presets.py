"""الإعدادات المُوصى بها — كل توصية مع **سببها**، تُطبَّق بأمر واحد.

لماذا وحدة مستقلة؟
    لأن التوصيات تراكمت عبر المهام في أمكنة متفرّقة (README، رسائل،
    ملفات PR) فصار تطبيقها يدوياً مرهقاً وعُرضة للنسيان. هنا تجتمع في
    مكان واحد، كل واحدة **بسببها المقيس** لا برأي.

مبدأ أساسي: **لا نلمس معاملات الاستراتيجية.**
    الدفتر منقول حرفياً (`طبّقها حرفيا بدون تغيير`)، ومعاملاته
    (EMA 50/30، RSI 10، BB 15/1.5، ATR 7، slcoef 1.1، TPSLRatio 1.5)
    لا تُغيَّر هنا أبداً. ما نُغيّره هو **كيف تحمي نفسك** حولها:
    حجم الصفقة، معدّلها، نظام السوق، والميزة.

وكل تغيير **قابل للتراجع** — نحفظ القيم السابقة قبل التطبيق.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# ── المجموعات ──
GROUP_RISK = "risk"
GROUP_QUALITY = "quality"
GROUP_EDGE = "edge"
GROUP_EXITS = "exits"

GROUP_TITLES = {
    GROUP_RISK: "🛡 إدارة المخاطر",
    GROUP_QUALITY: "🎯 جودة الإشارة",
    GROUP_EDGE: "📊 مقياس الميزة",
    GROUP_EXITS: "🚪 المخارج والتوقيت",
}


@dataclass
class Recommendation:
    """إعداد مُوصى به واحد."""

    path: str                            # المسار في config.toml
    value: Any                           # القيمة المُوصى بها
    set_key: str                         # أمر /set المقابل
    group: str = GROUP_RISK
    why: str = ""                        # السبب (مقيس إن أمكن)
    strategies: tuple[str, ...] = ()     # فارغ = لكل الاستراتيجيات
    needs: tuple[str, ...] = ()          # شروط: ("atr_exits",) / ("percent_exits",)


# ═══════════════════════ القائمة ═══════════════════════
RECOMMENDED: list[Recommendation] = [
    # ── إدارة المخاطر ──
    Recommendation(
        "risk.sizing", "risk", "sizing", GROUP_RISK,
        why="الحجم يُحسب من مسافة الوقف: وقف ضيق 0.9% وواسع 3% يعنيان مخاطرة "
            "تختلف 3 أضعاف بنفس المبلغ",
    ),
    Recommendation(
        "risk.risk_per_trade_pct", 0.01, "riskpct", GROUP_RISK,
        why="1% من الرصيد لكل صفقة — يصمد أمام 10 خسائر متتالية",
    ),
    Recommendation(
        "risk.max_trades_per_hour", 3, "maxtrades", GROUP_RISK,
        why="مشكلتك «إشارات كثيرة ضعيفة»: السقف يحذف الأسوأ تلقائياً",
    ),
    Recommendation(
        "risk.min_gap_seconds", 900, "mingap", GROUP_RISK,
        why="فاصل 15 دقيقة يمنع الدخول المتتالي في نفس الحركة",
    ),
    Recommendation(
        "risk.max_consecutive_losses", 3, "maxlosses", GROUP_RISK,
        why="قاطع بعد 3 خسائر: يحميك من نفسك في الوضع التلقائي",
    ),
    Recommendation(
        "risk.pause_after_losses_seconds", 3600, "pauseloss", GROUP_RISK,
        why="ساعة راحة تكفي لتبريد السوق والقرار",
    ),
    Recommendation(
        "risk.max_positions", 3, "maxpos", GROUP_RISK,
        why="3 صفقات مفتوحة تكفي لتركيز رأس المال على الأفضل",
    ),

    # ── جودة الإشارة ──
    Recommendation(
        "strategy.quality_enabled", True, "quality", GROUP_QUALITY,
        why="يُفعّل فلاتر نظام السوق (ADX) والتقلّب والإطار الأعلى",
    ),
    Recommendation(
        "strategy.regime", "range", "regime", GROUP_QUALITY,
        strategies=("rsi_williams",),
        why="قياسنا: rsi_williams تكسب في الجانبي (اتجاهها الصرف +0.2%) "
            "وتخسر في المتّجه (−0.45%)",
    ),
    Recommendation(
        "strategy.regime", "trend", "regime", GROUP_QUALITY,
        strategies=("scalping_i",),
        why="scalping_i فيها شرط اتجاه EMA 30/50 أصلاً، فنظامها الملائم "
            "هو المتّجه",
    ),
    Recommendation(
        "strategy.adx_trend_min", 25.0, "adxmin", GROUP_QUALITY,
        why="المرجعي المتعارف عليه: أقل من 25 = بلا اتجاه",
    ),
    Recommendation(
        "strategy.adx_range_max", 20.0, "adxmax", GROUP_QUALITY,
        why="أكثر من 20 = اتجاه قوي، فلا مكان للارتداد",
    ),
    Recommendation(
        "strategy.mtf_enabled", True, "mtf", GROUP_QUALITY,
        why="لا تشترِ في هبوط الإطار الأعلى — القاعدة الأقدم في المتاجرة",
    ),
    Recommendation(
        "strategy.mtf_timeframe", "1h", "mtftf", GROUP_QUALITY,
        why="إطار أعلى من إطار إشارتك يؤكّد الجهة",
    ),
    Recommendation(
        "strategy.volatility_min_pct", 0.003, "volmin", GROUP_QUALITY,
        why="الساكن لن يبلغ الهدف أبداً — العمولة تلتهمه",
    ),
    Recommendation(
        "strategy.volatility_max_pct", 0.02, "volmax", GROUP_QUALITY,
        why="الهائج يجعل المخاطرة أعلى ممّا خطّطت له",
    ),

    # ── مقياس الميزة ──
    Recommendation(
        "edge.enabled", True, "edge", GROUP_EDGE,
        why="لترى هل استراتيجيتك رابحة إحصائياً أم أنك تتداول ضجيجاً",
    ),
    Recommendation(
        "edge.gate", True, "edgegate", GROUP_EDGE,
        why="**الأهم**: يمنع التداول عند ثبوت الخسارة بفترة ثقة 95%",
    ),
    Recommendation(
        "edge.min_trades", 30, "edgemin", GROUP_EDGE,
        why="أقل من 30 صفقة قد يكون حظاً — لا نصدر حكماً",
    ),

    # ── المخارج والتوقيت ──
    Recommendation(
        "scanner.signal_ttl_seconds", 300, "ttl", GROUP_EXITS,
        why="الإشارة القديمة فقدت ميزتها — الدخول المتأخّر سبب «اشتريت فهبط»",
    ),
    Recommendation(
        "execution.block_stale_entry", True, "block_stale", GROUP_EXITS,
        why="ارفض الدخول إن تحرّك السعر أكثر من وقف كامل عن سعر الإشارة",
    ),
    Recommendation(
        "trade.stop_loss_pct", 0.02, "sl", GROUP_EXITS,
        strategies=("rsi_williams",), needs=("percent_exits",),
        why="وقف 0.9% على إطار 15m يبتلعه الضجيج — مع إطار أعلى يُوسَّع",
    ),
    Recommendation(
        "trade.take_profit_pct", 0.04, "tp", GROUP_EXITS,
        strategies=("rsi_williams",), needs=("percent_exits",),
        why="نسبة 2:1 مع الوقف الموسَّع — تُناسب الإطار الأعلى",
    ),
    Recommendation(
        "scanner.interval_seconds", 300, "interval", GROUP_EXITS,
        why="فحص كل 5 دقائق يكفي، ويُخفّف الحمل على المنصة",
    ),
]


# ═══════════════════════ المنطق ═══════════════════════
def _exit_mode(cfg) -> str:
    return str(cfg.get("exit.mode", "percent") or "percent").lower()


def applicable(cfg, strategy: str | None = None) -> list[Recommendation]:
    """التوصيات التي تنطبق على إعداداتك الحالية."""
    key = str(strategy or cfg.get("strategy.name", "") or "")
    mode = _exit_mode(cfg)
    out: list[Recommendation] = []
    for rec in RECOMMENDED:
        if rec.strategies and key not in rec.strategies:
            continue
        if "atr_exits" in rec.needs and mode != "atr":
            continue
        if "percent_exits" in rec.needs and mode != "percent":
            continue
        out.append(rec)
    return out


@dataclass
class Change:
    rec: Recommendation
    old: Any
    new: Any

    @property
    def changed(self) -> bool:
        return self.old != self.new


def diff(cfg, strategy: str | None = None) -> list[Change]:
    """ما الذي سيُغيَّر؟ (بدون تطبيق) — للعرض قبل التأكيد."""
    changes = []
    for rec in applicable(cfg, strategy):
        old = cfg.get(rec.path, None)
        changes.append(Change(rec=rec, old=old, new=rec.value))
    return changes


def snapshot(cfg, changes: Iterable[Change]) -> dict[str, Any]:
    """القيم الحالية قبل التطبيق — للتراجع."""
    return {c.rec.path: c.old for c in changes if c.changed}


def apply(cfg, strategy: str | None = None) -> tuple[list[Change], dict[str, Any]]:
    """يطبّق التوصيات ويُرجع (التغييرات، نسخة للتراجع)."""
    changes = diff(cfg, strategy)
    undo = snapshot(cfg, changes)
    for change in changes:
        if change.changed:
            cfg.set(change.rec.path, change.new)
    return changes, undo


def restore(cfg, undo: dict[str, Any]) -> list[str]:
    """يُعيد القيم السابقة — يُرجع المسارات التي أُعيدت."""
    done = []
    for path, value in (undo or {}).items():
        cfg.set(path, value)
        done.append(path)
    return done


def format_changes(changes: list[Change]) -> str:
    """يعرض التغييرات مجمّعة — يُستخدم قبل التأكيد وبعده."""
    lines: list[str] = []
    by_group: dict[str, list[Change]] = {}
    for change in changes:
        by_group.setdefault(change.rec.group, []).append(change)

    for group, items in by_group.items():
        lines.append(f"{GROUP_TITLES.get(group, group)}")
        for change in items:
            mark = "🔁" if change.changed else "✓"
            if change.changed:
                lines.append(
                    f"  {mark} <code>{change.rec.set_key}</code>: "
                    f"{_fmt(change.old)} → <b>{_fmt(change.new)}</b>"
                )
            else:
                lines.append(
                    f"  {mark} <code>{change.rec.set_key}</code>: "
                    f"{_fmt(change.new)} (مطبَّق مسبقاً)"
                )
            if change.changed:
                lines.append(f"      <i>{_clean(change.rec.why)}</i>")
        lines.append("")
    return "\n".join(lines)


def _clean(text: str) -> str:
    return str(text).replace("**", "")


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if value is None:
        return "—"
    return str(value)
