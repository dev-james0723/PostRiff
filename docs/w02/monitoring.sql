-- W-02 parallel Discord lane monitors. Aggregate-only, read-only; additions to the launch monitors (Q1-Q13).
--
-- Run against the production Supabase project with a read-only role or the SQL editor. Every statement is a SELECT
-- and returns counts, ages and states only: no workspace, job, channel, message, token or customer content. Record
-- results as counts. The lane's own per-invocation counters are in the function logs, one line per invocation:
-- event "discord.lane.completed" with stoppedBy, claimed, posted, verified, held, uncertain, rateDelayed, leaseLost,
-- rateWaits, idleWaits, permitWaits, bookedWaits and bookedSeconds (see AS-BUILT.md).
--
-- Thresholds (starting points; tune after the first busy hour):
--   M1  oldest due lag                  > 10 minutes            the lane is not keeping up, or is stopped (read M6)
--   M2  leases expired but still owned  > 0 for 5 minutes       a loop died mid-step; recovery should clear it
--   M3  busiest second                  > the policy capacity   must never happen; stop with the hold (runbook step 2)
--   M5  unobserved admissions > 2 min   rising, or any publish  slots kept by dead requests (see M5)
--   M6  any hold on the four rows       any                     the lane stops while it lasts (stoppedBy in logs)
--   M7  held for an expired approval    rising                  the queue is longer than an approval lives
--   M8  booked horizon                  near 1 s for minutes    the lane asks for more places than the window has (Q19)

-- M1. Due Discord work from the transactional projection (migration 126; the same index the lane claims through).
-- due_workspaces: workspaces with work due now; oldest_due_lag_seconds: how late the oldest of them is running.
WITH observed AS (SELECT extract(epoch FROM clock_timestamp())::double precision AS at)
SELECT count(*) FILTER (WHERE p.next_at <= observed.at) AS due_workspaces,
       count(*) FILTER (WHERE p.next_at > observed.at AND p.next_at <= observed.at + 300) AS due_within_5_min,
       coalesce(max(observed.at - p.next_at) FILTER (WHERE p.next_at <= observed.at), 0)::bigint AS oldest_due_lag_seconds
FROM public.pr_discord_worker_projection p CROSS JOIN observed
WHERE p.next_at IS NOT NULL;

-- M2. Discord jobs in flight by lease age (bounded sample, as Q7). A live lease is one loop working on that job now;
-- an expired lease that still names an owner is a loop that stopped mid-step: the next claim recovers it (unsent work
-- is released, sealed work is reconciled, never re-posted).
WITH sample AS MATERIALIZED (
    SELECT state FROM public.pr_workspaces
    WHERE state ? 'phase2' AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'
    ORDER BY id LIMIT 5000
), jobs AS MATERIALIZED (
    SELECT j FROM sample s
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.state #> '{phase2,jobs}', '[]'::jsonb)) j
    WHERE j #>> '{manifest,platform}' = 'Discord' AND j ->> 'leaseOwner' IS NOT NULL
), observed AS (SELECT extract(epoch FROM clock_timestamp())::double precision AS at)
SELECT count(*) FILTER (WHERE (j ->> 'leaseUntil')::double precision > observed.at) AS live_leases,
       count(*) FILTER (WHERE (j ->> 'leaseUntil')::double precision > observed.at
                          AND observed.at - (j #>> '{discordWorker,claimedAt}')::double precision > 30) AS live_over_30s,
       count(*) FILTER (WHERE (j ->> 'leaseUntil')::double precision <= observed.at) AS expired_still_owned,
       coalesce(max(observed.at - (j ->> 'leaseUntil')::double precision)
                FILTER (WHERE (j ->> 'leaseUntil')::double precision <= observed.at), 0)::bigint AS oldest_expired_seconds,
       count(*) FILTER (WHERE j #>> '{discordWorker,stage}' = 'sealed') AS sealed_now
FROM jobs CROSS JOIN observed;

-- M3. Request rate across every loop, last 10 minutes, from the coordinator's own admissions: the busiest second
-- and the average. The busiest second may reach twice the policy capacity where two fixed windows meet; above
-- that is a defect. Counted by WIRE time (sent_at, else reserved_at): a booked admission (OPEN-QUESTIONS Q19) is
-- stored with the instant it is to be sent, up to a second after the one it was made, and that instant is what the
-- ceiling counts. Each class has a ceiling of its own since the bearer budget (OPEN-QUESTIONS Q21): the person's own bearer
-- calls (credential_kind 'user'; 10 a second in the reviewed policy) and every other credential (25). One row each; with a
-- policy that has no bearer pair, add the two rows together and compare the sum with 25.
WITH seconds AS (
    SELECT date_trunc('second', coalesce(sent_at, reserved_at)) AS second, credential_kind = 'user' AS bearer, count(*) AS requests
    FROM public.pr_discord_request_admissions
    WHERE coalesce(sent_at, reserved_at) > now() - interval '10 minutes'
    GROUP BY 1, 2
)
SELECT bearer,
       coalesce(max(requests), 0) AS busiest_second,
       round(coalesce(sum(requests), 0) / 600.0, 2) AS average_per_second,
       count(*) FILTER (WHERE requests > CASE WHEN bearer THEN 10 ELSE 25 END) AS seconds_above_cap
FROM seconds
GROUP BY bearer
ORDER BY bearer;

-- M4. Posts waiting on the shared budget (released unsent with a rate wait): how many and how far out.
WITH sample AS MATERIALIZED (
    SELECT state FROM public.pr_workspaces
    WHERE state ? 'phase2' AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'
    ORDER BY id LIMIT 5000
), jobs AS MATERIALIZED (
    SELECT j FROM sample s
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.state #> '{phase2,jobs}', '[]'::jsonb)) j
    WHERE j #>> '{manifest,platform}' = 'Discord' AND j ->> 'state' = 'scheduled'
      AND j #> '{discordWorker,rateDelayedUntil}' IS NOT NULL
), observed AS (SELECT extract(epoch FROM clock_timestamp())::double precision AS at)
SELECT count(*) FILTER (WHERE (j #>> '{discordWorker,rateDelayedUntil}')::double precision > observed.at) AS rate_waiting,
       coalesce(max((j #>> '{discordWorker,rateDelayedUntil}')::double precision - observed.at), 0)::bigint AS longest_wait_seconds
FROM jobs CROSS JOIN observed;

-- M5. Admissions whose request was sent but whose answer was never recorded (the process stopped mid-request).
-- The coordinator keeps each one counted in every later window until it is reviewed: one slot of the application
-- budget, and on a route whose limits were not learned yet, that route's single probe (later posts to that channel
-- wait unsent). A publish here also has an 'uncertain' job to reconcile by hand. There is no reviewed procedure to
-- release these rows yet (OPEN-QUESTIONS.md Q3); do not edit them without one.
SELECT is_publish,
       count(*) AS unobserved,
       count(*) FILTER (WHERE bucket_key IS NULL) AS on_unlearned_route,
       min(sent_at) AS oldest_sent_at
FROM public.pr_discord_request_admissions
WHERE state IN ('sent', 'uncertain')
  AND coalesce(sent_at, reserved_at) < now() - interval '2 minutes'
GROUP BY is_publish
ORDER BY is_publish;

-- M6. The application-wide coordinator rows every loop reads before it claims (policy, the bearer budget's, bot global, bot
-- credential, invalid-request budget). A manual hold on the policy row is the runbook's stop (`WHERE kind = 'policy'` sets
-- the bearer budget's row too); while any hold is set, every loop ends with stoppedBy operator_hold or coordinator_hold.
-- An active block or circuit is slept out. The bearer budget's row (OPEN-QUESTIONS Q21) is a policy row told by its scope key.
-- room_now: since booking (Q19) the room the booked horizon still has as of the last admission, not the window's free
-- slots; 0 exactly when a booking would be refused (see M8). A lane that fills the budget reads about half of the 24
-- bookable, because its twelve loops hold at most twelve bookings at once.
SELECT CASE WHEN scope_key LIKE '01:%' THEN 'bearer' ELSE kind END AS row_kind,
       count(*) FILTER (WHERE manual_hold) AS holds,
       count(*) FILTER (WHERE blocked_until > now()) AS blocks_active,
       count(*) FILTER (WHERE circuit_until > now()) AS circuits_open,
       min(remaining) FILTER (WHERE kind = 'policy') AS room_now,
       max(greatest(blocked_until, circuit_until)) AS latest_embargo_until
FROM public.pr_discord_rate_state
WHERE kind IN ('policy', 'global', 'credential', 'invalid')
GROUP BY 1
ORDER BY 1;

-- M7. Discord posts held in the last hour because their approval expired before they could be sent (the event the
-- worker writes at claim; counts only). Rising means the queue outlasts approvals: see OPEN-QUESTIONS.md Q1.
WITH sample AS MATERIALIZED (
    SELECT state FROM public.pr_workspaces
    WHERE state ? 'phase2' AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'
    ORDER BY id LIMIT 5000
), jobs AS MATERIALIZED (
    SELECT j FROM sample s
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.state #> '{phase2,jobs}', '[]'::jsonb)) j
    WHERE j #>> '{manifest,platform}' = 'Discord' AND j ->> 'state' = 'held'
), observed AS (SELECT extract(epoch FROM clock_timestamp())::double precision AS at)
SELECT count(*) FILTER (WHERE (j #>> '{manifest,expiresAt}')::double precision <= observed.at
                          AND (j #>> '{manifest,expiresAt}')::double precision > observed.at - 3600) AS held_after_expiry_last_hour,
       count(*) AS held_total
FROM jobs CROSS JOIN observed;

-- M8. Booking (OPEN-QUESTIONS Q19): admissions that still wait for their wire time (reads and create permits booked ahead),
-- how far ahead the latest lies, and what the reads booked in the last minute waited. A horizon close to the book-ahead (1
-- second) means the booked horizon is full and callers are being refused again; the lane's bookedWaits and bookedSeconds
-- (per invocation, in the discord.lane.completed line) count the same from the lane's side. Newest 20,000 admissions.
WITH observed AS MATERIALIZED (SELECT clock_timestamp() AS at),
sample AS MATERIALIZED (
    SELECT is_publish, reserved_at, sent_at, coalesce(sent_at, reserved_at) AS wire
    FROM public.pr_discord_request_admissions ORDER BY request_seq DESC LIMIT 20000
)
SELECT count(*) FILTER (WHERE s.wire > o.at) AS admissions_ahead_now,
       round(extract(epoch FROM max(s.wire) FILTER (WHERE s.wire > o.at) - o.at)::numeric, 3) AS horizon_seconds,
       count(*) FILTER (WHERE NOT s.is_publish AND s.sent_at > s.reserved_at + interval '5 milliseconds'
                          AND s.reserved_at > o.at - interval '60 seconds') AS booked_reads_60s,
       round(coalesce(sum(extract(epoch FROM s.sent_at - s.reserved_at)) FILTER (WHERE NOT s.is_publish
                  AND s.sent_at > s.reserved_at + interval '5 milliseconds'
                  AND s.reserved_at > o.at - interval '60 seconds'), 0)::numeric, 3) AS booked_read_wait_seconds_60s
FROM sample s CROSS JOIN observed o
GROUP BY o.at;
