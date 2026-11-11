"""اختبارات النشر على Render (المنفذ · Supabase · النبضة · المخطط).

الهدف: أن ينجح النشر من أول محاولة، وأن نكتشف كسر هذه الاتفاقيات قبل
أن يكتشفها المستخدم على شاشة حمراء في لوحة Render.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from stratig.config import Config
from stratig.web.keepalive import MIN_INTERVAL, KeepAlive
from stratig.web.server import Dashboard

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# بيئة نظيفة: لا يرث الاختبار متغيرات جهاز المطوّر
CLEAN = [
    "PORT", "WEB_HOST", "WEB_TOKEN", "WEB_ENABLED",
    "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_ANON_KEY",
    "SUPABASE_BOT_ID", "SUPABASE_ENABLED", "BOT_ID",
    "EXCHANGE", "TESTNET", "DRY_RUN",
    "KEEP_AWAKE", "KEEP_AWAKE_URL", "KEEP_AWAKE_INTERVAL", "RENDER",
]


@pytest.fixture
def env(monkeypatch):
    """يمسح متغيرات النشر، ويُعيد دالّة للضبط."""
    for key in CLEAN:
        monkeypatch.delenv(key, raising=False)

    def setenv(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setenv(key, value)
    return setenv


def make_config(tmp_path, **kwargs):
    """ملف إعدادات بسيط + متغيرات بيئة اختيارية."""
    path = tmp_path / "config.toml"
    path.write_text("[web]\nenabled = false\nport = 8000\n", encoding="utf-8")
    for key, value in kwargs.items():
        os.environ[key] = value
    try:
        return Config.load(str(path), str(tmp_path / ".env.missing"))
    finally:
        for key in kwargs:
            os.environ.pop(key, None)


# ═══════════════════════ المنفذ (PORT) ═══════════════════════

def test_port_forces_web_enabled(env, tmp_path):
    """Render يمرّر PORT — بلا منفذ مفتوح يفشل النشر، فنفتح اللوحة وجوباً."""
    cfg = make_config(tmp_path, PORT="10000")
    assert cfg.get("web.enabled") is True
    assert cfg.get("web.port") == 10000


def test_port_does_not_override_explicit_web_enabled_false(env, tmp_path):
    """لكن إن عطّلها المستخدم صراحةً بـ WEB_ENABLED=false نحترم قراره."""
    cfg = make_config(tmp_path, PORT="10000", WEB_ENABLED="false")
    assert cfg.get("web.enabled") is False
    # المنفذ يبقى مضبوطاً: النشر يحتاجه، والتعطيل يعني «بلا واجهة» لا «بلا عنوان»
    assert cfg.get("web.port") == 10000


def test_no_port_keeps_file_values(env, tmp_path):
    """بلا PORT (تشغيل محلي على ويندوز) لا يتغيّر شيء."""
    cfg = make_config(tmp_path)
    assert cfg.get("web.enabled") is False
    assert cfg.get("web.port") == 8000


def test_garbage_port_is_ignored(env, tmp_path):
    """قيمة غير رقمية لا تُسقط البوت ولا تُفسد الإعدادات."""
    cfg = make_config(tmp_path, PORT="not-a-number")
    assert cfg.get("web.port") == 8000
    assert cfg.get("web.enabled") is False


def test_host_and_token_from_env(env, tmp_path):
    cfg = make_config(tmp_path, WEB_HOST="0.0.0.0", WEB_TOKEN="سري")
    assert cfg.get("web.host") == "0.0.0.0"
    assert cfg.get("web.token") == "سري"


# ═══════════════════════ Supabase ═══════════════════════

def test_supabase_autoenabled_when_url_and_key(env, tmp_path):
    """وجود الرابط والمفتاح يكفي — لا نطلب متغيراً ثالثاً على منصّة بلا ملف."""
    cfg = make_config(tmp_path, SUPABASE_URL="https://x.supabase.co", SUPABASE_KEY="k")
    assert cfg.get("supabase.enabled") is True
    assert cfg.get("supabase.url") == "https://x.supabase.co"
    assert cfg.get("supabase.key") == "k"


def test_supabase_stays_off_without_key(env, tmp_path):
    cfg = make_config(tmp_path, SUPABASE_URL="https://x.supabase.co")
    assert cfg.get("supabase.enabled") is False


def test_supabase_can_be_disabled_explicitly(env, tmp_path):
    cfg = make_config(tmp_path, SUPABASE_URL="https://x.supabase.co", SUPABASE_KEY="k",
                      SUPABASE_ENABLED="false")
    assert cfg.get("supabase.enabled") is False


def test_bot_id_accepts_vercel_name(env, tmp_path):
    """Vercel يقرأ BOT_ID و بايثون يقرأ SUPABASE_BOT_ID — نفس المعنى."""
    cfg = make_config(tmp_path, BOT_ID="render")
    assert cfg.get("supabase.bot_id") == "render"


def test_supabase_bot_id_wins_over_bot_id(env, tmp_path):
    """الاسم الأخص يطغى عند وجود الاثنين."""
    cfg = make_config(tmp_path, SUPABASE_BOT_ID="a", BOT_ID="b")
    assert cfg.get("supabase.bot_id") == "a"


def test_supabase_bot_id_and_anon_key(env, tmp_path):
    cfg = make_config(tmp_path, SUPABASE_BOT_ID="render", SUPABASE_ANON_KEY="anon")
    assert cfg.get("supabase.bot_id") == "render"
    assert cfg.get("supabase.anon_key") == "anon"


def test_anon_key_never_falls_back_to_service_key(env, tmp_path):
    """أهم اختبار أمني هنا: anon فارغ ⇒ لا يُستبدل بمفتاح الكتابة السرّي."""
    cfg = make_config(tmp_path, SUPABASE_KEY="service-secret")
    assert cfg.get("supabase.anon_key") == ""


# ═══════════════════════ /api/config (ما يراه المتصفح) ═══════════════════════

def _serve(tmp_path, public_config):
    """يشغّل خادماً على منفذ فارغ ويُعيد (الرابط، الإيقاف)."""
    dash = Dashboard(lambda: {"ok": True}, host="127.0.0.1", port=0)
    dash.public_config = public_config
    assert dash.start()
    base = f"http://127.0.0.1:{dash.port}"
    return base, dash


def _get(url):
    import json
    import urllib.request
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_api_config_returns_anon_key_only():
    base, dash = _serve(None, {"url": "https://x.supabase.co",
                               "anon_key": "anon-public", "bot_id": "render"})
    try:
        assert _get(f"{base}/api/config") == {
            "url": "https://x.supabase.co", "key": "anon-public", "botId": "render"}
    finally:
        dash.stop() if hasattr(dash, "stop") else None


def test_api_config_hides_service_key_when_anon_missing():
    """المفتاح السرّي **لا** يجب أن يظهر للمتصفح — حتى لو لم يُضبط anon."""
    base, dash = _serve(None, {"url": "https://x.supabase.co",
                               "anon_key": "", "bot_id": "render"})
    try:
        assert _get(f"{base}/api/config") == {"url": "", "key": "", "botId": ""}
    finally:
        dash.stop() if hasattr(dash, "stop") else None


def test_api_config_requires_both_url_and_key():
    base, dash = _serve(None, {"url": "https://x.supabase.co", "anon_key": ""})
    try:
        assert _get(f"{base}/api/config")["key"] == ""
    finally:
        dash.stop() if hasattr(dash, "stop") else None


# ═══════════════════════ النبضة (KEEP_AWAKE) ═══════════════════════

def test_keepalive_disabled_by_default(env):
    assert KeepAlive.from_env(None) is None


def test_keepalive_enabled_on_render(env):
    """Render يضبط RENDER=1 بنفسه — لا نطلب من المستخدم شيئاً."""
    env(RENDER="true", KEEP_AWAKE_URL="https://bot.onrender.com")
    keep = KeepAlive.from_env(None)
    assert keep is not None
    assert keep.url == "https://bot.onrender.com/api/health"


def test_keepalive_off_by_explicit_flag(env):
    env(RENDER="true", KEEP_AWAKE="0", KEEP_AWAKE_URL="https://bot.onrender.com")
    assert KeepAlive.from_env(None) is None


def test_keepalive_uses_render_external_url(env):
    """Render يوفّر عنوان الخدمة — نفضّله على أي تخمين."""
    env(RENDER="1", RENDER_EXTERNAL_URL="https://stratig-bot.onrender.com")
    keep = KeepAlive.from_env(None)
    assert keep.url == "https://stratig-bot.onrender.com/api/health"


def test_keepalive_falls_back_to_localhost(env, tmp_path):
    """بلا عنوان خارجي ننقر أنفسنا محلياً بدل أن نتوقف."""
    cfg = make_config(tmp_path, PORT="10000", WEB_HOST="0.0.0.0")
    env(RENDER="1")
    keep = KeepAlive.from_env(cfg)
    assert keep is not None
    # 0.0.0.0 ليس عنواناً يُطلب — يجب أن يتحوّل إلى 127.0.0.1
    assert keep.url == "http://127.0.0.1:10000/api/health"


def test_keepalive_interval_has_floor(env):
    """فاصل قصير جداً = إزعاج بلا فائدة — نرفعه للحد الأدنى."""
    env(RENDER="1", KEEP_AWAKE_URL="https://x.onrender.com", KEEP_AWAKE_INTERVAL="1")
    assert KeepAlive.from_env(None).interval == MIN_INTERVAL


def test_keepalive_bad_interval_falls_back(env):
    env(RENDER="1", KEEP_AWAKE_URL="https://x.onrender.com", KEEP_AWAKE_INTERVAL="سريع")
    assert KeepAlive.from_env(None).interval == 600.0


def test_keepalive_ping_counts(env):
    keep = KeepAlive("https://x/api/health", opener=lambda url, timeout: True)
    assert keep.ping() is True
    assert keep.failures == 0
    assert "يعمل" in keep.status()


def test_keepalive_ping_failure_is_silent(env):
    """فشل الشبكة يُسجَّل ولا يرفع استثناءً — البوت لا يسقط لأجل نبضة."""
    keep = KeepAlive("https://x/api/health", opener=lambda url, timeout: False)
    assert keep.ping() is False
    assert keep.failures == 1
    assert "خطأ" in keep.status()


def test_keepalive_without_url_is_disabled():
    assert KeepAlive("").ping() is False
    assert "معطّل" in KeepAlive("").status()


def test_keepalive_thread_starts_and_stops(env):
    import time

    hits: list[str] = []
    keep = KeepAlive("https://x/api/health", interval=MIN_INTERVAL,
                     opener=lambda url, timeout: hits.append(url) or True)
    assert keep.start() is True
    assert keep.start() is False          # لا نُشغّل خيطاً ثانياً
    time.sleep(0.05)
    assert keep.pings == 0                # لم يحن موعد النبضة بعد (MIN_INTERVAL)
    keep.stop()


# ═══════════════════════ ملفات النشر ═══════════════════════

def test_render_yaml_exists_and_parses():
    """Blueprint فاسد = نشر فاشل من اللحظة الأولى."""
    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("PyYAML غير مثبّت")
    data = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    services = {svc["name"]: svc for svc in data["services"]}
    assert set(services) == {"stratig-bot", "stratig-dashboard"}
    for svc in services.values():
        assert svc["plan"] == "free"
        assert svc["runtime"] == "docker"
        assert svc["healthCheckPath"] == "/api/health"


def test_render_yaml_secrets_are_not_synced():
    """الأسرار تُطلب من المستخدم ولا تُخزَّن في المستودع."""
    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("PyYAML غير مثبّت")
    data = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    for svc in data["services"]:
        secret_keys = [v["key"] for v in svc.get("envVars", [])
                       if v.get("sync") is False]
        assert "SUPABASE_KEY" in secret_keys
        for key in secret_keys:
            # لا قيمة مكتوبة بجانب أي سرّ
            assert "value" not in {k for k in svc and _vars_of(svc, key)}


def _vars_of(service, key):
    for item in service.get("envVars", []):
        if item["key"] == key:
            return set(item)
    return set()


def test_render_yaml_keeps_dashboard_without_keepalive():
    """اللوحة يجب أن تنام — 750 ساعة شهرياً لا تكفي لخدمتين مستيقظتين."""
    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("PyYAML غير مثبّت")
    data = yaml.safe_load((PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    services = {svc["name"]: svc for svc in data["services"]}
    dash_keys = {v["key"] for v in services["stratig-dashboard"]["envVars"]}
    assert "KEEP_AWAKE" not in dash_keys
    bot_keys = {v["key"] for v in services["stratig-bot"]["envVars"]}
    assert "KEEP_AWAKE" in bot_keys


def _blocks(text: str) -> dict[str, str]:
    """يقسم render.yaml إلى كتل خدمة بلا مكتبة YAML (المستودع بلا تبعيات)."""
    import re

    parts = re.split(r"(?m)^  - type: web\s*$", text)
    names = re.findall(r"(?m)^    name: (.+)$", text)
    return dict(zip([n.strip() for n in names], parts[1:]))


def _raw_yaml() -> str:
    return (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")


def test_render_yaml_structure_without_dependency():
    """التحقّق من المخطط يجب ألا يتوقف على توفّر PyYAML."""
    import re

    text = _raw_yaml()
    blocks = _blocks(text)
    assert set(blocks) == {"stratig-bot", "stratig-dashboard"}
    for body in blocks.values():
        assert re.search(r"(?m)^    plan: free$", body)
        assert re.search(r"(?m)^    runtime: docker$", body)
        assert re.search(r"(?m)^    healthCheckPath: /api/health$", body)


def test_render_yaml_commands():
    import re

    blocks = _blocks(_raw_yaml())
    assert re.search(r"(?m)^    dockerCommand: python main\.py$", blocks["stratig-bot"])
    assert re.search(r"(?m)^    dockerCommand: python scripts/dashboard\.py$",
                     blocks["stratig-dashboard"])


def test_render_yaml_no_value_next_to_secrets():
    """أي متغير معلَّم sync:false يجب ألا يحمل قيمة مكتوبة بجانبه."""
    import re

    for body in _blocks(_raw_yaml()).values():
        for entry in re.split(r"(?m)^      - key: ", body)[1:]:
            if "sync: false" in entry:
                assert "value:" not in entry, entry


def test_render_yaml_keepalive_only_on_bot():
    """إبقاء اللوحة يقظة يستنفد 750 الساعة ويوقف البوت في منتصف الشهر."""
    blocks = _blocks(_raw_yaml())
    assert "KEEP_AWAKE" in blocks["stratig-bot"]
    assert "KEEP_AWAKE" not in blocks["stratig-dashboard"]


def test_render_yaml_defaults_to_testnet():
    """النشر الافتراضي يجب أن يكون آمناً: تيستنت لا حقيقي."""
    body = _blocks(_raw_yaml())["stratig-bot"]
    assert 'key: TESTNET' in body and 'value: "true"' in body
    assert "CONFIRM_LIVE_TRADING" not in body


def test_schema_sql_defines_both_tables():
    sql = (PROJECT_ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    assert "bot_state" in sql and "bot_trades" in sql
    # القيد الفريد هو ما يجعل «تجاهل المكرّر» يعمل فعلاً
    assert "bot_trades_dedup" in sql
    # بلا RLS يصير المفتاح العام ثغرة كتابة
    assert "enable row level security" in sql
    assert sql.count("create policy") >= 2


def test_docs_render_exists():
    doc = (PROJECT_ROOT / "docs" / "render.md").read_text(encoding="utf-8")
    assert "render.yaml" in doc
    # الحقائق المزعجة يجب أن تكون مكتوبة لا مخفية
    for fact in ("750", "15", "تيستنت"):
        assert fact in doc
