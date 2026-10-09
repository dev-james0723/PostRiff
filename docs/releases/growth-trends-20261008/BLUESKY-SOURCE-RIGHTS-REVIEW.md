# Bluesky source-rights review — cross-workspace sharing

Date: 2026-10-09. Reviewer: integrator session, authorized by James Au to
conduct and document this review (conditional approval: share only if the terms
and data rights permit it, including retention, deletion, provenance and user
privacy). Sources were fetched 2026-10-08/09 and are quoted in the research memo
kept with the session evidence; the key ones are listed below.

## Decision

**`share_across_workspaces` stays DENIED for this release.**

The applicable terms do not forbid it: commercial use, multi-tenant display,
analysis and aggregate trend metrics are not prohibited anywhere. But the review
found the permission is conditional, and several conditions are not yet
implemented or verified in production (table below). Enabling it now would mean
showing other people's public posts to unrelated customers without the
deletion, labeling and privacy controls the sources require. Ordinary enrolled
workspaces therefore see an honest `unsupported / source_rights_pending` state
for Trends evidence. Nothing about the founder workspace's existing
single-workspace policy changes.

Assessment: permitted with conditions (terms: moderate–high confidence;
privacy law: moderate confidence, decided case by case).

## What the sources require (summary)

| Source | Requirement |
|---|---|
| atproto Account spec / account-lifecycle guide | Stop redistributing an inactive account's content (including derived views) immediately on deletion, takedown or deactivation; permanent deletion and aggregate updates may be deferred |
| atproto Sync spec | Respect record deletions and account status changes "within seconds or minutes"; no public bulk snapshots |
| Jetstream docs | `#account`, `#identity`, `#sync` events are delivered even to filtered consumers and must be handled, not dropped |
| atproto Labels spec / visibility preferences | Redact `!takedown`/`!suspend`; filter `!hide`; honor `!no-unauthenticated` where content is shown to people who are not logged-in Bluesky viewers; honor algorithmic-reach opt-outs for "top post" surfacing |
| Bluesky Developer Guidelines | Deletion-request method, report handling with records, public monitored contact email, reasonable security |
| Bluesky maintainers (atproto issue #3166) | Public data "is not a grant of rights"; firehose consumers are "not exempt from laws or regulations" |
| GDPR Art. 6(1)(f), 14, 17, 21; EDPB 1/2024; DPA scraping statements | Legitimate-interest assessment; Art. 14 notice (source, recipients, interests, retention, rights); erasure and objection handling; aggregate-first design; no profiling of individuals |
| User Intents proposal 0008 (draft, not shipped) | Future hook: exclude accounts that opt out of generative-AI use from LLM summarization |

## Condition checklist (status at base a522482e + lane A)

| # | Condition | Status | Owner / next step |
|---|---|---|---|
| 1 | Record deletes hidden within minutes everywhere (raw store, excerpts, projections, caches) | PARTIAL — delete markers are processed when ingestion runs; ingestion was stalled 10-04→fix | Lane A restores ingestion; measure delete latency in production after deploy |
| 2 | Account deactivation/deletion/takedown stops display immediately | BROKEN — v2 nests `account.active`; code read it flat, so `revoke_author` never fired | Lane A fix (nested markers) + production verification |
| 3 | Label handling (`!takedown`, `!hide`, `!no-unauthenticated`, adult self-labels) | NOT IMPLEMENTED — Jetstream post events carry no account labels | Needs a labeler/profile lookup and record self-label filtering |
| 4 | Opt-out / objection list (DID-level suppression) | PARTIAL — `pr_trend_author_tombstones` + `revoke_author` exist as an operator path; no public request channel | Public privacy contact + operator runbook |
| 5 | Art. 14 privacy notice naming source, recipients (customer workspaces), interests, retention, rights | NOT DONE | Public legal text — needs James's sign-off before publishing |
| 6 | Written legitimate-interest assessment | NOT DONE | Draft can be prepared; sign-off by James |
| 7 | Excerpts short, linked to bsky.app; no bulk raw export | PRESENT — product shows bounded excerpts + links; no export route | Keep |
| 8 | No training/fine-tuning | PRESENT — policy `train_or_finetune=deny` | Keep |
| 9 | Retention bounded | PRESENT — observations retention ≤ policy expiry (2026-11-03) | Renewal runbook before 2026-11-03 |
| 10 | Report handling + monitored contact email | UNVERIFIED | Confirm the public contact address |

## Safer interim option (not enabled)

An aggregate-only share is possible: shared-scope entitlements with
`retrieve` + `derive_metrics` only (no `display_excerpt`), so other workspaces
would see cluster-level counts and momentum but no individual posts. It still
needs conditions 1, 2, 4, 5 and 6, because the processing itself (and the topic
labels derived from post text) concerns identifiable people. It stays off until
those are met.

## What would flip this to ALLOW

Conditions 1–6 VERIFIED in production, then one reviewed shared-scope policy
row (`share_across_workspaces=allow`, `display_excerpt` only if condition 3 is
met) plus a contract row listing that operation, recorded with reviewer and
review reference pointing to this file. Lane C's enrollment then grants
entitlements automatically; no code change is needed to switch.
