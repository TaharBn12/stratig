"""فهرس أوامر /set — **مصدر واحد** لتوثيق Markdown وملف Excel.

لماذا ملف مشترك؟ لأن الوثيقتين كانتا ستُكتبان مرّتين (مرة باليد ومرة
بالتوليد)، وكل تكرار فرصة للانحراف عن الكود. الآن:
    scripts/set_catalog.py  ← المحتوى (من SET_KEYS + DEFAULT_CONFIG)
    scripts/export_set_docs.py  → docs/set-commands.md
    scripts/export_set_excel.py → docs/stratig-set-commands.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.bot.telegram_bot import (              # noqa: E402
    SET_CHECKS,
    SET_KEYS,
    volatility_preset,
)
from stratig.config import Config                   # noqa: E402

__all__ = [
    "GROUPS", "HEADERS", "GUIDE_HEADERS", "PROJECT_ROOT",
    "SET_CHECKS", "SET_KEYS", "volatility_preset",
    "type_label", "default_label", "accepted_label", "check_message",
    "PROBE_VALUES", "build_rows", "build_guide",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# تجميع الأوامر لعرضها — الترتيب هنا هو ترتيبها في الملفّين
GROUPS: list[tuple[str, list[str]]] = [
    ("الصفقة والمخارج", ["tp", "sl", "qty", "lev", "margin", "exit", "follow_exit",
                        "strict", "drift", "block_stale", "mode", "dryrun"]),
    ("الاستراتيجية", ["strategy", "tf", "both", "candles", "quality", "volmode",
                     "volmin", "volmax", "regime", "adxlen", "adxmin", "adxmax",
                     "mtf", "mtftf", "mtfema", "trend", "trendperiod"]),
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


def type_label(kind: str) -> str:
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


# قيم نجرّبها لاستخراج رسالة المجال: تحت الحد، وفوقه، والصفر
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
        except (TypeError, ValueError, OverflowError):
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
    """صفوف الورقة/الجدول: مجموعة واحدة لكل أمر."""
    cfg = Config({})
    rows: list[list] = []
    seen: set[str] = set()
    for group, keys in GROUPS:
        for key in keys:
            if key not in SET_KEYS:          # حماية: أمر حُذف من الكود
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
    """«الدليل السريع» — القواعد التي تمنع أخطاء الاستعمال."""
    return [
        ["طريقة الاستعمال", "الأمر والقيمة معاً", "/set tp 0.02 — الأسرع"],
        ["طريقة الاستعمال", "ثم القيمة", "/set tp  ثم أرسل 0.02 في رسالة تالية"],
        ["طريقة الاستعمال", "قائمة الأزرار", "/set  بلا قيمة ⇒ أزرار لكل الإعدادات"],
        ["قواعد القيم", "صح/خطأ", "true · false · 1 · 0 · yes · no · on · off · نعم · مفعّل"],
        ["قواعد القيم", "رقم عشري", "0.012  أو  1.2% (النسبة تُحوَّل تلقائياً)"],
        ["قواعد القيم", "خيارات", "واحدة فقط من القيم المذكورة، وإلا رسالة توضّح المسموح"],
        ["قواعد القيم", "الحفظ", "كل تعديل يُحفظ فوراً في config.toml ويُطبَّق بلا إعادة تشغيل"],
        ["مبدّل التقلّب", "/set volmode calm", "السوق الهادئ فقط — يستبعد ما فوق عتبة"],
        ["مبدّل التقلّب", "/set volmode volatile", "السوق المتقلّب فقط — يستبعد ما دون عتبة"],
        ["مبدّل التقلّب", "/set volmode band", "النطاق المعتدل بين العتبتين"],
        ["مبدّل التقلّب", "/set volmode off", "بلا فلتر — يتداول في كل الأحوال"],
        ["مبدّل التقلّب", "العتبات تُقاس على إطارك",
         "غيّرت tf؟ أعد /set volmode لتُحسب العتبات على الإطار الجديد"],
        ["مبدّل التقلّب", "quality يُفعَّل تلقائياً",
         "بدونه تُتجاهل volmin/volmax كلها بصمت — فعّلناه عنك"],
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
        ["أثر فوري", "/set volmode", "يضبط volmin و volmax معاً، ويفعّل quality"],
        ["أثر فوري", "/set tf",
         "يمسح «السمومية» عن كل الرموز (إلا لَمَا ظهرت إشارات الإطار الجديد قبل 30 دقيقة)"],
        ["أخطاء شائعة", "«إطار زمني غير مدعوم»", "اكتب 5m · 1h (يوَّحّد تلقائياً في الأغلب)"],
        ["أخطاء شائعة", "«إعداد غير معروف»", "الاسم خطأ — أرسل /set لترى القائمة"],
        ["أخطاء شائعة", "غيّرت tp/sl ولم يتغيّر شيء",
         "follow_exit = true افتراضياً ⇒ مخارج الاستراتيجية تطغى. اجعلها false إن أردت مخارجك"],
        ["أخطاء شائعة", "فلتر التقلّب لا يعمل",
         "quality = false ⇒ volmin/volmax/regime معطّلة. فعّل /set quality true (أو استخدم volmode)"],
        ["أخطاء شائعة", "/set supabase on بلا أثر", "اضبط supabaseurl و supabasekey أولاً"],
        ["أخطاء شائعة", "البوت يرفض التداول الحقيقي",
         "TESTNET=false بلا CONFIRM_LIVE_TRADING=1 — مقصود: حماية لا عطل"],
    ]
