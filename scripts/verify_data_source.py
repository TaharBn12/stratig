"""يتحقق من مصدر بيانات الشموع: حقيقي من المنصة أم محاكاة؟

    .venv\\Scripts\\python.exe scripts\\verify_data_source.py        (ويندوز)
    .venv/bin/python scripts/verify_data_source.py                 (لينكس/ماك)

يطلب البيانات فعلياً من المنصة ويطبع آخر الشموع كما وصلت،
حتى تتأكد بنفسك أن التحليل يتم على بيانات السوق الحقيقية.
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
from stratig.strategy.engine import evaluate  # noqa: E402

LINE = "═" * 66


def mask(value: str) -> str:
    value = (value or "").strip()
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]} (طول {len(value)})"


def main() -> int:
    config = Config.load()
    secrets = Secrets.from_env()

    print(LINE)
    print("  فحص مصدر بيانات الشموع")
    print(LINE)

    try:
        exchange = build_exchange(config, secrets)
    except Exception as err:
        print(f"\n❌ {err}")
        return 1

    url = getattr(exchange, "api_url", None)
    if not url:
        client = getattr(exchange, "client", None) or getattr(exchange, "session", None)
        url = getattr(client, "base_url", None) or getattr(client, "endpoint", None) or "غير معروف"
    testnet = bool(exchange.testnet)
    dry_run = bool(config.get("safety.dry_run", False))
    timeframe = str(config.get("strategy.timeframe", "15m"))
    limit = int(config.get("strategy.candles", 500))

    print(f"\n1) المنصة        : {exchange.name}")
    print(f"2) رابط API      : {url}")
    print(f"3) الشبكة        : {'تيستنت (أموال وهمية)' if testnet else 'حقيقي (أموال حقيقية)'}")
    print(f"4) مفتاح API     : {mask(secrets.creds(config.get('exchange.name'), testnet)[0])}")
    print(f"5) وضع المحاكاة  : {'مُفعّل — لا تُرسل أوامر' if dry_run else 'معطّل — تُرسل أوامر'}")
    print(f"6) الإطار الزمني : {timeframe} | عدد الشموع لكل رمز: {limit}")

    print(f"\n{LINE}")
    print("  جلب بيانات حقيقية الآن من المنصة…")
    print(LINE)

    try:
        symbols = exchange.usdt_symbols(top_n=5)
        print(f"\n✅ عدد الرموز المتاحة: {len(exchange.usdt_symbols(top_n=0))} "
              f"(أول 5: {symbols})")
    except Exception as err:
        print(f"❌ تعذّر جلب الرموز: {err}")
        return 1

    symbol = symbols[0] if symbols else "BTCUSDT"
    try:
        candles = exchange.klines(symbol, timeframe, limit)
    except Exception as err:
        print(f"\n❌ تعذّر جلب الشموع لـ {symbol}: {err}")
        print("   تأكد من المفاتيح والاتصال:  python main.py --check")
        return 1

    if not candles or len(candles) == 0:
        print("❌ المنصة أعادت صفر شموع")
        return 1

    print(f"\n✅ تم استلام {len(candles)} شمعة حقيقية لـ {symbol}")
    print(f"\nآخر 5 شموع (كما وصلت من المنصة):")
    print(f"  {'التوقيت UTC':<22}{'الافتتاح':>12}{'الأعلى':>12}{'الأدنى':>12}{'الإغلاق':>12}")
    for i in range(-5, 0):
        ts = candles.times[i]
        stamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  {stamp:<22}{candles.open[i]:>12.4f}{candles.high[i]:>12.4f}"
              f"{candles.low[i]:>12.4f}{candles.close[i]:>12.4f}")

    last_ts = candles.times[-1] / 1000
    age_min = (time.time() - last_ts) / 60
    price = exchange.mark_price(symbol)
    print(f"\nالسعر الحالي (mark price): {price}")
    print(f"عمر آخر شمعة: {age_min:.1f} دقيقة")
    if age_min > 90:
        print("⚠️  آخر شمعة قديمة — تأكد من اتصال الإنترنت")

    # ── التحليل الفعلي على هذه البيانات ──
    decision = evaluate(candles, config, symbol=symbol,
                        use_closed_candles=bool(config.get("strategy.use_closed_candles", True)))
    print(f"\n{LINE}")
    print("  التحليل على هذه البيانات الحقيقية")
    print(LINE)
    print(f"\nالرمز: {symbol} | الإطار: {timeframe}")
    print(decision.describe() or "  (لا توجد إشارات من المؤشرات)")
    print(f"\nالقرار: {decision.side or 'لا صفقة'}")

    print(f"\n{LINE}")
    print("  النتيجة")
    print(LINE)
    print("\n✅ تحليل الشموع يتم على بيانات حقيقية مُستلمة من API المنصة الآن.")
    if testnet:
        print("ℹ️  أنت على التيستنت: الأسعار من سوق Binance التجريبي، والأموال وهمية.")
        print("   للأسعار والأموال الحقيقية: TESTNET=false في ملف .env (مع مسؤوليتك).")
    if dry_run:
        print("ℹ️  وضع المحاكاة مُفعّل: التحليل حقيقي لكن لا تُرسل أي أوامر.")
    else:
        print("ℹ️  وضع المحاكاة معطّل: عند تأكيدك للإشارة يُرسل أمر فعلي للمنصة.")
    print("\n(البيانات الاصطناعية توجد فقط في scripts/demo_scan.py والاختبارات،")
    print(" ولا تُستخدم إطلاقاً عند تشغيل main.py)")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
