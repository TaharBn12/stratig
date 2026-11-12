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

# نفس تجميع docs/set-commands.md — مصدر واحد للشرح في الاثنين
GROUPS: list[tuple[str, list[str]]] = [
    ("الصفقة والمخارج", ["tp", "sl", "qty", "lev", "margin", "exit", "follow_exit",
                        "strict", "drift", "block_stale", "mode", "dryrun"]),
    ("الاستراتيجية", ["strategy", "tf", "both", "candles", "quality", "regime",
                     "adxlen", "adxmin", "adxmax", "mtf", "mtftf", "mtfema",
                     "volmin", "volmax", "trend", "trendperiod"]),
    ("معاملات scalping_i", ["sifast", "sislow", "sirsilen", "sibb", "sibbstd",
                            "siatr", "sibc", "sisl", "sitp"]),
    ("معاملات rsi_williams", ["rsiper", "rsios", "rsiob", "rsilook",
                              "wper", "wos", "wob", "wema"]),
    ("الفحص (الماسح)", ["interval", "ttl", "cooldown", "topn", "maxsig"]),
    ("إدارة المخاطرة", ["maxpos", "minnotional", "sizing", "riskpct", "maxqty",
                        "maxtrades", "mingap", "maxlosses", "pauseloss"]),
    ("مقياس الميزة (Edge)", ["edge", "edgegate", "edgemin", "edgelook"]),
    ("اللوحة و Supabase", ["webenable", "webport", "webtoken", "supabase",
                           "supabaseurl", "supabasekey", "botid"]),
]

HEADERS = ["المجموعة", "الأمر", "الإعداد (config.toml)", "النوع",
           "القيم المقبولة", "الافتراضي", "الشرح"]

GUIDE_HEADERS = ["القسم", "البند", "التفاصيل"]


# ═══════════════════════ بناء البيانات ═══════════════════════

def type_label(kind: str) -> str:
    # «خيارات» فقط — القائمة نفسها تُعرض في عمود «القيم المقبولة»
    if kind.startswith("choice:"):
        return "خيارات"
    return {"bool": "صح/خطأ", "int": "رقم صحيح", "float": "رقم عشري",
            "str": "نص"}.get(kind, kind)


def default_label(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value) if value != "" else "(فارغ)"


# قيم نجرّبها لاستخراج رسالة المجال: تحت الحد، وفوق الحد، والصفر.
# (-1 تكشف الحد الأدنى في كل المجالات الموجودة حالياً)
PROBE_VALUES = (-1, 10 ** 9, 0)


def check_message(key: str) -> str:
    """رسالة الخطأ التي يراها المستخدم عند قيمة خارجة عن المجال.

    نستخرجها من `SET_CHECKS` **نفسه** (لا من وصف مكتوب هنا)، فلا يعرض
    الملف مجالاً غير مطبَّق فعلاً. بعض التحقّقات (مثل cooldown >= 0)
    لا تُصدر رسالة إلا بقيمة تحت الحد — لذلك نجرّب أكثر من قيمة.
    """
    check = SET_CHECKS.get(key)
    if not callable(check):
        return ""
    for value in PROBE_VALUES:
        try:
            result = check(value)
        except (TypeError, ValueError, OverflowError):   # مجال لا يقبل السالب
            continue
        if result is not True and isinstance(result, str):
            return result
    return ""


def accepted_label(key: str, kind: str) -> str:
    """ما يقبله الأمر فعلاً — من نفس القاموس الذي يطبّقه البوت."""
    if kind.startswith("choice:"):
        return " · ".join(kind.split(":", 1)[1].split(","))
    if kind == "bool":
        return "true · false"
    return check_message(key) or {"int": "رقم صحيح", "float": "رقم عشري",
                                  "str": "نص"}.get(kind, kind)


def build_rows() -> list[list]:
    """صفوف ورقة «كل الأوامر» — مجموعة واحدة لكل أمر، مرتّبة بالتجميع."""
    cfg = Config({})
    rows: list[list] = []
    seen: set[str] = set()
    for group, keys in GROUPS:
        for key in keys:
            if key not in SET_KEYS:            # حماية: أمر حُذف من الكود
                continue
            seen.add(key)
            path, kind, hint = SET_KEYS[key]
            rows.append([group, f"/set {key}", path, type_label(kind),
                         accepted_label(key, kind),
                         default_label(cfg.get(path)), hint])
    # أي أمر أُضيف للكود ولم يُدرج في تجميع أعلاه ⇒ لا يضيع من الملف
    for key in SET_KEYS:
        if key in seen:
            continue
        path, kind, hint = SET_KEYS[key]
        rows.append(["أوامر أخرى", f"/set {key}", path, type_label(kind),
                     accepted_label(key, kind),
                     default_label(cfg.get(path)), hint])
    return rows


def build_guide() -> list[list]:
    """ورقة «الدليل السريع» — القواعد التي تمنع أخطاء الاستعمال."""
    guide: list[list] = [
        ["طريقة الاستعمال", "الأمر والقيمة معاً", "/set tp 0.02 — الأسرع"],
        ["طريقة الاستعمال", "ثم القيمة", "/set tp  ثم أرسل 0.02 في رسالة تالية"],
        ["طريقة الاستعمال", "قائمة الأزرار", "/set  بلا قيمة ⇒ أزرار لكل الإعدادات"],
        ["قواعد القيم", "صح/خطأ", "true · false · 1 · 0 · yes · no · on · off · نعم · مفعّل"],
        ["قواعد القيم", "رقم عشري", "0.012  أو  1.2% (النسبة تُحوَّل تلقائياً)"],
        ["قواعد القيم", "خيارات", "واحدة فقط من القيم المذكورة، وإلا رسالة توضّح المسموح"],
        ["قواعد القيم", "الحفظ", "كل تعديل يُحفظ فوراً في config.toml ويُطبَّق بلا إعادة تشغيل"],
        ["تحقّقات مدمجة", "/set lev", "1 ← 125"],
        ["تحقّقات مدمجة", "/set tp  ·  /set sl", "بين 0 و 1 (أو 2%)"],
        ["تحقّقات مدمجة", "/set qty", "أكبر من صفر"],
        ["تحقّقات مدمجة", "/set interval", "30 ثانية على الأقل"],
        ["تحقّقات مدمجة", "/set ttl", "60 ثانية على الأقل"],
        ["تحقّقات مدمجة", "/set maxpos", "1 ← 50"],
        ["تحقّقات مدمجة", "/set topn", "0 ← 2000 (وصفر = كل العملات)"],
        ["تحقّقات مدمجة", "/set maxsig", "1 ← 50"],
        ["تحقّقات مدمجة", "/set candles", "50 ← 5000"],
        ["تحقّقات مدمجة", "/set tf", "يوَّحّد (5 و 5min و 5M ⇒ 5m) ويرفض غير المدعوم"],
        ["أثر فوري", "/set interval", "يُعيد جدولة الفحص فوراً"],
        ["أثر فوري", "/set topn", "يبطل قائمة الرموز المخزّنة فتُجلب من جديد"],
        ["أثر فوري", "/set dryrun", "يُطبَّق على كائن المنصة حالاً"],
        ["أثر فوري", "/set strategy", "يبدّل الاستراتيجية ويُصلح تعارض المخارج"],
        ["أثر فوري", "/set exit · follow_exit · strict · candles",
         "يعيد فحص صرامة المخارج ويُبلّغك بأي تعارض أُصلح"],
        ["أثر فوري", "/set tf", "يمسح «السمومية» عن كل الرموز (إلا لَمَا ظهرت إشارات الإطار الجديد قبل 30 دقيقة)"],
        ["أخطاء شائعة", "«إطار زمني غير مدعوم»", "اكتب 5m · 1h (يوَّحّد تلقائياً في الأغلب)"],
        ["أخطاء شائعة", "«إعداد غير معروف»", "الاسم خطأ — أرسل /set لترى القائمة"],
        ["أخطاء شائعة", "غيّرت tp/sl ولم يتغيّر شيء",
         "follow_exit = true افتراضياً ⇒ مخارج الاستراتيجية تطغى. اجعلها false إن أردت مخارجك"],
        ["أخطاء شائعة", "/set supabase on بلا أثر", "اضبط supabaseurl و supabasekey أولاً"],
        ["أخطاء شائعة", "فلاتر الجودة لا تعمل",
         "quality = false ⇒ regime و volmin و volmax معطّلة تماماً. فعّل /set quality true أولاً"],
        ["أخطاء شائعة", "البوت يرفض التداول الحقيقي",
         "TESTNET=false بلا CONFIRM_LIVE_TRADING=1 — مقصود: حماية لا عطل"],
    ]
    return guide


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
