"""اختبارات لوحة التحكم: اللقطة · الرفع إلى Supabase · الخادم."""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config                      # noqa: E402
from stratig.risk import Journal, Trade                # noqa: E402
from stratig.web.server import Dashboard               # noqa: E402
from stratig.web.snapshot import (                     # noqa: E402
    build_snapshot,
    equity_curve,
    stats_block,
    trades_rows,
)
from stratig.web.supabase import SupabaseSync          # noqa: E402


def _journal(tmp_path) -> Journal:
    j = Journal(tmp_path / "trades.json", limit=100)
    j.add(Trade("BTCUSDT", "buy", 12.5, 1.2, opened_at=1000, closed_at=1100,
                strategy="rsi_williams"))
    j.add(Trade("ETHUSDT", "sell", -10.0, -1.0, opened_at=1200, closed_at=1300,
                strategy="rsi_williams"))
    j.add(Trade("SOLUSDT", "buy", 8.0, 0.8, opened_at=1400, closed_at=1500,
                strategy="scalping_i"))
    return j


# ═══════════════════════ اللقطة ═══════════════════════
def test_equity_curve_is_cumulative():
    trades = [Trade("BTCUSDT", "buy", 10.0), Trade("X", "buy", -4.0),
              Trade("Y", "buy", 6.0)]
    assert equity_curve(trades) == [10.0, 6.0, 12.0]


def test_trades_rows_newest_first():
    rows = trades_rows([Trade("A", "buy", 1.0), Trade("B", "sell", -2.0)])
    assert [r["symbol"] for r in rows] == ["B", "A"]
    assert rows[0]["pnl"] == -2.0


def test_stats_block_matches_journal(tmp_path):
    j = _journal(tmp_path)
    stats = stats_block(j)
    assert stats["count"] == 3
    assert stats["wins"] == 2 and stats["losses"] == 1
    assert stats["total_pnl"] == 10.5
    assert abs(stats["win_rate"] - 66.7) < 0.1


def test_snapshot_offline_reads_journal_from_disk(tmp_path):
    cfg = Config({"risk": {"journal_path": str(tmp_path / "trades.json")}})
    _journal(tmp_path)                       # يكتب السجل على القرص
    snap = build_snapshot(config=cfg, bot_id="test-bot")
    assert snap["bot_id"] == "test-bot"
    assert snap["stats"]["count"] == 3
    assert snap["equity_curve"] == [12.5, 2.5, 10.5]
    assert snap["live"] is False
    assert snap["positions"] == []


def test_snapshot_offline_does_not_touch_exchange(tmp_path):
    """الوضع المستقل يجب ألا يحتاج مفاتيح أو اتصالاً."""
    cfg = Config({"risk": {"journal_path": str(tmp_path / "empty.json")}})
    snap = build_snapshot(config=cfg)
    assert snap["stats"]["count"] == 0
    assert snap["balance"] == 0.0
    assert snap["risk"]["trading_allowed"] is True


def test_snapshot_includes_risk_and_config(tmp_path):
    cfg = Config({
        "strategy": {"name": "scalping_i", "timeframe": "1h"},
        "execution": {"mode": "auto"},
        "safety": {"dry_run": True},
        "exchange": {"testnet": False},
        "risk": {"journal_path": str(tmp_path / "t.json")},
    })
    snap = build_snapshot(config=cfg)
    assert snap["strategy"] == "scalping_i"
    assert snap["timeframe"] == "1h"
    assert snap["mode"] == "auto"
    assert snap["dry_run"] is True
    assert snap["testnet"] is False


def test_snapshot_with_trader_uses_live_objects(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_core import make_trader

    tr, _ex = make_trader(tmp_path, risk__journal_path=str(tmp_path / "t.json"))
    tr.journal.add(Trade("BTCUSDT", "buy", 5.0, 0.5))
    tr.stats["scans"] = 7
    snap = build_snapshot(tr, tr.cfg, live=True)
    assert snap["scans"] == 7
    assert snap["live"] is True
    assert snap["stats"]["count"] == 1
    assert isinstance(snap["positions"], list)
    assert "trading_allowed" in snap["risk"]


# ═══════════════════════ Supabase ═══════════════════════
def test_sync_disabled_by_default():
    sync = SupabaseSync.from_config(Config({}))
    assert sync.enabled is False
    assert sync.status() == "معطّل"
    assert sync.push_state({"ts": 0}) is False


def test_sync_disabled_without_url_or_key():
    assert SupabaseSync(url="https://x.supabase.co", key="").enabled is False
    assert SupabaseSync(url="", key="k").enabled is False


def test_sync_builds_correct_request(monkeypatch):
    seen = {}

    class FakeResponse:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["apikey"] = request.get_header("Apikey")
        seen["auth"] = request.get_header("Authorization")
        seen["prefer"] = request.get_header("Prefer")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sync = SupabaseSync(url="https://demo.supabase.co", key="SECRET",
                        bot_id="bot-1", enabled=True)
    assert sync.push_state({"ts": 1_700_000_000}) is True

    assert seen["url"] == "https://demo.supabase.co/rest/v1/bot_state"
    assert seen["method"] == "POST"
    assert seen["apikey"] == "SECRET"
    assert seen["auth"] == "Bearer SECRET"
    assert seen["prefer"] == "resolution=merge-duplicates"
    assert seen["body"]["bot_id"] == "bot-1"
    assert seen["body"]["payload"] == {"ts": 1_700_000_000}
    assert sync.pushed == 1


def test_sync_pushes_only_new_trades(monkeypatch):
    bodies = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        bodies.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sync = SupabaseSync(url="https://demo.supabase.co", key="K", enabled=True)
    rows = [{"symbol": "BTCUSDT", "side": "buy", "pnl": 3.0, "r": 0.5,
             "opened_at": 1000, "closed_at": 1100, "strategy": "s"}]
    assert sync.push_trades(rows) is True
    assert bodies[0][0]["symbol"] == "BTCUSDT"
    assert bodies[0][0]["r_multiple"] == 0.5
    assert sync.push_trades([]) is False          # لا طلبات فارغة


def test_sync_reports_errors_without_raising(monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized",
                                     {}, BytesIO(b'{"message":"bad key"}'))

    monkeypatch.setattr("urllib.request.urlopen", boom)
    sync = SupabaseSync(url="https://demo.supabase.co", key="BAD", enabled=True)
    assert sync.push_state({"ts": 1}) is False
    assert "401" in sync.last_error
    assert "خطأ" in sync.status()


def test_sync_survives_network_failure(monkeypatch):
    def boom(request, timeout=None):
        raise OSError("لا يوجد اتصال")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    sync = SupabaseSync(url="https://demo.supabase.co", key="K", enabled=True)
    assert sync.push_state({"ts": 1}) is False
    assert "لا يوجد اتصال" in sync.last_error


# ═══════════════════════ الخادم ═══════════════════════
@pytest.fixture()
def server(tmp_path):
    page = tmp_path / "index.html"
    page.write_text("<html><body>لوحة</body></html>", encoding="utf-8")
    dash = Dashboard(lambda: {"ok": True, "stats": {"count": 2}},
                     host="127.0.0.1", port=0)
    dash.page = page
    assert dash.start() is True
    yield dash
    dash.stop()


def _get(dash: Dashboard, path: str, token: str = "") -> tuple[int, str]:
    url = f"http://127.0.0.1:{dash.port}{path}"
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-Stratig-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8")


def test_server_serves_the_dashboard_page(server):
    code, body = _get(server, "/")
    assert code == 200
    assert "لوحة" in body


def test_server_serves_state_json(server):
    code, body = _get(server, "/api/state")
    assert code == 200
    assert json.loads(body)["stats"]["count"] == 2


def test_server_health_endpoint(server):
    code, body = _get(server, "/api/health")
    assert code == 200 and json.loads(body)["ok"] is True


def test_server_returns_404_for_unknown_path(server):
    assert _get(server, "/nothing")[0] == 404


def test_token_protects_the_dashboard(tmp_path):
    page = tmp_path / "i.html"
    page.write_text("سري", encoding="utf-8")
    dash = Dashboard(lambda: {}, host="127.0.0.1", port=0, token="abc123")
    dash.page = page
    assert dash.start() is True
    try:
        assert _get(dash, "/")[0] == 401
        assert _get(dash, "/api/state")[0] == 401
        assert _get(dash, "/", token="abc123")[0] == 200
        assert _get(dash, "/?token=abc123")[0] == 200
    finally:
        dash.stop()


def test_server_survives_a_failing_snapshot(tmp_path):
    def boom():
        raise RuntimeError("المنصة غير متاحة")

    page = tmp_path / "i.html"
    page.write_text("x", encoding="utf-8")
    dash = Dashboard(boom, host="127.0.0.1", port=0)
    dash.page = page
    assert dash.start() is True
    try:
        code, body = _get(dash, "/api/state")
        assert code == 500
        assert "المنصة غير متاحة" in json.loads(body)["error"]
    finally:
        dash.stop()


def test_dashboard_file_exists_in_repo():
    """اللوحة تُشحن مع المستودع — وإلا تظهر صفحة الخطأ للمستخدم."""
    from stratig.config import PROJECT_ROOT
    from stratig.web.server import default_page

    page = default_page()
    assert page.exists(), page
    text = page.read_text(encoding="utf-8")
    assert "لوحة تحكم ستراتيج" in text
    assert "api/state" in text
