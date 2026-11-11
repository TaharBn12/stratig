"""خادم لوحة التحكم — مكتبة بايثون القياسية فقط.

`ThreadingHTTPServer` يعمل في خيط خلفي (daemon) داخل البوت، أو وحده في
`scripts/dashboard.py` لقراءة سجل الصفقات. لا يضيف أي تبعية جديدة،
وهذا مقصود: بوتك يعمل على ويندوز ببيئة خالية من المكتبات المترجَمة.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("stratig")

GetSnapshot = Callable[[], dict[str, Any]]


def default_page() -> Path:
    """ملف اللوحة الوحيد — نفس الملف الذي ينشره Vercel.

    (لا نسخة مكرّرة داخل الحزمة: مصدر واحد للحقيقة يمنع انحراف الواجهتين.)
    """
    from ..config import PROJECT_ROOT

    return Path(PROJECT_ROOT) / "dashboard" / "index.html"


class _Handler(BaseHTTPRequestHandler):
    """يعرض صفحة واحدة وثلاث نقاط JSON."""

    getter: GetSnapshot = lambda: {}  # type: ignore[assignment]
    auth_token: str = ""
    page: Path | None = None

    # ── أساسيات ──
    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("[web] " + fmt, *args)

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
            pass

    def _json(self, payload: Any, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        """رمز اختياري يمنع أي شخص على الشبكة من رؤية صفقاتك."""
        if not _Handler.auth_token:
            return True
        # يُمرَّر كرأس أو كمتغير ?token=
        header = self.headers.get("X-Stratig-Token", "")
        query = self.path.split("token=")[-1].split("&")[0] if "token=" in self.path else ""
        return _Handler.auth_token in (header, query)

    # ── الطلبات ──
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/", "/index.html"):
            self._serve_page()
        elif path == "/api/state":
            if not self._authorized():
                return self._json({"error": "غير مصرّح"}, 401)
            try:
                self._json(self.getter())
            except Exception as err:
                log.warning("[web] فشل بناء اللقطة: %s", err)
                self._json({"error": str(err)}, 500)
        elif path == "/api/health":
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def _serve_page(self) -> None:
        if not self._authorized():
            return self._json({"error": "غير مصرّح"}, 401)
        page = _Handler.page or default_page()
        if not page.exists():  # pragma: no cover
            self._send(500, b"dashboard missing", "text/plain; charset=utf-8")
            return
        self._send(200, page.read_bytes(), "text/html; charset=utf-8")


class Dashboard:
    """يُدير خادم اللوحة في خيط خلفي."""

    def __init__(
        self,
        getter: GetSnapshot,
        host: str = "0.0.0.0",
        port: int = 8000,
        token: str = "",
    ) -> None:
        self.host = str(host or "0.0.0.0")
        # 0 منفذ صالح («اختر منفذاً متاحاً») — لذا لا نستخدم `or` هنا
        self.port = 8000 if port is None else int(port)
        self.token = str(token or "")
        self.page = None
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._getter = getter

    @property
    def url(self) -> str:
        shown = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return f"http://{shown}:{self.port}/"

    def start(self) -> bool:
        """يُشغّل الخادم — لا يرفع استثناءً أبداً (اللوحة ترف، لا أساس)."""
        try:
            self.server = ThreadingHTTPServer((self.host, self.port), _Handler)
        except OSError as err:
            log.warning("[web] تعذّر تشغيل لوحة التحكم على %s:%s — %s",
                        self.host, self.port, err)
            return False

        handler_cls = self.server.RequestHandlerClass
        handler_cls.getter = staticmethod(self._getter)  # type: ignore[attr-defined]
        handler_cls.auth_token = self.token             # type: ignore[attr-defined]
        handler_cls.page = self.page                    # type: ignore[attr-defined]

        # المنفذ 0 = «اختر منفذاً متاحاً» — يفيد الاختبارات ويمنع التصادم
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="stratig-dashboard", daemon=True)
        self.thread.start()
        log.info("لوحة التحكم: %s", self.url)
        return True

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
