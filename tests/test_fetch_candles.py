"""اختبارات جالب الشموع الحقيقية (OKX، بلا مفتاح).

الشبكة محجوبة في بيئة التطوير، فنختبر المنطق بمُزيّف لـ urlopen:
الترقيم للخلف، الترتيب، القصّ على النافذة المطلوبة، ورسائل الخطأ.
"""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import fetch_candles as fc                    # noqa: E402


# ═══════════════════════════ مُزيّف الشبكة ═══════════════════════════

class _FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _row(ms: int, price: float = 1.0) -> list[str]:
    """صفّ بصيغة OKX: time, o, h, l, c, vol, volCcy, volCcyQuote, confirm."""
    return [str(ms), f"{price}", f"{price + 2}", f"{price - 2}",
            f"{price + 1}", "100", "200", "300", "1"]


def _patch(monkeypatch, pages: list[dict]):
    """يُرجع صفحات بالترتيب (للخلف)، ويسجّل الروابط المطلوبة."""
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        return _FakeResponse(pages[len(calls) - 1] if len(calls) <= len(pages)
                             else {"code": "0", "data": []})

    monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(fc.time, "sleep", lambda *_: None)
    return calls


# ═══════════════════════════ اسم الأداة ═══════════════════════════

def test_instrument_maps_swap_and_spot():
    assert fc.okx_instrument("ONEUSDT") == "ONE-USDT-SWAP"
    assert fc.okx_instrument("oneusdt") == "ONE-USDT-SWAP"
    assert fc.okx_instrument("ONEUSDT", "spot") == "ONE-USDT"
    assert fc.okx_instrument("BTCUSDC") == "BTC-USDC-SWAP"


def test_instrument_rejects_a_symbol_it_cannot_parse():
    with pytest.raises(fc.FetchError, match="ONEUSDT"):
        fc.okx_instrument("ONE")
    with pytest.raises(fc.FetchError):
        fc.okx_instrument("")


# ═══════════════════════════ الجلب ═══════════════════════════

def test_fetch_paginates_backwards_and_sorts_oldest_first(monkeypatch):
    now = 1_700_000_000_000
    step = 900_000                                  # 15m
    page1 = {"code": "0", "data": [_row(now - i * step, 100 + i) for i in range(100)]}
    page2 = {"code": "0", "data": [_row(now - (100 + i) * step, 90 + i)
                                   for i in range(100)]}
    calls = _patch(monkeypatch, [page1, page2])

    rows = fc.fetch_okx("ONE-USDT-SWAP", "15m", now - 400 * step, now)
    assert len(rows) == 200
    times = [int(r[0]) for r in rows]
    assert times == sorted(times)                   # تصاعدي: الأقدم أولاً
    assert "history-candles" in calls[0] and "bar=15m" in calls[0]
    assert int(calls[1].split("after=")[1]) < int(calls[0].split("after=")[1])


def test_fetch_keeps_only_the_requested_window(monkeypatch):
    now = 1_700_000_000_000
    step = 900_000
    page = {"code": "0", "data": [_row(now - i * step) for i in range(100)]}
    _patch(monkeypatch, [page])
    rows = fc.fetch_okx("ONE-USDT-SWAP", "15m", now - 10 * step, now)
    assert len(rows) == 11                          # داخل النافذة فقط
    assert int(rows[0][0]) == now - 10 * step


def test_fetch_rejects_a_timeframe_okx_does_not_have(monkeypatch):
    with pytest.raises(fc.FetchError, match="8h"):
        fc.fetch_okx("ONE-USDT-SWAP", "8h", 0, 1)


def test_fetch_raises_a_clear_error_when_the_venue_refuses(monkeypatch):
    _patch(monkeypatch, [{"code": "50011", "msg": "Instrument ID does not exist"}])
    with pytest.raises(fc.FetchError, match="does not exist"):
        fc.fetch_okx("XXX-USDT-SWAP", "15m", 0, 10_000_000_000_000)


def test_fetch_raises_a_clear_error_when_the_venue_returns_nothing(monkeypatch):
    _patch(monkeypatch, [{"code": "0", "data": []}])
    with pytest.raises(fc.FetchError, match="لم تعد"):
        fc.fetch_okx("ONE-USDT-SWAP", "15m", 0, 10_000_000_000_000)


def test_network_failure_is_reported_in_arabic(monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.URLError("DNS failure")

    monkeypatch.setattr(fc.urllib.request, "urlopen", boom)
    with pytest.raises(fc.FetchError, match="تعذّر الوصول"):
        fc._get("https://www.okx.com/api/v5/market/candles")


def test_a_non_json_reply_is_reported_clearly(monkeypatch):
    class _Html(_FakeResponse):
        def __init__(self):
            self._raw = b"<html>blocked by country</html>"

    monkeypatch.setattr(fc.urllib.request, "urlopen", lambda *a, **k: _Html())
    with pytest.raises(fc.FetchError, match="ردّ غير مفهوم"):
        fc._get("https://www.okx.com/api/v5/market/candles")


# ═══════════════════════════ الكتابة ═══════════════════════════

def test_write_csv_creates_the_folder_and_the_header(tmp_path):
    out = tmp_path / "deep" / "data" / "ONEUSDT-15m.csv"
    path = fc.write_csv([["1", "2", "3", "4", "5", "6"]], out)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "time,open,high,low,close,volume"
    assert lines[1] == "1,2,3,4,5,6"


def _patch_dynamic(monkeypatch, *, step: int = 900_000, per_page: int = 100,
                   max_pages: int = 3):
    """مُزيّف يولّد الصفحة **من قيمة `after` في الرابط** — أي يتعامل مع
    الوقت الحقيقي الذي يستخدمه `main`، لا مع وقت ثابت."""
    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if len(calls) > max_pages:
            return _FakeResponse({"code": "0", "data": []})
        after = int(request.full_url.split("after=")[1])
        data = [_row(after - i * step, 100 + 10 * len(calls) + i)
                for i in range(per_page)]
        return _FakeResponse({"code": "0", "data": data})

    monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(fc.time, "sleep", lambda *_: None)
    return calls


def test_main_end_to_end_writes_a_file_the_lab_can_read(tmp_path, monkeypatch):
    _patch_dynamic(monkeypatch)
    out = tmp_path / "ONEUSDT-15m.csv"
    code = fc.main(["--symbol", "ONEUSDT", "--tf", "15m", "--days", "1",
                    "--out", str(out), "--quiet"])
    assert code == 0 and out.exists()

    from scripts.lab import load_csv               # نفس ما يقرأه المختبر
    candles = load_csv(out)
    assert len(candles) > 0
    assert candles.close[0] != candles.close[-1]
