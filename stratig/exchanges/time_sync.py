"""مزامنة التوقيت مع المنصة — تمنع خطأ Binance ‎-1021‎.

Binance ترفض أي طلب يكون توقيته **متقدّماً** على توقيت الخادم بأكثر من
نحو 1000 مللي ثانية، حتى لو كان `recvWindow` كبيراً:

    (400, -1021, "Timestamp for this request was 1000ms ahead of the server's time.")

وسببه عادةً أن ساعة الجهاز متقدّمة أو منحرفة قليلاً عن التوقيت العالمي.

الحل هنا ثلاث طبقات:
1. قياس الفرق (offset) بين توقيتنا وتوقيت المنصة عند الإقلاع وكل نصف ساعة.
2. ترقيع `get_timestamp` داخل موصّل Binance ليستخدم التوقيت المُصحَّح
   في **كل** طلب (أوامر، رصيد، صفقات…) بدل ساعة الجهاز،
   مع هامش أمان يجعلنا متأخرين قليلاً لا متقدّمين (التأخير مقبول دائماً).
3. إعادة المحاولة تلقائياً عند ظهور ‎-1021‎ بعد مزامنة فورية.
"""
from __future__ import annotations

import importlib
import logging
import sys
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# الوحدات التي تحمل الدالة المستخدمة في توقيع الطلبات داخل موصّل Binance
_BINANCE_MODULES = (
    "binance.api",
    "binance.lib.utils",
    "binance.websocket.websocket_client",
)


class TimeSync:
    """يحسب فرق التوقيت عن المنصة ويوفّر توقيتاً مصحّحاً لكل الطلبات."""

    SAFETY_MS = 1_000          # نتأخّر قليلاً بدل أن نتقدّم (التقدّم مرفوض)
    REFRESH_SECONDS = 1_800    # إعادة مزامنة كل نصف ساعة

    def __init__(
        self,
        server_time_fn: Callable[[], int],
        safety_ms: int = SAFETY_MS,
        refresh_seconds: float = REFRESH_SECONDS,
    ) -> None:
        self._server_time = server_time_fn
        self.safety_ms = int(safety_ms)
        self.refresh_seconds = float(refresh_seconds)
        self.offset_ms: int = 0            # التوقيت الذي نستخدمه = المحلي + offset
        self.last_sync: float = 0.0
        self.last_error: str = ""

    # ─────────────────── القراءة ───────────────────
    @property
    def drift_ms(self) -> int:
        """الفرق الحقيقي بين توقيتنا وتوقيت المنصة (موجب = ساعتنا متأخّرة)."""
        return self.offset_ms + self.safety_ms

    @property
    def synced(self) -> bool:
        return self.last_sync > 0

    def describe(self) -> str:
        if not self.synced:
            return f"غير معروف ({self.last_error or 'لم تُجرَ مزامنة بعد'})"
        drift = self.drift_ms / 1000
        sign = "+" if drift >= 0 else "−"
        return f"المنصة تتقدّم علينا بـ {sign}{abs(drift):.2f} ثانية — يُصحَّح تلقائياً"

    def now(self) -> int:
        """التوقيت المُصحَّح بالمللي ثانية (يُستخدم في توقيع الطلبات)."""
        return int(time.time() * 1000) + self.offset_ms

    # ─────────────────── المزامنة ───────────────────
    def sync(self, force: bool = False) -> int:
        if not force and self.last_sync and (time.time() - self.last_sync) < self.refresh_seconds:
            return self.offset_ms
        try:
            server = int(self._server_time())
        except Exception as err:            # الشبكة قد تكون مقطوعة — لا نُسقط البوت
            self.last_error = str(err)
            log.debug("تعذّر جلب توقيت المنصة: %s", err)
            return self.offset_ms
        if server <= 0:
            return self.offset_ms
        local = int(time.time() * 1000)
        self.offset_ms = server - local - self.safety_ms
        self.last_sync = time.time()
        self.last_error = ""
        drift = self.drift_ms
        if abs(drift) >= 1_000 and force:
            log.warning(
                "ساعة الجهاز منحرفة عن المنصة بـ %.2f ثانية — تمت المزامنة تلقائياً. "
                "يُنصح بمزامنة وقت ويندوز: w32tm /resync",
                drift / 1000,
            )
        return self.offset_ms

    def maybe_sync(self) -> None:
        """يُستدعى قبل كل طلب موقّع: يعيد المزامنة إن مرّ وقت طويل."""
        self.sync(force=False)

    # ─────────────────── الترقيع ───────────────────
    def patch_connector(self) -> int:
        """يجعل موصّل Binance يستخدم توقيتنا المُصحَّح في كل طلب."""
        patched = 0
        for name in _BINANCE_MODULES:
            module = sys.modules.get(name)
            if module is None:
                try:
                    module = importlib.import_module(name)
                except Exception:  # pragma: no cover — موصّل غير مثبّت
                    continue
            if not hasattr(module, "get_timestamp"):
                continue
            try:
                setattr(module, "get_timestamp", self.now)
                patched += 1
            except Exception as err:  # pragma: no cover
                log.debug("تعذّر ترقيع %s: %s", name, err)
        return patched


def server_time_from(client) -> Callable[[], int]:
    """ينشئ دالة تجلب توقيت المنصة من عميل Binance.

    يُمرَّر كائن العميل أو دالة تُعيده (مفيد في الاختبارات حين يُستبدل العميل).
    """

    def _fetch() -> int:
        target = client() if callable(client) else client
        data = target.time()
        if isinstance(data, dict):
            return int(data.get("serverTime", 0))
        return int(data)

    return _fetch


__all__ = ["TimeSync", "server_time_from"]
