# Bounded YouTube publishing agent

Execution state: **IMPLEMENTED BUT UNVERIFIED**. This document describes code and synthetic controls, not provider acceptance or a public-launch approval.

The Creator page can prepare a plan from an inspected immutable workspace Library video, proposed title/description, channel goal, exact destination channel, explicit audience/synthetic-media declarations, rights confirmation, local publication time and IANA time zone. A filename can supply an editable proposed title. The planner makes no paid AI call and does not claim to understand video content or predict audience performance. DST gaps are rejected and repeated clock times require an explicit occurrence.

Manual approval presents the exact video, metadata, immutable YouTube Channel ID, visibility, upload workflow and date. Approval runs the existing `p2_variant_review`, `p2_review` and `p2_approve` commands. The resulting standard immutable manifest, media checks, account permissions, billing, quota admission, worker claim, upload journal and idempotency protections remain authoritative. The plan retains the resulting Queue job ID so repeated dispatch cannot upload again.

Two distinct workflows are available:

- Upload privately after approval and, for intended public visibility, use the existing native YouTube future `publishAt` flow after processing.
- Queue the upload itself for a selected later time, at least ten minutes before the planned public publication. This interval is a minimum safety lead, not a guarantee that processing will finish in time. Expired publication dates fail closed and require explicit rescheduling.

Private visibility remains private. A future plan date never turns a private upload public implicitly. Provider acceptance, processing, native scheduled state and actual publication remain separate receipts in the existing worker.

## Owner-authorized autopilot

Standing authority is finite: one connection and immutable channel, an exact list of draft digests and Library asset IDs, exact scheduled dates/times, IANA daily-limit time zone, maximum one to 20 publications/day and an expiry within 30 days. The owner reviews a policy before a separate activation confirmation. Activation requires fresh interactive owner authentication, the exact channel ID and policy digest. Changed plans, changed media and changed metadata require a new policy; wildcard sources and arbitrary future video selections are unsupported.

The agentic connection uses the separately configured and routed Google OAuth client. `provider_for_connection` resolves the encrypted client/lane binding. The runtime gate rejects standard human grants, unknown binding versions, client mismatch, lane mismatch, missing refresh binding and absent independent Google/YouTube public approvals. The UI prepares a separate Google consent request; the actual account owner must complete Google consent. No user account consent is inferred from operator setup authority.

The existing worker maintenance calls the bounded dispatcher. It selects at most one eligible plan per tick, revalidates the agentic grant/channel, checks the granting owner is still active, applies ordinary billing/queue limits and atomically prepares/approves a normal job. Job claim and forward-write guards recheck the live policy, scope, expiry and owner. A recoverable upload uses the existing resumable journal, never a new upload operation. Provider/quota/permission failures produce a paused policy with a durable human-intervention reason and an audit event.

Pause and revoke stop future uploads and API writes. **An already accepted native YouTube schedule remains scheduled on YouTube until separately cancelled through the exact creator cancellation approval.** Read-only provider reconciliation remains allowed so receipts stay accurate. Disconnect/revocation stops credentials and the existing publishing worker gates.

## Server routes

All routes are workspace- and connection-scoped under `/api/workspaces/{workspace}/youtube/{connection}/agent`:

- `GET /`: secret-free plans, policies, activation gate, intervention state and pause disclosure.
- `POST /drafts`: editorial plan preparation with workspace revision.
- `POST /drafts/{id}/approve`: exact digest and explicit manual approval, requiring current publish permission.
- `POST /policies/preview`: owner-only finite policy preparation.
- `POST /policies/{id}/activate`: fresh owner confirmation plus agentic/provider public gates.
- `POST /policies/{id}/pause` and `/revoke`: owner controls.

Existing API tokens have no agent-route allowlist scope. State and publishing records retain workspace tenancy; credentials and provider session URLs never enter these responses. Policy/draft state lives in the existing workspace JSON and audit events contain identifiers/status only.

## Validation and unresolved acceptance

`tests/test_youtube_agent.py` provides synthetic regression coverage for normal-manifest dispatch and duplicate fencing, stale media/metadata, separate upload/publication times, expired times, DST, explicit rights and declarations, owner/API-token restrictions, finite scope, daily limits, expiry, pause/revoke and exact agentic client binding. These tests are included by the cloud YouTube regression harness. Full cloud execution and release evidence belong in the root launch receipt.

Real agentic Google consent, verified scope approval, YouTube audit/public-upload eligibility, approved quota capacity, independent-account tenant acceptance, real private/public uploads and real scheduled publication remain external/provider-backed acceptance gates. Each autopilot policy covers its finite exact plans; expanding content selection requires new owner consent and must retain these controls.

## Integrated Rafii chat tools

The existing `agent_runtime_v2` domain extension registers four tools and binds them to the Manager/content/publishing/analytics specialist scopes. The existing customer-invoked runtime owns AI model routing, consent and budget metering. This extension starts no new model call, provider or background paid analysis:

- `youtube_plan_context` lists this workspace's inspected video IDs and technical eligibility plus exact connected channel identities. It returns no video bytes, filenames, transcripts, private stored goals or storage paths. It explicitly does not understand the video. Existing `image_analyze` and approved Library-fact tools remain the paths for content analysis with their established media-processor/source-sharing consent.
- `youtube_plan_prepare` accepts model-proposed titles/descriptions and saves an unapproved exact Library/channel/future-time plan through the same `creator.agent.prepare` service. It rereads the saved plan before recording a verified local draft. Current workspace edit permission is checked again. Rights, made-for-kids and synthetic-media declarations must come from the actual human message this turn; tool arguments cannot assert them. Ambiguous/missing declarations ask the person. The user reviews and separately approves the exact plan in Creator.
- `youtube_analytics_summary` requires an explicit current-turn request for YouTube analytics, the exact protected separate agentic OAuth client/lane, actual read and nonmonetary Analytics scopes, current workspace membership and the existing creator read/capability/throttle path. It accepts an explicit range of at most 90 days. At most 100 selected native metric observations reach the configured model, preserving their original column names, finite numeric values, dates and provider order, with source/requested-date context. No independent totals, averages, ratios, scores, rankings or predictions are calculated. Free-text fields, viewer identities, video text, revenue and credentials are excluded; invalid/missing/out-of-range values are omitted rather than imputed as zero. Provider coverage and projection truncation are separate flags. Ownership and role are rechecked after retrieval. Evidence stays in this turn's ledger.
- `youtube_recommendations` uses only that current-turn native-metric evidence, with no implicit fetch. It provides reviewable planning guidance relating native observations to the person's goals; it does not calculate or rank API-derived metrics or infer the best posting hour, content performance or posting-time causation. Older aggregate evidence is not accepted by this path. Without retrieved evidence it provides planning guidance and reports performance evidence unavailable. Additional derived-metric functionality remains off pending the applicable owner-reviewed amendment and Google determination.

There is no chat tool for publication approval, standing-authority activation, consent, account settings or deletion. Tool outputs are untrusted data under the runtime's existing schema, tenant/scope, cancellation and permission gates. `tests/test_youtube_agent_tools.py` covers registration/scope, real local draft creation and authoritative readback, model-consent refusal, role/tenant/asset/time boundaries, agentic custody, unchanged native metric projection, bounded payloads, ambiguous-column refusal and rejection of old derived evidence. All tests are synthetic. A real metered chat turn, consented video analysis and real agentic Analytics retrieval require separate deployment acceptance. The public privacy page conditionally describes native-metric sharing and finite standing authority; its legal draft status, unknown operator/contact facts and processor/training/retention review gates remain unchanged.

Current operational limits: a policy restart permits new plan dispatch and does not automatically resume an already held publishing job; that job requires separate exact review. Creator recovery applies only to a recoverable journaled upload; a hold before any provider session exists cannot use that recovery route. A policy still covers finite selected plans rather than discovering and approving arbitrary future videos. The 100-plan cap counts pending future proposals, and the 100-policy cap counts unexpired prepared/active/paused policies. Completed, expired and revoked records remain intact and do not impose a lifetime creator cap. Retained records currently live in workspace JSON; growth, pagination and a separate archival design remain scalability work. No receipt or audit record is silently deleted to free capacity.
