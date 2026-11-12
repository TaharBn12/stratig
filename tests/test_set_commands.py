"""انسجام أوامر /set: الكود · خريطة الأوامر · التوثيق.

الدافع: وجدنا `candles` مُعالَجاً داخل `_apply_setting` لكنه **غائب من
`SET_KEYS`** — فكان `/set candles` يُرفض كأنه غير موجود، بينما الكود جاهز
له. هذا النوع من الانحراف لا يظهر في مراجعة الكود، فنمنعه بالاختبارات.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from stratig.bot.telegram_bot import SET_KEYS
from stratig.config import Config

ROOT = Path(__file__).resolve().parents[1]
BOT_SOURCE = ROOT / "stratig" / "bot" / "telegram_bot.py"
DOCS = ROOT / "docs" / "set-commands.md"


def _keys_handled_in_apply() -> set[str]:
    """كل مفتاح يُقارَن به `key` داخل _apply_setting (مثل key == 'tf')."""
    tree = ast.parse(BOT_SOURCE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Name) and left.id == "key"):
            continue
        for comparator in node.comparators:
            if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                found.add(comparator.value)
            elif isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
                for item in comparator.elts:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        found.add(item.value)
    return found


def test_every_handled_key_is_a_valid_command():
    """أي مفتاح يعالجه الكود يجب أن يكون أمراً معرّفاً — وإلا صار ميتاً."""
    handled = _keys_handled_in_apply()
    assert handled, "لم يُعثر على مقارنات — تغيّر هيكل الكود؟"
    missing = sorted(k for k in handled if k not in SET_KEYS)
    assert not missing, (
        f"مفاتيح مُعالَجة في الكود لكنها غائبة من SET_KEYS (أوامر ميتة): {missing}")


def test_candles_command_is_wired():
    """اختبار مباشر للخطأ الذي وجدناه — لا يُحذف مستقبلاً."""
    assert "candles" in SET_KEYS
    path, kind, _hint = SET_KEYS["candles"]
    assert path == "strategy.candles"
    assert kind == "int"


def test_every_command_maps_to_known_config():
    cfg = Config({})
    for key, (path, _kind, _hint) in SET_KEYS.items():
        # Config.get يُعيد None للمسار غير المعروف — نريده أن يُعيد الافتراضي
        assert cfg.get(path, "__missing__") != "__missing__", (
            f"/set {key} يشير إلى مسار غير معروف: {path}")


def test_every_command_has_a_default_value():
    """عمود «الافتراضي» في التوثيق يُقرأ من هنا — لا نريد فراغات."""
    cfg = Config({})
    for key, (path, _kind, _hint) in SET_KEYS.items():
        assert cfg.get(path) is not None, f"/set {key} بلا قيمة افتراضية ({path})"


def test_command_names_are_lowercase_and_safe():
    for key in SET_KEYS:
        assert key == key.lower(), f"{key} يجب أن يكون صغيراً (الكود يحوّله لـ lower)"
        assert key.replace("_", "").isalnum(), f"{key} يحتوي رموزاً غير مدعومة"


def test_choice_commands_have_at_least_two_options():
    for key, (_path, kind, _hint) in SET_KEYS.items():
        if kind.startswith("choice:"):
            options = kind.split(":", 1)[1].split(",")
            assert len(options) >= 2, f"/set {key} خياراته أقل من اثنين"


def test_docs_cover_every_command():
    """التوثيق يُولَّد من الكود — إن أضفت أمراً ونسيت التوثيق، يفشل الاختبار."""
    if not DOCS.exists():
        pytest.fail("docs/set-commands.md مفقود")
    text = DOCS.read_text(encoding="utf-8")
    missing = [k for k in SET_KEYS if f"/set {k}`" not in text and f"/set {k} " not in text]
    assert not missing, f"أوامر غير موثّقة: {sorted(missing)}"


# صفوف الجدول المُولَّد فقط: | المجموعة | `/set key` | `path` | … — لا أمثلة النصّ
# (عمود المجموعة يسبق الأمر، لذا لا نثبّت بداية السطر على `/set`)
_DOC_ROW = re.compile(r"^\| [^|]+ \| `/set ([a-z_]+)` \| `[a-z0-9_.]+` \|")


def test_docs_command_count_matches_code():
    """كل أمر في الكود له صف في التوثيق، والعكس — بلا زيادة ولا نقصان."""
    text = DOCS.read_text(encoding="utf-8")
    documented = set()
    for line in text.splitlines():
        match = _DOC_ROW.match(line)
        if match:
            documented.add(match.group(1))
    assert documented == set(SET_KEYS), (
        f"فرق بين الكود والتوثيق: "
        f"في الكود فقط={sorted(set(SET_KEYS) - documented)} · "
        f"في التوثيق فقط={sorted(documented - set(SET_KEYS))}")


def test_no_duplicate_command_names():
    """الخريطة dict أصلاً، لكن نثبّت أن العدد يطابق المفاتيز الفريدة."""
    assert len(SET_KEYS) == len(set(SET_KEYS))


@pytest.mark.parametrize("key", sorted(SET_KEYS))
def test_command_hint_is_not_empty(key):
    _, _kind, hint = SET_KEYS[key]
    assert hint and hint.strip(), f"/set {key} بلا شرح يظهر للمستخدم"
