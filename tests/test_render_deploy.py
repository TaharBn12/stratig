# ============================================================
#  النشر على Render — لا يموت البوت، والفشل لا يبدو نجاحاً
# ============================================================
#  لماذا هذا الملف؟
#  على منصّات النشر (Render) **موت العملية = نشر فاشل**. رأينا البوت يسقط
#  برمز 1 و«تتبّع» طويل لمجرّد ومضة شبكة لحظية لحظة الإقلاع، ويتوقّف المنفذ
#  معه فلا تجد اللوحة مَن يخدمها. وأسوأ: كان main() يُعيد 0 دائماً، فيبدو
#  البوت الميت «نشراً ناجحاً».
#
#  القاعدة هنا: الإقلاع **صامد** أمام أي خطأ عابر، ويُسقط عمداً أمام خطأ
#  من عندنا لن يُصلح نفسه (توكن غير صالح) — ويُبلّغ عن ذلك برمز خروج صادق.
#
#  كل اختبار هنا **يُشغّل** run() فعلاً مع استثناءات حقيقية؛ ما نقرأه من
#  الكود لا يكفي (درس متكرّر في هذا المشروع).
# ============================================================

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from telegram.error import Conflict, InvalidToken, NetworkError

from stratig.bot.telegram_bot import TelegramBot
from stratig.config import Config, Secrets
from stratig.services.trader import Trader

from test_commands_live import FakeExchange  # noqa: E402  (نفس المُسجّلة)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ═══════════════════════ تجهيز ═══════════════════════


def _load_main():
    """يستورد main.py من جذره (ليس حزمة)، كما يستورده Render تماماً."""
    spec = importlib.util.spec_from_file_location("stratig_main_entry",
                                                  ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bot(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    cfg = Config.load(str(path), str(tmp_path / ".env.missing"))
    cfg.set("web.enabled", False)
    cfg.set("supabase.enabled", False)
    cfg.set("risk.journal_path", str(tmp_path / "trades.json"))
    trader = Trader(cfg, FakeExchange())
    return TelegramBot(Secrets(telegram_token="123456:AAA-fake", chat_ids=[1]),
                       cfg, trader)


@pytest.fixture
def no_sleep(monkeypatch):
    """يمنع النوم الحقيقي ويعدّ مرّاته."""
    calls = []

    def fake_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr("time.sleep", fake_sleep)
    return calls


def _polling(*failures):
    """يبني run_polling يرفع الاستثناءات المطلوبة ثم (ربما) ينجح."""
    seq = list(failures)

    def run_polling(**kwargs):
        if seq:
            raise seq.pop(0)
        return None

    return run_polling


# ═══════════════════════ الإقلاع الصامد ═══════════════════════


def test_run_returns_zero_when_polling_succeeds(bot, monkeypatch):
    """الإقلاع السليم يبقى كما كان: رمز 0."""
    monkeypatch.setattr(bot.app, "run_polling", _polling())
    assert bot.run() == 0


def test_run_retries_after_network_error(bot, monkeypatch, no_sleep):
    """أهم سيناريو على Render: ومضة شبكة لحظية ⇒ نعيد المحاولة ولا نموت."""
    monkeypatch.setattr(bot.app, "run_polling",
                        _polling(NetworkError("TLS/SSL EOF"),
                                 NetworkError("read timeout")))
    assert bot.run() == 0
    assert len(no_sleep) == 2, "يجب أن ننتظر قليلاً بين المحاولات"


def test_run_survives_unexpected_exception(bot, monkeypatch, no_sleep):
    """أي استثناء غير متوقّع يجب ألا يُسقط النشر."""
    monkeypatch.setattr(bot.app, "run_polling", _polling(RuntimeError("بووم")))
    assert bot.run() == 0


def test_run_keeps_dashboard_alive_while_retrying(bot, monkeypatch, no_sleep):
    """المنفذ واللوحة مفتوحان أصلاً قبل run_polling — نتحقّق أننا لا نغلقهما."""
    seen = {}

    def run_polling(**kwargs):
        seen["kwargs"] = kwargs
        raise NetworkError("boom")

    monkeypatch.setattr(bot.app, "run_polling", run_polling)
    bot.run(max_retries=2)
    assert seen["kwargs"]["drop_pending_updates"] is True


def test_run_reports_failure_when_retries_exhausted(bot, monkeypatch, no_sleep):
    """إن استنفدنا المحاولات المحدّدة ⇒ رمز 1 صادق (لا 0 يخدع)."""
    monkeypatch.setattr(bot.app, "run_polling",
                        _polling(*[NetworkError("x")] * 5))
    assert bot.run(max_retries=3) == 1


# ═══════════════════ التوكن: خطؤنا، لا يُصلح نفسه ═══════════════════


def test_run_fails_fast_on_invalid_token(bot, monkeypatch, no_sleep):
    """توكن غير صالح ⇒ نُسقط فوراً، بلا إعادة محاولة بلا جدوى."""
    monkeypatch.setattr(bot.app, "run_polling", _polling(InvalidToken("bad")))
    assert bot.run() == 2
    assert no_sleep == [], "التوكن الخاطئ لا يُصلح بالانتظار"


def test_run_conflict_warns_about_second_instance(bot, monkeypatch, no_sleep,
                                                  caplog):
    """409 = نسختان بالتوكن نفسه (ويندوز + Render) — نشرح السبب للمستخدم."""
    monkeypatch.setattr(bot.app, "run_polling", _polling(Conflict("dup")))
    with caplog.at_level("ERROR"):
        assert bot.run(max_retries=1) == 1
    assert "نسخة أخرى" in caplog.text


# ═══════════════════ main() يصدق في رمز الخروج ═══════════════════


def _render_env(tmp_path):
    """ملف .env كما يضبطه المستخدم على Render (أسرار حقيقية الشكل)."""
    env = tmp_path / "e.env"
    env.write_text(
        "TELEGRAM_BOT_TOKEN=123456:AAA-fake-token\n"
        "BINANCE_TESTNET_API_KEY=fake-key\n"
        "BINANCE_TESTNET_API_SECRET=fake-secret\n",
        encoding="utf-8")
    cfg = tmp_path / "c.toml"
    cfg.write_text("[exchange]\nname = \"binance\"\ntestnet = true\n",
                   encoding="utf-8")
    return ["--config", str(cfg), "--env", str(env)]


def test_main_propagates_bot_exit_code(tmp_path, monkeypatch):
    """main() يعيد رمز البوت — الفشل لا يبدو نجاحاً على Render."""
    module = _load_main()
    monkeypatch.setattr(module, "KeepAlive", type("K", (), {
        "from_env": staticmethod(lambda cfg: None)}))
    monkeypatch.setattr(module.TelegramBot, "run",
                        lambda self, max_retries=0: 2)
    assert module.main(_render_env(tmp_path)) == 2


def test_main_returns_zero_on_healthy_run(tmp_path, monkeypatch):
    module = _load_main()
    monkeypatch.setattr(module, "KeepAlive", type("K", (), {
        "from_env": staticmethod(lambda cfg: None)}))
    monkeypatch.setattr(module.TelegramBot, "run",
                        lambda self, max_retries=0: 0)
    assert module.main(_render_env(tmp_path)) == 0


def test_main_reports_missing_secrets_before_running(tmp_path, monkeypatch):
    """بلا أسرار ⇒ 2 واضح، لا 0 يوهم بنجاح النشر (ما حدث في محاكاتنا)."""
    module = _load_main()
    # dotenv يُلوّث os.environ بملف .env الذي قرأه اختبار سابق — نُنظّفه،
    # وإلا ورث هذا الاختبار مفاتيحَ وهمية وظننّا الإقلاع سالماً وهو ليس كذلك.
    for key in ("TELEGRAM_BOT_TOKEN", "BINANCE_TESTNET_API_KEY",
                "BINANCE_TESTNET_API_SECRET", "BINANCE_API_KEY",
                "BINANCE_API_SECRET", "TELEGRAM_CHAT_IDS"):
        monkeypatch.delenv(key, raising=False)
    # حاجز أمان: لن نصل إلى الشبكة أبداً في الاختبارات
    monkeypatch.setattr(module.TelegramBot, "run",
                        lambda self, max_retries=0: 0)

    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    cfg = tmp_path / "c.toml"
    cfg.write_text("[exchange]\nname = \"binance\"\ntestnet = true\n",
                   encoding="utf-8")
    assert module.main(["--config", str(cfg), "--env", str(empty)]) == 2


# ═══════════════════ ملف النشر ═══════════════════════


def test_render_yaml_uses_only_free_tier_features():
    """Blueprint على الخطة المجانية: لا preDeployCommand (مدفوع) ولا أقراص."""
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "preDeployCommand" not in text, "غير مدعوم على المجاني"
    assert "disk" not in text, "غير مدعوم على المجاني"
    assert "plan: free" in text


def test_health_answers_without_telegram(bot):
    """/ api/health يستجيب ولو كان تليجرام معطوباً — أساس نشرٍ صامد.

    اللوحة مكتبة قياسية (http.server) ولا تعتمد على تليجرام إطلاقاً،
    لذا فحص صحة Render يمرّ دائماً، ويبقى المنفذ مفتوحاً بينما البوت
    يعيد محاولة الاتصال. المنفذ 0 = «اختر منفذاً متاحاً» (ميزة في الكود).
    """
    from urllib.request import urlopen

    from stratig.web.server import Dashboard

    dash = Dashboard(getter=lambda: {}, host="127.0.0.1", port=0)
    assert dash.start() is True, "يجب أن تفتح اللوحة منفذها"
    try:
        body = urlopen(f"http://127.0.0.1:{dash.port}/api/health",
                       timeout=5).read().decode("utf-8")
        assert json.loads(body)["ok"] is True
    finally:
        dash.stop()


def test_asyncio_entrypoint_imports():
    """لا استيراد مكسور في نقطة الدخول (أكثر سبب صامت لفشل النشر)."""
    _load_main()


# ═══════════════ سياق بناء Docker (سبب فشل خدمة اللوحة) ═══════════════


def _docker_commands():
    """يستخرج أوامر الإقلاع من render.yaml بلا مكتبة YAML."""
    import re

    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    return re.findall(r"(?m)^\s*dockerCommand:\s*(.+?)\s*$", text)


def _dockerignore_patterns():
    """قواعد .dockerignore (نتجاهل الاستثناءات المسبوقة بـ !)."""
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines
            if ln.strip() and not ln.strip().startswith("#")
            and not ln.strip().startswith("!")]


def _ignored(rel_path: str, patterns) -> str | None:
    """هل يحجب .dockerignore هذا المسار (أو أحد آبائه)؟ يُعيد القاعدة."""
    import fnmatch

    parts = Path(rel_path).parts
    for i in range(len(parts)):
        prefix = "/".join(parts[: i + 1])
        for pattern in patterns:
            rule = pattern.rstrip("/")
            if fnmatch.fnmatch(prefix, rule) or fnmatch.fnmatch(
                    parts[i], rule):
                return pattern
    return None


def test_every_docker_command_target_survives_dockerignore():
    """أهم اختبار في هذا الملف — الخلل الذي أسقط خدمة اللوحة على Render.

    كان `.dockerignore` يستثني مجلد `scripts/`، بينما render.yaml يُشغّل
    `python scripts/dashboard.py` ⇒ الملف غير موجود داخل الصورة ⇒ can't open
    file ⇒ لا يفتح منفذ ⇒ يفشل فحص /api/health ⇒ «نشر فاشل» من اللحظة الأولى.
    """
    commands = _docker_commands()
    assert commands, "لم نجد dockerCommand في render.yaml"
    patterns = _dockerignore_patterns()

    for command in commands:
        targets = [tok for tok in command.split()
                   if tok.endswith(".py") and not tok.startswith("-")]
        assert targets, f"لا ملف بايثون في الأمر: {command}"
        for target in targets:
            assert (ROOT / target).exists(), f"الملف غير موجود أصلاً: {target}"
            rule = _ignored(target, patterns)
            assert rule is None, (
                f"⛔ `.dockerignore` يستثني `{target}` (القاعدة: {rule}) "
                f"لكن render.yaml يُشغّله — النشر سيفشل")


def test_no_secret_file_bakes_into_the_image():
    """الوجه الآخر للعملة: صورة Docker يجب ألا تحمل أي سرّ."""
    patterns = _dockerignore_patterns()
    assert ".env" in patterns, "يجب تجاهل .env عند بناء الصورة"
    assert ".env.*" in patterns, "يجب تجاهل نسخ .env الأخرى"
    # الاستثناء الوحيد المسموح: المثال الخالي من الأسرار
    assert "!.env.example" in (ROOT / ".dockerignore").read_text(encoding="utf-8")


def test_dockerfile_default_command_matches_blueprint():
    """CMD الافتراضي في Dockerfile يجب أن يطابق خدمة البوت."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["python", "main.py"]' in dockerfile
    assert any(cmd.strip() == "python main.py" for cmd in _docker_commands())
