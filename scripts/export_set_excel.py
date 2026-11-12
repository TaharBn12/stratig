"""يُصدّر كل أوامر /set إلى ملف Excel (.xlsx) — بالمكتبة القياسية وحدها.

    python scripts/export_set_excel.py
    python scripts/export_set_excel.py --out docs/set-commands.xlsx

لماذا بلا openpyxl؟ لأن المستودع متعمَّد أن يكون بايثون خالصة بلا أي مكتبة
مترجَمة، وألا تُضاف تبعية جديدة لأجل ملف يُولَّد مرة. و`.xlsx` في حقيقته
أرشيف ZIP من ملفات XML — نكتبه مباشرة بـ `zipfile`.

المصدر الوحيد للحقيقة هو `SET_KEYS` + `DEFAULT_CONFIG`، فلا تتقادم الورقة
عن الكود أبداً. (واختبار `tests/test_export_excel.py` يفحص ذلك.)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.bot.telegram_bot import SET_CHECKS, SET_KEYS   # noqa: E402
from stratig.config import Config                           # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "docs" / "stratig-set-commands.xlsx"

# المحتوى كله من المصدر المشترك (scripts/set_catalog.py) — لا نسخة ثانية
from scripts.set_catalog import (          # noqa: E402
    GUIDE_HEADERS,
    HEADERS,
    PROBE_VALUES,
    accepted_label,
    build_guide,
    build_rows,
    check_message,
    default_label,
    type_label,
)

# ═══════════════════════ كاتب XLSX مصغّر ═══════════════════════

class XlsxWriter:
    """يكتب .xlsx صالحاً بـ zipfile و XML — بلا أي تبعية خارجية."""

    def __init__(self) -> None:
        self.sheets: list[tuple[str, list[list], list[int]]] = []
        # نصوص مشتركة: Excel يخزّرها مرة واحدة ويشير إليها بالفهرس
        self._strings: dict[str, int] = {}

    # ── النصوص المشتركة ──
    def _sid(self, text: str) -> int:
        if text not in self._strings:
            self._strings[text] = len(self._strings)
        return self._strings[text]

    def add_sheet(self, name: str, rows: list[list], widths: list[int]) -> None:
        self.sheets.append((name, rows, widths))

    # ── أدوات ──
    @staticmethod
    def _col_letter(index: int) -> str:
        """1 ⇒ A · 27 ⇒ AA"""
        letters = ""
        while index > 0:
            index, rest = divmod(index - 1, 26)
            letters = chr(65 + rest) + letters
        return letters

    def _cell(self, ref: str, value, style: int) -> str:
        """خلية واحدة: رقم يُكتب رقماً، والباقي نصّاً مشتركاً."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
        text = "" if value is None else str(value)
        return f'<c r="{ref}" s="{style}" t="s"><v>{self._sid(text)}</v></c>'

    def _sheet_xml(self, rows: list[list], widths: list[int]) -> str:
        ncols = max((len(r) for r in rows), default=1)
        nrows = len(rows)
        dimension = f"A1:{self._col_letter(ncols)}{max(nrows, 1)}"

        cols = "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths))

        body = []
        for r, row in enumerate(rows, start=1):
            style = 1 if r == 1 else 2          # 1 = ترويسة · 2 = خلية بحدود
            cells = "".join(
                self._cell(f"{self._col_letter(c)}{r}", value, style)
                for c, value in enumerate(row, start=1))
            body.append(f'<row r="{r}">{cells}</row>')

        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="{dimension}"/>'
            # rightToLeft: الأعمدة تبدأ من اليمين لأن المحتوى عربي
            '<sheetViews><sheetView rightToLeft="1" workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/>'
            f'<cols>{cols}</cols>'
            f'<sheetData>{"".join(body)}</sheetData>'
            f'<autoFilter ref="{dimension}"/>'
            '</worksheet>'
        )

    def _shared_strings_xml(self) -> str:
        items = "".join(f"<si><t xml:space=\"preserve\">{escape(text)}</t></si>"
                        for text in self._strings)
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                f'count="{len(self._strings)}" uniqueCount="{len(self._strings)}">'
                f"{items}</sst>")

    @staticmethod
    def _styles_xml() -> str:
        """ترويسة عريضة بخلفية، وخلايا بحدود رقيقة والتفاف نصّ."""
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2">'
            '<font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font>'
            '</fonts>'
            '<fills count="3">'
            '<fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid">'
            '<fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill>'
            '</fills>'
            '<borders count="2">'
            '<border><left/><right/><top/><bottom/><diagonal/></border>'
            '<border>'
            '<left style="thin"><color rgb="FFBFBFBF"/></left>'
            '<right style="thin"><color rgb="FFBFBFBF"/></right>'
            '<top style="thin"><color rgb="FFBFBFBF"/></top>'
            '<bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border>'
            '</borders>'
            '<cellStyleXfs count="1">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0"'
            ' applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment vertical="center" wrapText="1"/></xf>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"'
            ' applyBorder="1" applyAlignment="1">'
            '<alignment vertical="top" wrapText="1"/></xf>'
            '</cellXfs>'
            '<cellStyles count="1">'
            '<cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>'
        )

    def save(self, path: Path) -> None:
        # تُبنى الترويسات أولاً حتى تُسجَّل نصوصها في الجدول المشترك
        sheet_xml = [self._sheet_xml(rows, widths) for _n, rows, widths in self.sheets]
        shared = self._shared_strings_xml()

        n_sheets = len(self.sheets)
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml"'
                ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, n_sheets + 1))
            + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '</Types>'
        )

        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )

        sheets_xml = "".join(
            f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>'
            for i, (name, _rows, _w) in enumerate(self.sheets, start=1))

        workbook = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{sheets_xml}</sheets></workbook>'
        )

        # rId1..n للأوراق، ثم الأنماط، ثم النصوص المشتركة
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
            f' Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, n_sheets + 1))
        rels += (
            f'<Relationship Id="rId{n_sheets + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
            ' Target="styles.xml"/>'
            f'<Relationship Id="rId{n_sheets + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"'
            ' Target="sharedStrings.xml"/>'
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{rels}</Relationships>'
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(path, "w", ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", root_rels)
            zf.writestr("xl/workbook.xml", workbook)
            zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            zf.writestr("xl/styles.xml", self._styles_xml())
            zf.writestr("xl/sharedStrings.xml", shared)
            for i, xml in enumerate(sheet_xml, start=1):
                zf.writestr(f"xl/worksheets/sheet{i}.xml", xml)


# ═══════════════════════ التشغيل ═══════════════════════

def export(path: Path = DEFAULT_OUT) -> Path:
    """يُصدّر الأوامر إلى `path` ويُعيده."""
    rows = build_rows()
    guide = build_guide()

    writer = XlsxWriter()
    writer.add_sheet("كل الأوامر", [HEADERS] + rows, [18, 20, 26, 12, 22, 14, 62])
    writer.add_sheet("الدليل السريع", [GUIDE_HEADERS] + guide, [18, 34, 78])
    writer.save(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="تصدير أوامر /set إلى Excel")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="مسار الملف الناتج")
    args = parser.parse_args(argv)

    path = export(Path(args.out))
    total = len(SET_KEYS)
    print(f"✅ كُتب {path}")
    print(f"   {total} أمراً في ورقة «كل الأوامر» + {len(build_guide())} بنداً في «الدليل السريع»")
    print(f"   أُنشئ: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
