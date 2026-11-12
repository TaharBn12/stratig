"""اختبارات مُصدِّر Excel — الملف يجب ألا يتقادم عن الكود أبداً.

المُصدِّر مكتوب بالمكتبة القياسية وحدها (`zipfile` + XML)، لذا هذه
الاختبارات لا تحتاج openpyxl ولا أي تبعية.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from stratig.bot.telegram_bot import SET_CHECKS, SET_KEYS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
XLSX = PROJECT_ROOT / "docs" / "stratig-set-commands.xlsx"

pytest.importorskip  # لا تبعيات أصلاً — يبقى للتوضيح


def _sheet_rows(path: Path, sheet_index: int = 1) -> list[list[str]]:
    """يقرأ ورقة بلا openpyxl: يفكّ الضغط ويحلّل XML بـ ElementTree."""
    import xml.etree.ElementTree as ET

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        shared = [
            (node.text or "")
            for node in ET.fromstring(zf.read("xl/sharedStrings.xml")).findall(f"{ns}si/{ns}t")
        ]
        sheet = ET.fromstring(zf.read(f"xl/worksheets/sheet{sheet_index}.xml"))
    rows: list[list[str]] = []
    for row in sheet.findall(f"{ns}sheetData/{ns}row"):
        cells: list[str] = []
        for cell in row.findall(f"{ns}c"):
            value = cell.find(f"{ns}v")
            if value is None:
                cells.append("")
            elif cell.get("t") == "s":
                cells.append(shared[int(value.text)])
            else:
                cells.append(value.text or "")
        rows.append(cells)
    return rows


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> Path:
    """يُصدّر إلى ملف مؤقّت مرة واحدة لكل الاختبارات."""
    from scripts.export_set_excel import export

    out = tmp_path_factory.mktemp("xlsx") / "out.xlsx"
    export(out)
    return out


# ── الملف المرفوع مع المشروع ──

def test_committed_file_is_valid_zip():
    assert XLSX.exists(), "docs/stratig-set-commands.xlsx مفقود"
    with zipfile.ZipFile(XLSX) as zf:
        assert zf.testzip() is None
        names = set(zf.namelist())
    for required in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                     "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                     "xl/sharedStrings.xml",
                     "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"):
        assert required in names, f"جزء ناقص من الملف: {required}"


def test_committed_file_is_up_to_date(exported):
    """الأهم: الملف المرفوع يطابق الكود الحالي (لا يُنسى بعد تعديل أمر)."""
    fresh = _sheet_rows(exported)
    committed = _sheet_rows(XLSX)
    assert fresh == committed, (
        "docs/stratig-set-commands.xlsx قديم — أعد تشغيل "
        "python scripts/export_set_excel.py")


# ── المحتوى ──

def test_every_command_appears(exported):
    rows = _sheet_rows(exported)
    commands = {row[1] for row in rows[1:]}
    missing = {k for k in SET_KEYS if f"/set {k}" not in commands}
    assert not missing, f"أوامر غائبة من الملف: {sorted(missing)}"


def test_row_count_matches_commands(exported):
    rows = _sheet_rows(exported)
    assert len(rows) - 1 == len(SET_KEYS), (
        f"الملف فيه {len(rows) - 1} صفاً والكود فيه {len(SET_KEYS)} أمراً")


def test_headers_are_correct(exported):
    assert _sheet_rows(exported)[0] == [
        "المجموعة", "الأمر", "الإعداد (config.toml)", "النوع",
        "القيم المقبولة", "الافتراضي", "الشرح"]


def test_guide_sheet_has_content(exported):
    rows = _sheet_rows(exported, sheet_index=2)
    assert rows[0] == ["القسم", "البند", "التفاصيل"]
    assert len(rows) > 10
    sections = {row[0] for row in rows[1:]}
    assert {"طريقة الاستعمال", "قواعد القيم", "أثر فوري"} <= sections


# ── المجالات: المعروض = المطبَّق ──

def test_accepted_values_come_from_real_checks():
    """عمود «القيم المقبولة» يُقرأ من SET_CHECKS — لا من نسخة مكتوبة."""
    from scripts.export_set_excel import accepted_label, check_message

    for key, (_path, kind, _hint) in SET_KEYS.items():
        label = accepted_label(key, kind)
        assert label, f"/set {key} بلا «قيم مقبولة»"
        if key in SET_CHECKS and not kind.startswith("choice:"):
            # المعروض يجب أن يكون **رسالة الخطأ نفسها** المستخرجة من الكود
            expected = check_message(key)
            assert label == expected, (
                f"/set {key}: المعروض «{label}» لا يطابق ما يطبّقه البوت «{expected}»")


def test_choice_commands_show_all_options():
    from scripts.export_set_excel import accepted_label

    for key, (_path, kind, _hint) in SET_KEYS.items():
        if kind.startswith("choice:"):
            options = kind.split(":", 1)[1].split(",")
            label = accepted_label(key, kind)
            for option in options:
                assert option in label, f"/set {key} لا يعرض الخيار {option}"


def test_every_check_key_is_an_exported_command():
    """مجال بلا أمر = تحقّق ميت لا يصل إليه المستخدم."""
    assert set(SET_CHECKS) <= set(SET_KEYS), (
        f"مجالات بلا أوامر: {sorted(set(SET_CHECKS) - set(SET_KEYS))}")


# ── صلاحية الملف لأدوات الخارج ──

def test_opens_with_openpyxl(exported):
    """مقياس النجاح الحقيقي: أن يفتحه Excel فعلاً، لا أن يكون ZIP صالحاً."""
    openpyxl = pytest.importorskip("openpyxl")

    book = openpyxl.load_workbook(exported)
    assert book.sheetnames == ["كل الأوامر", "الدليل السريع"]
    sheet = book["كل الأوامر"]
    assert sheet.max_row == len(SET_KEYS) + 1
    assert sheet.max_column == 7
    # ترويسة مثبّتة + فلتر + اتجاه عربي
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref
    assert sheet.sheet_view.rightToLeft is True


def test_defaults_match_config(exported):
    """الافتراضي في الورقة = الافتراضي في الكود، حرفياً."""
    from stratig.config import Config

    cfg = Config({})
    rows = _sheet_rows(exported)
    for row in rows[1:]:
        path = row[2]
        shown = row[5]
        value = cfg.get(path)
        expected = ("" if value is None
                    else "true" if value is True
                    else "false" if value is False
                    else "(فارغ)" if value == ""
                    else str(value))
        assert shown == expected, f"{path}: الورقة «{shown}» والكود «{expected}»"
