-- How Rafii talks to one person (docs/design/rafii-live-agent/CONTRACTS.md, Contract 1): tone, detail, speaking
-- pace, voice, language and initiative, for written answers and voice alike. A person-level preference like the
-- others on the profile row (migration 011), so it follows the person across workspaces. The API stores only enum
-- values it validated (agent_runtime_v2/style.py); the database bounds the shape and the size. '{}' is the default
-- style. Grants are unchanged: the browser role keeps reading its own row (001) and gets no write.
alter table public.pr_profiles add column if not exists agent_style jsonb not null default '{}'::jsonb
  check (jsonb_typeof(agent_style)='object' and pg_column_size(agent_style) <= 512);
