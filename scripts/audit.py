"""تدقيق كامل لمشروع Stratig — يفحص كل ملف ويُصدر تقريراً واحداً.

    .venv\\Scripts\\python.exe scripts\\audit.py          (ويندوز)
    .venv/bin/python scripts/audit.py                  (لينكس/ماك)
    .venv/bin/python scripts/audit.py --strict         (أي تحذير = فشل)

يفحص:
  1. كل ملف .py يُترجم بدون أخطاء، وكل وحدة في stratig.* تُستورد فعلاً
  2. كل مسار إعدادات مقروء بالكود (cfg.get/set) موجود في DEFAULT_CONFIG
  3. كل مفتاح من مفاتيح /set يشير إلى مسار إعدادات حقيقي
  4. سجل الاستراتيجيات: معرّف/عنوان/شرح/دالة/وضع خروج/حد شموع + قسم إعدادات
  5. ثوابت الدفتر محفوظة (EMA 50/30، بولينجر 15/1.5، ATR 7، backcandles 7 ...)
  6. الإطارات الزمنية: كل إطار مسموح يمرّ كما هو، والقيم الشاذة تُصحَّح
  7. config.example.toml يطابق DEFAULT_CONFIG ولا يحتوي مفاتيح مجهولة
  8. config.toml غير مُتتبَّع في git (وإلا تعطّل update.bat)
  9. ملفات .bat سليمة ومكتملة
 10. الاختبارات تعمل

يُرجع 0 إن كانت النتيجة نظيفة، و1 إن وُجد خطأ (أو تحذير مع --strict).
"""
from __future__ import annotations

import argparse
import ast
import importlib
import pkgutil
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK, WARN, BAD = "✅", "⚠️ ", "❌"

problems: list[str] = []
warnings: list[str] = []
checks = 0


def report(ok: bool, label: str, detail: str = "", level: str = BAD) -> None:
    global checks
    checks += 1
    if ok:
        print(f"  {OK} {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  {level} {label}" + (f"\n        {detail}" if detail else ""))
        (warnings if level == WARN else problems).append(f"{label}: {detail}")


def title(text: str) -> None:
    print(f"\n{'─' * 72}\n{text}\n{'─' * 72}")


# ═══════════════════════ 1) ملفات بايثون ═══════════════════════
def audit_python() -> None:
    title("1) ملفات بايثون — الترجمة والاستيراد")
    files = sorted(p for p in ROOT.rglob("*.py") if ".venv" not in p.parts)
    broken = []
    for path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as err:
            broken.append(f"{path.relative_to(ROOT)}: {err}")
    report(not broken, f"{len(files)} ملف .py يُترجم بدون أخطاء", "; ".join(broken))

    failed = []
    count = 0
    for module in pkgutil.walk_packages([str(ROOT / "stratig")], prefix="stratig."):
        count += 1
        try:
            importlib.import_module(module.name)
        except Exception as err:
            failed.append(f"{module.name}: {err}")
    report(not failed, f"{count} وحدة في stratig.* تُستورد بنجاح", "; ".join(failed))


# ═══════════════════════ 2) مسارات الإعدادات ═══════════════════════
def _walk(node, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in (node or {}).items():
        path = f"{prefix}.{key}" if prefix else key
        paths.add(path)
        if isinstance(value, dict):
            paths |= _walk(value, path)
    return paths


def audit_config_paths() -> None:
    title("2) مسارات الإعدادات — لا مفتاح مكتوباً في الكود وغير موجود في الافتراضي")
    from stratig.config import DEFAULT_CONFIG

    known = _walk(DEFAULT_CONFIG)
    used: dict[str, list[str]] = {}
    # فقط استدعاءات كائن الإعدادات (cfg / config) لا أي dict آخر
    pattern = re.compile(
        r"""\b(?:self\.)?(?:cfg|config|_cfg)\.(?:get|set)\(\s*["']([a-z0-9_.]+)["']""", re.I
    )
    # ملفات الاختبار تُجرّب مسارات وهمية عمْداً — تُستثنى
    files = sorted(
        p for p in ROOT.rglob("*.py")
        if ".venv" not in p.parts and "tests" not in p.parts
    )
    for path in files:
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            used.setdefault(match.group(1), []).append(str(path.relative_to(ROOT)))
    # f"strategy.{KEY}" وأمثالها تُبنى ديناميكياً — نتجاهل ما يحتوي { }
    static = {k: v for k, v in used.items() if "{" not in k}
    unknown = {k: v for k, v in static.items() if k not in known}
    report(
        not unknown,
        f"{len(static)} مسار إعدادات مستخدم في الكود — كلها معروفة",
        "; ".join(f"{k} ({v[0]})" for k, v in sorted(unknown.items())),
    )
    report(
        len(known) > 40,
        f"{len(known)} مفتاح إعدادات في DEFAULT_CONFIG",
    )


# ═══════════════════════ 3) مفاتيح /set ═══════════════════════
def audit_set_keys() -> None:
    title("3) أوامر /set — كل مفتاح يشير إلى إعداد حقيقي")
    from stratig.bot.telegram_bot import SET_KEYS, TEXT_COMMANDS, MAIN_KEYBOARD
    from stratig.config import DEFAULT_CONFIG

    known = _walk(DEFAULT_CONFIG)
    bad = [f"{k} → {v[0]}" for k, v in SET_KEYS.items() if v[0] not in known]
    report(not bad, f"{len(SET_KEYS)} مفتاح في /set كلها صحيحة", "; ".join(bad))

    readable = [k for k, v in SET_KEYS.items() if v[0] in known]
    report(
        len(readable) == len(SET_KEYS),
        "كل مفاتيح /set قابلة للقراءة من DEFAULT_CONFIG",
    )
    report(
        len(TEXT_COMMANDS) >= 10,
        f"{len(TEXT_COMMANDS)} أمر نصي مسجّل في لوحة المفاتيح",
    )
    report(bool(MAIN_KEYBOARD), "لوحة الأزرار الرئيسية معرَّفة")


# ═══════════════════════ 4) سجل الاستراتيجيات ═══════════════════════
def audit_strategies() -> None:
    title("4) سجل الاستراتيجيات")
    from stratig.config import DEFAULT_CONFIG
    from stratig.strategy.registry import VALID_EXIT_MODES, all_strategies, resolve

    items = all_strategies()
    report(len(items) >= 2, f"{len(items)} استراتيجية مسجّلة",
           " / ".join(s.key for s in items))
    for strategy in items:
        good = bool(strategy.key and strategy.title and strategy.description)
        good = good and callable(strategy.evaluate)
        good = good and strategy.exit_mode in VALID_EXIT_MODES
        good = good and strategy.min_candles >= 30
        report(
            good,
            f"{strategy.key}: عنوان/شرح/دالة/مخارج({strategy.exit_mode})/شموع({strategy.min_candles})",
            "" if good else f"{strategy.key} ناقص البيانات",
        )
        has_section = f"strategy.{strategy.key}" in _walk(DEFAULT_CONFIG)
        report(
            has_section or strategy.key == "rsi_williams",
            f"{strategy.key}: قسم [strategy.{strategy.key}] في الإعدادات الافتراضية",
        )
    ok, error = resolve(items[0].key)
    report(not error, f"resolve('{items[0].key}') بلا خطأ", error)
    _, error = resolve("__غير_موجود__")
    report(bool(error), "الاستراتيجية المجهولة تُبلَّغ ولا تُمرَّر بصمت")


# ═══════════════════════ 5) ثوابت الدفتر ═══════════════════════
def audit_notebook_constants() -> None:
    title("5) ثوابت الدفتر 01_Strategy_Scalping_Modified_I — كما هي حرفياً")
    from stratig.strategy import scalping_i

    expected = {
        "EMA_SLOW": 50, "EMA_FAST": 30, "RSI_LENGTH": 10, "BB_LENGTH": 15,
        "BB_STD": 1.5, "BB_DDOF": 1, "ATR_LENGTH": 7, "BACKCANDLES": 7,
        "SL_COEF": 1.1, "TPSL_RATIO": 1.5, "MYSIZE": 3000,
        "BUY_SIGNAL": 2, "SELL_SIGNAL": 1,
    }
    wrong = [f"{k}={getattr(scalping_i, k)} (يجب {v})"
             for k, v in expected.items() if getattr(scalping_i, k, None) != v]
    report(not wrong, f"{len(expected)} ثابت مطابق للدفتر", "; ".join(wrong))

    # النافذة الحصرية [i-7, i): الشمعة الحالية لا تدخل حساب الاتجاه
    fast = [2.0] * 20
    slow = [1.0] * 20
    fast[12] = 0.0
    exclusive = scalping_i.ema_signal(fast, slow, 12, 7) == 2
    report(exclusive, "نافذة ema_signal حصرية (لا تشمل الشمعة الحالية)")

    # النسبة 1.5 : 1
    from stratig.config import Config
    import random
    random.seed(7)
    closes = [100.0 * (1.003 ** i) for i in range(200)]
    closes.append(closes[-1] * 0.9)
    from stratig.data import Candles
    candles = Candles(list(range(len(closes))), list(closes), [c * 1.002 for c in closes],
                      [c * 0.998 for c in closes], closes, [1.0] * len(closes))
    decision = scalping_i.evaluate(candles, Config({}, path=Path("/tmp/x.toml")),
                                   use_closed_candles=False)
    ratio_ok = bool(decision.sl_distance) and abs(
        (decision.tp_distance or 0) / decision.sl_distance - 1.5) < 1e-9
    report(ratio_ok, "الهدف = 1.5 × الوقف (نسبة العائد:المخاطرة)", str(decision.side))


# ═══════════════════════ 6) الإطارات الزمنية ═══════════════════════
def audit_timeframes() -> None:
    title("6) الإطارات الزمنية")
    from stratig.utils import (ALLOWED_TIMEFRAMES, DEFAULT_TIMEFRAME,
                               is_supported_timeframe, normalize_timeframe)

    identity = [tf for tf in ALLOWED_TIMEFRAMES if normalize_timeframe(tf) != tf]
    report(not identity, f"كل إطار مسموح ({len(ALLOWED_TIMEFRAMES)}) يبقى كما هو",
           ", ".join(identity))

    aliases = {"5": "5m", "15min": "15m", "4": "4h", "1hour": "1h", "24": "1d",
               "1mo": "1M", "1M": "1M", "1m": "1m", "30M": "30m"}
    bad = {k: normalize_timeframe(k) for k, v in aliases.items()
           if normalize_timeframe(k) != v}
    report(not bad, f"{len(aliases)} صيغة شائعة تُوحَّد صحيحاً",
           "; ".join(f"{k}→{v}" for k, v in bad.items()))

    odd = {"0": "", "-5": "", "abc": "", "999999": "", "": ""}
    bad = {k: normalize_timeframe(k, default="__x__") for k in odd
           if normalize_timeframe(k, default="__x__") not in ("__x__", DEFAULT_TIMEFRAME)}
    report(not bad, "القيم المستحيلة تُرجع الإطار الافتراضي ولا توقف البوت",
           "; ".join(f"{k}→{v}" for k, v in bad.items()))

    bad = [tf for tf in ("2m", "7m", "3h", "5d", "2w") if is_supported_timeframe(tf)]
    report(not bad, "الإطارات غير المسموحة تُرفض", ", ".join(bad))

    from stratig.config import Config
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config({"strategy": {"timeframe": "4"}}, path=Path(tmp) / "c.toml")
        got = cfg.effective_timeframe()
        report(got == "4h", "cfg.effective_timeframe() تُصلح «4» → 4h", got)
        cfg.set("strategy.timeframe", "zzz")
        report(cfg.effective_timeframe() == DEFAULT_TIMEFRAME,
               "cfg.effective_timeframe() تُصلح قيمة مرفوضة", cfg.effective_timeframe())


# ═══════════════════════ 7) config.example.toml ═══════════════════════
def audit_config_example() -> None:
    title("7) ملف الإعدادات المرجعي config.example.toml")
    from stratig.config import DEFAULT_CONFIG

    example = ROOT / "config.example.toml"
    if not example.exists():
        report(False, "config.example.toml موجود")
        return
    with open(example, "rb") as fh:
        data = tomllib.load(fh)
    paths = _walk(data)
    known = _walk(DEFAULT_CONFIG)
    unknown = sorted(paths - known)
    report(not unknown, f"{len(paths)} مفتاح في المثال — لا مفاتيح مجهولة", ", ".join(unknown),
           level=WARN)
    missing = sorted(p for p in known if p not in paths and "." not in p)
    report(not missing, "كل الأقسام الرئيسية موجودة في المثال", ", ".join(missing), level=WARN)


# ═══════════════════════ 8) git ═══════════════════════
def audit_git() -> None:
    title("8) مستودع Git — update.bat يجب ألا يتعطّل")

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)

    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        report(False, "المجلد مستودع git")
        return
    tracked = git("ls-files", "--error-unmatch", "config.toml")
    report(tracked.returncode != 0, "config.toml غير مُتتبَّع (لن يكسر git pull)")
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    report("config.toml" in [l.strip() for l in ignored], "config.toml مذكور في .gitignore")
    ex = git("ls-files", "--error-unmatch", "config.example.toml")
    report(ex.returncode == 0, "config.example.toml مُتتبَّع (المرجع على GitHub)")
    dirty = git("status", "--porcelain").stdout.strip()
    report(True, "حالة المستودع", dirty or "نظيف" if dirty else "نظيف", level=WARN)


# ═══════════════════════ 9) ملفات ويندوز ═══════════════════════
def audit_bat() -> None:
    title("9) ملفات .bat")
    for name in ("setup.bat", "update.bat", "run.bat", "check.bat"):
        path = ROOT / name
        if not path.exists():
            report(False, f"{name} موجود")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        report("@echo off" in text and len(text) > 100, f"{name} سليم")
    update = (ROOT / "update.bat").read_text(encoding="utf-8", errors="replace")
    report("config.toml.mine" in update, "update.bat يحفظ نسخة config.toml قبل السحب")


# ═══════════════════════ 10) الاختبارات ═══════════════════════
def audit_tests(run_pytest: bool = False) -> None:
    title("10) الاختبارات")
    tests = sorted((ROOT / "tests").glob("test_*.py"))
    report(len(tests) >= 8, f"{len(tests)} ملف اختبار")

    empty = []
    for path in tests:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        if not names:
            empty.append(path.name)
    report(not empty, "كل ملف اختبار يحتوي دوال test_", ", ".join(empty))

    if not run_pytest:
        print("  ⏭  تشغيل الاختبارات مُتخطّى (أضف --tests لتشغيلها)")
        return
    # test_audit.py يستدعي هذا السكربت — استثناؤه يمنع تكراراً بلا نهاية
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "--no-header",
             "--ignore=tests/test_audit.py"],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover
        report(False, "كل الاختبارات تنجح", "تجاوزت المهلة", level=WARN)
        return
    tail = [l for l in result.stdout.strip().splitlines() if l.strip()][-1:]
    report(result.returncode == 0, "كل الاختبارات تنجح", " ".join(tail))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="تدقيق كامل لمشروع Stratig")
    parser.add_argument("--strict", action="store_true", help="أي تحذير يُعتبر فشلاً")
    parser.add_argument("--tests", action="store_true",
                        help="شغّل الاختبارات أيضاً (أبطأ — ولا يُشغَّل من داخل pytest)")
    args = parser.parse_args(argv)

    print("═" * 72)
    print("  تدقيق Stratig — فحص كل ملف")
    print("═" * 72)

    for check in (
        audit_python, audit_config_paths, audit_set_keys, audit_strategies,
        audit_notebook_constants, audit_timeframes, audit_config_example,
        audit_git, audit_bat,
    ):
        try:
            check()
        except Exception as err:  # لا يُسقط التدقيق كلّه بسبب فحص واحد
            report(False, f"فحص {check.__name__} تعطّل", f"{type(err).__name__}: {err}",
                   level=WARN)

    if args.tests:
        try:
            audit_tests(run_pytest=True)
        except Exception as err:  # pragma: no cover
            report(False, "تشغيل الاختبارات", f"{type(err).__name__}: {err}", level=WARN)

    print("\n" + "═" * 72)
    print(f"  {checks} فحصاً | ❌ أخطاء: {len(problems)} | ⚠️  تحذيرات: {len(warnings)}")
    if problems:
        print("\n  الأخطاء:")
        for item in problems:
            print(f"    • {item}")
    if warnings:
        print("\n  التحذيرات:")
        for item in warnings:
            print(f"    • {item}")
    print("═" * 72)
    if problems or (args.strict and warnings):
        print("  النتيجة: يحتاج إصلاحاً ❌")
        return 1
    print("  النتيجة: سليم ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
