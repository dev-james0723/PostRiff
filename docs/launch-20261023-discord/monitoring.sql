-- Rafii Discord launch monitors (O-01). Aggregate-only, read-only.
--
-- Run against the PRODUCTION Supabase project with a read-only role or the Supabase SQL editor. Every statement is a
-- SELECT; none returns ciphertext, tokens, provider account ids, channel ids, message text or any customer content.
-- Paste results into the ledger as counts only. Do not write exact production usage into this public repository.
--
-- Thresholds (page the on-call named in H-07 when any holds):
--   Q2  invalid requests in 10 minutes            > 1,000                       (Discord restricts the IP above 10,000)
--   Q3  coordinator-wide circuit or block open    > 5 minutes (kinds listed there)
--   Q5  uncertain publishes in 15 minutes         >= 3                          (stop condition: never resend)
--   Q4  server errors in 5 minutes                > 2 percent of responses
--   Q6  policy expiry                             < 7 days (renew by the date in RC-RECEIPT.md; this is a cross-check)
--   Q7  oldest eligible job lag                   > 15 minutes, or held / dead letters rising
--   Q9  servers in use                            >= 80 percent of POSTRIFF_DISCORD_GUILD_CAP
-- Runtime errors and the 5xx rate of Rafii's own API are not in the database: use the Vercel runtime logs for the
-- promoted deployment (errors only) and compare with Q4.

-- Q1. Requests per 5 minutes, last 2 hours: volume, outcomes, publishes.
SELECT date_bin(interval '5 minutes', reserved_at, timestamptz '2000-01-01') AS bucket,
       is_publish,
       count(*) AS admissions,
       count(*) FILTER (WHERE state = 'observed') AS observed,
       count(*) FILTER (WHERE state = 'uncertain') AS uncertain,
       count(*) FILTER (WHERE state = 'blocked') AS blocked,
       count(*) FILTER (WHERE status_code = 429) AS rate_limited,
       count(*) FILTER (WHERE status_code >= 500) AS server_errors
FROM public.pr_discord_request_admissions
WHERE reserved_at > now() - interval '2 hours'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- Q2. Invalid requests in the last 10 minutes (401, 403, and 429 that is not shared-scope). Page above 1,000.
SELECT count(*) AS invalid_requests_10_min
FROM public.pr_discord_request_admissions
WHERE coalesce(outcome_at, sent_at, reserved_at) > now() - interval '10 minutes'
  AND (status_code IN (401, 403)
       OR (status_code = 429 AND coalesce(rate_scope, 'unknown') <> 'shared'));

-- Q3. Open circuits, blocks and manual holds by scope kind. Page when 'global', 'policy', 'invalid' or 'credential'
-- stays open for more than 5 minutes. Route-level circuits from a 403 or 404 last until the policy expires by design
-- (bot removed, channel deleted); watch the count, do not page on each one.
SELECT kind,
       count(*) FILTER (WHERE circuit_until > now()) AS circuits_open,
       count(*) FILTER (WHERE blocked_until > now()) AS blocks_active,
       count(*) FILTER (WHERE manual_hold) AS manual_holds,
       count(*) FILTER (WHERE greatest(circuit_until, blocked_until) > now()
                          AND updated_at < now() - interval '5 minutes') AS open_over_5_min,
       max(greatest(circuit_until, blocked_until)) AS latest_embargo_until
FROM public.pr_discord_rate_state
GROUP BY kind
ORDER BY kind;

-- Q4. Server-error share of Discord responses in the last 5 minutes. Page above 2 percent with at least 20 responses.
SELECT count(*) AS responses,
       count(*) FILTER (WHERE status_code >= 500) AS server_errors,
       round(100.0 * count(*) FILTER (WHERE status_code >= 500) / nullif(count(*), 0), 2) AS server_error_percent
FROM public.pr_discord_request_admissions
WHERE outcome_at > now() - interval '5 minutes'
  AND status_code IS NOT NULL;

-- Q5. Uncertain publishes in the last 15 minutes. Three or more is a stop condition; an uncertain delivery is never
-- resent. (State 'uncertain' means the request may have reached Discord but no response was recorded.)
SELECT count(*) AS uncertain_publishes_15_min
FROM public.pr_discord_request_admissions
WHERE is_publish
  AND state = 'uncertain'
  AND coalesce(outcome_at, sent_at, reserved_at) > now() - interval '15 minutes';

-- Q6. Rate-policy expiry as last exercised by the coordinator. Page below 7 days. After a renewal the new revision
-- appears here only once traffic has used it.
SELECT policy_revision,
       count(*) AS state_rows,
       min(policy_expires_at) AS earliest_expiry,
       round((extract(epoch FROM (min(policy_expires_at) - now())) / 86400)::numeric, 1) AS days_left
FROM public.pr_discord_rate_state
WHERE policy_expires_at IS NOT NULL
GROUP BY policy_revision
ORDER BY earliest_expiry;

-- Q7. Discord job queue, same definition as the worker's own report (jobs from the workspace state, terminal states
-- excluded). Bounded to 5,000 workspaces, which is far above Wave 1.
WITH sample AS MATERIALIZED (
    SELECT state FROM public.pr_workspaces
    WHERE state ? 'phase2' AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'
    ORDER BY id LIMIT 5000
), jobs AS MATERIALIZED (
    SELECT j FROM sample s
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.state #> '{phase2,jobs}', '[]'::jsonb)) j
    WHERE j #>> '{manifest,platform}' = 'Discord'
), observed AS (SELECT extract(epoch FROM clock_timestamp())::double precision AS at)
SELECT count(*) FILTER (WHERE j ->> 'state' NOT IN ('verified', 'failed', 'canceled', 'held')) AS queue_depth,
       coalesce(max(greatest(0, observed.at - coalesce((j ->> 'nextAt')::double precision, observed.at)))
                FILTER (WHERE j ->> 'state' NOT IN ('verified', 'failed', 'canceled', 'held')
                          AND coalesce((j ->> 'leaseUntil')::double precision, 0) <= observed.at), 0) AS oldest_eligible_lag_seconds,
       count(*) FILTER (WHERE j ->> 'state' = 'held') AS held,
       count(*) FILTER (WHERE j ->> 'state' = 'uncertain') AS uncertain,
       count(*) FILTER (WHERE j #> '{discordWorker,deadLetter}' IS NOT NULL) AS dead_letters
FROM jobs CROSS JOIN observed;

-- Q8. Connect attempts and their outcomes, per hour, last 24 hours (state values only; no ids).
SELECT date_trunc('hour', created_at) AS hour,
       coalesce(outcome, CASE WHEN consumed_at IS NULL AND expires_at > now() THEN 'in_flight'
                              WHEN consumed_at IS NULL THEN 'expired_unused' ELSE 'consumed_no_outcome' END) AS outcome,
       ('bot' = ANY (scopes)) AS installs_the_bot,
       count(*) AS attempts
FROM public.pr_oauth_transactions
WHERE provider = 'discord'
  AND created_at > now() - interval '24 hours'
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2, 3;

-- Q9. Servers counted against the cap: the same expression the connect gate uses (distinct servers with a bot-install
-- grant, revoked ones included because a disconnect leaves the shared bot in the server, plus every installation start
-- that is live or mid-exchange, one slot per row). It can UNDERCOUNT Discord's own number (deleted workspaces take their
-- rows with them, and server admins can add or remove the bot without us): compare with the server count in the
-- Developer Portal and lower POSTRIFF_DISCORD_GUILD_CAP by the difference. Page at 80 percent of the cap.
SELECT (SELECT count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials
         WHERE provider = 'discord' AND 'bot' = ANY (scopes)) AS servers_counted,
       (SELECT count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials
         WHERE provider = 'discord' AND revoked_at IS NULL AND 'bot' = ANY (scopes)) AS servers_with_a_live_grant,
       (SELECT count(*) FROM public.pr_oauth_transactions
         WHERE provider = 'discord' AND 'bot' = ANY (scopes)
           AND ((consumed_at IS NULL AND expires_at > now())
                OR (outcome = 'exchange_started' AND consumed_at > now() - interval '10 minutes'))) AS installs_in_flight;
-- installs_in_flight counts every live start, one slot per row (a double click is two, a reconnect start is one): each
-- is a server the bot may join. servers_counted + installs_in_flight is the number the gate compares with the cap.

-- Q10. Grants by kind and recent revocations (counts only).
SELECT ('bot' = ANY (scopes)) AS bot_install,
       count(*) FILTER (WHERE revoked_at IS NULL) AS active,
       count(*) FILTER (WHERE revoked_at > now() - interval '24 hours') AS revoked_last_24h
FROM public.pr_encrypted_credentials
WHERE provider = 'discord'
GROUP BY 1
ORDER BY 1;

-- Q11. Stored capability levels on Discord connections. Compare with the baseline in the ledger; an unexpected change
-- of any row count is a stop condition ("capability rows changing unexpectedly").
SELECT c.capability, c.level, count(*) AS connections
FROM public.pr_channel_capabilities c
WHERE EXISTS (SELECT 1 FROM public.pr_encrypted_credentials e
              WHERE e.workspace_id = c.workspace_id AND e.connection_id = c.connection_id AND e.provider = 'discord')
GROUP BY 1, 2
ORDER BY 1, 2;

-- Q12. Installs that may have put the bot in a server Rafii holds no row for (an UPPER BOUND, last 24 hours, counts only).
-- The bot joins on Discord's consent screen, BEFORE our callback runs. These bot-install attempts ended without a stored
-- connection: consent never came back (tab closed), the callback failed or was refused, a different server was picked
-- than the one reserved, or consent arrived after the ten-minute window. Not every one added the bot. Read it with Q9
-- and the Developer Portal: if (Portal server count - servers_counted) is larger than the sum of these four numbers plus
-- two, someone is adding the public bot outside Rafii and the cap should be lowered or the gate closed.
SELECT count(*) FILTER (WHERE consumed_at IS NULL AND expires_at <= now()) AS never_returned,
       count(*) FILTER (WHERE outcome IN ('expired', 'mismatch')) AS expired_or_mismatched,
       count(*) FILTER (WHERE outcome = 'exchange_started' AND consumed_at <= now() - interval '10 minutes') AS exchange_never_finished,
       count(*) FILTER (WHERE outcome = 'denied') AS denied_or_callback_error
FROM public.pr_oauth_transactions
WHERE provider = 'discord' AND 'bot' = ANY (scopes)
  AND created_at > now() - interval '24 hours';

-- Q13. Hoarding check (counts only, no ids): how many people (workspace and member) have 1, 2 or 3 bot-install starts in
-- flight right now. The gate refuses a fourth start from one person, so no row may show more than 3. Many people at 3 at
-- once while few installs complete means the cap is being held by sign-ups rather than servers: close the gate (promote
-- D1) and read Q8. Holds expire by themselves after ten minutes.
SELECT starts_in_flight, count(*) AS people
FROM (SELECT workspace_id, member_id, count(*) AS starts_in_flight
      FROM public.pr_oauth_transactions
      WHERE provider = 'discord' AND 'bot' = ANY (scopes)
        AND ((consumed_at IS NULL AND expires_at > now())
             OR (outcome = 'exchange_started' AND consumed_at > now() - interval '10 minutes'))
      GROUP BY workspace_id, member_id) AS per_person
GROUP BY starts_in_flight
ORDER BY starts_in_flight DESC;
