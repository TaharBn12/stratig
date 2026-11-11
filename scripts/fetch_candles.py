"""جلب شموع **حقيقية** إلى ملف CSV — بلا مفاتيح، بلا حساب، بلا إنترنت خاص.

لماذا هذا السكربت؟
    「اختبرها على عملة one قبل 4 ايام」 — أي اختبار على **بيانات حقيقية**.
    المختبر (`scripts/lab.py`) يقرأ CSV، لكن من أين يأتي الـ CSV؟ المنصّات
    التي يتداول عليها البوت (Binance/Bybit) **تحجب** بعض البلدان جغرافياً،
    فتحتاج مفتاحاً وVPN. لذلك يستخدم هذا السكربت واجهة **OKX العامة**
    (بيانات السوق لا تحتاج مفتاحاً ولا KYC) ويكتب CSV جاهزاً للمختبر.

    python scripts/fetch_candles.py --symbol ONEUSDT --tf 15m --days 4
    python scripts/fetch_candles.py --symbol BTCUSDT --tf 5m --days 30 --out data/btc.csv

    ثم:
    python scripts/lab.py --csv data/ONEUSDT-15m.csv --min-trades 80

⚠️ تنبيهان مهمّان:
    1. المصدر **OKX** (عقود مؤجّلة ONE-USDT-SWAP). الأسعار متقاربة بين
       المنصّات لكنها **ليست متطابقة** — فروق بسيطة في السيولة قد تغيّر
       نتيجة استراتيجية سكالبينغ. للقرارات الحقيقية استخدم بيانات منصّتك.
    2. لا يستخدم أي مفتاح: بيانات السوق العامة فقط. لا يلمس حسابك.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OKX_HOST = "https://www.okx.com"
# OKX: أطول 100 شمعة في الطلب الواحد
MAX_PER_REQUEST = 100
# احترام حدّ المعدّل (40 طلب/ثانية لبيانات السوق) — نحن أبطأ بكثير
REQUEST_PAUSE = 0.25

# تحويل إطار البوت إلى صيغة OKX (OKX تستعمل H/D كبيرة)
OKX_BARS: dict[str, str] = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "1w": "1W",
}
# كم ملّي ثانية في الإطار (لحساب عدد الشموع)
BAR_MS: dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
    "12h": 43_200_000, "1d": 86_400_000, "1w": 604_800_000,
}


class FetchError(RuntimeError):
    """فشل الجلب — برسالة عربية واضحة للمستخدم."""


def okx_instrument(symbol: str, market: str = "swap") -> str:
    """ONEUSDT ⇒ ONE-USDT-SWAP (عقود) أو ONE-USDT (فوري)."""
    text = (symbol or "").strip().upper()
    if not text:
        raise FetchError("لم تُحدَّد العملة — مرّر --symbol ONEUSDT")
    for quote in ("USDT", "USDC"):
        if text.endswith(quote) and len(text) > len(quote):
            base = text[: -len(quote)]
            if market == "swap":
                return f"{base}-{quote}-SWAP"
            return f"{base}-{quote}"
    raise FetchError(f"صيغة العملة غير مفهومة: {symbol} (المتوقّع: ONEUSDT)")


def _get(url: str, timeout: int = 20) -> dict:
    """طلب GET بسيط — urllib من المكتبة القياسية (بلا تبعيات)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "stratig/fetch_candles"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:                    # شبكة/DNS/حجب
        raise FetchError(
            f"تعذّر الوصول إلى {OKX_HOST} — تحقّق من الإنترنت أو من حجب الموقع"
            f" في بلدك. التفصيل: {exc}") from exc
    except TimeoutError as exc:                             # انتهاء المهلة
        raise FetchError(f"انتهت مهلة الاتصال بـ {OKX_HOST}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetchError(f"ردّ غير مفهوم من المنصّة: {raw[:120]}") from exc


def fetch_okx(inst_id: str, bar: str, start_ms: int, end_ms: int,
              *, verbose: bool = False) -> list[list[str]]:
    """يجلب الشموع بين start_ms و end_ms (تصاعدياً: الأقدم أولاً).

    يمشي للخلف بطلبات متتالية (`after` = أقدم شمعة حصلنا عليها) لأن OKX
    لا يُعيد أكثر من 100 شمعة في الطلب.
    """
    if bar not in OKX_BARS:
        raise FetchError(f"الإطار {bar} غير مدعوم في OKX"
                         f" (المدعوم: {', '.join(OKX_BARS)})")

    rows: list[list[str]] = []
    after = end_ms
    step = BAR_MS[bar]
    while after > start_ms:
        url = (f"{OKX_HOST}/api/v5/market/history-candles?instId={inst_id}"
               f"&bar={OKX_BARS[bar]}&limit={MAX_PER_REQUEST}&after={after}")
        payload = _get(url)
        if str(payload.get("code")) != "0":
            raise FetchError(f"رفضت OKX الطلب: {payload.get('msg') or payload}")
        batch = payload.get("data") or []
        if not batch:
            break
        oldest = int(batch[-1][0])
        for item in batch:
            ts = int(item[0])
            if start_ms <= ts <= end_ms:
                rows.append([str(ts), item[1], item[2], item[3], item[4], item[5]])
        after = oldest - step                    # نمشي للخلف
        if verbose:
            print(f"    … {len(rows)} شمعة", flush=True)
        if oldest <= start_ms or len(batch) < MAX_PER_REQUEST:
            break
        time.sleep(REQUEST_PAUSE)

    if not rows:
        raise FetchError("لم تعد المنصّة أي شمعة في هذه الفترة — جرّب إطاراً أو"
                         " مدّة أصغر، أو تأكّد من رمز العملة")
    rows.sort(key=lambda row: int(row[0]))       # الأقدم أولاً
    return rows


def write_csv(rows: list[list[str]], path: str | Path) -> Path:
    """يكتب CSV بالصيغة التي يقرأها `scripts/lab.py --csv`."""
    out = Path(path)
    if out.parent and str(out.parent) != ".":
        out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        writer.writerows(rows)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="جلب شموع حقيقية إلى CSV (واجهة OKX العامة، بلا مفتاح)")
    parser.add_argument("--symbol", default="BTCUSDT", help="مثال: ONEUSDT")
    parser.add_argument("--tf", default="15m",
                        choices=tuple(OKX_BARS), help="إطار الشمعة")
    parser.add_argument("--days", type=float, default=4.0,
                        help="كم يوماً للخلف من الآن")
    parser.add_argument("--market", default="swap", choices=("swap", "spot"),
                        help="swap = عقود مؤجّلة (الافتراضي) · spot = فوري")
    parser.add_argument("--out", default="",
                        help="مسار الملف (افتراضياً data/ONEUSDT-15m.csv)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    inst_id = okx_instrument(args.symbol, args.market)
    end_ms = int(time.time() * 1000)
    end_ms -= end_ms % BAR_MS[args.tf]           # نهايات شمعة مضبوطة
    start_ms = end_ms - int(args.days * 86_400_000)

    if not args.quiet:
        print(f"  العملة: {args.symbol} ({inst_id}) · الإطار: {args.tf}"
              f" · المدّة: {args.days} يوماً")
        print(f"  المصدر: OKX العام (بلا مفتاح) · الشموع المتوقّعة:"
              f" ~{int((end_ms - start_ms) / BAR_MS[args.tf])}")

    rows = fetch_okx(inst_id, args.tf, start_ms, end_ms, verbose=not args.quiet)

    out = args.out or f"data/{args.symbol.upper()}-{args.tf}.csv"
    path = write_csv(rows, out)
    if not args.quiet:
        first = rows[0]
        last = rows[-1]
        print(f"  ✅ كتبنا {len(rows)} شمعة في {path}")
        print(f"     من {_stamp(int(first[0]))} (إغلاق {first[4]})"
              f" إلى {_stamp(int(last[0]))} (إغلاق {last[4]})")
        print(f"\n  شغّل المختبر الآن:")
        print(f"     python scripts/lab.py --csv {path} --min-trades 80")
    return 0


def _stamp(ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000)) + " UTC"


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FetchError as error:
        print(f"\n  ❌ {error}", file=sys.stderr)
        sys.exit(1)
