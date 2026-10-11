-- Ejecutar una vez en Supabase > SQL Editor. Admite varios fondos (calidad, catalizadores).
create table if not exists fund_state (
  fund_id text primary key,
  cash numeric not null,
  initial_capital numeric not null,
  inception date,
  pending jsonb default '[]'::jsonb,
  updated_at timestamptz
);

create table if not exists positions (
  fund_id text not null,
  ticker text not null,
  shares numeric not null,
  avg_cost numeric not null,
  opened_at date,
  last_price numeric,
  name text,
  sector text,
  stop numeric,
  extra jsonb,
  primary key (fund_id, ticker)
);

create table if not exists fundamentals (
  ticker text primary key,
  data jsonb,
  updated_at timestamptz
);

create table if not exists trades (
  id bigserial primary key,
  fund_id text not null,
  date date not null,
  ticker text not null,
  side text not null,
  shares numeric,
  price numeric,
  value numeric,
  cost numeric,
  reason text,
  auto boolean default false,
  created_at timestamptz default now()
);
create index if not exists trades_fund_idx on trades (fund_id, id desc);

create table if not exists nav_history (
  fund_id text not null,
  date date not null,
  nav numeric not null,
  cash numeric,
  n_positions int,
  bench jsonb,
  primary key (fund_id, date)
);

create table if not exists daily_reports (
  fund_id text not null,
  date date not null,
  market_view text,
  notes text,
  decisions jsonb,
  rejected jsonb,
  model text,
  usage jsonb,
  primary key (fund_id, date)
);

-- Seguridad: el bot escribe con la service key; el panel solo puede leer.
do $$
declare t text;
begin
  foreach t in array array['fund_state','positions','trades','nav_history','daily_reports'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "lectura publica" on %I', t);
    execute format('create policy "lectura publica" on %I for select to anon using (true)', t);
  end loop;
end $$;
alter table fundamentals enable row level security;
