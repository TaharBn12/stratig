"""تحميل الإعدادات (config.yaml) والأسرار (.env)."""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_CONFIG: dict[str, Any] = {
    "exchange": {"name": "binance", "testnet": True},
    "strategy": {
        "timeframe": "15m",
        "candles": 500,
        "use_closed_candles": True,
        "require_both": True,
        "rsi": {"enabled": True, "period": 14, "oversold": 30, "overbought": 70, "lookback": 3},
        "williams_r": {
            "enabled": True,
            "lbp": 24,
            "ema_window": 24,
            "extreme_oversold": -99.5,
            "extreme_overbought": -0.5,
            "oversold": -75,
            "overbought": -25,
        },
    },
    "trade": {
        "order_type": "market",
        "qty_usdt": 50,
        "leverage": 10,
        "margin_mode": "isolated",
        "take_profit_pct": 0.012,
        "stop_loss_pct": 0.009,
        "tp_trigger": "mark_price",
    },
    "risk": {
        "max_positions": 5,
        "min_notional": 20,
        "daily_max_trades": 0,
        "daily_max_loss_usdt": 0,
    },
    "scanner": {
        "autostart": True,
        "interval_seconds": 120,
        "symbols_source": "auto",
        "top_n": 40,
        "manual_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
        "exclude": ["USDCUSDT", "FDUSDUSDT"],
        "cooldown_seconds": 1800,
        "signal_ttl_seconds": 900,
        "request_delay": 0.2,
        "notify_no_signal": False,
    },
    "execution": {"mode": "manual"},
    "safety": {"dry_run": False},
    "telegram": {"notify_startup": True, "notify_scan_summary": False, "language": "ar"},
}


def deep_merge(base: dict, override: dict) -> dict:
    """دمج متكرر: قيم override تطغى على base."""
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """وصول بسيط للإعدادات عبر مسارات نقطية: cfg.get('trade.take_profit_pct')."""

    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self._data = deep_merge(DEFAULT_CONFIG, data or {})
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH

    # ---------- تحميل / حفظ ----------
    @classmethod
    def load(cls, path: str | Path | None = None, env_path: str | Path | None = None) -> "Config":
        load_dotenv(env_path or DEFAULT_ENV_PATH, override=False)
        cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
        data: dict[str, Any] = {}
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        cfg = cls(data, cfg_path)
        cfg._apply_env_overrides()
        return cfg

    def _apply_env_overrides(self) -> None:
        """متغيرات البيئة تطغى على الملف (مفيد في Docker)."""
        name = os.getenv("EXCHANGE")
        if name:
            self.set("exchange.name", name.strip().lower())
        testnet = os.getenv("TESTNET")
        if testnet is not None:
            self.set("exchange.testnet", testnet.strip().lower() in ("1", "true", "yes", "on"))
        dry = os.getenv("DRY_RUN")
        if dry is not None:
            self.set("safety.dry_run", dry.strip().lower() in ("1", "true", "yes", "on"))

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self._data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # ---------- وصول ----------
    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        node = self._data
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Config exchange={self.get('exchange.name')} testnet={self.get('exchange.testnet')}>"


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError:
            continue
    return ids


class Secrets:
    """الأسرار تُقرأ من البيئة فقط (.env)."""

    def __init__(
        self,
        telegram_token: str = "",
        chat_ids: Iterable[int] = (),
        binance_key: str = "",
        binance_secret: str = "",
        bybit_key: str = "",
        bybit_secret: str = "",
        confirm_live: bool = False,
    ):
        self.telegram_token = telegram_token
        self.chat_ids = list(chat_ids)
        self.binance_key = binance_key
        self.binance_secret = binance_secret
        self.bybit_key = bybit_key
        self.bybit_secret = bybit_secret
        self.confirm_live = confirm_live

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "Secrets":
        load_dotenv(env_path or DEFAULT_ENV_PATH, override=False)
        return cls(
            telegram_token=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(),
            chat_ids=_parse_ids(os.getenv("TELEGRAM_CHAT_IDS")),
            binance_key=(os.getenv("BINANCE_API_KEY") or "").strip(),
            binance_secret=(os.getenv("BINANCE_API_SECRET") or "").strip(),
            bybit_key=(os.getenv("BYBIT_API_KEY") or "").strip(),
            bybit_secret=(os.getenv("BYBIT_API_SECRET") or "").strip(),
            confirm_live=(os.getenv("CONFIRM_LIVE_TRADING") or "0").strip().lower() in ("1", "true", "yes"),
        )

    def creds(self, exchange: str, testnet: bool) -> tuple[str, str]:
        """يرجع (api_key, api_secret) المناسبين للمنصة والشبكة."""
        ex = (exchange or "binance").lower()
        if ex == "binance":
            if testnet:
                return (
                    os.getenv("BINANCE_TESTNET_API_KEY", "") or self.binance_key,
                    os.getenv("BINANCE_TESTNET_API_SECRET", "") or self.binance_secret,
                )
            return self.binance_key, self.binance_secret
        if ex == "bybit":
            if testnet:
                return (
                    os.getenv("BYBIT_TESTNET_API_KEY", "") or self.bybit_key,
                    os.getenv("BYBIT_TESTNET_API_SECRET", "") or self.bybit_secret,
                )
            return self.bybit_key, self.bybit_secret
        return "", ""

    def valid(self) -> tuple[bool, str]:
        if not self.telegram_token:
            return False, "TELEGRAM_BOT_TOKEN غير مضبوط في ملف .env"
        return True, ""
