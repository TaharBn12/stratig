"""نقطة الدخول:  python main.py

أمثلة:
    python main.py                # تشغيل البوت
    python main.py --check        # فحص المفاتيح والاتصال بالمنصة فقط
    python main.py --dry-run      # محاكاة: لا تُرسل أوامر حقيقية
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from stratig.bot.telegram_bot import TelegramBot
from stratig.config import Config, Secrets
from stratig.exchanges import build_exchange
from stratig.logging_setup import setup_logging
from stratig.services.trader import Trader

log = logging.getLogger("stratig")


def check_connection(config: Config, secrets: Secrets) -> int:
    """فحص المفاتيح والاتصال — بدون تليجرام."""
    name = str(config.get("exchange.name", "binance")).lower()
    testnet = bool(config.get("exchange.testnet", True))
    try:
        exchange = build_exchange(config, secrets)
    except Exception as err:
        print(f"❌ {err}")
        suffix = "_TESTNET_" if testnet else "_"
        print(f"   املأ هذين المتغيرين في ملف .env:")
        print(f"   {name.upper()}{suffix}API_KEY=...")
        print(f"   {name.upper()}{suffix}API_SECRET=...")
        return 1
    print(f"\nالمنصة: {exchange.name}  ({'تيستنت' if exchange.testnet else 'حقيقي'})")
    try:
        bal = exchange.balance()
        print(f"✅ الاتصال ناجح | الرصيد: {bal.total} USDT | المتاح: {bal.available} USDT")
    except Exception as err:
        print(f"❌ فشل الاتصال: {err}")
        return 1

    try:
        symbols = exchange.usdt_symbols(
            top_n=int(config.get("scanner.top_n", 40)),
            exclude=tuple(config.get("scanner.exclude") or ()),
        )
        print(f"✅ عدد الرموز المتاحة: {len(symbols)} — أول 10: {symbols[:10]}")
    except Exception as err:
        print(f"⚠️  تعذّر جلب الرموز: {err}")

    try:
        info = exchange.symbol_info(symbols[0] if symbols else "BTCUSDT")
        print(f"✅ مثال فلاتر {info.symbol}: tick={info.tick_size} step={info.step_size} "
              f"minNotional={info.min_notional}")
    except Exception as err:
        print(f"⚠️  تعذّر جلب فلاتر الرمز: {err}")

    try:
        df = exchange.klines(symbols[0] if symbols else "BTCUSDT",
                             str(config.get("strategy.timeframe", "15m")), 200)
        print(f"✅ الشموع: {len(df)} صف — آخر إغلاق: {df.Close.iloc[-1]}")
    except Exception as err:
        print(f"⚠️  تعذّر جلب الشموع: {err}")

    try:
        positions = exchange.positions()
        print(f"✅ الصفقات المفتوحة: {len(positions)}")
    except Exception as err:
        print(f"⚠️  تعذّر جلب الصفقات: {err}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="بوت تليجرام لتداول العقود الآجلة")
    parser.add_argument("--config", default=os.getenv("STRATIG_CONFIG", "config.toml"))
    parser.add_argument("--env", default=os.getenv("STRATIG_ENV", ".env"))
    parser.add_argument("--check", action="store_true", help="فحص الاتصال بالمنصة فقط")
    parser.add_argument("--dry-run", action="store_true", help="محاكاة بدون أوامر حقيقية")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    config = Config.load(args.config, args.env)
    secrets = Secrets.from_env(args.env)
    if args.dry_run:
        config.set("safety.dry_run", True)
    setup_logging(args.log_level)

    if args.check:
        return check_connection(config, secrets)

    # ── أمان: التداول الحقيقي يحتاج تأكيداً صريحاً ──
    if not bool(config.get("exchange.testnet", True)) and not secrets.confirm_live:
        log.error(
            "التداول الحقيقي موقوف للحماية. لتشغيله ضع CONFIRM_LIVE_TRADING=1 في ملف .env "
            "وتأكد أنك تتحمّل المسؤولية كاملة."
        )
        return 2

    ok, reason = secrets.valid()
    if not ok:
        log.error(reason)
        return 2

    try:
        exchange = build_exchange(config, secrets)
    except Exception as err:
        log.error(str(err))
        return 2

    trader = Trader(config, exchange)
    bot = TelegramBot(secrets, config, trader)
    log.info("الإعدادات: %s | الوضع: %s | المحاكاة: %s",
             config.get("exchange.name"), config.get("execution.mode"),
             config.get("safety.dry_run"))
    bot.run()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nتم الإيقاف.")
