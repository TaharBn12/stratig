"""اختبارات طبقة الحماية من مكتبات التشفير المترجَمة."""
from __future__ import annotations

import builtins
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from stratig.compat import ensure_crypto_stub  # noqa: E402


def test_stub_is_created_when_crypto_missing(monkeypatch):
    """إن تعذّر تحميل pycryptodome يجب أن يعمل المشروع ببديل وهمي."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("Crypto") and name not in sys.modules:
            raise ImportError("DLL load failed (محاكاة)", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for key in [k for k in sys.modules if k == "Crypto" or k.startswith("Crypto.")]:
        monkeypatch.delitem(sys.modules, key, raising=False)

    assert ensure_crypto_stub() is True
    assert "Crypto" in sys.modules
    assert "Crypto.PublicKey" in sys.modules
    assert "Crypto.Hash" in sys.modules

    # الأهم: محوّل المنصة يُبنى بنجاح رغم غياب المكتبة
    from stratig.exchanges.binance_futures import BinanceFutures

    exchange = BinanceFutures("key", "secret", testnet=True)
    assert exchange.client is not None
    assert "testnet" in exchange.client.base_url

    # تنظيف: نعيد الحالة الأصلية حتى لا تؤثر على باقي الاختبارات
    for key in [k for k in sys.modules if k == "Crypto" or k.startswith("Crypto.")]:
        del sys.modules[key]
    for key in [k for k in sys.modules if k == "binance" or k.startswith("binance.")]:
        del sys.modules[key]


def test_stub_is_not_used_when_crypto_available(monkeypatch):
    """إن كانت المكتبة متاحة فلا يُستخدم أي بديل."""
    for key in [k for k in sys.modules if k == "Crypto" or k.startswith("Crypto.")]:
        monkeypatch.delitem(sys.modules, key, raising=False)
    try:
        import Crypto  # noqa: F401

        available = True
    except Exception:
        available = False
    if not available:
        pytest.skip("pycryptodome غير مثبتة في هذه البيئة")
    assert ensure_crypto_stub() is False
