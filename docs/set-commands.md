# ⚙️ شرح كل أوامر `/set`

**70 أمراً**، مستخرجة تلقائياً من خريطة الإعدادات في الكود
(`SET_KEYS` في `stratig/bot/telegram_bot.py`) مع **القيم الافتراضية
الحقيقية** من `DEFAULT_CONFIG` — لا من التوثيق المكتوب يدوياً.

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

### 💰 الصفقة والمخارج

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set tp` | `trade.take_profit_pct` | رقم عشري (أو `2%`) | `0.012` | جني الأرباح — مثال: 0.02 أو 2% |
| `/set sl` | `trade.stop_loss_pct` | رقم عشري (أو `2%`) | `0.009` | وقف الخسارة — مثال: 0.01 أو 1% |
| `/set qty` | `trade.qty_usdt` | رقم عشري (أو `2%`) | `50` | حجم الصفقة بالـ USDT — مثال: 50 |
| `/set lev` | `trade.leverage` | رقم صحيح | `10` | الرافعة المالية — مثال: 10 |
| `/set margin` | `trade.margin_mode` | `isolated` · `cross` | `isolated` | نوع الهامش |
| `/set exit` | `exit.mode` | `percent` · `atr` | `percent` | مخارج الصفقة: نسب ثابتة أم ATR |
| `/set follow_exit` | `exit.follow_strategy` | `true` / `false` | `true` | الصرامة: مخارج الاستراتيجية تطغى على exit.mode (true / false) |
| `/set strict` | `exit.strict` | `true` / `false` | `true` | الصرامة: ارفض فتح صفقة بمخارج لا تنتمي للاستراتيجية (true / false) |
| `/set drift` | `execution.max_entry_drift` | رقم عشري (أو `2%`) | `1.0` | أقصى انحراف مسموح عن سعر الإشارة كنسبة من الوقف (1.0 = وقف كامل) |
| `/set block_stale` | `execution.block_stale_entry` | `true` / `false` | `false` | ارفض الدخول المتأخّر بدل التحذير فقط (true / false) |
| `/set mode` | `execution.mode` | `manual` · `auto` | `manual` | وضع التنفيذ |
| `/set dryrun` | `safety.dry_run` | `true` / `false` | `false` | المحاكاة (لا تُرسل أوامر حقيقية) |

### 🧠 الاستراتيجية

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set strategy` | `strategy.name` | `rsi_williams` · `scalping_i` | `rsi_williams` | الاستراتيجية المستخدمة |
| `/set tf` | `strategy.timeframe` | نص | `15m` | الإطار الزمني — مثال: 15m أو 1h |
| `/set both` | `strategy.require_both` | `true` / `false` | `true` | التأكيد المزدوج (RSI + Williams %R) |
| `/set candles` | `strategy.candles` | رقم صحيح | `500` | عدد الشموع المجلوبة لكل رمز — مثال: 500 |
| `/set quality` | `strategy.quality_enabled` | `true` / `false` | `false` | فلاتر الجودة: نظام السوق + MTF + تقلّب |
| `/set regime` | `strategy.regime` | `off` · `trend` · `range` | `off` | نظام السوق المسموح: off = الكل · trend = اتجاهي فقط · range = جانبي فقط |
| `/set adxlen` | `strategy.adx_length` | رقم صحيح | `14` | فترة ADX — مثال: 14 |
| `/set adxmin` | `strategy.adx_trend_min` | رقم عشري (أو `2%`) | `25.0` | أدنى ADX لاعتبار السوق متّجهاً — 25 |
| `/set adxmax` | `strategy.adx_range_max` | رقم عشري (أو `2%`) | `20.0` | أقصى ADX لاعتبار السوق جانبياً — 20 |
| `/set mtf` | `strategy.mtf_enabled` | `true` / `false` | `false` | تأكيد الإطار الأعلى قبل الدخول |
| `/set mtftf` | `strategy.mtf_timeframe` | نص | `1h` | الإطار الأعلى للتأكيد — مثال: 1h |
| `/set mtfema` | `strategy.mtf_ema_period` | رقم صحيح | `50` | فترة متوسط الإطار الأعلى — 50 |
| `/set volmin` | `strategy.volatility_min_pct` | رقم عشري (أو `2%`) | `0.0` | أدنى تقلّب مسموح (ATR%) — مثال: 0.003 |
| `/set volmax` | `strategy.volatility_max_pct` | رقم عشري (أو `2%`) | `0.0` | أقصى تقلّب مسموح (ATR%) — مثال: 0.02 |
| `/set trend` | `strategy.trend_filter` | `off` · `ema` | `off` | فلتر الاتجاه: off = حرفي · ema = ارفض الإشارات عكس الاتجاه العام |
| `/set trendperiod` | `strategy.trend_period` | رقم صحيح | `200` | فترة EMA لفلتر الاتجاه — مثال: 200 |

### ⚙️ معاملات scalping_i

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set sifast` | `strategy.scalping_i.ema_fast` | رقم صحيح | `30` | scalping_i: EMA سريع — 30 |
| `/set sislow` | `strategy.scalping_i.ema_slow` | رقم صحيح | `50` | scalping_i: EMA بطيء — 50 |
| `/set sirsilen` | `strategy.scalping_i.rsi_length` | رقم صحيح | `10` | scalping_i: فترة RSI — 10 |
| `/set sibb` | `strategy.scalping_i.bb_length` | رقم صحيح | `15` | scalping_i: فترة بولينجر — 15 |
| `/set sibbstd` | `strategy.scalping_i.bb_std` | رقم عشري (أو `2%`) | `1.5` | scalping_i: انحراف بولينجر — 1.5 |
| `/set siatr` | `strategy.scalping_i.atr_length` | رقم صحيح | `7` | scalping_i: فترة ATR — 7 |
| `/set sibc` | `strategy.scalping_i.backcandles` | رقم صحيح | `7` | scalping_i: شموع النظر للخلف — 7 |
| `/set sisl` | `strategy.scalping_i.sl_coef` | رقم عشري (أو `2%`) | `1.1` | scalping_i: معامل الوقف — 1.1 |
| `/set sitp` | `strategy.scalping_i.tp_sl_ratio` | رقم عشري (أو `2%`) | `1.5` | scalping_i: نسبة الهدف للوقف — 1.5 |

### ⚙️ معاملات rsi_williams

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set rsiper` | `strategy.rsi.period` | رقم صحيح | `14` | rsi_williams: فترة RSI — 14 |
| `/set rsios` | `strategy.rsi.oversold` | رقم عشري (أو `2%`) | `30` | rsi_williams: تشبّع بيعي — 30 |
| `/set rsiob` | `strategy.rsi.overbought` | رقم عشري (أو `2%`) | `70` | rsi_williams: تشبّع شرائي — 70 |
| `/set rsilook` | `strategy.rsi.lookback` | رقم صحيح | `3` | rsi_williams: شموع النظر للخلف — 3 |
| `/set wper` | `strategy.williams_r.lbp` | رقم صحيح | `24` | rsi_williams: فترة وليامز — 24 |
| `/set wos` | `strategy.williams_r.oversold` | رقم عشري (أو `2%`) | `-75` | rsi_williams: وليامز تشبّع بيعي — -75 |
| `/set wob` | `strategy.williams_r.overbought` | رقم عشري (أو `2%`) | `-25` | rsi_williams: وليامز تشبّع شرائي — -25 |
| `/set wema` | `strategy.williams_r.ema_window` | رقم صحيح | `24` | rsi_williams: نافذة تنعيم وليامز — 24 |

### 🔎 الفحص (الماسح)

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set interval` | `scanner.interval_seconds` | رقم صحيح | `120` | مدة الفحص بالثواني — مثال: 120 |
| `/set ttl` | `scanner.signal_ttl_seconds` | رقم صحيح | `900` | مدة صلاحية الإشارة بالثواني — مثال: 900 |
| `/set cooldown` | `scanner.cooldown_seconds` | رقم صحيح | `1800` | فترة السمومية لكل رمز بالثواني — مثال: 1800 |
| `/set topn` | `scanner.top_n` | رقم صحيح | `40` | عدد الرموز المفحوصة — 0 = كل العملات |
| `/set maxsig` | `scanner.max_signals_per_scan` | رقم صحيح | `5` | أقصى إشارات في الفحص الواحد — مثال: 5 |

### 🛡 إدارة المخاطرة

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set maxpos` | `risk.max_positions` | رقم صحيح | `5` | أقصى عدد صفقات مفتوحة — مثال: 5 |
| `/set minnotional` | `risk.min_notional` | رقم عشري (أو `2%`) | `20` | أدنى قيمة للصفقة بالـ USDT — مثال: 20 |
| `/set sizing` | `risk.sizing` | `fixed` · `risk` | `fixed` | حجم الصفقة: fixed = ثابت · risk = خسارة ثابتة = نسبة من الرصيد |
| `/set riskpct` | `risk.risk_per_trade_pct` | رقم عشري (أو `2%`) | `0.01` | نسبة المخاطرة من الرصيد لكل صفقة — مثال: 0.01 (1%) |
| `/set maxqty` | `risk.max_qty_usdt` | رقم عشري (أو `2%`) | `0` | أقصى قيمة للصفقة بالـ USDT (0 = بلا حد) |
| `/set maxtrades` | `risk.max_trades_per_hour` | رقم صحيح | `0` | أقصى صفقات في الساعة (0 = بلا حد) |
| `/set mingap` | `risk.min_gap_seconds` | رقم صحيح | `0` | فاصل إلزامي بين صفقتين بالثواني |
| `/set maxlosses` | `risk.max_consecutive_losses` | رقم صحيح | `0` | قاطع: أوقف التداول بعد كم خسارة متتالية (0 = معطّل) |
| `/set pauseloss` | `risk.pause_after_losses_seconds` | رقم صحيح | `3600` | مدة الإيقاف بالثواني بعد القاطع |

### 📊 مقياس الميزة (Edge)

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set edge` | `edge.enabled` | `true` / `false` | `true` | مقياس الميزة في /edge |
| `/set edgegate` | `edge.gate` | `true` / `false` | `false` | منع التداول عند ثبوت الخسارة إحصائياً |
| `/set edgemin` | `edge.min_trades` | رقم صحيح | `30` | أدنى صفقات قبل إصدار حكم — 30 |
| `/set edgelook` | `edge.lookback` | رقم صحيح | `0` | 0 = كل الصفقات، وإلا آخر N صفقة |

### 🌐 اللوحة و Supabase

| الأمر | الإعداد | القيم المقبولة | الافتراضي | الشرح |
|---|---|---|---|---|
| `/set webenable` | `web.enabled` | `true` / `false` | `false` | لوحة التحكم على جهازك |
| `/set webport` | `web.port` | رقم صحيح | `8000` | منفذ لوحة التحكم — مثال: 8000 |
| `/set webtoken` | `web.token` | نص | *(فارغ)* | رمز حماية اللوحة (فارغ = بلا حماية) |
| `/set supabase` | `supabase.enabled` | `true` / `false` | `false` | رفع البيانات إلى Supabase |
| `/set supabaseurl` | `supabase.url` | نص | *(فارغ)* | رابط مشروع Supabase |
| `/set supabasekey` | `supabase.key` | نص | *(فارغ)* | المفتاح السرّي لـ Supabase |
| `/set botid` | `supabase.bot_id` | نص | `default` | معرّف البوت في Supabase |

<!-- العدد الكلي: 70 -->

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
| `/set dryrun` | يُطبَّق على كائن المنصة **حالاً** (وإلا بقيت الأوامر محاكاة حتى إعادة التشغيل) |
| `/set strategy` | يبدّل الاستراتيجية ويُصلح تعارض المخارج |
| `/set exit` · `follow_exit` · `strict` · `candles` | يُعيد فحص **صرامة المخارج** ويُبلّغك بأي تعارض أُصلح |
| `/set tf` | **يمسح «السمومية»** عن كل الرموز — لولاها لَمَا ظهرت إشارات الإطار الجديد قبل 30 دقيقة |

## ⚠️ أخطاء شائعة

| العَرَض | السبب | العلاج |
|---|---|---|
| «إطار زمني غير مدعوم» | كتبت `5min` أو `1H` | اكتب `5m` · `1h` (يُوَّحّد تلقائياً في الأغلب) |
| «إعداد غير معروف» | اسم الأمر خطأ | أرسل `/set` لترى القائمة كاملة |
| غيّرت `tp`/`sl` ولم يتغيّر شيء | `follow_exit = true` (**الافتراضي**) ⇒ مخارج الاستراتيجية تطغى | اجعلها `false` إن أردت مخارجك اليدوية |
| `/set supabase on` بلا أثر | الرابط أو المفتاح فارغ | اضبط `supabaseurl` و `supabasekey` أولاً |
| فلاتر الجودة لا تعمل | `quality = false` ⇒ **`regime`/`volmin`/`volmax` معطّلة** | `/set quality true` أولاً — **وهو الفخّ الأخطر** |
| البوت يرفض التداول الحقيقي | `TESTNET=false` بلا `CONFIRM_LIVE_TRADING=1` | مقصود: حماية لا عطل |

## 🧭 أوامر أخرى غير `/set` (للسياق)

`/start` · `/help` · `/settings` (قائمة) · `/pause` · `/resume` · `/live` ·
`/dryrun` · `/stats` · `/edge` · `/recommended` · `/dashboard` · `/id`

> `/recommended` يضبط **الإعدادات المُوصى بها** دفعة واحدة بدل تعديل كل
> أمر على حدة — أنصح به كنقطة بداية.
