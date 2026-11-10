"""يشخّص انحراف ساعة جهازك عن توقيت المنصة (خطأ Binance ‎-1021‎).

    .venv\\Scripts\\python.exe scripts\\fix_time.py        (ويندوز)
    .venv/bin/python scripts/fix_time.py                 (لينكس/ماك)

الخطأ الذي يعالجه هذا الفحص:
    (400, -1021, "Timestamp for this request was 1000ms ahead of the server's time.")

أي أن ساعة جهازك **متقدّمة** على توقيت Binance — وBinance ترفض أي طلب
توقيته في المستقبل حتى لو كان recvWindow كبيراً.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stratig.config import Config, Secrets  # noqa: E402
from stratig.exchanges import build_exchange  # noqa: E402

LINE = "═" * 66


def main() -> int:
    config = Config.load()
    secrets = Secrets.from_env()

    print(LINE)
    print("  فحص توقيت الجهاز مقابل توقيت المنصة")
    print(LINE)

    try:
        exchange = build_exchange(config, secrets)
    except Exception as err:
        print(f"\n❌ {err}")
        return 1

    try:
        server_ms = int(exchange.client.time()["serverTime"])
    except Exception as err:
        print(f"\n❌ تعذّر جلب توقيت المنصة: {err}")
        return 1

    local_ms = int(time.time() * 1000)
    drift = server_ms - local_ms          # موجب = المنصة متقدّمة = جهازك متأخّر
    ahead = -drift                        # موجب = جهازك متقدّم (هذا ما ترفضه Binance)

    def stamp(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n  توقيت جهازك : {stamp(local_ms)} UTC  ({local_ms})")
    print(f"  توقيت المنصة: {stamp(server_ms)} UTC  ({server_ms})")
    print(f"\n  الفرق: {drift / 1000:+.3f} ثانية "
          f"({'جهازك متأخّر' if drift > 0 else 'جهازك متقدّم ← سبب -1021'})")

    print(f"\n{LINE}")
    print("  النتيجة")
    print(LINE)

    if abs(drift) < 1000:
        print("\n✅ التوقيت سليم (الفرق أقل من ثانية) — الخطأ إن ظهر فسببه الشبكة لحظياً.")
    else:
        print(f"\n⚠️  انحراف {abs(drift) / 1000:.2f} ثانية.")
        if ahead > 0:
            print("   جهازك **متقدّم** على المنصة، وهذا بالضبط ما ترفضه Binance (-1021).")
        else:
            print("   جهازك متأخّر عن المنصة.")

    print("\n✅ البوت يعوّض هذا الفرق تلقائياً (مزامنة وقت الموصّل + إعادة محاولة).")
    print("   لكن الأفضل إصلاح ساعة ويندوز نفسها:")

    print("\n   ── الطريقة السريعة (موجّه أوامر كمسؤول) ──")
    print("   w32tm /resync")
    print("\n   ── أو من الواجهة ──")
    print("   الإعدادات ← الوقت واللغة ← «مزامنة الساعة الآن»")
    print("   وتأكد من اختيار المنطقة الزمنية الصحيحة وتفعيل «ضبط الوقت تلقائياً».")

    # عرض حالة المزامنة داخل البوت
    sync = getattr(exchange, "time_sync", None)
    if sync is not None:
        try:
            sync.sync(force=True)
            print(f"\n   حالة المزامنة داخل البوت: {sync.describe()}")
            print(f"   التوقيت المُرسل الآن: {sync.now()} (مصحّح)")
        except Exception as err:  # pragma: no cover
            print(f"\n   تعذّرت المزامنة: {err}")

    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
