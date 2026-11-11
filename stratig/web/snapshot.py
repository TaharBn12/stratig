"""لقطة حالة البوت — البنية الموحّدة التي تعرضها لوحة التحكم.

لماذا وحدة مستقلة؟ لأن لوحة التحكم تعمل بثلاث طرق:
    1. مُضمّنة في البوت (بيانات حيّة من المنصة)
    2. مستقلة عن البوت (تقرأ سجل الصفقات من القرص — تكفي لـ 90% من الأسئلة)
    3. مرفوعة إلى Supabase (للوصول من الهاتف في أي مكان)

الثلاثة يبنون **نفس القاموس**، فتعمل الواجهة مع أي مصدر بدون تغيير.
"""
from __future__ import annotations

import time
from typing import Any


def _round(value: Any, digits: int = 2) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value != value or value in (float("inf"), float("-inf")):
        return 0.0
    return round(value, digits)


def equity_curve(trades) -> list[float]:
    """منحنى الرصيد التراكمي — أهم رسم بياني في اللوحة.

    يكشف ما لا تكشفه الأرقام: ربح إجمالي موجود لكن المنحنى ينهار في
    نصفه الثاني = الاستراتيجية لم تعد تعمل.
    """
    curve: list[float] = []
    total = 0.0
    for trade in trades:
        total += float(getattr(trade, "pnl", 0.0) or 0.0)
        curve.append(round(total, 2))
    return curve


def trades_rows(trades, limit: int = 50) -> list[dict[str, Any]]:
    """آخر الصفقات — الأحدث أولاً."""
    rows = []
    for trade in list(trades)[-limit:][::-1]:
        rows.append(
            {
                "symbol": getattr(trade, "symbol", ""),
                "side": getattr(trade, "side", ""),
                "pnl": _round(getattr(trade, "pnl", 0.0)),
                "r": _round(getattr(trade, "r_multiple", 0.0), 3),
                "opened_at": float(getattr(trade, "opened_at", 0.0) or 0.0),
                "closed_at": float(getattr(trade, "closed_at", 0.0) or 0.0),
                "strategy": getattr(trade, "strategy", ""),
            }
        )
    return rows


def stats_block(journal, trader=None) -> dict[str, Any]:
    """مؤشرات الأداء — نفس أرقام ‎/stats‎ في تليجرام."""
    today_trades = journal.today()
    return {
        "count": int(journal.count),
        "win_rate": _round(journal.win_rate, 1),
        "expectancy_r": _round(journal.expectancy_r, 3),
        "profit_factor": _round(journal.profit_factor, 2),
        "total_pnl": _round(journal.total_pnl, 2),
        "max_drawdown": _round(journal.max_drawdown, 2),
        "today_count": len(today_trades),
        "today_pnl": _round(sum(t.pnl for t in today_trades), 2),
        "wins": len(journal.wins),
        "losses": len(journal.losses),
    }


def risk_block(trader) -> dict[str, Any]:
    """حالة إدارة المخاطر: هل البوت مسموح له بالتداول الآن؟"""
    if trader is None:
        return {"trading_allowed": True, "reason": "", "trades_left": 0,
                "breaker_paused": False, "consecutive_losses": 0}
    allowed, reason = trader.risk_gate()
    breaker = getattr(trader, "breaker", None)
    paused = bool(breaker and getattr(breaker, "paused_until", 0.0) > time.time())
    return {
        "trading_allowed": bool(allowed),
        "reason": str(reason or getattr(trader, "_risk_reason", "") or ""),
        "trades_left": int(trader.rate.remaining()),
        "breaker_paused": paused,
        "consecutive_losses": int(getattr(breaker, "losses", 0) or 0),
    }


def positions_block(trader) -> list[dict[str, Any]]:
    """الصفقات المفتوحة الآن (تحتاج اتصالاً بالمنصة — قد تفشل)."""
    if trader is None:
        return []
    try:
        positions = trader.exchange.positions()
    except Exception:
        return []
    rows = []
    for pos in positions:
        try:
            if abs(float(getattr(pos, "size", 0.0) or 0.0)) <= 0:
                continue
            meta = (getattr(trader, "_opened_meta", {}) or {}).get(
                str(getattr(pos, "symbol", "")).upper(), {})
            rows.append({
                "symbol": getattr(pos, "symbol", ""),
                "side": getattr(pos, "side", ""),
                "size": _round(abs(float(getattr(pos, "size", 0.0) or 0.0)), 4),
                "entry": _round(getattr(pos, "entry_price", 0.0), 6),
                "mark": _round(getattr(pos, "mark_price", 0.0), 6),
                "pnl": _round(getattr(pos, "pnl", 0.0)),
                "roe_pct": _round(getattr(pos, "roe_pct", 0.0)),
                "stop": _round(meta.get("sl_price") or 0.0, 6),
                "target": _round(meta.get("tp_price") or 0.0, 6),
            })
        except Exception:  # pragma: no cover
            continue
    return rows


def build_snapshot(
    trader=None,
    config=None,
    bot_id: str = "default",
    *,
    live: bool = False,
) -> dict[str, Any]:
    """يبني اللقطة الموحّدة.

    trader=None ⇒ وضع القراءة من القرص (سجل الصفقات فقط، بلا منصة).
    """
    cfg = config
    get = (lambda key, default=None: cfg.get(key, default)) if cfg else (
        lambda key, default=None: default)

    journal = getattr(trader, "journal", None)
    trades = list(getattr(journal, "trades", []) or [])

    # وضع القراءة من القرص: نحمّل السجل مباشرة
    if journal is None and cfg is not None:
        from ..risk import Journal

        path = get("risk.journal_path", "state/trades.json")
        journal = Journal(path, limit=int(get("risk.journal_limit", 1000)))
        trades = list(journal.trades)

    stats = stats_block(journal) if journal else {
        "count": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0,
        "total_pnl": 0.0, "max_drawdown": 0.0, "today_count": 0,
        "today_pnl": 0.0, "wins": 0, "losses": 0,
    }

    balance = 0.0
    if trader is not None:
        try:
            balance = float(trader.exchange.balance().available)
        except Exception:
            balance = 0.0

    return {
        "bot_id": str(bot_id),
        "ts": time.time(),
        "live": bool(live),
        "strategy": str(get("strategy.name", "")),
        "timeframe": str(get("strategy.timeframe", "")),
        "mode": str(get("execution.mode", "manual")),
        "dry_run": bool(get("safety.dry_run", False)),
        "testnet": bool(get("exchange.testnet", True)),
        "exchange": str(get("exchange.name", "")),
        "balance": _round(balance),
        "scans": int(getattr(trader, "stats", {}).get("scans", 0)) if trader else 0,
        "signals": int(getattr(trader, "stats", {}).get("signals", 0)) if trader else 0,
        "opened": int(getattr(trader, "stats", {}).get("opened", 0)) if trader else 0,
        "stats": stats,
        "risk": risk_block(trader) if trader else risk_block(None),
        "positions": positions_block(trader) if live else [],
        "equity_curve": equity_curve(trades),
        "trades": trades_rows(trades),
    }
