-- Supabase schema for Asgard lit-review pipeline orchestration.
-- Keeps jobs, presets, and streaming job events/artifacts.

create extension if not exists "uuid-ossp";

create table if not exists public.profiles (
    id uuid primary key default uuid_generate_v4(),
    auth_user_id uuid not null,
    email text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists public.presets (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null,
    name text not null,
    description text,
    config jsonb not null,
    is_default boolean default false,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists public.jobs (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null,
    title text,
    research_focus text,
    status text not null default 'queued', -- queued | running | completed | failed | cancelled
    config jsonb not null,
    input_uri text, -- storage URI or path to PDF dir
    output_uri text, -- storage prefix for outputs
    error text,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    started_at timestamptz,
    finished_at timestamptz
);

create table if not exists public.job_events (
    id bigserial primary key,
    job_id uuid not null references public.jobs(id) on delete cascade,
    event_type text not null, -- status | log | token | artifact
    message text,
    data jsonb,
    created_at timestamptz default now()
);

create table if not exists public.artifacts (
    id bigserial primary key,
    job_id uuid not null references public.jobs(id) on delete cascade,
    kind text not null, -- chunk_summary | agent_report | judge | lit_review | raw_response | media
    label text,
    path text not null,
    metadata jsonb,
    created_at timestamptz default now()
);

-- Row level security
alter table public.profiles enable row level security;
alter table public.presets enable row level security;
alter table public.jobs enable row level security;
alter table public.job_events enable row level security;
alter table public.artifacts enable row level security;

-- Profiles: each user can select/update their row; service role manages creation.
create policy if not exists "profiles_select_own"
    on public.profiles for select using (auth.uid() = auth_user_id);
create policy if not exists "profiles_update_own"
    on public.profiles for update using (auth.uid() = auth_user_id);

-- Presets: owner only.
create policy if not exists "presets_select_own"
    on public.presets for select using (auth.uid() = user_id);
create policy if not exists "presets_modify_own"
    on public.presets for all using (auth.uid() = user_id);

-- Jobs: owner only.
create policy if not exists "jobs_select_own"
    on public.jobs for select using (auth.uid() = user_id);
create policy if not exists "jobs_modify_own"
    on public.jobs for all using (auth.uid() = user_id);

-- Job events: owner only via job relation.
create policy if not exists "job_events_select_own"
    on public.job_events for select using (
        exists (select 1 from public.jobs j where j.id = job_id and j.user_id = auth.uid())
    );
create policy if not exists "job_events_insert_own"
    on public.job_events for insert with check (
        exists (select 1 from public.jobs j where j.id = job_id and j.user_id = auth.uid())
    );

-- Artifacts: owner only via job relation.
create policy if not exists "artifacts_select_own"
    on public.artifacts for select using (
        exists (select 1 from public.jobs j where j.id = job_id and j.user_id = auth.uid())
    );
create policy if not exists "artifacts_insert_own"
    on public.artifacts for insert with check (
        exists (select 1 from public.jobs j where j.id = job_id and j.user_id = auth.uid())
    );

-- Helpful indexes
create index if not exists idx_jobs_user_status on public.jobs (user_id, status);
create index if not exists idx_job_events_job_time on public.job_events (job_id, created_at);
create index if not exists idx_artifacts_job on public.artifacts (job_id);
