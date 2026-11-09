# 🤖 Stratig — بوت تليجرام لتداول العقود الآجلة (Binance Testnet / Bybit)

استراتيجية **RSI + Williams %R** مع **تأكيد مزدوج**، تعمل على عقود USDT-M الآجلة،
ويتحكم بها **بوت تليجرام في وضع يدوي**: البوت يفحص السوق، يرسل لك الإشارة،
**وأنت تضغط ✅ للفتح أو ❌ للتجاهل**.

> ⚠️ **تنبيه**: هذا المشروع للتعلّم والتجربة. التداول بالرافعة المالية يضاعف الخسارة
> كما يضاعف الربح. ابدأ دائماً على **التيستنت** (أموال وهمية) وتحمّل مسؤولية قراراتك.

---

## ✨ المميزات

| الميزة | الشرح |
|---|---|
| 🧠 تأكيد مزدوج | لا إشارة إلا إذا اتّفق **RSI** و **Williams %R** على نفس الاتجاه |
| 🖐️ تحكم يدوي | البوت **يقترح**، وأنت تؤكد من تليجرام بأزرار ✅ / ❌ |
| 🔔 إشعارات فورية | إشارة، فتح صفقة، إغلاق، أخطاء، ملخص الحالة |
| 🧪 وضع المحاكاة | `dry_run` يمنع إرسال أي أمر حقيقي (للتجربة الآمنة) |
| 🔒 أمان | قائمة بيضاء للمستخدمين + رفض التشغيل الحقيقي دون `CONFIRM_LIVE_TRADING=1` |
| 🛡️ حماية تلقائية | لا تُترك صفقة بلا `وقف خسارة` — وإلا تُغلق فوراً |
| 🔁 منصتان | **Binance Futures** (افتراضي، مع التيستنت) و **Bybit** — بنفس الكود |
| ⚙️ إعدادات حيّة | عدّل كل شيء من `/set` بدون إعادة تشغيل (يُحفظ في `config.toml`) |
| 📊 إدارة مخاطرة | أقصى صفقات، حد يومي للصفقات، حد يومي للخسارة، فترة سمومية لكل رمز |

---

## 🚀 التشغيل السريع (Binance Testnet)

### 1) مفاتيح Binance التجريبية
1. ادخل إلى https://testnet.binancefuture.com وسجّل بحساب جوجل/فيسبوك.
2. من قائمة **API Key** أنشئ مفتاحاً جديداً (HMAC).
3. احتفظ بـ **API Key** و **Secret Key**.
4. (اختياري) اطلب رصيداً تجريبياً من الزر **Deposit / Faucet** داخل التيستنت.

### 2) بوت تليجرام
1. افتح [@BotFather](https://t.me/BotFather) ← `/newbot` ← اختر اسماً واسم مستخدم.
2. انسخ **التوكن**.
3. أرسل `/start` للبوت، ثم أرسل `/id` لتعرف معرّفك (chat id) — أو استخدم [@userinfobot](https://t.me/userinfobot).

### 3) ملف البيئة
```bash
cp .env.example .env
nano .env          # املأ القيم
```
```env
TELEGRAM_BOT_TOKEN=123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_IDS=123456789
EXCHANGE=binance
TESTNET=true
BINANCE_TESTNET_API_KEY=...
BINANCE_TESTNET_API_SECRET=...
```

### 4) التثبيت
```bash
python3 -m venv .venv
source .venv/bin/activate          # ويندوز: .venv\Scripts\activate
pip install -r requirements.txt
```
> لا حاجة لأي مصنّف C++ : الإعدادات TOML (مكتبة قياسية) والمؤشرات محسوبة داخلياً بـ pandas.

### 5) تحقّق ثم تشغيل
```bash
python main.py --check     # يتحقق من المفاتيح والاتصال (بدون تليجرام)
python main.py             # تشغيل البوت
```
افتح تليجرام وأرسل للبوت: `/start`

> جرّب أولاً: `python main.py --dry-run` (محاكاة كاملة بدون أوامر)،
> أو `python scripts/demo_scan.py` (عرض توضيحي على بيانات اصطناعية بدون إنترنت).

---

## 📱 أوامر البوت

| الأمر | الوظيفة |
|---|---|
| `/start` | ترحيب + لوحة الأزرار |
| `/status` | حالة البوت، آخر فحص، الإحصائيات، ربح اليوم |
| `/balance` | الرصيد (إجمالي / متاح / غير محقق) |
| `/positions` | الصفقات المفتوحة + زر إغلاق لكل صفقة |
| `/pnl` | ربح اليوم + آخر 50 صفقة |
| `/scan` | فحص السوق **الآن** (بدون انتظار الدورة) |
| `/settings` | عرض كل الإعدادات |
| `/set` | قائمة تفاعلية لتعديل إعداد — أو `/set tp 0.02` |
| `/symbols` | إدارة قائمة الرموز (تلقائي/يدوي، إضافة، حذف) |
| `/pause` · `/resume` | إيقاف / تشغيل الفحص التلقائي |
| `/close BTCUSDT` | إغلاق صفقة رمز محدد |
| `/closeall` | إغلاق كل الصفقات (مع تأكيد) |
| `/id` | معرّف محادثتك (لإضافته للقائمة البيضاء) |
| `/help` | كل الأوامر |

**مفاتيح `/set`**: `tp` `sl` `qty` `lev` `margin` `tf` `interval` `ttl`
`cooldown` `maxpos` `topn` `minnotional` `mode` `dryrun` `both`

أمثلة:
```
/set tp 2%          →  جني أرباح 2%
/set sl 0.01        →  وقف خسارة 1%
/set lev 5          →  رافعة 5x
/set maxpos 3       →  3 صفقات كحد أقصى
/set mode manual    →  رجوع للوضع اليدوي
```

### سير العمل في الوضع اليدوي
```
⏰ كل 120 ثانية → فحص كل الرموز
        ↓
🎯 RSI و Williams %R يتفقان على اتجاه واحد
        ↓
📨 رسالة إشارة + زرّان: [ ✅ فتح ] [ ❌ تجاهل ]
        ↓
👆 أنت تضغط ✅
        ↓
⚡ أمر ماركت + TP + SL تلقائياً   →   📨 رسالة تأكيد + زر [ إغلاق ]
```

---

## 🧠 الاستراتيجية

### RSI (مؤشر القوة النسبية)
```
شراء:  RSI[-3] < 30  و  RSI[-2] < 30  و  RSI[-1] > 30   (اختراق صاعد من تشبّع بيعي)
بيع:   RSI[-3] > 70  و  RSI[-2] > 70  و  RSI[-1] < 70   (كسر هابط من تشبّع شرائي)
```

### Williams %R
```
شراء:  W%R < -99.5                                   (تشبّع بيعي شديد)
       أو  W%R < -75 ويتقاطع صاعداً فوق EMA(24)
بيع:   W%R > -0.5                                    (تشبّع شرائي شديد)
       أو  W%R > -25 ويتقاطع هابطاً تحت EMA(24)
```

### الدمج (التأكيد المزدوج)
`strategy.require_both: true` → **يجب** أن يتفق المؤشران، وأي تعارض يُلغي الصفقة.

### حماية الصفقة
- TP/SL تُوضع كأوامر `TAKE_PROFIT_MARKET` / `STOP_MARKET` مع `closePosition=true`
  (أي تغلق كامل الصفقة تلقائياً عند التحقيق).
- إن فشل وضع **وقف الخسارة** → يُغلق المركز فوراً حمايةً للمال.

### أهم الإعدادات (config.toml)
| المسار | الافتراضي | المعنى |
|---|---|---|
| `strategy.timeframe` | `15m` | الإطار الزمني |
| `strategy.use_closed_candles` | `true` | الحساب على شمعة مكتملة (بدون إعادة رسم) |
| `strategy.require_both` | `true` | التأكيد المزدوج |
| `trade.qty_usdt` | `50` | حجم الصفقة |
| `trade.leverage` | `10` | الرافعة |
| `trade.take_profit_pct` / `stop_loss_pct` | `0.012` / `0.009` | الهدف / الوقف |
| `risk.max_positions` | `5` | أقصى صفقات مفتوحة |
| `scanner.interval_seconds` | `120` | كل كم يفحص البوت |
| `scanner.cooldown_seconds` | `1800` | منع تكرار الإشارة لنفس الرمز |
| `scanner.signal_ttl_seconds` | `900` | مدة صلاحية الإشارة قبل أن تنتهي |
| `execution.mode` | `manual` | `manual` (بتأكيدك) أو `auto` (تلقائي) |
| `safety.dry_run` | `false` | محاكاة بدون أوامر حقيقية |

---

## 🔁 التبديل إلى Bybit أو التداول الحقيقي

**Bybit** (نفس الكود، محوّل جاهز):
```toml
[exchange]
name = "bybit"
testnet = true        # https://testnet.bybit.com
```
مع مفاتيح `BYBIT_TESTNET_API_KEY` / `BYBIT_TESTNET_API_SECRET` في `.env`.

**التداول الحقيقي** (بعد تجربة طويلة على التيستنت — على مسؤوليتك):
```env
TESTNET=false
CONFIRM_LIVE_TRADING=1
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```
بدون `CONFIRM_LIVE_TRADING=1` يرفض البرنامج العمل على الشبكة الحقيقية.

---

## 🧩 بنية المشروع

```
stratig/
├── main.py                     # نقطة الدخول (--check / --dry-run)
├── config.toml                 # كل الإعدادات (يُعدَّل من تليجرام أيضاً)
├── .env                        # الأسرار فقط (غير مرفوع لـ Git)
├── requirements.txt
├── Dockerfile / docker-compose.yml / stratig-bot.service
├── stratig/
│   ├── config.py               # تحميل config.toml + .env
│   ├── utils.py                # أدوات مشتركة
│   ├── logging_setup.py
│   ├── exchanges/
│   │   ├── base.py             # الواجهة الموحّدة (+ حساب الكميات/الدقة)
│   │   ├── binance_futures.py  # Binance USDT-M (تيستنت + حقيقي)
│   │   └── bybit.py            # Bybit (pybit)
│   ├── strategy/
│   │   ├── indicators.py       # RSI + Williams %R
│   │   └── engine.py           # الدمج والتأكيد المزدوج
│   ├── services/
│   │   ├── trader.py           # الفحص، الإشارات، التنفيذ، المخاطرة
│   │   └── notifier.py         # إشعارات تليجرام
│   └── bot/
│       ├── telegram_bot.py     # الأوامر والأزرار
│       └── formatters.py       # نصوص الرسائل العربية
├── scripts/demo_scan.py        # تجربة بدون مفاتيح ولا إنترنت
└── tests/                      # 48 اختباراً
```

> ملفاتك الأصلية (`Derivatives.py` و `class/`) لم تُمسّ — الكود الجديد مستقل عنها.

---

## 🧪 الاختبارات
```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```
تغطي الاختبارات: المؤشرات، الدمج والتعارض، محوّل Binance (بعميل وهمي:
حساب الكميات، الحد الأدنى، TP/SL، الإغلاق الاضطراري)، الإعدادات،
ودورة المحرك الكاملة (إشارة → تأكيد → فتح → إغلاق، السمومية، الحدود اليومية).

---

## 🖥️ النشر الدائم

**systemd** (VPS):
```bash
sudo cp stratig-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/stratig-bot.service   # عدّل المسارات والمستخدم
sudo systemctl daemon-reload
sudo systemctl enable --now stratig
sudo journalctl -u stratig -f
```

**Docker**:
```bash
docker compose up -d --build
docker compose logs -f
docker compose restart        # بعد تعديل .env
```

---

## 🆘 استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| `مفاتيح API غير مضبوطة` | املأ `.env` ثم `python main.py --check` |
| البوت لا يرد | تأكد من التوكن، وأن معرّفك داخل `TELEGRAM_CHAT_IDS` (أو اتركه فارغاً) |
| لا تصل إشارات | أرسل `/start` للبوت أولاً، وتأكد أن الفحص يعمل (`/status` → يعمل 🟢) |
| `الحد الأدنى لقيمة الصفقة` | ارفع `trade.qty_usdt` (Binance يرفض أقل من ~20 USDT) |
| لا إشارات لفترة طويلة | طبيعي — التأكيد المزدوج نادر. جرّب `/set tf 5m` أو `/set both false` |
| `Timestamp for this request...` | اضبط وقت الجهاز (تزامن NTP) |

---

## ⚠️ إخلاء مسؤولية
هذا الكود مقدَّم للتعلّم والبحث، **بدون أي ضمان**. التداول بالهامش والرافعة
ينطوي على مخاطر عالية لخسارة رأس المال بالكامل. اختبر دائماً على التيستنت،
وابدأ بمبالغ صغيرة جداً، ولا تستثمر ما لا يمكنك تحمّل خسارته.
