"""مصنع المنصات: يختار المحوّل المناسب حسب الإعدادات."""
from __future__ import annotations

import logging

from ..config import Config
from .base import ExchangeBase

log = logging.getLogger(__name__)


def build_exchange(config: Config, secrets) -> ExchangeBase:
    """ينشئ كائن المنصة من (config.toml + .env)."""
    name = str(config.get("exchange.name", "binance")).strip().lower()
    testnet = bool(config.get("exchange.testnet", True))
    dry_run = bool(config.get("safety.dry_run", False))
    api_key, api_secret = secrets.creds(name, testnet)

    if not api_key or not api_secret:
        raise RuntimeError(
            f"مفاتيح API غير مضبوطة لـ {name} ({'testnet' if testnet else 'mainnet'}) — راجع ملف .env"
        )

    if name == "binance":
        from .binance_futures import BinanceFutures

        return BinanceFutures(api_key, api_secret, testnet=testnet, dry_run=dry_run)
    if name == "bybit":
        from .bybit import BybitFutures

        return BybitFutures(api_key, api_secret, testnet=testnet, dry_run=dry_run)
    raise RuntimeError(f"منصة غير مدعومة: {name} (المدعوم: binance, bybit)")


__all__ = ["build_exchange", "ExchangeBase"]
