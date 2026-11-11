"""رفع اللقطة إلى Supabase — حتى تفتح اللوحة من هاتفك في أي مكان.

لماذا Supabase بدل خادم محلي؟ لأن البوت يعمل على جهازك خلف موجّه (NAT):
لا تستطيع فتح منفذ للعالم. البوت **يدفع** البيانات إلى السحابة، واللوحة
تقرأها من هناك — لا تحتاج توجيه منافذ ولا IP ثابت.

يستخدم مكتبة `urllib` من بايثون فقط (بلا تبعيات جديدة)، ويفشل بصمت:
أي خطأ في الشبكة يُسجَّل ولا يوقف البوت أبداً.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("stratig")

DEFAULT_TIMEOUT = 8.0


class SupabaseSync:
    """عميل REST بسيط لجدولَي اللوحة."""

    def __init__(
        self,
        url: str = "",
        key: str = "",
        bot_id: str = "default",
        *,
        enabled: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.url = str(url or "").rstrip("/")
        self.key = str(key or "")
        self.bot_id = str(bot_id or "default")
        self.enabled = bool(enabled) and bool(self.url) and bool(self.key)
        self.timeout = float(timeout)
        self.last_error = ""
        self.pushed = 0

    @classmethod
    def from_config(cls, config) -> "SupabaseSync":
        if config is None:
            return cls()
        g = config.get
        return cls(
            url=str(g("supabase.url", "") or ""),
            key=str(g("supabase.key", "") or ""),
            bot_id=str(g("supabase.bot_id", "default") or "default"),
            enabled=bool(g("supabase.enabled", False)),
        )

    # ── الشبكة ──
    def _request(self, path: str, payload: Any, prefer: str,
                 method: str = "POST") -> tuple[bool, str]:
        if not self.enabled:
            return False, "معطّل"
        endpoint = f"{self.url}/rest/v1/{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            method=method,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": prefer,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if 200 <= response.status < 300:
                    self.last_error = ""
                    return True, ""
                self.last_error = f"HTTP {response.status}"
                return False, self.last_error
        except urllib.error.HTTPError as err:
            detail = ""
            try:
                detail = err.read().decode("utf-8", "ignore")[:200]
            except Exception:
                pass
            self.last_error = f"HTTP {err.code}: {detail}"
            return False, self.last_error
        except Exception as err:
            self.last_error = f"{type(err).__name__}: {err}"
            return False, self.last_error

    # ── الحالة ──
    def push_state(self, snapshot: dict[str, Any]) -> bool:
        """يحدّث صف الحالة (إنشاؤه إن لم يكن موجوداً)."""
        row = {
            "bot_id": self.bot_id,
            "updated_at": _iso(snapshot.get("ts")),
            "payload": snapshot,
        }
        ok, err = self._request("bot_state", row, "resolution=merge-duplicates")
        if ok:
            self.pushed += 1
        elif err != "معطّل":
            log.debug("[supabase] فشل رفع الحالة: %s", err)
        return ok

    # ── الصفقات ──
    def push_trades(self, rows: list[dict[str, Any]]) -> bool:
        """يرفع صفقات جديدة — يتجاهل المكرّر (unique على الرمز ووقت الإغلاق)."""
        if not rows:
            return False
        payload = []
        for row in rows:
            payload.append({
                "bot_id": self.bot_id,
                "symbol": str(row.get("symbol", "")),
                "side": str(row.get("side", "")),
                "pnl": _num(row.get("pnl")),
                "r_multiple": _num(row.get("r")),
                "opened_at": _iso(row.get("opened_at")),
                "closed_at": _iso(row.get("closed_at")),
                "strategy": str(row.get("strategy", "")),
            })
        ok, err = self._request("bot_trades", payload,
                                "resolution=ignore-duplicates,return=minimal")
        if not ok and err != "معطّل":
            log.debug("[supabase] فشل رفع الصفقات: %s", err)
        return ok

    def status(self) -> str:
        if not self.enabled:
            return "معطّل"
        if self.last_error:
            return f"خطأ: {self.last_error[:60]}"
        return f"يعمل ({self.pushed} رفع)"


def _iso(value: Any) -> str | None:
    """طابع زمني بايثون → نص ISO للتخزين في Postgres."""
    from datetime import datetime, timezone

    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def _num(value: Any, digits: int = 6) -> float:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0
