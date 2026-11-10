"""تحميل الإعدادات (config.toml) والأسرار (.env).

ملاحظة مهمة: الإعدادات بصيغة **TOML** (المكتبة القياسية `tomllib` في بايثون 3.11+)
حتى لا نحتاج أي مكتبة خارجية تحتاج مصنّف C++ على ويندوز (مثل PyYAML).
"""
from __future__ import annotations

import logging
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from .utils import (
    ALLOWED_TIMEFRAMES,
    DEFAULT_TIMEFRAME,
    is_supported_timeframe,
    normalize_timeframe,
)

log = logging.getLogger(__name__)

try:  # بايثون 3.11+
    import tomllib
except ModuleNotFoundError:  # بايثون أقدم: tomli الاختياري
    tomllib = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.toml"
LEGACY_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_CONFIG: dict[str, Any] = {
    "exchange": {"name": "binance", "testnet": True},
    "strategy": {
        "name": "rsi_williams",          # rsi_williams | scalping_i
        "timeframe": "15m",
        "candles": 500,
        "use_closed_candles": True,
        "require_both": True,
        # ثوابت استراتيجية الدفتر 01_Strategy_Scalping_Modified_I (كما هي)
        "scalping_i": {
            "ema_slow": 50,
            "ema_fast": 30,
            "rsi_length": 10,
            "bb_length": 15,
            "bb_std": 1.5,
            "bb_ddof": 1,
            "atr_length": 7,
            "atr_mode": "rma",
            "backcandles": 7,
            "sl_coef": 1.1,
            "tp_sl_ratio": 1.5,
        },
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
    "exit": {
        "mode": "percent",              # percent | atr
        "atr": {"length": 7, "sl_coef": 1.1, "tp_ratio": 1.5},
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
        "max_signals_per_scan": 5,
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


# ═════════════════════════ كاتب TOML بسيط ═════════════════════════
def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _toml_key(key: str) -> str:
    clean = key.replace("_", "").replace("-", "")
    return key if clean.isalnum() else _toml_scalar(key)


def toml_dumps(data: dict[str, Any]) -> str:
    """يحوّل القاموس إلى نص TOML (يكفي احتياجات ملف الإعدادات)."""
    lines: list[str] = []

    def emit(table: dict[str, Any], prefix: str = "") -> None:
        simple, nested = [], []
        for key, value in table.items():
            (nested if isinstance(value, dict) else simple).append((key, value))
        for key, value in simple:
            rendered = (
                "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
                if isinstance(value, (list, tuple))
                else _toml_scalar(value)
            )
            lines.append(f"{_toml_key(key)} = {rendered}")
        for key, value in nested:
            lines.append("")
            lines.append(f"[{prefix}{_toml_key(key)}]")
            emit(value, f"{prefix}{_toml_key(key)}.")

    emit(data)
    return "\n".join(lines).rstrip() + "\n"


# ═════════════════════════ الإعدادات ═════════════════════════
class Config:
    """وصول بسيط للإعدادات عبر مسارات نقطية: cfg.get('trade.take_profit_pct')."""

    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self._data = deep_merge(DEFAULT_CONFIG, data or {})
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self._mtime: float | None = None
        # قيم م ثبَّتة من سطر الأوامر (مثل --dry-run) — لا يطغى عليها إعادة التحميل
        self._pinned: dict[str, Any] = {}

    # ---------- تحميل / حفظ ----------
    @classmethod
    def load(cls, path: str | Path | None = None, env_path: str | Path | None = None) -> "Config":
        load_dotenv(env_path or DEFAULT_ENV_PATH, override=False)
        cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH

        if not cfg_path.exists() and path is None and LEGACY_CONFIG_PATH.exists():
            cfg_path = LEGACY_CONFIG_PATH  # توافق مع النسخة القديمة (config.yaml)

        # config.toml ملف محلي غير مُتتبَّع في git — إن غاب ننسخه من المثال
        if not cfg_path.exists() and path is None and EXAMPLE_CONFIG_PATH.exists():
            try:
                shutil.copyfile(EXAMPLE_CONFIG_PATH, cfg_path)
                log.info("أنشأتُ %s من config.example.toml", cfg_path.name)
            except OSError as err:  # pragma: no cover
                log.warning("تعذّر إنشاء %s: %s", cfg_path.name, err)

        data: dict[str, Any] = {}
        if cfg_path.exists():
            data = cls._read_file(cfg_path)
        cfg = cls(data, cfg_path)
        cfg._apply_env_overrides()
        try:
            cfg._mtime = cfg_path.stat().st_mtime if cfg_path.exists() else None
        except OSError:  # pragma: no cover
            cfg._mtime = None
        return cfg

    @staticmethod
    def _read_file(path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        if suffix in (".toml",):
            if tomllib is None:
                print("⚠️  بايثون أقدم من 3.11 ولا توجد مكتبة tomli — سيتم استخدام الإعدادات الافتراضية")
                return {}
            with open(path, "rb") as fh:
                return tomllib.load(fh) or {}
        if suffix in (".yaml", ".yml"):
            try:
                import yaml  # اختياري: فقط لملفات قديمة بصيغة YAML
            except ImportError:
                print(f"⚠️  ملف {path.name} بصيغة YAML ومكتبة PyYAML غير مثبتة — "
                      f"سيتم استخدام الإعدادات الافتراضية (أو أنشئ config.toml)")
                return {}
            with open(path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
        print(f"⚠️  صيغة غير مدعومة لملف الإعدادات: {path.name}")
        return {}

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

    def _save_quietly(self) -> None:
        """حفظ دون إيقاف البوت إن تعذّر الكتابة (ملف للقراءة فقط مثلاً)."""
        try:
            self.save()
        except OSError as err:  # pragma: no cover
            log.warning("تعذّر حفظ %s: %s", self.path, err)

    def ensure_timeframe(self) -> str:
        """يتحقق من strategy.timeframe ويُصحّحه بدل إيقاف البوت.

        يُرجع ملاحظة جاهزة للعرض في السجل (أو نصاً فارغاً إن كانت القيمة سليمة).
        """
        raw = self.get("strategy.timeframe", DEFAULT_TIMEFRAME)
        tf = normalize_timeframe(raw)
        if is_supported_timeframe(tf):
            if tf != str(raw):
                self.set("strategy.timeframe", tf)
                self._save_quietly()          # نثبّت التصحيح حتى لا يتكرر كل إقلاع
                return f"تم توحيد الإطار الزمني: {raw} → {tf}"
            return ""
        # قيمة لا تقبلها أي منصة → نُصحّحها ولا نوقف البوت
        self.set("strategy.timeframe", DEFAULT_TIMEFRAME)
        self._save_quietly()
        return (
            f"الإطار الزمني \"{raw}\" غير مدعوم — تم استخدام "
            f"{DEFAULT_TIMEFRAME} بدلاً منه واستمر البوت. "
            f"المسموح: {', '.join(ALLOWED_TIMEFRAMES)} — غيّره بـ /tf 4h"
        )

    def pin(self, path: str, value: Any) -> None:
        """يثبّت قيمة من سطر الأوامر بحيث تبقى حتى بعد إعادة تحميل الملف."""
        self._pinned[path] = value
        self.set(path, value)

    def reload(self) -> bool:
        """يعيد قراءة الملف من القرص — يلتقط التعديلات اليدوية أثناء عمل البوت.

        يُرجع True إن تغيّر الملف فعلاً. لا يطغى على القيم المثبَّتة (--dry-run)
        ولا على متغيرات البيئة.
        """
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if self._mtime is not None and mtime == self._mtime:
            return False

        data: dict[str, Any] = {}
        if self.path.exists():
            try:
                data = self._read_file(self.path)
            except Exception as err:  # ملف نصف مكتوب → نتجاهل هذه الدورة
                log.warning("تعذّر قراءة %s: %s", self.path, err)
                return False
        self._data = deep_merge(DEFAULT_CONFIG, data)
        self._apply_env_overrides()
        for path, value in self._pinned.items():
            self.set(path, value)
        self._mtime = mtime
        return True

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(toml_dumps(self._data))
        try:
            self._mtime = self.path.stat().st_mtime   # لا نُعيد تحميل ما كتبناه للتو
        except OSError:  # pragma: no cover
            pass

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
