# Rafii POC-2 — read-only preflight (2026-10-15)

POC-2 asks one question: can **one real, already-authorized account** return comparable native metrics at a fixed post age (24h)?

This preflight used **read-only** SQL aggregates on the production and staging databases:
- It never read identities, values, tokens or ciphertext.
- It made no provider call.
- It changed no data and no configuration.
- It started no OAuth and did no token refresh.

## What exists today
| Check | Production (`postriff-phase2-private`) | Staging (`rafii-consumer-staging`) |
|---|---|---|
| Instagram/Threads credentials, not revoked | 2 Instagram, 1 of which carries both native-insights scopes; Threads 0 | 0 |
| `analytics` capability rows | Direct 2, Unsupported 8 | Unsupported 3 |
| The insights-scoped account | Owner/admin account of the requesting founder, single-member workspace; analytics `Direct`; access token valid for about 48 more days (refresh supported, **not used**) | — |
| Rafii-verified publications on that account | **0** (0 in the last 30 days) | — |
| Stored native observations | 6. One lifetime `backfill` read on 2026-10-04: views, reach, likes, comments, saved, shares, all `available`, definition `2026-09` | 0 |
| Scheduled t0/1h/24h/7d reads, ever | **0**. The only `pr_metric_reads` row is that one `backfill` read | 0 |

## Conclusion
The question **cannot be answered from stored data**. Two independent facts block it:

1. **No Rafii-verified posts on the account.** Scheduled 24h reads are created only when Rafii verifies a publication (`on_post_verified`). The account has never had one, so no 24h reading can exist.
2. ~~**No scheduled reads have ever run in production.** Metric-read admission is evidently not active for this workspace.~~
   **Corrected during AP-4 execution, same day.** Admission *was* active. Production logs show `metric_reads.tick` every minute; `POSTRIFF_METRIC_READS` and `POSTRIFF_METRIC_WORKSPACE_ALLOWLIST` have existed in Production since about 4 October; and the 8 October Growth/Trends launch record calls the founder's *second* workspace the "non-allowlisted" one. Scheduled reads simply never had a verified Rafii post to read. This is the same blocker that launch record logged as P1-6, "One publish-linked Instagram proof post".

**Positive evidence.** On 2026-10-04 the platform returned all six native metrics for this account, under the current definition. This shows that the fields exist. It does not show that values are comparable at a fixed age.

## Decision (delegated by James)
Use the founder's own Instagram account. Do **not** attempt Threads: no grant exists. Do **not** use staging: no account is connected there.

Answer POC-2 with three steps, in order:
1. **Prospective readings.** Collect a few prospective 24h readings using the existing scheduler, unchanged. This is not an extra canary, and nothing is backfilled.
2. **James publishes.** James publishes 3 ordinary Instagram posts through Rafii's existing review and approval, as normal use. Claude never publishes.
3. **Read-only check.** After 24–27 hours, run the read-only qualification query below.

AP-4 was approved and executed (receipt in APPROVAL-PACKAGES.md). It sets the allowlist to exactly the founder workspace and redeploys the same production commit, so admission is now guaranteed rather than inferred.

## Read-only qualification query (to run after the readings exist)
Same window rule as POC-1:
- the reading is labelled `24h`;
- the definition is `2026-09`;
- it was observed between publication + 24h and publication + 27h;
- missing never counts as zero.

```sql
with posts as (
  select w.id as workspace_id, j->>'id' as job_id, j->'manifest'->>'channelId' as connection_id,
         (j->'verification'->>'at')::float8 as published
  from public.pr_workspaces w, jsonb_array_elements(coalesce(w.state->'phase2'->'jobs','[]'::jsonb)) j
  where w.id = :workspace_id and j->>'state' = 'verified' and j->'manifest'->>'platform' = 'Instagram')
select p.job_id, o.metric, o.availability, o.value, o.read_offset, o.definition_version,
       extract(epoch from o.observed_at) - p.published as actual_age_seconds,
       case when o.read_offset is null then 'unknown'
            when o.read_offset <> '24h' then 'other_window'
            when extract(epoch from o.observed_at) < p.published + 86400 then 'early'
            when extract(epoch from o.observed_at) > p.published + 86400 + 10800 then 'missed'
            else 'within_tolerance' end as window_qualification
from posts p left join public.pr_metric_observations o
  on o.workspace_id = p.workspace_id and o.job_id = p.job_id and o.connection_id = p.connection_id
order by p.job_id, o.metric;
```

POC-2 **passes** when all three hold:
- every one of the 3 posts has a `24h` reading `within_tolerance` for `reach`;
- the definition is `2026-09`;
- the ingest and observation timestamps are present.

It **degrades** if:
- readings are `missed`;
- or the fields are missing.

In that case: rank the product down to an as-of snapshot, and do not build more UI.
