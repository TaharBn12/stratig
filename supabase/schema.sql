-- ─────────────────────────────────────────────────────────────────────────────
-- ستراتيج — مخطط الحالة المشتركة على Supabase
--
-- لماذا نحتاجه؟ قرص الخدمة المجانية على Render **مؤقّت**: أي ملف يُكتب داخل
-- الحاوية يضيع مع إعادة النشر أو النوم. فالبوت «يدفع» صفقاته إلى هنا،
-- واللوحة (على Render أو Vercel أو هاتفك) تقرأها من هنا.
--
-- كيف تنفّذه؟ افتح Supabase → SQL Editor → الصق هذا الملف → Run.
-- الملف آمن للتكرار (IF NOT EXISTS في كل مكان).
-- ─────────────────────────────────────────────────────────────────────────────

-- ── 1. الحالة الحية: صف واحد لكل بوت ─────────────────────────────────────────
create table if not exists public.bot_state (
  bot_id     text primary key,
  updated_at timestamptz,
  payload    jsonb not null default '{}'::jsonb
);

-- ── 2. سجل الصفقات ───────────────────────────────────────────────────────────
create table if not exists public.bot_trades (
  id         bigint generated always as identity primary key,
  bot_id     text not null default 'default',
  symbol     text not null default '',
  side       text not null default '',
  pnl        double precision,
  r_multiple double precision,
  opened_at  timestamptz,
  closed_at  timestamptz,
  strategy   text not null default ''
);

-- القيد الذي يجعل «تجاهل المكرّر» يعمل: البوت يرفع نفس الصفقة أكثر من مرة
-- (كل دقيقة)، وبدون هذا القيد تتضاعف الصفقات في كل مرة.
-- (عبارة ON CONFLICT في PostgREST تحتاج فهرساً فريداً مطابقاً.)
create unique index if not exists bot_trades_dedup
  on public.bot_trades (bot_id, symbol, closed_at);

create index if not exists bot_trades_bot_closed
  on public.bot_trades (bot_id, closed_at desc);

-- ── 3. الحماية (RLS) ─────────────────────────────────────────────────────────
-- المفتاح «القابل للنشر» (anon) يصل إلى المتصفح — أي شخص قد يقرأه من الصفحة.
-- لذلك الحماية الحقيقية ليست إخفاءه، بل منعه من الكتابة أو رؤية غير المسموح.
-- مفتاح service (الذي يستعمله البوت للكتابة) يتجاوز RLS تلقائياً.
alter table public.bot_state  enable row level security;
alter table public.bot_trades enable row level security;

drop policy if exists "bot_state readable"  on public.bot_state;
create policy "bot_state readable"  on public.bot_state
  for select using (true);

drop policy if exists "bot_trades readable" on public.bot_trades;
create policy "bot_trades readable" on public.bot_trades
  for select using (true);

-- لا سياسة insert/update ⇒ anon **لا يقدر على الكتابة أبداً**، حتى لو
-- وقع المفتاح في أيدي الغير. الكتابة حِكر على مفتاح service داخل الخدمة.

-- ═════════════════════════════════════════════════════════════════════════════
-- ✅ تحقّق سريع — يجب أن يُظهر الصفقات التي رفعها البوت:
--    select bot_id, count(*) from public.bot_trades group by 1;
-- ═════════════════════════════════════════════════════════════════════════════
