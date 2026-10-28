-- Bluesky launch watch (D5). Read-only. Production Supabase project buoyhkbodnhzngaotoel.
-- Run every 15 minutes from promotion to T0 + 60 minutes; post one status line per run.
-- Never select ciphertext, handles or provider account ids. First reading 2026-10-22 ~05:43Z: all zero.

-- W1 New Bluesky connections and how many still renew (K5 input).
select count(*) filter (where created_at > now() - interval '24 hours') as connected_24h,
       count(*) filter (where revoked_at is null) as active,
       count(*) filter (where revoked_at is null and refresh_supported) as renewing,
       count(*) filter (where revoked_at is null and not refresh_supported) as needs_reconnect
from public.pr_encrypted_credentials where provider = 'bluesky';

-- W2 OAuth outcomes per 15 minutes (K2). NULL outcome = started, not finished.
select date_trunc('hour', created_at) + floor(extract(minute from created_at) / 15) * interval '15 minutes' as slot,
       coalesce(outcome, '(open)') as outcome, count(*) as n
from public.pr_oauth_transactions
where provider = 'bluesky' and created_at > now() - interval '2 hours'
group by 1, 2 order by 1 desc, 2;

-- W3 Health projection (K5).
select state, connection_state, count(*) as n
from public.pr_connection_health where provider = 'bluesky' group by 1, 2 order by 3 desc;

-- W4 Capability levels (identity Direct; publish Assisted until REVIEWED).
select c.capability, c.level, count(*) as n
from public.pr_channel_capabilities c
join public.pr_encrypted_credentials e using (workspace_id, connection_id)
where e.provider = 'bluesky' and e.revoked_at is null
group by 1, 2 order by 1, 2;

-- W5 Throttle buckets touched in the last minute (K6 proxy; the Bluesky cap is 300 starts per minute).
select count(*) as throttle_buckets_last_minute from public.pr_auth_throttle where window_start > now() - interval '1 minute';

-- W6 (Vercel): get_runtime_logs(projectId=prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L, environment=production,
--     query="bluesky", since="15m", group_by="requestPath"), and level=error for /api/oauth/bluesky/*.
