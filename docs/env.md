# 🔐 مرجع متغيرات البيئة (env)

كل ما يقرأه ستراتيج من البيئة. مصدره **فحص الكود نفسه**
(`os.getenv` في `stratig/` و `scripts/` و `main.py` ووظيفة Vercel).

> ⚠️ **لا تضع القيم الحقيقية في Git أبداً.** الملفات المسموح بها هي
> `.env` محلياً (مُتجاهَل في Git) و **Environment** في لوحة Render/Vercel.

---

## 1. تليجرام (مطلوبة)

| المتغير | مثال | من أين |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `123456:ABC-DEF...` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_IDS` | `123456789` أو `111,222` | أرسل `/id` للبوت، أو [@userinfobot](https://t.me/userinfobot) |

- البوت **لا يعمل** بدون التوكن (يخرج برسالة واضحة).
- `TELEGRAM_CHAT_IDS` فارغ ⇒ **أي شخص وجد البوت يتحكّم به**. لا تتركه فارغاً.

## 2. المنصة (اختيارية — لها افتراضات آمنة)

| المتغير | الافتراضي | الوصف |
|---|---|---|
| `EXCHANGE` | `binance` | `binance` أو `bybit` |
| `TESTNET` | `true` | `true` = أموال وهمية · `false` = حقيقي |
| `DRY_RUN` | `false` | `true` = إشارات على تليجرام **بلا أوامر** |
| `CONFIRM_LIVE_TRADING` | `0` | **يجب** `=1` للتداول الحقيقي — وإلا يرفض البوت التشغيل |

> **أمان مدمج:** إن كان `TESTNET=false` ولم تضبط `CONFIRM_LIVE_TRADING=1`
> يتوقف البوت ويشرح السبب. هذه حماية مقصودة، لا عطل.

## 3. مفاتيح المنصة (مطلوبة حسب الوضع)

### Binance
| المتغير | الوضع | من أين |
|---|---|---|
| `BINANCE_TESTNET_API_KEY`<br>`BINANCE_TESTNET_API_SECRET` | تيستنت | [testnet.binancefuture.com](https://testnet.binancefuture.com) |
| `BINANCE_API_KEY`<br>`BINANCE_API_SECRET` | حقيقي | [binance.com → API Management](https://www.binance.com/en/my/settings/api-management) |

### Bybit
| المتغير | الوضع | من أين |
|---|---|---|
| `BYBIT_TESTNET_API_KEY`<br>`BYBIT_TESTNET_API_SECRET` | تيستنت | [testnet.bybit.com](https://testnet.bybit.com) |
| `BYBIT_API_KEY`<br>`BYBIT_API_SECRET` | حقيقي | [bybit.com → API](https://www.bybit.com/user/api-management) |

- على التيستنت إن لم تضبط مفاتيح الاختبار، **يقع البوت تلقائياً** على
  المفاتيح الحقيقية — فانتبه (سلوك قديم محتفظ به للتوافق).
- **لا تعطِ المنصة صلاحية السحب (withdraw) أبداً.** التداول يكفي.

## 4. Supabase (الحالة المشتركة — مهم على Render)

| المتغير | سري؟ | من أين |
|---|---|---|
| `SUPABASE_URL` | لا | Settings → API → Project URL |
| `SUPABASE_KEY` | 🔴 **نعم** | Settings → API → **service_role** (للكتابة) |
| `SUPABASE_ANON_KEY` | 🟢 لا (للقراءة) | Settings → API → **anon / publishable** |
| `SUPABASE_BOT_ID` | لا | أي اسم تختاره · الافتراضي `default` |
| `BOT_ID` | لا | **مرادف** لـ `SUPABASE_BOT_ID` (اسم وظيفة Vercel) |
| `SUPABASE_ENABLED` | لا | `true/false` · يُشتغل تلقائياً إن وُجد الرابط والمفتاح |

```
SUPABASE_URL        = https://cazwkhcbkzhnsluuafwz.supabase.co
SUPABASE_BOT_ID     = render
SUPABASE_ANON_KEY   = من Settings → API → anon public
SUPABASE_KEY        = من Settings → API → service_role  (لا تكشفه)
```

> 🔒 **`SUPABASE_KEY` لا يخرج من الخدمة أبداً.** الذي يراه المتصفح هو
> `SUPABASE_ANON_KEY` فقط، و **RLS يمنعه من الكتابة** ولو وقع في أيدي الغير.
> إن تُرك `SUPABASE_ANON_KEY` فارغاً ⇒ `/api/config` يُعيد فراغاً وتعمل
> اللوحة محلياً. **الفشل الافتراضي آمن.**

## 5. الويب والنشر

| المتغير | الافتراضي | الوصف |
|---|---|---|
| `PORT` | `8000` | **تضبطه Render تلقائياً** — وجوده يعني «نحن على منصّة» فيُشغّل اللوحة وجوباً |
| `WEB_HOST` | `0.0.0.0` | عنوان الربط |
| `WEB_ENABLED` | `true` مع `PORT` | `false` لتعطيل اللوحة |
| `WEB_TOKEN` | فارغ | رمز حماية اللوحة · فارغ = **بلا حماية** |
| `LOG_LEVEL` | `INFO` | `DEBUG` للتشخيص |
| `KEEP_AWAKE` | `1` على Render | `0` لتعطيل النبضة |
| `KEEP_AWAKE_URL` | `RENDER_EXTERNAL_URL` | العنوان المنقور |
| `KEEP_AWAKE_INTERVAL` | `600` | بالثواني · الحد الأدنى 60 |

### تضبطها المنصّة (لا تكتبها يدوياً)
`RENDER` · `RENDER_EXTERNAL_URL` — تضبطهما Render بنفسها.

## 6. مسارات الملفات (نادراً تحتاجها)

| المتغير | الافتراضي |
|---|---|
| `STRATIG_CONFIG` | `config.toml` |
| `STRATIG_ENV` | `.env` |

---

## 📋 جاهز للنسخ

### Render → خدمة `stratig-bot`
```
EXCHANGE=binance
TESTNET=true
KEEP_AWAKE=1
LOG_LEVEL=INFO
SUPABASE_BOT_ID=render
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_IDS=
BINANCE_TESTNET_API_KEY=
BINANCE_TESTNET_API_SECRET=
SUPABASE_URL=https://cazwkhcbkzhnsluuafwz.supabase.co
SUPABASE_KEY=
SUPABASE_ANON_KEY=
WEB_TOKEN=
```

### Render → خدمة `stratig-dashboard` (أو Vercel)
```
SUPABASE_BOT_ID=render
SUPABASE_URL=https://cazwkhcbkzhnsluuafwz.supabase.co
SUPABASE_KEY=
SUPABASE_ANON_KEY=
WEB_TOKEN=
```
> على **Vercel** الأسماء نفسها تعمل (`BOT_ID` مقبول أيضاً) — لا حاجة لتكرارها.

---

## ✅ تحقّق سريع بعد النشر
```bash
curl https://stratig-bot-XXXX.onrender.com/api/health          # {"ok":true}
curl https://stratig-bot-XXXX.onrender.com/api/config          # url + مفتاح anon فقط
```
إن أرجعت `/api/config` مفتاحاً يبدو كـ `service_role` ⇒ **أوقف فوراً** وراجع
`SUPABASE_ANON_KEY`.
