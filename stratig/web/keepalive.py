"""إبقاء الخدمة يقظة على منصّات النشر المجانية (Render تحديداً).

المشكلة: الخدمة المجانية على Render **تنام بعد 15 دقيقة بلا طلب داخلي**،
والبوت النائم لا يرى الشموع ولا يرسل إشارات. الحل المتعارف عليه: طلب خفيف
دوري إلى عنوان الخدمة العام — الخروج إلى الإنترنت والعودة عبر موازن الحمل
يُحتسب طلباً داخلياً، فيبقى العدّاد حيّاً.

لماذا نبقيه داخلياً بدل الاكتفاء بخدمة خارجية (UptimeRobot)؟ لأن الأخيرة
تحتاج حساباً وإعداداً إضافياً، ولأن النبض الداخلي يعمل حتى لو نسي المستخدم
تسجيل الخدمة. **والأفضل استخدامهما معاً** — موثّق في docs/render.md.

يستخدم `urllib` من المكتبة القياسية فقط، ويفشل بصمت: أي خطأ شبكة يُسجَّل
ولا يوقف البوت أبداً.
"""
from __future__ import annotations

import logging
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Callable

log = logging.getLogger("stratig")

DEFAULT_INTERVAL = 600.0     # 10 دقائق < 15 دقيقة (مهلة النوم على Render)
MIN_INTERVAL = 60.0          # أقل من دقيقة = إزعاج بلا فائدة
DEFAULT_TIMEOUT = 10.0
HEALTH_PATH = "/api/health"


def _env_flag(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return text in ("1", "true", "yes", "on")


class KeepAlive:
    """خيط خفي (daemon) ينقر نقطة الفحص الصحي كل فترة."""

    def __init__(
        self,
        url: str = "",
        interval: float = DEFAULT_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        opener: Callable[[str, float], bool] | None = None,
    ) -> None:
        self.url = str(url or "").rstrip("/")
        # لا نسمح بفاصل أقصر من الحد الأدنى — حماية من الطلبات اللانهائية
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL
        self.interval = max(MIN_INTERVAL, interval)
        self.timeout = float(timeout)
        self._opener = opener
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.pings = 0
        self.failures = 0
        self.last_error = ""

    # ── البناء من البيئة ──
    @classmethod
    def from_env(cls, config: Any = None) -> "KeepAlive | None":
        """يُعيد نبضة جاهزة، أو None إن كانت مُعطَّلة.

        مُفعَّلة تلقائياً على Render (المتغير RENDER=1 تضبطه المنصّة نفسها)،
        ويمكن تفعيلها يدوياً بـ KEEP_AWAKE=1 على أي منصّة أخرى.
        """
        on_render = _env_flag(os.getenv("RENDER"), False)
        if not _env_flag(os.getenv("KEEP_AWAKE"), on_render):
            return None

        url = (os.getenv("KEEP_AWAKE_URL")
               or os.getenv("RENDER_EXTERNAL_URL")
               or "").strip()

        # لا عنوان خارجي؟ ننقر أنفسنا محلياً — يكفي لإبقاء العملية نشطة
        # على منصّات تحسب الطلب المحلي، وهو الخيار الآمن إن لم يتوفّر غيره.
        if not url and config is not None:
            try:
                host = str(config.get("web.host", "") or "127.0.0.1")
                port = int(config.get("web.port", 8000) or 8000)
            except (TypeError, ValueError):
                host, port = "127.0.0.1", 8000
            if host in ("0.0.0.0", "", "::"):
                host = "127.0.0.1"
            url = f"http://{host}:{port}"

        if not url:
            return None

        interval = DEFAULT_INTERVAL
        raw = (os.getenv("KEEP_AWAKE_INTERVAL") or "").strip()
        if raw:
            try:
                interval = max(MIN_INTERVAL, float(raw))
            except ValueError:
                log.warning("[keepalive] KEEP_AWAKE_INTERVAL غير صالح (%s) — سأستخدم %.0f ثانية",
                            raw, DEFAULT_INTERVAL)
        return cls(f"{url.rstrip('/')}{HEALTH_PATH}", interval)

    # ── النبض ──
    def ping(self) -> bool:
        """طلب واحد. يُعيد True إن نجح."""
        if not self.url:
            self.last_error = "لا يوجد عنوان"
            return False
        if self._opener is not None:
            ok = bool(self._opener(self.url, self.timeout))
            self.pings += 1
            if not ok:
                self.failures += 1
                self.last_error = "فشل (اختبار)"
            return ok
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as response:
                ok = 200 <= response.status < 300
        except Exception as err:      # الشبكة لا يجب أن تُسقط البوت أبداً
            ok = False
            self.last_error = f"{type(err).__name__}: {err}"
        self.pings += 1
        if ok:
            self.last_error = ""
        else:
            self.failures += 1
        return ok

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.ping()
            except Exception as err:  # pragma: no cover — درع أخير
                log.debug("[keepalive] خطأ غير متوقع: %s", err)

    def start(self) -> bool:
        if not self.url or self._thread is not None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="stratig-keepalive", daemon=True)
        self._thread.start()
        log.info("نبضة الإيقاظ تعمل: %s كل %.0f ثانية", self.url, self.interval)
        return True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> str:
        if not self.url:
            return "معطّل"
        if self.last_error:
            return f"خطأ: {self.last_error[:60]}"
        return f"يعمل ({self.pings} نبضة)"
