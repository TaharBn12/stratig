"""يُولّد docs/set-commands.md من الكود — فلا يتقادم التوثيق أبداً.

    python scripts/export_set_docs.py

المحتوى من `scripts.set_catalog` (وهو بدوره من `SET_KEYS` +
`DEFAULT_CONFIG`)، فالمصدر واحد للـ Markdown ولملف Excel معاً.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.set_catalog import (
    GROUPS,
    PROJECT_ROOT,
    SET_KEYS,
    build_guide,
    volatility_preset,
)

DEFAULT_OUT = PROJECT_ROOT / "docs" / "set-commands.md"

PREAMBLE = """# ⚙️ شرح كل أوامر `/set`

**{count} أمراً**، مستخرجة تلقائياً من خريطة الإعدادات في الكود
(`SET_KEYS` في `stratig/bot/telegram_bot.py`) مع **القيم الافتراضية
الحقيقية** من `DEFAULT_CONFIG` — لا من التوثيق المكتوب يدوياً.

> 🔄 هذا الملف **مُولَّد** بـ `python scripts/export_set_docs.py`.
> عدّل الكود لا هذا الملف، ثم أعد التوليد (والاختبارات تُلزمك بذلك).

---

## كيف تستخدمه

ثلاث طرق، كلها متكافئة:

```text
/set tp 0.02          ← الأمر والقيمة معاً (الأسرع)
/set tp               ← ثم أرسل القيمة في رسالة تالية
/set                  ← قائمة أزرار بكل الإعدادات (اضغط ثم أرسل القيمة)
```

**قواعد القيم:**

| النوع | تقبل |
|---|---|
| `bool` | `true` `false` `1` `0` `yes` `no` `on` `off` **نعم** **مفعّل** |
| `float` | `0.012` أو `1.2%` (النسبة تُحوَّل تلقائياً) |
| `int` | أرقام صحيحة |
| خيارات | واحدة فقط من القيم المذكورة، وإلا رسالة خطأ توضّح المسموح |

> كل تعديل **يُحفظ فوراً في `config.toml`** ويُطبَّق بلا إعادة تشغيل
> (باستثناء ما يذكر خلاف ذلك). و`/set` يعرض لك القيمة القديمة والجديدة.
"""

VOLMODE_SECTION = """
---

## 🌊 مبدّل التقلّب — `/set volmode`

**هذا هو الأمر الذي يبدّل بين تتبع السوق المتقلّب بقوة والهادئ.**

```text
/set volmode calm        ← تتبّع السوق الهادئ فقط
/set volmode volatile    ← تتبّع السوق المتقلّب فقط
/set volmode band        ← النطاق المعتدل بينهما
/set volmode off         ← بلا فلتر (يتداول في كل الأحوال)
```

يضبط `volmin` و `volmax` **معاً** بعتبات محسوبة، و**يفعّل `quality`
تلقائياً** — لأن بدونه تُتجاهل العتبتان بصمت (وهو الفخّ الأخطر في البوت).

### لماذا عتبة نسبية لا رقم ثابت

قسنا التقلّب (**ATR%** بطريقة وايلدر 14 — نفس الدالّة التي يستخدمها الفلتر)
على **5 عملات × 15m × 60 يوماً = 1,105 قياس**:

| الإطار | p25 | p40 | p60 | p75 | الوسيط |
|---|---|---|---|---|---|
| 15m | 0.264% | 0.318% | 0.394% | 0.476% | 0.354% |
| 1h | 0.590% | 0.689% | 0.823% | 0.949% | 0.751% |

**وسيط التقلّب على 1h أكثر من ضعف وسيطه على 15m.** فعتبة واحدة ثابتة
(مثل 0.5%) تعني شيئاً مختلفاً تماماً على الإطارين: على 15m تحجب أغلب
السوق، وعلى 1h تحجب أقلّه. لذلك العتبات **تُقاس على إطارك**:

- خط أساس مُقاس على 15m،
- يُضرب في `√(دقائق الإطار ÷ 15)` — لأن التقلّب ينمو مع جذر الزمن،
  وقد تحقّقنا منه: توقّع 0.708% لوسيط 1h مقابل **0.751% فعلي (خطأ 5.8%)**.

**العتبات الناتجة:**

| الإطار | calm (أقصى) | volatile (أدنى) | band (من ← إلى) |
|---|---|---|---|
| 5m | 0.184% | 0.228% | 0.152% ← 0.275% |
| 15m | 0.318% | 0.394% | 0.264% ← 0.476% |
| 30m | 0.450% | 0.557% | 0.373% ← 0.673% |
| 1h | 0.636% | 0.788% | 0.528% ← 0.952% |
| 4h | 1.272% | 1.576% | 1.056% ← 1.904% |

> ⏱ **غيّرتَ الإطار؟** أعد `/set volmode ...` لتُحسب العتبات على الإطار
> الجديد (القيم تُحفظ كأرقام، فلا تُحدَّث تلقائياً).
"""

TAIL = """
---

## 🔒 تحقّقات مدمجة (تمنع القيم الخطرة)

| الأمر | المجال المسموح |
|---|---|
| `/set lev` | 1 → 125 |
| `/set tp` · `/set sl` | بين 0 و 1 (أو `2%`) |
| `/set qty` | أكبر من صفر |
| `/set interval` | 30 ثانية على الأقل |
| `/set ttl` | 60 ثانية على الأقل |
| `/set maxpos` | 1 → 50 |
| `/set topn` | 0 → 2000 (وصفر = كل العملات) |
| `/set maxsig` | 1 → 50 |
| `/set candles` | 50 → 5000 |
| `/set tf` | يُوَّحّد (`5` و `5min` و `5M` ⇒ `5m`) ويرفض غير المدعوم |

## ⚡ أوامر لها أثر فوري يتجاوز الحفظ

| الأمر | ماذا يحدث بعده مباشرة |
|---|---|
| `/set interval` | يُعيد جدولة الفحص فوراً |
| `/set topn` | يُبطل قائمة الرموز المخزّنة فتُجلب من جديد |
| `/set dryrun` | يُطبَّق على كائن المنصة **حالاً** |
| `/set strategy` | يبدّل الاستراتيجية ويُصلح تعارض المخارج |
| `/set volmode` | يضبط `volmin` و `volmax` معاً، ويفعّل `quality` |
| `/set exit` · `follow_exit` · `strict` · `candles` | يُعيد فحص **صرامة المخارج** ويُبلّغك بأي تعارض أُصلح |
| `/set tf` | **يمسح «السمومية»** عن كل الرموز — لولاها لَمَا ظهرت إشارات الإطار الجديد قبل 30 دقيقة |

## 🧭 أوامر أخرى غير `/set` (للسياق)

`/start` · `/help` · `/settings` (قائمة) · `/pause` · `/resume` · `/live` ·
`/dryrun` · `/stats` · `/edge` · `/recommended` · `/dashboard` · `/id`

> `/recommended` يضبط **الإعدادات المُوصى بها** دفعة واحدة بدل تعديل كل
> أمر على حدة — أنصح به كنقطة بداية.
"""


def render() -> str:
    """يبني نصّ الملف كاملاً."""
    from scripts.set_catalog import HEADERS, build_rows

    rows = build_rows()
    guide = build_guide()

    out = [PREAMBLE.format(count=len(SET_KEYS))]

    # ── الجداول حسب المجموعة ──
    by_group: dict[str, list[list]] = {}
    for row in rows:
        by_group.setdefault(row[0], []).append(row)
    order = [name for name, _keys in GROUPS] + ["أوامر أخرى"]

    out.append("\n## 📋 الأوامر (حسب المجموعة)\n")
    for group in order:
        if group not in by_group:
            continue
        out.append(f"\n### {group}\n")
        out.append("| " + " | ".join(HEADERS) + " |")
        out.append("|" + "---|" * len(HEADERS))
        for row in by_group[group]:
            cells = list(row)
            # الأمر ومسار الإعداد بصيغة الكود — أوضح في القراءة وأسهل بحثاً
            cells[1] = f"`{cells[1]}`"
            cells[2] = f"`{cells[2]}`"
            cells = [str(c).replace("|", "\\|") for c in cells]
            out.append("| " + " | ".join(cells) + " |")

    # ── مبدّل التقلّب ──
    out.append(VOLMODE_SECTION)

    # ── الدليل السريع ──
    out.append("\n---\n\n## 📖 الدليل السريع\n")
    out.append("| القسم | البند | التفاصيل |")
    out.append("|---|---|---|")
    for row in guide:
        cells = [str(c).replace("|", "\\|") for c in row]
        out.append("| " + " | ".join(cells) + " |")

    out.append(TAIL)
    out.append(f"\n<!-- مُولَّد آلياً · {len(SET_KEYS)} أمراً · "
               f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC -->")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="توليد docs/set-commands.md")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    print(f"✅ كُتب {path}")
    print(f"   {len(SET_KEYS)} أمراً")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
