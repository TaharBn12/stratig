"""محوّل Binance USDT-M Futures (يدعم التيستنت رسمياً).

التيستنت: https://testnet.binancefuture.com
    - أنشئ حساباً بفيسبوك/جوجل ثم من Hamburger menu → API Key
    - المفاتيح تختلف عن مفاتيح المنصة الحقيقية

ترتيب الشموع في Binance: الأقدم أولاً → لا نعكس المصفوفة.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..compat import import_module_safely
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
    fmt_num,
    normalize_interval,
    round_step,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# تغيير جوهري في Binance (ساري منذ 2025-12-09):
# الأوامر الشرطية (STOP / STOP_MARKET / TAKE_PROFIT / TAKE_PROFIT_MARKET /
# TRAILING_STOP_MARKET) انتقلت من POST /fapi/v1/order إلى نقاط Algo.
# إرسالها للنقطة القديمة يُرجع الخطأ -4120:
#   "Order type not supported for this endpoint.
#    Please use the Algo Order API endpoints instead."
# النقاط الجديدة:
#   POST   /fapi/v1/algoOrder      (algoType=CONDITIONAL, triggerPrice)
#   GET    /fapi/v1/openAlgoOrders
#   DELETE /fapi/v1/algoOrder      (algoId)
# ملاحظة: اسم حقل سعر الإطلاق تغيّر من stopPrice إلى triggerPrice.
# ─────────────────────────────────────────────────────────────────────
ALGO_ORDER_PATH = "/fapi/v1/algoOrder"
OPEN_ALGO_PATH = "/fapi/v1/openAlgoOrders"

# أكواد أخطاء بنانس التي يمكن تجاهلها بأمان
IGNORED_ERRORS = {
    -4046: "نوع الهامش مضبوط مسبقاً",
    -4028: "الرافعة مضبوطة مسبقاً",
    -4059: "وضع الصفقات مضبوط مسبقاً",
    -4164: "الرمز غير مدرج (MinNotional)",
}


class BinanceFutures(ExchangeBase):
    name = "binance"
    MAINNET_URL = "https://fapi.binance.com"
    TESTNET_URL = "https://testnet.binancefuture.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        recv_window: int = 10000,
        dry_run: bool = False,
    ):
        from binance.error import ClientError  # noqa: F401  (يُستخدم في except)

        UMFutures = import_module_safely("binance.um_futures", "UMFutures")

        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.testnet = bool(testnet)
        self.dry_run = bool(dry_run)
        self.recv_window = int(recv_window)
        self.name = "binance-testnet" if testnet else "binance"
        self.client = UMFutures(
            key=self.api_key,
            secret=self.api_secret,
            base_url=self.TESTNET_URL if testnet else self.MAINNET_URL,
        )
        self.api_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self._info: dict | None = None
        self._info_ts = 0.0
        self._dual_side: bool | None = None

    # ═══════════════════ أدوات داخلية ═══════════════════
    def _rw(self) -> dict:
        return {"recvWindow": self.recv_window}

    def _ignorable(self, err: Exception) -> bool:
        code = getattr(err, "error_code", None)
        return code in IGNORED_ERRORS

    def exchange_info(self, force: bool = False) -> dict:
        """معلومات كل الرموز مع تخزين مؤقت لساعة."""
        now = time.time()
        if force or not self._info or now - self._info_ts > 3600:
            self._info = self.client.exchange_info()
            self._info_ts = now
        return self._info or {"symbols": []}

    # ═══════════════════ بيانات السوق ═══════════════════
    def symbol_info(self, symbol: str) -> SymbolInfo:
        for item in self.exchange_info().get("symbols", []):
            if item.get("symbol") != symbol:
                continue
            tick_size = step_size = min_qty = min_notional = 0.0
            market_seen = False
            for flt in item.get("filters", []):
                ftype = flt.get("filterType")
                if ftype == "PRICE_FILTER":
                    tick_size = float(flt.get("tickSize", 0) or 0)
                elif ftype == "LOT_SIZE" and not market_seen:
                    step_size = float(flt.get("stepSize", 0) or 0)
                    min_qty = float(flt.get("minQty", 0) or 0)
                elif ftype == "MARKET_LOT_SIZE":
                    step_size = float(flt.get("stepSize", 0) or 0)
                    min_qty = float(flt.get("minQty", 0) or 0)
                    market_seen = True
                elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                    min_notional = float(flt.get("notional") or flt.get("minNotional") or 0)
            return SymbolInfo(
                symbol=symbol,
                price_precision=int(item.get("pricePrecision", 8)),
                qty_precision=int(item.get("quantityPrecision", 8)),
                tick_size=tick_size,
                step_size=step_size,
                min_qty=min_qty,
                min_notional=min_notional,
            )
        raise ExchangeError(f"الرمز {symbol} غير موجود على Binance")

    def usdt_symbols(self, top_n: int = 40, exclude: tuple[str, ...] = ()) -> list[str]:
        """أعلى الرموز نشاطاً (حسب حجم التداول 24س) من عقود USDT الدائمة."""
        symbols = {
            s["symbol"]
            for s in self.exchange_info().get("symbols", [])
            if s.get("status") == "TRADING"
            and s.get("quoteAsset") == "USDT"
            and s.get("contractType") == "PERPETUAL"
        }
        volumes: dict[str, float] = {}
        try:
            for ticker in self.client.ticker_24hr_price_change():
                try:
                    volumes[ticker["symbol"]] = float(ticker.get("quoteVolume", 0) or 0)
                except (KeyError, TypeError, ValueError):
                    continue
        except Exception as err:  # السوق قد يفشل مؤقتاً → ترتيب أبجدي
            log.debug("تعذّر جلب أحجام التداول: %s", err)

        ordered = sorted(symbols, key=lambda s: volumes.get(s, 0.0), reverse=True)
        blocked = {str(s).upper() for s in (exclude or ())}
        out = [s for s in ordered if s not in blocked]
        return out[:top_n] if top_n and top_n > 0 else out

    def klines(self, symbol: str, interval: str = "15m", limit: int = 500) -> Candles:
        raw = self.client.klines(
            symbol=symbol, interval=normalize_interval(interval), limit=int(limit), **self._rw()
        )
        return make_candles(raw, reverse=False)   # Binance: الأقدم أولاً

    def mark_price(self, symbol: str) -> float:
        try:
            data = self.client.mark_price(symbol=symbol, **self._rw())
            if isinstance(data, dict):
                return float(data["markPrice"])
            if isinstance(data, list) and data:
                return float(data[0]["markPrice"])
        except Exception as err:
            log.debug("mark_price غير متاح لـ %s (%s) — استخدام lastPrice", symbol, err)
        data = self.client.ticker_price(symbol=symbol)
        return float(data["price"])

    # ═══════════════════ الحساب ═══════════════════
    def balance(self) -> Balance:
        resp = self.client.balance(**self._rw())
        for asset in resp:
            if asset.get("asset") == "USDT":
                total = float(asset.get("balance", 0) or 0)
                available = float(asset.get("availableBalance", total) or total)
                unrealized = float(asset.get("crossUnPnl", 0) or 0)
                return Balance(total=total, available=available, unrealized=unrealized)
        raise ExchangeError("لم يتم العثور على رصيد USDT")

    def positions(self) -> list[Position]:
        resp = self.client.get_position_risk(**self._rw())
        out: list[Position] = []
        for item in resp:
            try:
                size = float(item.get("positionAmt", 0) or 0)
            except (TypeError, ValueError):
                continue
            if abs(size) < 1e-12:
                continue
            entry = float(item.get("entryPrice", 0) or 0)
            mark = float(item.get("markPrice", 0) or 0)
            pnl = float(item.get("unRealizedProfit", 0) or 0)
            lev = float(item.get("leverage", 1) or 1) or 1.0
            notional = abs(size) * mark
            margin = notional / lev if lev else notional
            out.append(
                Position(
                    symbol=item["symbol"],
                    side=BUY if size > 0 else SELL,
                    size=abs(size),
                    entry_price=entry,
                    mark_price=mark,
                    pnl=pnl,
                    leverage=lev,
                    margin_type=str(item.get("marginType", "") or "").lower(),
                    notional=notional,
                    roe_pct=(pnl / margin * 100) if margin else 0.0,
                )
            )
        return out

    def recent_pnl(self, limit: int = 50, since_ms: int | None = None) -> float:
        """مجموع الربح المحقق (REALIZED_PNL) — أو منذ since_ms إن أعطيت."""
        try:
            params: dict[str, Any] = {"incomeType": "REALIZED_PNL", "limit": int(limit)}
            if since_ms:
                params["startTime"] = int(since_ms)
            params.update(self._rw())
            resp = self.client.get_income_history(**params)
            return round(sum(float(x.get("income", 0) or 0) for x in resp), 4)
        except Exception as err:
            log.warning("تعذّر جلب سجل الأرباح: %s", err)
            return 0.0

    # ═══════════════════ إعدادات الرمز ═══════════════════
    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self.client.change_leverage(symbol=symbol, leverage=int(leverage), **self._rw())
        except Exception as err:
            if not self._ignorable(err):
                log.warning("[%s] تعذّر ضبط الرافعة: %s", symbol, err)

    def set_margin_mode(self, symbol: str, margin_mode: str) -> None:
        try:
            self.client.change_margin_type(
                symbol=symbol, marginType=str(margin_mode).upper(), **self._rw()
            )
        except Exception as err:
            if not self._ignorable(err):
                log.warning("[%s] تعذّر ضبط نوع الهامش: %s", symbol, err)

    def _ensure_single_position_mode(self) -> None:
        """نحوّل الحساب إلى وضع one-way (أسهل في الإدارة)."""
        if self._dual_side is not None:
            return
        try:
            resp = self.client.get_position_mode(**self._rw())
            self._dual_side = bool(resp.get("dualSidePosition"))
            if self._dual_side:
                self.client.change_position_mode(dualSidePosition=False, **self._rw())
                self._dual_side = False
                log.info("تم تحويل الحساب إلى وضع One-Way")
        except Exception as err:
            if not self._ignorable(err):
                log.debug("تعذّر قراءة/تعديل وضع الصفقات: %s", err)
            self._dual_side = False

    def _side_extra(self, side: str) -> dict:
        """يضيف positionSide عند العمل في وضع Hedge."""
        if self._dual_side:
            return {"positionSide": "LONG" if side == BUY else "SHORT"}
        return {}

    # ═══════════════════ أوامر Algo (الشرطية) ═══════════════════
    def _signed(self, method: str, path: str, params: dict | None = None) -> Any:
        """نداء REST موقّع — عبر موصّل Binance إن توفّر، وإلا توقيع يدوي."""
        payload: dict[str, Any] = {k: v for k, v in (params or {}).items() if v is not None}
        payload.update(self._rw())
        sign_request = getattr(self.client, "sign_request", None)
        if callable(sign_request):
            return sign_request(method, path, payload)
        return self._sign_manually(method, path, payload)

    def _sign_manually(self, method: str, path: str, payload: dict) -> Any:
        """توقيع HMAC-SHA256 يدوي (احتياط عند غياب sign_request في الموصّل)."""
        import hashlib
        import hmac
        import urllib.parse

        request = import_module_safely("requests", "request")
        params = dict(payload)
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params, doseq=True)
        signature = hmac.new(
            self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        response = request(
            method,
            f"{self.api_url}{path}?{query}&signature={signature}",
            headers={"X-MBX-APIKEY": self.api_key},
            timeout=20,
        )
        try:
            data = response.json()
        except Exception:  # pragma: no cover — ردّ غير JSON
            data = {}
        if int(getattr(response, "status_code", 200) or 200) >= 400:
            raise ExchangeError(
                f"({response.status_code}, {data.get('code')}, {data.get('msg')!r})"
            )
        if isinstance(data, dict) and data.get("code", 0) not in (0, None, "200"):
            raise ExchangeError(f"({data.get('code')}, {data.get('msg')})")
        return data

    def place_conditional_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        trigger_price: float,
        precision: int = 8,
        working_type: str = "CONTRACT_PRICE",
        close_position: bool = True,
        quantity: str | None = None,
        position_side: str | None = None,
        client_algo_id: str | None = None,
    ) -> dict:
        """يضع أمراً شرطياً (وقف خسارة / جني أرباح) على نقطة Algo."""
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "triggerPrice": fmt_num(trigger_price, precision),
            "workingType": working_type,
        }
        if close_position:
            # يُغلق كامل الصفقة عند الإطلاق — لا يجوز إرسال quantity/reduceOnly معه
            params["closePosition"] = "true"
        else:
            params["quantity"] = quantity
            params["reduceOnly"] = "true"   # ممنوع في وضع Hedge
        if position_side:
            params["positionSide"] = position_side
        if client_algo_id:
            params["clientAlgoId"] = str(client_algo_id)[:36]
        return self._signed("POST", ALGO_ORDER_PATH, params)

    def open_algo_orders(self, symbol: str | None = None) -> list[dict]:
        """قائمة الأوامر الشرطية المفتوحة (وقف/هدف) لرمز أو لكل الحساب."""
        payload = {"symbol": symbol} if symbol else {}
        resp = self._signed("GET", OPEN_ALGO_PATH, payload)
        if isinstance(resp, dict):
            orders = resp.get("orders") or []
        else:
            orders = resp or []
        return [o for o in orders if isinstance(o, dict)]

    def cancel_algo_orders(self, symbol: str) -> int:
        """يلغي كل الأوامر الشرطية المفتوحة على الرمز (بعد إغلاق الصفقة)."""
        try:
            orders = self.open_algo_orders(symbol)
        except Exception as err:
            log.debug("[%s] تعذّر جلب أوامر algo المفتوحة: %s", symbol, err)
            return 0
        cancelled = 0
        for order in orders:
            algo_id = order.get("algoId")
            if not algo_id:
                continue
            try:
                self._signed("DELETE", ALGO_ORDER_PATH, {"symbol": symbol, "algoId": algo_id})
                cancelled += 1
            except Exception as err:
                log.warning("[%s] تعذّر إلغاء أمر algo %s: %s", symbol, algo_id, err)
        return cancelled

    # ═══════════════════ التنفيذ ═══════════════════
    def _calc_qty(self, info: SymbolInfo, qty_usdt: float, price: float, min_notional: float) -> float:
        """يحسب الكمية من قيمة الدولار مع احترام stepSize / minQty / minNotional."""
        if price <= 0:
            raise ExchangeError(f"سعر غير صالح لـ {info.symbol}")
        raw = float(qty_usdt) / price
        qty = round_step(raw, info.step_size)
        floor = max(info.min_qty, info.step_size or 0.0)
        if qty < floor:
            qty = round_step(floor, info.step_size) or floor
        min_notional = float(min_notional or info.min_notional or 0.0)
        if min_notional and qty * price < min_notional:
            needed = min_notional / price
            qty = round_step(needed, info.step_size) + (info.step_size or 0.0)
            log.info("[%s] تم رفع الكمية إلى الحد الأدنى %s USDT", info.symbol, min_notional)
        if qty <= 0:
            raise ExchangeError(f"الكمية المحسوبة لـ {info.symbol} صفر — زد trade.qty_usdt")
        return qty

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
        if side not in (BUY, SELL):
            raise ExchangeError(f"اتجاه غير معروف: {side}")

        info = self.symbol_info(symbol)
        price = self.mark_price(symbol)
        qty = self._calc_qty(info, qty_usdt, price, min_notional)

        if self.dry_run:
            tp_price = price * (1 + tp_pct) if side == BUY else price * (1 - tp_pct)
            sl_price = price * (1 - sl_pct) if side == BUY else price * (1 + sl_pct)
            return OrderResult(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                tp_price=round(tp_price, info.price_precision),
                sl_price=round(sl_price, info.price_precision),
                notional=qty * price,
                simulated=True,
            )

        self._ensure_single_position_mode()
        self.set_margin_mode(symbol, margin_mode)
        self.set_leverage(symbol, leverage)

        order_side = "BUY" if side == BUY else "SELL"
        resp = self.client.new_order(
            symbol=symbol,
            side=order_side,
            type="MARKET",
            quantity=fmt_num(qty, info.qty_precision),
            newOrderRespType="RESULT",
            **self._side_extra(side),
            **self._rw(),
        )
        order_id = str(resp.get("orderId", ""))
        fill_price = float(resp.get("avgPrice") or 0) or price
        if not float(resp.get("avgPrice") or 0):
            # أوامر الماركت قد تُرجع avgPrice=0 في الرد الأول
            time.sleep(0.8)
            try:
                q = self.client.query_order(symbol=symbol, orderId=resp["orderId"], **self._rw())
                fill_price = float(q.get("avgPrice") or 0) or price
            except Exception:  # نبقى على سعر المارك
                pass

        result = OrderResult(
            symbol=symbol,
            side=side,
            qty=qty,
            price=fill_price,
            order_id=order_id,
            notional=qty * fill_price,
            raw=resp,
        )

        # ── جني الأرباح ووقف الخسارة (نقطة Algo بعد تغيير Binance) ──
        working = "MARK_PRICE" if str(tp_trigger).lower() == "mark_price" else "CONTRACT_PRICE"
        if side == BUY:
            tp_price = fill_price * (1 + tp_pct)
            sl_price = fill_price * (1 - sl_pct)
        else:
            tp_price = fill_price * (1 - tp_pct)
            sl_price = fill_price * (1 + sl_pct)

        if self._place_protection(symbol, result, side, "TAKE_PROFIT_MARKET", tp_price, info, qty, working):
            result.tp_price = round(tp_price, info.price_precision)
        if self._place_protection(symbol, result, side, "STOP_MARKET", sl_price, info, qty, working):
            result.sl_price = round(sl_price, info.price_precision)

        if result.sl_price is None:
            # أمان: لا نترك صفقة بلا حماية
            log.error("[%s] لم يُضبط وقف الخسارة — سيتم إغلاق الصفقة فوراً", symbol)
            try:
                self.cancel_algo_orders(symbol)   # لا نترك هدفاً يفتح صفقة لاحقاً
            except Exception as err:  # pragma: no cover
                log.warning("[%s] تعذّر إلغاء أوامر algo: %s", symbol, err)
            try:
                self.close_position(symbol)
            except Exception as err:  # pragma: no cover
                log.critical("[%s] فشل الإغلاق الاضطراري! تدخّل يدوياً: %s", symbol, err)
            raise ExchangeError(
                f"تم فتح الصفقة ثم إغلاقها: تعذّر وضع وقف الخسارة لـ {symbol}"
            )
        return result

    def _place_protection(
        self,
        symbol: str,
        result: OrderResult,
        side: str,
        order_type: str,
        trigger_price: float,
        info: SymbolInfo,
        qty: float,
        working_type: str,
    ) -> bool:
        """يضع أمر حماية (هدف/وقف) عبر نقطة Algo. يُرجع True عند النجاح."""
        tag = "جني الأرباح" if order_type == "TAKE_PROFIT_MARKET" else "وقف الخسارة"
        close_side = "SELL" if side == BUY else "BUY"
        position_side = ("LONG" if side == BUY else "SHORT") if self._dual_side else None

        # المحاولة الأساسية: closePosition (يُغلق كل الصفقة)
        # الاحتياط: quantity + reduceOnly (بعض الحسابات ترفض closePosition)
        attempts: list[dict] = [{"close_position": True, "quantity": None}]
        if not self._dual_side:
            attempts.append(
                {"close_position": False, "quantity": fmt_num(qty, info.qty_precision)}
            )

        last_err: Exception | None = None
        for attempt in attempts:
            try:
                resp = self.place_conditional_order(
                    symbol=symbol,
                    side=close_side,
                    order_type=order_type,
                    trigger_price=trigger_price,
                    precision=info.price_precision,
                    working_type=working_type,
                    position_side=position_side,
                    close_position=attempt["close_position"],
                    quantity=attempt["quantity"],
                )
                algo_id = str((resp or {}).get("algoId") or "")
                if algo_id:
                    result.algo_ids.append(algo_id)
                return True
            except Exception as err:
                last_err = err
                log.warning("[%s] محاولة وضع %s فشلت: %s", symbol, tag, err)
        log.error("[%s] فشل وضع أمر %s: %s", symbol, tag, last_err)
        return False

    def close_position(self, symbol: str) -> OrderResult | None:
        pos = self.get_position(symbol)
        if not pos:
            return None
        try:
            self.client.cancel_open_orders(symbol=symbol, **self._rw())
        except Exception as err:
            log.debug("[%s] لا توجد أوامر معلقة للإلغاء: %s", symbol, err)
        # أوامر الوقف/الهدف تعيش على نقطة Algo ولا تلغيها cancel_open_orders؛
        # تركها يفتح صفقة جديدة بالخطأ عند إطلاقها لاحقاً.
        if not self.dry_run:
            self.cancel_algo_orders(symbol)

        info = self.symbol_info(symbol)
        close_side = "SELL" if pos.side == BUY else "BUY"
        qty = round_step(pos.size, info.step_size) or pos.size
        if self.dry_run:
            return OrderResult(symbol=symbol, side=close_side.lower(), qty=qty, price=pos.mark_price, simulated=True)
        resp = self.client.new_order(
            symbol=symbol,
            side=close_side,
            type="MARKET",
            quantity=fmt_num(qty, info.qty_precision),
            reduceOnly="true",
            **self._side_extra(pos.side),
            **self._rw(),
        )
        return OrderResult(
            symbol=symbol,
            side=close_side.lower(),
            qty=qty,
            price=float(resp.get("avgPrice") or pos.mark_price),
            order_id=str(resp.get("orderId", "")),
            raw=resp,
        )
