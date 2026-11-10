"""يفحص أن كل صفقة مفتوحة عليها وقف خسارة وجني أرباح فعليان على المنصة.

    .venv\\Scripts\\python.exe scripts\\check_protection.py        (ويندوز)
    .venv/bin/python scripts/check_protection.py                 (لينكس/ماك)

السبب: نقلت Binance الأوامر الشرطية (STOP_MARKET / TAKE_PROFIT_MARKET) من
`POST /fapi/v1/order` إلى `POST /fapi/v1/algoOrder` بتاريخ 2025-12-09.
أي كود قديم يرسلها للنقطة القديمة يحصل على:

    (400, -4120, 'Order type not supported for this endpoint.
     Please use the Algo Order API endpoints instead.')

فتُفتح الصفقة بلا حماية. هذا السكربت يقرأ الحساب فعلياً ويخبرك إن كانت
كل صفقة محمية أم لا.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stratig.config import Config, Secrets  # noqa: E402
from stratig.exchanges import build_exchange  # noqa: E402

LINE = "═" * 66

AR_TYPE = {
    "STOP_MARKET": "وقف خسارة",
    "TAKE_PROFIT_MARKET": "جني أرباح",
    "STOP": "وقف خسارة (limit)",
    "TAKE_PROFIT": "جني أرباح (limit)",
    "TRAILING_STOP_MARKET": "وقف متحرك",
}


def main() -> int:
    config = Config.load()
    secrets = Secrets.from_env()

    print(LINE)
    print("  فحص حماية الصفقات المفتوحة (وقف خسارة + جني أرباح)")
    print(LINE)

    try:
        exchange = build_exchange(config, secrets)
    except Exception as err:
        print(f"\n❌ {err}")
        return 1

    url = getattr(exchange, "api_url", None) or "غير معروف"
    print(f"\nالمنصة : {exchange.name}")
    print(f"الرابط : {url}")
    print(f"الشبكة : {'تيستنت 🧪' if exchange.testnet else 'حقيقي 🔴'}")

    has_algo = callable(getattr(exchange, "open_algo_orders", None))
    if not has_algo:
        print("\nℹ️  هذه المنصة لا تستخدم نقاط Algo — سأعرض الصفقات فقط.")

    # ── الأوامر الشرطية المفتوحة ──
    algos: list[dict] = []
    if has_algo:
        print(f"\n{LINE}")
        print("  الأوامر الشرطية المفتوحة (من /fapi/v1/openAlgoOrders)")
        print(LINE)
        try:
            algos = exchange.open_algo_orders()
        except Exception as err:
            print(f"\n❌ تعذّر جلب الأوامر الشرطية: {err}")
            print("   تحقق من صلاحيات المفتاح (Enable Futures) ومن .env")
            return 1
        if not algos:
            print("\nلا توجد أوامر شرطية مفتوحة.")
        else:
            for order in algos:
                otype = str(order.get("orderType") or order.get("type") or "?")
                print(
                    f"  • {order.get('symbol'):<14} {AR_TYPE.get(otype, otype):<18}"
                    f" عند {order.get('triggerPrice')} | algoId {order.get('algoId')}"
                )

    by_symbol: dict[str, set[str]] = {}
    for order in algos:
        otype = str(order.get("orderType") or order.get("type") or "")
        by_symbol.setdefault(str(order.get("symbol")), set()).add(otype)

    # ── الصفقات المفتوحة ──
    print(f"\n{LINE}")
    print("  الصفقات المفتوحة")
    print(LINE)
    try:
        positions = exchange.positions()
    except Exception as err:
        print(f"\n❌ تعذّر جلب الصفقات: {err}")
        return 1

    if not positions:
        print("\nلا توجد صفقات مفتوحة — لا شيء لفحصه. ✅")
        return 0

    unprotected = 0
    for pos in positions:
        types = by_symbol.get(pos.symbol, set())
        has_sl = bool(types & {"STOP_MARKET", "STOP"})
        has_tp = bool(types & {"TAKE_PROFIT_MARKET", "TAKE_PROFIT"})
        sl_mark = "✅" if has_sl else "❌"
        tp_mark = "✅" if has_tp else "❌"
        print(
            f"\n  {pos.symbol} — {'شراء 🟢' if pos.side == 'buy' else 'بيع 🔴'}"
            f" | الكمية {pos.size:g} | الدخول {pos.entry_price:g} | الآن {pos.mark_price:g}"
        )
        print(f"     وقف الخسارة: {sl_mark}     جني الأرباح: {tp_mark}")
        if not has_sl:
            unprotected += 1

    print(f"\n{LINE}")
    print("  النتيجة")
    print(LINE)
    if unprotected:
        print(f"\n❌ يوجد {unprotected} صفقة بلا وقف خسارة على المنصة!")
        print("   أغلقها يدوياً أو أعد تشغيل البوت بعد تحديثه:")
        print(r"     git pull && .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
    else:
        print("\n✅ كل صفقة مفتوحة عليها وقف خسارة مسجَّل في المنصة.")
    print(LINE)
    return 0 if not unprotected else 2


if __name__ == "__main__":
    sys.exit(main())
