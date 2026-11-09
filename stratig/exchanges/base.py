"""واجهة موحّدة لمنصات العقود الآجلة (Binance / Bybit).

كل محوّل (adapter) يطبّق نفس الدوال، حتى يعمل المحرك والبوت مع أي منصة
دون تغيير أي سطر في الاستراتيجية.

ملاحظة مهمة عن ترتيب الشموع:
    كل الدوال تُرجع DataFrame بحيث أن ``df.iloc[-1]`` هي أحدث شمعة
    و``df.iloc[0]`` هي الأقدم — مثل الكود الأصلي في Derivatives.py
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

from ..data import Candles, make_candles

BUY = "buy"
SELL = "sell"


class ExchangeError(Exception):
    """أي خطأ من المنصة أو من طبقة التحويل."""


KLINE_COLUMNS = ["Time", "Open", "High", "Low", "Close", "Volume", "Turnover"]


@dataclass
class SymbolInfo:
    symbol: str
    price_precision: int = 8
    qty_precision: int = 8
    tick_size: float = 0.0
    step_size: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0


@dataclass
class Position:
    symbol: str
    side: str                 # buy (Long) | sell (Short)
    size: float
    entry_price: float = 0.0
    mark_price: float = 0.0
    pnl: float = 0.0          # ربح/خسارة غير محققة
    leverage: float = 1.0
    margin_type: str = ""
    notional: float = 0.0
    roe_pct: float = 0.0      # العائد على الهامش %


@dataclass
class Balance:
    total: float = 0.0
    available: float = 0.0
    unrealized: float = 0.0


@dataclass
class OrderResult:
    symbol: str
    side: str
    qty: float
    price: float = 0.0
    order_id: str = ""
    tp_price: float | None = None
    sl_price: float | None = None
    notional: float = 0.0
    simulated: bool = False
    raw: Any = field(default=None, repr=False)


# ───────────────────────── أدوات مساعدة ─────────────────────────
def round_step(value: float, step: float) -> float:
    """تقريب الكمية/السعر حسب خطوة المنصة (دائماً للأسفل لتجنّب تجاوز الهامش)."""
    if not step or step <= 0:
        return float(value)
    val = Decimal(str(value))
    stp = Decimal(str(step))
    return float((val / stp).quantize(Decimal("1"), rounding=ROUND_DOWN) * stp)


def fmt_num(value: float, precision: int) -> str:
    """تنسيق رقم كنص بالدقة المطلوبة (المنصات ترفض الأرقام بصيغة علمية)."""
    precision = max(0, int(precision))
    return f"{float(value):.{precision}f}"


def normalize_interval(interval: Any) -> str:
    """15 أو '15' → '15m' (Binance)."""
    text = str(interval).strip().lower()
    if text.isdigit():
        return f"{int(text)}m"
    return text


def interval_to_minutes(interval: Any) -> int:
    """'15m' → 15 (مستخدم في Bybit)."""
    text = str(interval).strip().lower()
    if text.isdigit():
        return int(text)
    units = {"m": 1, "h": 60, "d": 60 * 24, "w": 60 * 24 * 7}
    if text and text[-1] in units:
        try:
            return int(text[:-1]) * units[text[-1]]
        except ValueError:
            return 15
    return 15


class ExchangeBase(ABC):
    """الواجهة المشتركة — كل منصة تطبّق هذه الدوال."""

    name: str = "base"
    testnet: bool = True

    # ---------- بيانات السوق ----------
    @abstractmethod
    def klines(self, symbol: str, interval: str = "15m", limit: int = 500) -> Candles: ...

    @abstractmethod
    def mark_price(self, symbol: str) -> float: ...

    @abstractmethod
    def symbol_info(self, symbol: str) -> SymbolInfo: ...

    @abstractmethod
    def usdt_symbols(self, top_n: int = 40, exclude: tuple[str, ...] = ()) -> list[str]: ...

    # ---------- الحساب ----------
    @abstractmethod
    def balance(self) -> Balance: ...

    @abstractmethod
    def positions(self) -> list[Position]: ...

    @abstractmethod
    def recent_pnl(self, limit: int = 50, since_ms: int | None = None) -> float: ...

    # ---------- تنفيذ ----------
    @abstractmethod
    def open_market(
        self,
        symbol: str,
        side: str,
        qty_usdt: float,
        tp_pct: float,
        sl_pct: float,
        leverage: int = 10,
        margin_mode: str = "isolated",
        tp_trigger: str = "mark_price",
        min_notional: float = 0.0,
    ) -> OrderResult: ...

    @abstractmethod
    def close_position(self, symbol: str) -> OrderResult | None: ...

    # ---------- إعدادات الرمز ----------
    def set_leverage(self, symbol: str, leverage: int) -> None:
        """اختياري — يُتجاهل إن لم تدعمه المنصة."""

    def set_margin_mode(self, symbol: str, margin_mode: str) -> None:
        """اختياري."""

    # ---------- راحة ----------
    def open_position_symbols(self) -> set[str]:
        try:
            return {p.symbol for p in self.positions()}
        except Exception:
            return set()

    def get_position(self, symbol: str) -> Position | None:
        for pos in self.positions():
            if pos.symbol == symbol:
                return pos
        return None

    def ping(self) -> bool:
        try:
            return self.balance() is not None
        except Exception:
            return False

    def __repr__(self) -> str:  # pragma: no cover
        net = "testnet" if self.testnet else "mainnet"
        return f"<{self.__class__.__name__} {net}>"
