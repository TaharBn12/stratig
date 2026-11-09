"""محوّل Bybit (عقود linear USDT) — مبني على pybit مثل كودك الأصلي.

مُبقًى عليه حتى تستطيع الرجوع إلى Bybit في أي لحظة بتغيير:
    exchange.name = "bybit"   في ملف config.toml

ملاحظة: Bybit يُعيد الشموع من الأحدث إلى الأقدم → نعكسها ليصبح
آخر صف هو أحدث شمعة (نفس منطق Derivatives.py).
"""
from __future__ import annotations

import logging

from ..data import Candles, make_candles
from .base import (
    BUY,
    SELL,
    Balance,
    ExchangeBase,
    ExchangeError,
    OrderResult,
    Position,
    SymbolInfo,
    interval_to_minutes,
    round_step,
)

log = logging.getLogger(__name__)


class BybitFutures(ExchangeBase):
    name = "bybit"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        category: str = "linear",
        dry_run: bool = False,
    ):
        from pybit.unified_trading import HTTP

        self.category = category
        self.testnet = bool(testnet)
        self.dry_run = bool(dry_run)
        self.name = "bybit-testnet" if testnet else "bybit"
        self.session = HTTP(api_key=api_key or "", api_secret=api_secret or "", testnet=testnet)

    # ═══════════════════ بيانات السوق ═══════════════════
    def symbol_info(self, symbol: str) -> SymbolInfo:
        resp = self.session.get_instruments_info(category=self.category, symbol=symbol)["result"]["list"]
        if not resp:
            raise ExchangeError(f"الرمز {symbol} غير موجود على Bybit")
        item = resp[0]
        tick = str(item["priceFilter"]["tickSize"])
        step = str(item["lotSizeFilter"]["qtyStep"])
        return SymbolInfo(
            symbol=symbol,
            price_precision=len(tick.split(".")[1]) if "." in tick else 0,
            qty_precision=len(step.split(".")[1]) if "." in step else 0,
            tick_size=float(tick),
            step_size=float(step),
            min_qty=float(item["lotSizeFilter"].get("minOrderQty", 0) or 0),
            min_notional=float(item["lotSizeFilter"].get("minOrderAmt", 0) or 0),
        )

    def usdt_symbols(self, top_n: int = 40, exclude: tuple[str, ...] = ()) -> list[str]:
        resp = self.session.get_tickers(category=self.category)["result"]["list"]
        blocked = {str(s).upper() for s in (exclude or ())}
        rows = []
        for elem in resp:
            sym = elem.get("symbol", "")
            if "USDT" not in sym or "USDC" in sym or sym in blocked:
                continue
            try:
                rows.append((sym, float(elem.get("turnover24h", 0) or 0)))
            except (TypeError, ValueError):
                rows.append((sym, 0.0))
        rows.sort(key=lambda x: x[1], reverse=True)
        out = [s for s, _ in rows]
        return out[:top_n] if top_n and top_n > 0 else out

    def klines(self, symbol: str, interval: str = "15m", limit: int = 500) -> Candles:
        raw = self.session.get_kline(
            category=self.category,
            symbol=symbol,
            interval=interval_to_minutes(interval),
            limit=int(limit),
        )["result"]["list"]
        return make_candles(raw, reverse=True)   # Bybit: الأحدث أولاً

    def mark_price(self, symbol: str) -> float:
        resp = self.session.get_tickers(category=self.category, symbol=symbol)["result"]["list"]
        return float(resp[0].get("markPrice") or resp[0]["lastPrice"])

    # ═══════════════════ الحساب ═══════════════════
    def balance(self) -> Balance:
        resp = self.session.get_wallet_balance(accountType="UNIFIED", coin="USDT")["result"]["list"]
        if not resp:
            raise ExchangeError("تعذّر قراءة رصيد Bybit")
        coin = resp[0]["coin"][0]
        total = float(coin.get("walletBalance", 0) or 0)
        return Balance(
            total=total,
            available=float(coin.get("availableToWithdraw", total) or total),
            unrealized=float(coin.get("unrealisedPnl", 0) or 0),
        )

    def positions(self) -> list[Position]:
        resp = self.session.get_positions(category=self.category, settleCoin="USDT")["result"]["list"]
        out: list[Position] = []
        for item in resp:
            try:
                size = float(item.get("size", 0) or 0)
            except (TypeError, ValueError):
                continue
            if size <= 0:
                continue
            mark = float(item.get("markPrice", 0) or 0)
            entry = float(item.get("avgPrice", 0) or 0)
            pnl = float(item.get("unrealisedPnl", 0) or 0)
            lev = float(item.get("leverage", 1) or 1) or 1.0
            notional = size * mark
            margin = notional / lev if lev else notional
            out.append(
                Position(
                    symbol=item["symbol"],
                    side=BUY if str(item.get("side", "")).lower() == "buy" else SELL,
                    size=size,
                    entry_price=entry,
                    mark_price=mark,
                    pnl=pnl,
                    leverage=lev,
                    margin_type=str(item.get("tradeMode", "")).lower(),
                    notional=notional,
                    roe_pct=(pnl / margin * 100) if margin else 0.0,
                )
            )
        return out

    def recent_pnl(self, limit: int = 50, since_ms: int | None = None) -> float:
        params = {"category": self.category, "limit": int(limit)}
        if since_ms:
            params["startTime"] = int(since_ms)
        resp = self.session.get_closed_pnl(**params)["result"]["list"]
        return round(sum(float(x.get("closedPnl", 0) or 0) for x in resp), 4)

    # ═══════════════════ إعدادات الرمز ═══════════════════
    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self.session.set_leverage(
                category=self.category,
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
        except Exception as err:
            if "110043" not in str(err):
                log.warning("[%s] تعذّر ضبط الرافعة: %s", symbol, err)

    def set_margin_mode(self, symbol: str, margin_mode: str) -> None:
        trade_mode = 1 if str(margin_mode).lower() == "isolated" else 0
        try:
            self.session.switch_margin_mode(
                category=self.category, symbol=symbol, tradeMode=trade_mode
            )
        except Exception as err:
            if "110026" not in str(err):
                log.warning("[%s] تعذّر ضبط نوع الهامش: %s", symbol, err)

    # ═══════════════════ التنفيذ ═══════════════════
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
    ) -> OrderResult:
        side = side.lower()
        info = self.symbol_info(symbol)
        price = self.mark_price(symbol)
        qty = round_step(float(qty_usdt) / price, info.step_size) if price > 0 else 0.0
        if qty < (info.min_qty or info.step_size):
            qty = round_step(info.min_qty or info.step_size, info.step_size)
        if qty <= 0:
            raise ExchangeError(f"الكمية المحسوبة لـ {symbol} صفر")

        tp_price = price * (1 + tp_pct) if side == BUY else price * (1 - tp_pct)
        sl_price = price * (1 - sl_pct) if side == BUY else price * (1 + sl_pct)

        if self.dry_run:
            return OrderResult(
                symbol=symbol, side=side, qty=qty, price=price,
                tp_price=round(tp_price, info.price_precision),
                sl_price=round(sl_price, info.price_precision),
                notional=qty * price, simulated=True,
            )

        self.set_margin_mode(symbol, margin_mode)
        self.set_leverage(symbol, leverage)
        trigger = "MarkPrice" if str(tp_trigger).lower() == "mark_price" else "LastPrice"
        resp = self.session.place_order(
            category=self.category,
            symbol=symbol,
            side="Buy" if side == BUY else "Sell",
            orderType="Market",
            qty=qty,
            takeProfit=round(tp_price, info.price_precision),
            stopLoss=round(sl_price, info.price_precision),
            tpTriggerBy=trigger,
            slTriggerBy=trigger,
        )
        return OrderResult(
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            order_id=str(resp.get("result", {}).get("orderId", "")),
            tp_price=round(tp_price, info.price_precision),
            sl_price=round(sl_price, info.price_precision),
            notional=qty * price,
            raw=resp,
        )

    def close_position(self, symbol: str) -> OrderResult | None:
        pos = self.get_position(symbol)
        if not pos:
            return None
        try:
            self.session.cancel_all_orders(category=self.category, symbol=symbol)
        except Exception as err:
            log.debug("[%s] لا توجد أوامر معلقة للإلغاء: %s", symbol, err)
        if self.dry_run:
            return OrderResult(symbol=symbol, side=SELL if pos.side == BUY else BUY,
                               qty=pos.size, price=pos.mark_price, simulated=True)
        resp = self.session.place_order(
            category=self.category,
            symbol=symbol,
            side="Sell" if pos.side == BUY else "Buy",
            orderType="Market",
            qty=pos.size,
            reduceOnly=True,
        )
        return OrderResult(
            symbol=symbol,
            side=SELL if pos.side == BUY else BUY,
            qty=pos.size,
            price=pos.mark_price,
            order_id=str(resp.get("result", {}).get("orderId", "")),
            raw=resp,
        )
