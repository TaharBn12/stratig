"""تجهيزات مشتركة للاختبارات."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# مجلد الاختبارات في مسار البحث حتى تعمل الاستيرادات المباشرة
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_core import make_trader as _make_trader  # noqa: E402


@pytest.fixture()
def make_trader():
    """ينشئ (Trader, FakeExchange) — التعريف الأصلي في test_core."""
    return _make_trader
