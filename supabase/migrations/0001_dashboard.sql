-- لوحة تحكم ستراتيج: حالة البوت + سجل الصفقات
-- نُفّذت على مشروع Supabase (ترحيل: stratig_dashboard)

create table if not exists bot_state (
  bot_id      text primary key,
  updated_at  timestamptz not null default now(),
  payload     jsonb not null
);

create table if not exists bot_trades (
  id          bigint generated always as identity primary key,
  bot_id      text not null,
  symbol      text not null,
  side        text,
  pnl         double precision default 0,
  r_multiple  double precision default 0,
  opened_at   timestamptz,
  closed_at   timestamptz,
  strategy    text,
  constraint bot_trades_unique unique (bot_id, symbol, closed_at)
);

create index if not exists bot_trades_bot_idx
  on bot_trades (bot_id, closed_at desc);

-- الحماية: RLS مفعّل، والقراءة مسموحة للوحة فقط.
-- الكتابة تتم بالمفتاح السرّي (service_role) الذي يتجاوز RLS.
alter table bot_state  enable row level security;
alter table bot_trades enable row level security;

drop policy if exists "anon read bot_state" on bot_state;
create policy "anon read bot_state" on bot_state for select to anon using (true);

drop policy if exists "anon read bot_trades" on bot_trades;
create policy "anon read bot_trades" on bot_trades for select to anon using (true);
