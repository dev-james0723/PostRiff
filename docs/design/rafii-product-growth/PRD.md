# RAFII Product Growth & Retention
## Consolidated engineering specification and PRD · v2.0

**Owner:** James  
**Repository:** `dev-james0723/PostRiff` only  
**Prepared:** 2026-10-01 · America/Indiana/Indianapolis  
**Source checkpoint:** 2026-10-01T16:22:18Z (12:22:18 EDT); repository and deployment observations were collected immediately before this checkpoint.  
**Document status:** Execution-ready design and handoff, not a claim of implemented or released functionality.  
**Program identifier:** `RAFII-PRODUCT-GROWTH-v2`  
**Phase names:** `G0`–`G4`. These are NOT the Founder Admin PRD's P0/P1/P2 phases.

> **Product promise:** Turn the user's real expertise and materials into a reviewed, deliverable week of content; help them follow through on relevant opportunities; show what was actually completed and what outcomes can be supported by evidence.
>
> **Engineering direction:** Connect and extend the existing product. Do not rebuild Weekly Operator, Brand Brain, Growth Loop, Evergreen, Inbox, billing, the agent runtime, notifications, or Founder Control.

---

## 0. Executive brief · 給 James／agent 的重點

這份 PRD 整合指定的 `RAFII-Repo-Market-Growth-Audit-2026-10-01.md`、本次對話的功能建議，以及 Pricing v2、Inbox v1、Founder Admin 的既有文件和最新讀到的狀態。不是將兩份建議直接疊加成更大的功能清單。

**最重要的取捨：**

- 收費沿用已決定的 **Free + Creator**。Creator 預設 **US$59/月、3,500 credits**；US$49/59/79 是相同權益的候選價格實驗，不另起 Core/Growth/Agency 套餐。
- **First Week Ready** 要接通真實素材、首篇採納、首週審閱及交付，但不能偷偷送出未獲批准的免費 AI writing、錄音轉寫或整週生成額度。
- 商機與結果分開記錄：用戶自己的 booking／lead，不是 RAFII 的訂閱收入；第一方事件也不是「證明 RAFII 造成增長」。
- **Signature Series** 是延伸已有 Evergreen，加來源有效期、系列脈絡及新角度，不是重做 reshare。
- 先完成一款可編輯的六頁 carousel 成品包；不在本輪建完整視頻編輯器或擴大 avatar 工作。
- 付費及留存指標改用可核對付款與歷史事件，與 Founder 共用定義。不能把「非 trial」直接當作真正付費。
- G0–G4 都有明確交付，agent 不應只做 G0 或重寫計劃就停。受限的 live 啟用要記明具體 blocker，繼續其他獨立工作。

**本次只是產出文件及 prompt，沒有修改產品程式、推送、部署、收費或啟用外部服務。** 之後將 handoff prompt 交給 agent 執行時，依 §2 的授權邊界及 §16 的驗收定義工作。

---

## 1. Inputs, authority and conflict resolutions

### 1.1 Inputs that were actually read

| ID | Source | Role |
|---|---|---|
| S01 | `/Users/ouxianxing/Downloads/RAFII-Repo-Market-Growth-Audit-2026-10-01.md` (232 lines) | Primary consolidated audit: existing implementations, actual gaps, market rationale, commercial decisions and release boundaries. |
| S02 | This conversation's six recommended investments | First Week Ready; Business Results; Content Compounder; Relationship Follow-up; Personal Opportunity Brief; Branded Publish Pack. |
| S03 | Pricing v2 worker handoff in the pricing worktree; full path in §18 | Authoritative commercial target, Free allowances, credits policy, legacy treatment and commercial activation restrictions. |
| S04 | Inbox v1 local completion receipt; full path in §18 | Existing operational sync/reply work, provider scope, test evidence and release restrictions. |
| S05 | `Rafii-Founder-Admin-Intelligence-PRD-v2.0.md` (915 lines including implementation addenda) | Adjacent Founder ownership, shared metrics and ledger dependencies. Not a mandate to redo Founder work. |
| S06 | Current GitHub PR #84/#86 metadata; PR #86 P0 `CONTRACTS.md` excerpt; Vercel production metadata; local HEAD reads | Current integration checkpoint, with evidence limitations below. |
| S07 | Production-pinned `coworker/growth.py` | Direct verification of the legacy paid-conversion/cohort defect. |
| S08 | Official Buffer, Stripe and W3C pages; source index in §18 | Narrow current verification for competition, payment events and accessibility. |

### 1.2 Authority order

1. James's current explicit instructions and action-specific permissions.
2. Verified current code, migrations, capability contracts and deployment receipts for **what exists now**. Code does not override approved product intent merely because legacy behavior remains.
3. Existing approved Pricing v2 commercial rules and security/provider/activation policies.
4. This PRD for the customer growth program, including explicit proposed definition revisions.
5. Historical audits and chat suggestions as rationale, not current deployment truth.

Resolve conflicts once in the integration decision log. Do not invent fresh pricing, broaden Free use, remove approvals, or rewrite a neighboring team's contracts to make a test pass.

### 1.3 Reconciled decisions

| Decision | Resolution |
|---|---|
| Chat suggested Core/Growth/Team packaging | Superseded for this implementation by S03: launch Free + Creator. Outcome-led copy changes are allowed; a new tariff is not. |
| “Add a Weekly Operator / notification system / Time Back” | Already implemented. Improve continuity and verify delivery using the existing services. |
| “Add evergreen repurposing” | Basic Evergreen already exists. New work is Signature Series, fact expiry, angle history and derivative lineage. |
| “One recording/PDF becomes a campaign” | Customer-facing workflow requirement. Reuse existing attachment/transcription/parsing capabilities where they exist; fill only the missing connection. An input enum or transcript-only function is not raw-file support. |
| “More analytics means more value” | Prioritize qualified result sources and decisions. Do not create unsupported follower/lead/revenue figures or decorative charts. |
| Founder “paid customers” definitions vs growth conversion | Publish explicit versioned definitions and align through the shared metric owner. Preserve status-based operational views under accurate labels; never silently relabel them cash-paid. |
| “Production ready” vs prior local-only restrictions | Production verification remains the end goal. This document does not override existing live-commercial, hosted-migration, identity or provider-activation gates. Report blocked deployment/activation truthfully. |
| Extensive parallel worktrees | Reuse completed owned work, integrate one reviewed slice at a time, and preserve live voice/phone fixes. Do not start duplicate implementations. |

---

## 2. Scope and execution authority

### 2.1 Included product scope

G0–G4 include: existing pricing and Inbox reconciliation; corrected product/payment metrics; anonymous-result continuation; First Week Ready; bounded source ingestion; manual relationships and first-party result tracking; Signature Series; one publish-ready visual format; relevant opportunity briefs; weekly/monthly proof; a feedback-to-next-plan loop; existing-app integration; deployment preparation and authorized production verification.

Each is a bounded extension with acceptance criteria in §§6–16. A working partial release is allowed, but it must not be described as completion of the entire program.

### 2.2 Explicit non-goals

No second repository, product, dashboard, billing ledger, agent framework, scheduler, CRM platform or design system. No automatic cold outreach, password-based social scraping, guessed cross-platform identities, purchased data access, new social scopes, unapproved provider activation, live price experiment launch, hidden top-ups, mandatory daily engagement loops, avatar redesign, general video editor, or unrestricted autonomous publishing.

Team/agency packaging, referral-credit incentives and broad video editing remain deferred. Preserve existing functionality in these areas; do not delete another team's work.

### 2.3 Permissions by operation

| Operation | Required authority |
|---|---|
| This document task | Read scoped sources and write new specification/handoff files. No product changes. |
| When James sends the accompanying implementation prompt | Implement this scope in a coordinated isolated worktree; test; update implementation records; make focused commits; push/open PRs where existing source-delivery permission allows. Check whether a push creates a preview before doing it. |
| Preview and production release | Use existing project, protected environments and release authority. If a relevant prior handoff explicitly prohibits deployment, obtain the specific superseding permission, not an inferred blanket override. |
| Hosted migrations, live Stripe Prices/checkout, real charges, refunds, production credit grants | Preserve S03's separate approval boundary. Local/disposable DB and configured Stripe test mode are distinct evidence classes. |
| Real social publish/reply, paid model/research/render/transcription, notifications | Require the exact approved account/capability, enabled service, consent, quote/budget and any required content approval. Approval of this PRD is not approval of arbitrary external messages. |
| Founder enrollment, privileged identities, phone delivery, Founder-only operations | Owned by the Founder program and its explicit gates. Not expanded by this program. |

Do all independently executable implementation and test work before reporting blockers. Group genuinely external decisions into a short unblock list with exact effect, owner and evidence. Never repeatedly ask about routine choices this PRD already settles.

---

## 3. Verified checkpoint and integration ownership

### 3.1 Snapshot, not a pinned implementation base

| Surface | Observation at this document checkpoint | Interpretation |
|---|---|---|
| Production alias | `postriff-phase2-private.vercel.app` → `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL`, READY, SHA `dcb5bcdcd76577835a6944f50310e25f16be9de8`, branch `fix/rafii-call-lifecycle-20260930` | Deployment metadata was re-read. No authenticated production customer journey was executed in this document task. |
| PR #84 | Open, not merged; head is the production SHA above; base `consumer-saas` at `1acd88a8b77c5e8a3f2b877dd927e755c2900a56` | Preserve the eight-commit, 29-file voice/phone release delta. Do not revert production to a stale default checkout. |
| Canonical local checkout | `/Users/ouxianxing/Documents/James-Au-Studio`, `consumer-saas` at `d91660b7936a5158b820914107306ad4a1e51c2d` | Local HEAD is older than the remote baseline. Do not use it as release truth. |
| Pricing v2 local work | `feat/rafii-pricing-credits-v2` at `b862cf1f96d28af6a4bec3b07b8a58f5067286e9` | HEAD and handoff re-read. Push/merge/live activation were not reverified here. |
| Inbox v1 local work | `codex/rafii-inbox-v1-20260928` at `cb4d5f6a4a0227304fc83e9f1d67bdc00dff97f1` | Receipt says local/synthetic completion, no push/merge/production release by that work. Current HEAD re-read. |
| Founder PR #86 | Open draft, unmerged, current head `cb40a7274db096954279a890afbade921a9ee9d6`, updated 2026-10-01T16:05:16Z; same local HEAD | Has moved beyond the `ced7138c` tested snapshot discussed in the PR body. Those old test counts are NOT verification of the new head. Coordinate with its owner. |
| Founder #83/#85 | Historical parent/continuation work described in S05 | Not re-audited independently in this pass. Reconcile ancestry and active ownership at execution start. |

The audit and Founder document contain different historical ahead/file counts. The refreshed PR #84 metadata above is the checkpoint for that comparison; do not copy the older “24 commits” statement into a new release claim.

### 3.2 First execution task: one integration map

Record current remote/default/release refs, production SHA, active worktree owners, dirty status, migration checksums and the first incomplete requirement. Use ancestry and focused diffs rather than copying all branches into one merge.

Reuse an owned isolated worktree when suitable. Otherwise create one coordinated worktree from the agreed base that preserves the verified production fixes. Never reset, clean, stash, overwrite or switch a shared dirty checkout. Do not stop another coding session or start multiple heavy builds on James's loaded Mac. Prefer existing CI for the full suite; run focused local tests first.

### 3.3 Reuse map

Paths are inspected anchors from S01/S03/S04/S07, not permission to overwrite them. Reconfirm exact functions and routing in the execution base.

| Capability | Existing anchor | Required delta / owner boundary |
|---|---|---|
| First-value acquisition | `web/src/features/growth/public-post-doctor.tsx`; public Post Doctor / DNA routes | Consentful continuation into the same draft and then a week. Growth UI owner. |
| Sources and facts | `coworker/source_intake.py`, `fact_pack.py`, `research_broker.py` | Qualified raw audio/PDF path, source version and fact-review integration. Reuse attachment services first. |
| Weekly planning | `coworker/weekly_operator.py`, `service.py`; `web/src/features/coworker/weekly/` | Guided first week, checkpoint/resume, exact review and partial completion. No replacement planner. |
| Goals and proof | `coworker/growth_loop.py`, `performance.py`; existing analytics/growth views | Outcome-source coverage, versioned proofs and approved next-plan actions. |
| Reuse of old content | `campaigns.py::evergreen_post`, existing library/campaign state | Series and derivative metadata; no second reshare selector. |
| Inbox | `audience.py`, `coworker/engagement.py`; local `audience_sync.py`, `audience_worker.py`, `inbox_providers.py` | Integrate existing v1 first; add workspace relationship/follow-up layer. |
| Billing and credits | `billing.py`, `billing_stripe.py`, `CreditBook`, `pr_usage_ledger`; local Pricing v2 `plan_pricing.py` / `free_lifecycle.py` | Integrate v2 and fix metrics through existing billing hooks. Billing owner controls shared changes. |
| Attention and notification delivery | `coworker/attention.py`, `notifications/`, existing Time Back | Relevant opportunity ranking and proof events; retain operational priority and existing delivery dedupe. |
| Visuals | `coworker/creative.py`, existing asset/image pipeline | Editable six-slide artifact through export/Queue, not just planning. |
| Agent | `agent_runtime_v2`, existing site-agent/text/voice paths | Typed operations and result verification for these additions, identical authority for voice and text. |
| Product metrics | `coworker/growth.py`, `pr_product_events`, learning/usage/time ledgers | Durable outcome-level instrumentation, paid-cohort correction, current shared metric contracts. |
| Founder consumption | `rafii_control` QueryService/catalog/receipts and current Founder branch | Metadata-only projections and shared definition versions. No second Founder dashboard or broad customer-body access. |

---

## 4. Product strategy, user and success model

### 4.1 Working customer hypothesis

Initial focus: a solo service founder or knowledge-led creator with real expertise, an offer and no full-time content team. Consultants, educators and coaching/service businesses are candidate segments; select one coherent pilot cohort rather than treating all as a measured customer base.

The business hypotheses are: quicker first useful output improves activation; reliable weekly delivery supports repeat use; traceable inquiries/results support willingness to pay; accumulated source/series/relationship history reduces repeated setup. None is a demonstrated RAFII conversion or retention lift. No current customer dataset was examined.

### 4.2 Product loop

`Real material → reviewed draft → approved week → verified publish / assisted export → qualified outcomes → useful proof → user-approved next step`

Deliverable status, external distribution status and business result status are separate. An export is not a published post; a published post is not a lead; a lead is not a sale; a sale is not proof of incremental impact caused by RAFII.

### 4.3 Market rationale, deliberately narrow

Buffer's current official page includes AI assistance and Community Inbox in Free, with Essentials displayed at US$5 per channel/month when billed yearly. Generic AI writing and scheduling therefore have an inexpensive reference point [E01]. The audit's broader competitor comparison remains background research [S01], not independently proven customer outcomes.

The Blaze page was reopened but its current parsed response did not expose a readable price table; this PRD does not recertify an exact Blaze price. Avoid baking competitor prices or unverified provider model prices into product constants.

**Decision:** compete on a completed workflow, personal relevance, reliable handoff and honest results. More platform logos, more dashboards and more model names are not acceptance criteria.

---

## 5. Commercial and cost contract [R-COM]

These numbers are inherited commercial requirements from S03, not new recommendations.

### R-COM-01 · Catalog and legacy

Launch-visible plans: **Free US$0**, **Creator US$59/month default with 3,500 managed credits/month**. Prepared Creator variants US$49/59/79 have identical entitlements and credits, with stable server-owned workspace assignment. Do not activate the experiment without its existing approval.

Starter US$29/1,000 credits and Studio US$149/8,000 credits remain hidden/non-purchasable. Top-up candidates 1,000/US$15 and 2,000/US$29 remain disabled. Do not introduce Core/Growth/Agency price plans.

Grandfather active legacy `studio-v1`/`assist-v1` subscriptions, invoices and renewals; preserve existing trials until expiry. With v2 enabled, new workspaces use Free; expired legacy trials and ended v2 subscriptions fall back to Free without deleting content. Access after downgrade follows existing entitlements, not an invented unlimited allowance.

### R-COM-02 · One cost authority

Use `pr_usage_ledger`, CreditBook and existing quote/reserve/settle/release/refund machinery. **300 credits = US$1 verified billable provider/tool cost; round once per canonical task using v2's existing rounding policy.** Aggregate bounded internal attempts before final task settlement; do not charge again for polling, resuming a task or downloading an already rendered artifact.

Reserve the authorized maximum before paid I/O. A known failed task releases customer credits under v2 policy; platform-incurred cost must still be recorded. Unknown cost remains pending for reconciliation, not falsely zero or automatically resent. Actual cost over the confirmed maximum is platform-absorbed. Keep credit expiry, no default monthly rollover, currency and milli-credit storage rules intact.

### R-COM-03 · First Week Ready must not bypass Free

Free has zero fungible managed credits. Preserve exactly the one platform-funded Post Doctor first-value run and one one-time recent-20 Genome analysis/import permitted by S03; respect its account cap and platform budget. No recurring free writer/transcription/image/research allowance is created here.

Before an upgrade, users can retain their consented material, manually edit it, inspect genuinely available diagnostic results and see a deterministic plan preview. Full new paid writing/transcription/rendering requires an entitled balance and quote, or a separately approved platform-funded allowance. Do not disguise a paid generation as “preview.”

One free entitlement cannot be consumed again through the anonymous page, signup, resume, another tab or an alternate endpoint. Reuse its existing entitlement identity and abuse boundary; do not add fingerprinting or silently store anonymous content.

### R-COM-04 · Consistent promises and recovery

Public pricing, landing cards, JSON-LD, signup, account billing, help, upgrade sheets and server checkout must agree for the active catalog version. Only legacy users see applicable legacy writing-batch language.

On insufficient balance, preserve the source and work already prepared; show what costs money, the bounded quote and how to continue. A workflow grant is not a publish/reply approval. Model, amount and Price IDs remain server-owned.

**Acceptance:** catalog/legacy/Free/credit scenarios in §15 pass; no hidden tier can checkout; invoice credit grants are once-only; failure, replay, uncertain-cost and maximum-cap cases preserve correct wallet and provider-cost records.

---

## 6. First Week Ready and source continuity [R-FWR]

### R-FWR-01 · Consentful anonymous continuation

Keep the anonymous Post Doctor's existing no-storage promise. Add an explicit **“Continue with this draft”** action that explains what will be retained and lets the user choose the original and/or edited version. No server-side content retention before this choice. Never place draft text, email, brand details or source credentials in URLs, analytics or OAuth state.

Default implementation: after consent, retain a minimal same-tab sessionStorage continuation with a 24-hour expiry, source/version identifiers and the selected text. Use an opaque nonce for navigation only. After authentication, confirm the destination workspace and import through the normal authorized source/draft command. The nonce is not authorization. Cross-device continuation is not promised in this release.

Replays in the same workspace return the same canonical draft; replays into another workspace require a new explicit import. Wrong-account login, expired state, unavailable storage and cancelled signup have clear recovery: reselect/paste the source, not silent loss or fallback to fictional content. Clear local retained content after successful import, explicit discard or expiry on next access. Browser storage is not a vault: reuse the app's XSS/CSP controls and do not retain unrelated sensitive material.

### R-FWR-02 · One guided first-week journey

Use the existing agent/Weekly views, not a new onboarding application. Read approved Brand Brain/voice settings and ask only for missing information that affects the result. A default starting plan is **three posts on one supported channel**; users can reduce this or adjust within existing Weekly limits. This default is a proposed UX choice, not a change to pricing entitlements.

The journey is: consented source → purpose/audience when missing → one editable draft → explicit acceptance → suggested week → item-level review → existing Queue approvals → distribution receipts. Channel connection is not required to inspect a draft or manually edit a plan. Paid generation still obeys §5.

Every slot shows the draft, source, intended channel/language, needed asset, readiness, cost state and next action. Display genuine partial states such as `needs_source`, `needs_asset`, `channel_unavailable` and `approval_expired`. Missing one asset must not discard other completed slots. Never fabricate a personal anecdote, customer quote, result or product fact to fill a slot.

### R-FWR-03 · Resume without repeating work or authority

Persist the journey's references and checkpoint through existing workspace commands, not a second set of draft/queue records. A refresh, agent interruption, reconnect or repeated click resumes the same source, week, draft and reservation IDs. Changes require expected revision and invalidate any affected approval digest.

“Accept this draft,” “approve this week's content,” and “authorize this exact publication” are distinct actions. A single review can prepare the existing approval UI, but cannot bypass it. The UI reads scheduling/publishing state back from Queue; generated prose never sets `scheduled` or `verified`.

### R-FWR-04 · Bounded raw-file intake

First inspect existing attachment, audio, PDF and storage services. Connect an already qualified capability rather than replacing it. Where missing, add a bounded adapter to the existing source pipeline and worker. Proposed launch ceilings are audio ≤10 minutes/30 MB and PDF ≤20 MB/100 pages with extracted text ≤60,000 characters; lower existing safety or provider limits win. Show limits before upload and reject or ask for selected pages instead of silently truncating.

Raw voice is transcribed only through a configured, authorized, budgeted route. Show the transcript for correction before creating claims from it. Text PDFs use existing parsing; scanned/unsupported material requires a qualified extraction route or an explicit request for readable text. Do not label a transcript-only endpoint “audio upload supported.” No new model/vendor is automatically enrolled.

Long work uses the existing durable job mechanism with bounded attempts, cancellation, progress and immutable result references. Do not turn the synchronous agent runtime into an unbounded background runner. Source excerpts are untrusted data, never tool instructions. Retain raw uploads under the existing privacy policy; any shorter new default must be documented, and no longer retention is inferred here.

**Acceptance:** an anonymous draft survives an expressly consented same-tab signup; a Creator user completes a genuine first-week journey; a Free user cannot bypass allowances; interrupted, partial, unsupported-input and reconnect cases preserve work and truthful state.

---

## 7. Relationship follow-up and business results [R-REL / R-OUT]

### R-REL-01 · A light relationship layer over the existing Inbox

Integrate the existing Inbox v1 work before adding another sender or sync path. Initial relationship records can be manually created and explicitly linked to permitted threads already ingested by the workspace. Store a user-given name, optional contact reference, stated interest, linked threads, bounded notes, owner, next action and due date. Provider identity is scoped to provider + account; no automatic cross-platform person matching or sensitive personal profiling.

States: `new`, `replied`, `waiting`, `follow_up_due`, `won`, `closed`. The user controls outcome transitions; a deterministic rule may suggest a state, with its supporting thread/date, but cannot assert that someone bought a service. “Won” requires a declared result and retains its provenance. Snooze/close must be reversible and audited.

Use workspace-scoped read/edit permissions; assignment cannot disclose a relationship to a non-member. Do not put private relationship text into Founder-wide analytics. An aggregate follow-up count is not permission for Founder tools to read customer conversations.

### R-REL-02 · Follow-up means assistance, not unsolicited automation

A due follow-up surfaces in existing Attention with the prior exchange, reason, editable reply suggestion and one clear action. The user can dismiss it as irrelevant. Preserve timezone, quiet hours and notification preferences. Internal follow-up reminders do not themselves contact the lead.

Actual replies use the existing draft → exact preview/approval → fenced worker → provider receipt path. Editing content, destination, account or permissions invalidates approval. Uncertain delivery never causes a blind resend. Threads is the only direct Inbox provider evidenced by the local v1 receipt; Instagram DMs and universal cross-platform replies are not launch claims [S04]. Unsupported channels use an honest provider link or assisted workflow.

### R-OUT-01 · Three result-source classes, never one invented ROI number

These are the customer's business results, not RAFII subscription revenue. Record results with one of:

| Class | Meaning | Permitted display |
|---|---|---|
| `provider_native` | A qualified native provider metric with account, definition and observation window | “Platform-reported …” with coverage and source. |
| `first_party_reported` | An event from the user's approved site/form/booking integration | “Reported by your connected …”; authentic transport does not independently prove the business claim. |
| `user_declared` | A result entered or confirmed by the user | “You reported …”; do not relabel as independently verified. |

Each result has type (`click`, `lead`, `booking`, `newsletter_signup`, `sale`), source connection, occurrence/receipt timestamps, native event ID or declaration ID, optional campaign/post/link association, revision/correction reference, and evidence/coverage. Money is optional native minor units + currency, never inferred from a lead. Do not add unlike currencies or unlike provider metrics. `Unavailable`, measured zero and unqualified sources remain distinct.

### R-OUT-02 · First release: manual outcomes plus one first-party contract

Implement manual create/amend/reverse and one documented, signed first-party webhook receiver for an approved user-controlled form or booking producer. Include a test producer and connection setup/health UI. Do not claim turnkey Calendly, CRM or newsletter support unless that adapter has been implemented and verified. Real connection setup and traffic are an explicit rollout step, not proof supplied by a synthetic webhook test.

Extend existing tracking links when available. A server-created opaque link binds workspace, campaign and destination. Allow approved HTTPS destinations only; do not create an open redirect or fetch arbitrary internal network URLs. Do not put contact data in tracking parameters. Log only the minimal event needed; no fingerprinting. Total observed clicks are not unique people, and bot filtering must be described rather than presented as perfect.

### R-OUT-03 · Ingestion and attribution contract

Verify signature on exact raw bytes using a scoped connection secret and a bounded replay window (proposed default five minutes, with a signed delivery timestamp distinct from event occurrence). Support secret rotation without revealing keys. Enforce body limits and per-connection rate budgets before expensive processing.

Use unique `(workspace_id, source_connection_id, provider_event_id)` identity. Exact replay is a no-op; conflicting payload for the same event ID is quarantined/rejected, never silently replaced. Late events retain `occurred_at` and `received_at`; source health shows lag. Reversals are append-only corrections linked to the original event. Removal of a connection prevents new ingestion and follows existing deletion/retention rules.

Attribute only from an explicit carried link/campaign identifier that resolves to the same workspace. A proposed 30-day link-association window is stored with a definition version and can be changed prospectively. Unmatched events stay `unattributed`; do not guess from names, IP address or timing. Counts describe reported associations, not causal lift or incremental revenue generated by RAFII.

**Acceptance:** a permitted thread becomes a reversible follow-up; exact reply approval remains required; a signed booking associates with its own campaign; duplicates, wrong-tenant IDs, stale signatures, conflicting replays, refunds/reversals and unavailable sources behave explicitly.

---

## 8. Signature Series / Content Compounder [R-SER]

### R-SER-01 · Extend Evergreen into a maintained series

Reuse `campaigns.evergreen_post`, library assets, campaigns and verified publication history [S01]. Add a series record with audience question, goal, source references, owner, status and a bounded initial 2–6 episode plan. Each episode has a distinct role/angle, factual claims, source version, review/expiry date and existing draft/asset references.

Examples of distinct roles are explanation, worked example, case study, FAQ and update. A translated or lightly rephrased duplicate is not automatically a new episode. Let users see which audience questions have been covered and approve the next episode; do not generate an indefinite content queue.

### R-SER-02 · Freshness, variation and memory boundaries

Keep originals immutable and attach derivative lineage. Reuse existing Evergreen eligibility, cooldown and prior-use rules. Add exact-duplicate prevention and reviewable similarity/angle warnings. Missing or expired support for a claim sets `needs_fact_review`; facts must be updated or explicitly removed before release, not silently assumed still true.

Store accepted/rejected angles and user “do not repeat” decisions in the existing scoped preference/strategy system. Do not rewrite the user's identity/voice to imitate one successful post. Performance recommendations retain current comparable-cohort, observation-window and non-causal constraints. A model cannot invent a popularity or virality measurement.

**Acceptance:** an eligible old source yields a new, traceable episode; a duplicate is flagged; an expired fact blocks unsupported reuse; an accepted series preference influences the next plan and can be revoked without changing Brand Brain identity.

---

## 9. Publish-ready Visual Pack [R-VIS]

### R-VIS-01 · One complete format before a general editor

Deliver one editable **six-slide, 1080×1350 carousel** through the existing Creative Agent and asset pipeline. The user can edit text, replace approved images, reorder slides, and apply the existing brand palette/type settings. Use licensed app fonts and existing components; do not distribute private font files or add a second design system.

Deliver: six actual PNGs, caption, per-slide alt text, an ordered asset manifest with dimensions/hashes/source lineage, and a document export only where the selected channel requires and supports it. An editable pack is an app data model plus editor, not a screenshot of text. Keep slide count fixed for this first format; broader layouts and a full video editor are deferred.

### R-VIS-02 · Deterministic checks around creative output

Reuse `creative.plan_assets` for planning and the existing generation/edit route for approved paid I/O. A plan is not a rendered result. Keep typography/layout deterministic where possible. Check actual glyph coverage, text measurement, safe areas, overflow, missing images, slide order, output dimensions and downloadable file integrity. Never shrink text indefinitely to force it to fit; offer shorter copy or a supported layout adjustment.

Use English and Traditional Chinese cases, including mixed scripts, long names and punctuation. Preview the final rendered assets, not a separate approximation. Alt text must reflect visible content, not fabricate observations. Generated editorial imagery is labelled appropriately and never used as proof of a real customer event or result.

Any changed claim/CTA updates affected pack text and invalidates the affected approval/exports. Keep source images and earlier versions intact. Retries and downloads do not duplicate generation charges.

### R-VIS-03 · Honest distribution

Only offer Direct publishing for an exact qualified account/format/capability. Otherwise expose an **assisted export** with actual files and a clear next step. `export_ready`, `downloaded`, `user_confirmed_used`, `provider_accepted` and `verified_published` are different facts. Feed the existing Queue the ordered asset IDs and frozen manifest; do not create a parallel publishing pipeline.

**Acceptance:** source → editable pack → real export → correct Queue/assisted handoff works on desktop/mobile; text remains legible; exports match the latest accepted revision and cannot be mistaken for successful publication.

---

## 10. Relevant Opportunity Brief, proof and next-week learning [R-BRF / R-PROOF]

### R-BRF-01 · A small decision brief, not a new feed

Extend Radar/Trends, Attention and NotificationService. Select **0–3** actionable opportunities per edition from permitted, sufficiently fresh evidence, the user's goals and their own material. Zero is a valid result. Every item shows its source, published/retrieved times when known, coverage, relevance, a distinct possible angle, effort category and one supported action.

Prioritize unanswered audience questions and opportunities the user can credibly address. Do not equate source popularity, a model ranking and expected customer impact. “Whitespace” must identify an observed gap and its evidence, not promise nobody else has discussed the topic. Stored-only data is labelled stored; unavailable live acquisition cannot masquerade as today's research.

Page loads and passive refresh never start paid research. New live collection requires a permitted provider operation, consent and budget; existing research jobs supply data where qualified. Do not scrape restricted sources to fill an empty brief.

### R-BRF-02 · Delivery and feedback

Use existing in-app and enabled email/push channels. No newly activated outbound channel by default. Proposed growth-delivery cap: at most one opportunity digest per recipient/day, with a weekly cadence as the initial suggestion; user preferences and stricter existing caps win. Keep operational failures/reconnect/security events in their existing priority lane and policy. A model cannot manufacture urgency or bypass quiet hours.

Deduplicate by recipient, edition/period and material content revision across retries and the existing cross-channel policy. Do not send a new alert for cosmetic text changes. Snooze, mute, unsubscribe and “not relevant” must work from the existing controls. Capture accepted action, dismissal reason and outcome references, not merely opens.

### R-PROOF-01 · Weekly/monthly evidence in the existing Growth Loop

Reuse existing proof snapshots and Time Back. A proof includes: accepted work, verified publications, assisted exports separately, unresolved slots, qualified native/first-party/user-declared outcomes, data coverage, estimated/measured/reported time categories using the existing taxonomy, actual/unknown costs where appropriate, and a small next-step proposal.

Every figure links to its underlying scoped evidence. Missing analytics does not erase a verified delivery; delivery does not manufacture external growth. Record period, timezone, definition version, `as_of` and source watermark. New late data creates a new proof revision; preserve the prior snapshot and explain material corrections. Never present different confidence classes of time savings as a single measured fact.

### R-PROOF-02 · Close the loop with explicit adoption

A user can accept, edit or reject a proposed next-week action. Accepted strategy references are scoped to goal/account/language/format, versioned and revocable, using existing overlays/performance mechanisms. Rejected suggestions do not silently reappear each week. Updating strategy does not change identity/voice or authorize publishing. The next plan records which accepted decision it applied, or why it could not apply it.

**Acceptance:** an empty/unsupported brief sends no fabricated opportunity; mute/quiet hours hold; proof agrees with authoritative records; an accepted recommendation is visible in the next plan and revocation stops future use.

---

## 11. Architecture, contracts and persistence [R-ENG]

### R-ENG-01 · Extend the existing app and execution boundary

Keep the existing Next.js web app, Python domain services, workspace repository, agent runtime, durable workers, Queue and notifications. Customer pages reuse Rafii components, tokens, motion and responsive patterns. No additional top-level navigation unless a task cannot be represented in Weekly, Inbox, Library, Growth/Analytics or the existing agent panel.

The implementation path is:

```text
Customer UI / text or voice agent
  → existing authenticated, typed command/tool boundary
  → workspace permission + consent + revision + budget check
  → existing domain service / bounded worker
  → canonical source, draft, week, asset, queue and ledger records
  → scoped read-back + evidence receipt
  → existing proof / notification / approved next-plan input

Founder consumer
  → existing Founder boundary + restricted projection + shared definition
  → aggregate/metadata receipt, never unrestricted customer text
```

No model can directly set delivery status, write financial totals or bypass typed tools. Voice and text have the same authority. Expose read, draft/prepare, reversible edit, and approved dispatch as distinct operations. External effects stay in the existing explicitly approved executor, not a new unrestricted agent tool.

### R-ENG-02 · Logical API contracts

The following are **logical operations**, not claims that these exact endpoints already exist. Bind them to current routes/tools first; add one versioned route only where genuinely missing. The coordinator records the final route/tool mapping in the implementation plan.

| Logical operation | Required behavior |
|---|---|
| `continue_source` | Consent record + selected content → existing source/draft IDs; authenticated import, idempotent within the selected workspace. |
| `prepare_first_week` / `resume_week` | Existing recipe/week IDs, bounded quote, pending inputs and current revisions; no implicit dispatch. |
| `relationship_upsert` / `followup_transition` | Member permission, scoped thread refs, expected revision; content-free audit of changes. |
| `outcome_declare` / `outcome_reverse` | Explicit provenance, currency if relevant, original-event link for correction. |
| `first_party_event_ingest` | Connection-bound signature, tenant binding, dedupe, bounded payload and durable receipt. |
| `series_prepare` / `episode_prepare` | Source/version/expiry checks, distinct angle, existing draft IDs and approval status. |
| `visual_pack_prepare` / `edit` / `export` | Versioned pack, quoted rendering job, ordered assets and immutable manifest. |
| `brief_read` / `brief_action` | Read existing evidence without paid I/O; action requires its own permission/quote. |
| `proof_read` / `strategy_decide` | Versioned evidence snapshot; explicit accepted/revoked preference and revision. |

All authenticated operations derive workspace and actor authority on the server. A client workspace ID selects a target; it does not grant access. Mutations take the existing idempotency key and expected revision, validate cross-record membership and return authoritative IDs plus read-back state. Replays return the existing result; conflicting reuse of a key returns a conflict.

Reuse the current API envelope, adding compatible fields where needed: `requestId`, `definitionVersion`, `asOf`, `dataMode`, `environment`, `dataState`, `coverage`, entity/revision refs, evidence/receipt IDs, job state, usage/quote state, and an actionable error reason. Never replace all existing responses to enforce a new wrapper.

Map errors to explicit states: consent required, unsupported input/capability, source unavailable/stale, insufficient budget, approval required/expired, revision conflict, retry later, and delivery uncertain. Retryability is deterministic; an unknown external outcome is not a retry invitation.

### R-ENG-03 · Logical data ownership and migration rules

The table below defines required information, not mandatory new physical tables. **Inspect current schemas, including concurrent Founder changes, before allocating a migration or table.** Existing equivalent records win.

| Logical record | Canonical owner / requirements |
|---|---|
| Continuation | Temporary consented browser data; canonical source/draft only after authorized import. No anonymous content warehouse. |
| First-week checkpoint | Existing Weekly/workspace command state, references only; no duplicated draft bodies. |
| Relationship and follow-up | Small workspace-owned record plus scoped thread references; bounded notes, due time/zone, revision and transition history. |
| Result event | Append-only workspace result evidence, source ID, event identity, association and corrections. Separate from RAFII billing events. |
| Series and episode | Existing campaign/library extension with source versions, episode role, freshness, lineage and draft references. |
| Visual pack | Versioned layout/text/asset references; private assets use the existing storage and deletion mechanism. |
| Brief and proof | Reuse current opportunities/proof snapshots, edition IDs, evidence refs and material-revision dedupe. |
| Subscription/payment history | Reuse or extend billing and current Founder invoice/subscription projections; never create two competing paid histories. |
| Usage and product metrics | Existing usage ledger and product event taxonomy; shared versioned projections for Founder and Growth. |

New event history should not grow an unbounded workspace JSON blob. Use the existing normalized event/table pattern for high-volume records, with indexes for `(workspace_id, occurred_at, id)` and identity/revision constraints as applicable. Foreign-key validation must prevent a record in one workspace referencing private assets/threads in another. Add forced RLS and least-privilege service/reader grants consistent with the existing project.

Use bounded cursor pagination (default 25, maximum 50 records) and deterministic ordering; never fetch an entire fleet into the browser. Store instants in UTC plus the relevant IANA timezone for civil scheduling. Test daylight-saving gaps and repeated local times with the existing scheduler convention.

Migrations are additive and compatible with the preceding deploy while rolling out. Recheck numbering across active refs; historical 047/048/050/054/055 assignments are not permission to reuse a prefix. Applied migrations are immutable. Unapplied conflicts are resolved by the migration owner before integration, with checksum and dependency receipts. No production DDL is implied by writing the migration.

---

## 12. Measurement and Founder contract [R-MET]

### R-MET-01 · One versioned dictionary, clearly different concepts

Reuse the existing event store and shared metric catalog. Register the following definitions with the Founder/metrics owner, mapping or versioning existing IDs rather than silently changing their meaning. These are this PRD's proposed product measurement rules, not universal accounting definitions.

Default unit is **customer workspace**, not person, event or generated post. Exclude classified internal/test/demo workspaces and non-live provider fixtures; report unclassified/excluded population counts and incomplete coverage. Keep legacy trial and v2 Free cohorts separate. Use half-open time windows, event time, source watermark and definition version. A current period is partial until its full observation window and source coverage have matured.

| Metric | Definition and important boundary |
|---|---|
| `first_accepted_draft_at` | Earliest explicit acceptance of a real canonical draft revision by an authorized user; generated/opened is not accepted. |
| `time_to_first_accepted_draft` | Above timestamp minus workspace creation; name the workspace origin explicitly, not account signup unless that event is actually known. |
| `first_week_ready` | At least one plan with its committed scope, valid sources and all non-cancelled slots ready for review. Track partial plans separately. |
| `completed_work_week` | A reviewed plan whose committed slots each reach the selected delivery outcome: verified publication, or an assisted export explicitly accepted as the chosen handoff. Report those subtypes separately; this is not a publication count. |
| `next_week_completion_rate` | Of customer workspaces completing a work week N, share completing N+1, only for fully observed next weeks. Logins and passive notification events do not qualify. |
| `first_verified_publish_at` | First authoritative Queue/provider read-back for an owned post. Export or provider request acceptance does not qualify. |
| `qualified_business_results` | Result counts by provenance/type and exact association definition from §7, with unmatched and reversed records visible. |
| `cost_per_accepted_artifact` | Total verified provider cost for the declared task population, including failed attempts and platform-funded work, divided by distinct accepted artifacts. Unknown cost stays a separate coverage amount/count; denominator zero returns unavailable. |
| `edit_burden` | Existing versioned edit-distance measure plus review actions/time where observed. “≤0.15 edit distance” is not proof of human quality or an independently measured time saving. |
| `brief_to_useful_action` | Delivered/available brief items leading to their linked accepted action within the declared observation window (initially seven days). Opens/clicks alone are not success. |
| `notification_noise` | Mute/unsubscribe/dismissals with eligible-recipient denominator and window shown; “sent” is not always “delivered.” |

Freeze the committed weekly scope at approval. Scope changes are explicit, versioned and audited; do not improve completion rate by silently dropping failed slots. Cancelled weeks and changed-scope weeks remain visible.

### R-MET-02 · Correct payment conversion and historical retention

S07 directly confirms that legacy `growth.fleet` uses non-trial status as conversion and today's status as retention. Replace that measurement path through the shared definition owner, not by maintaining a second analytics function with different answers.

1. **First cash-paid subscription conversion:** earliest verified, live, positive payment allocated to that workspace's recurring subscription. A checkout redirect, subscription `active`, zero-due invoice, trial, credit top-up, test payment or manually set status does not establish this fact. Resolve payment/invoice relationships using the repository's pinned provider API and verified webhook data. Stripe explicitly distinguishes subscription events and invoice/payment events; active status alone is not a complete payment history [E03].
2. **Historical origin:** retain immutable payment evidence and its service period. A later refund/dispute creates a linked correction and net/refunded classification; it does not silently move the original first-payment timestamp. Invalid/misattributed evidence must be corrected with a revision receipt. Show gross acquisition and any refund-adjusted measure under different names.
3. **Free→paid within 30 days:** denominator is eligible new v2 Free workspaces whose full first 30 days are observable; numerator is those with the qualifying first subscription payment inside that window. Report n/d, exclusions and as-of time. A legacy trial→paid metric has its own population/window.
4. **Cash-paid retention at D30/D60/D90:** reconstruct the checkpoint from historical subscription, invoice/payment and service-period evidence relative to the first qualifying payment, not current status. Count paid service coverage at that checkpoint under the approved correction/refund policy. Free/trial access is not paid retention. Past-due/grace entitlement without paid coverage is reported separately. A cancellation notice with an already paid, unexpired period can still have paid coverage.
5. **Coverage:** when service periods, historical events, refund treatment or provider linkage are insufficient, return unknown/partial and explain the missing source. Never rebuild past milestones by projecting today's subscription backwards. Define allowed source lateness and do not label a checkpoint final before its reconciliation watermark passes it.

Status-based operating counts, MRR, cash received and cash-paid conversion are different views. Stripe offers configurable analytics definitions [E04]; this PRD does not declare every `active/past_due` operating metric wrong. Preserve useful existing metrics with accurate labels and version their changes. Do not activate financial projections with an unresolved policy difference between Founder and Growth.

### R-MET-03 · Events, costs and rollout learning

Map to existing accepted-draft, review, publish, learning, notification and usage events first. Add missing semantic events only once, for continuation claimed, week scope approved/completed, relationship follow-up outcome, result ingestion/reversal, series episode accepted, pack accepted/exported, brief action and strategy decision. Dedupe on semantic entity + revision + event type, not page render. A background actor is explicitly system/worker, not a forged user.

Analytics properties contain allowlisted IDs, enums, counts, durations and versions, not source text, private conversations, contact details, signed URLs or secrets. Record real external cost even when customer credits are refunded. Attribute settlement through reservation lineage rather than the generic `settle:` prefix. `pr_model_usage_events` alone is not complete product cost coverage [S05].

A proposed 10–15-customer focused pilot evaluates why drafts are accepted/rejected, review friction, weekly repeat completion and willingness to renew. This is qualitative evidence, not a powered test or promised uplift. Report cohort size, selection, actual paid evidence and missing windows. Do not call US$49/59/79 a winning price from a tiny, non-comparable sample. Pilot observation can continue after a technical release; do not invent matured retention to close an engineering ticket.

---

## 13. Quality, security, privacy and resource budgets [R-NFR]

### R-NFR-01 · Preserve trust boundaries

Enforce existing membership/RLS, CSRF where applicable, typed permissions, exact approvals, content-free audit and server-owned provider credentials on every relevant operation, not just the route layout. Founder AAL2/operator checks remain separate from customer workspace roles. An agent prompt or source document cannot grant permissions.

Parse links/files as untrusted data. Preserve SSRF, MIME/size, malware-handling and safe-extraction controls already present; render user content safely without arbitrary HTML/script execution. Secrets never appear in telemetry, screenshots, public manifests or downloaded evidence. Test cross-tenant references and revoked membership during an in-flight job.

### R-NFR-02 · Consent, retention and deletion

Continuation, contact follow-up, external source access and outbound channels have separately understandable controls. Do not silently broaden the existing anonymous no-retention promise, privacy policy, training/memory use or financial retention rules. Exports and logs exclude unrelated personal data.

Account/source deletion and access revocation propagate through derivative references, result records and future jobs according to the current approved policy. Stop new generation/dispatch against revoked material. Preserve only the minimum tombstone/audit or legally required financial records allowed by that policy. This program does not make a new legal retention decision. Failure to delete a dependent artifact is visible and retryable, not silently complete.

### R-NFR-03 · Interface and accessibility

Keep the current Rafii visual language. Use progressive disclosure: one primary next action, clear pending work, coverage labels, undo where reversible, keyboard focus management and meaningful errors. Never replace failed writes with success toasts. Existing desktop/mobile conversation preview behavior and reduced-motion preference must not regress.

Target WCAG 2.2 AA for changed flows, including contrast, keyboard access, focus visibility, labels, error identification and usable targets [E06]. Verify 390px phone, 768px tablet and 1440px desktop, English and Traditional Chinese, plus keyboard/reduced-motion cases. Automated axe checks are supporting evidence, not proof of complete conformance. Audio capture and any native-browser-dependent interaction need a separately identified physical-device check before claiming that device is verified.

### R-NFR-04 · Bounded operations and observability

Reuse existing provider/model/task budgets and per-task cost quotes. No unbounded polling, background research on page load, infinite generation retries, or model upgrade that exceeds the approved quote. Failed/unknown external attempts retain their durable state. Use one recovery/reconciliation path, with correlation IDs and privacy-safe reason codes.

Proposed staging performance target: ordinary bounded metadata reads return p95 ≤1 second for 10 concurrent sessions and 50-row pages on an agreed representative fixture, excluding model generation and upload time. Record payload sizes, fixture size, environment and measured results before adopting an SLO. Do not add an infrastructure purchase to achieve a provisional target without approval.

Long tasks return a durable job acknowledgment and visible progress/cancel/resume state. Enforce documented per-stage deadlines and attempt caps; use existing stricter limits. The user must never be stuck with an indefinite spinner after a worker has failed.

Run focused local checks on James's Mac; the coordinator controls shared dependency installs, full builds and disposable DB runs. Prefer existing CI for expensive suites. Do not delete other sessions' caches, stop active coding jobs or launch multiple heavy servers to validate this document's implementation.

---

## 14. Implementation sequence and ownership

G0–G4 describe this customer growth program only. Do not reinterpret them as Founder Admin P0/P1/P2. All bounded scope below belongs to the requested implementation; deferred items in §2.2 do not.

| Stage | Work packages and requirement families | Dependencies | Exit artifact / proof |
|---|---|---|---|
| **G0 · Reconcile and stabilize** | G0.1 current integration/ownership map; G0.2 reuse Pricing v2 and Inbox v1 changes; G0.3 shared payment/product definitions and minimal required history hooks. R-COM, R-ENG, R-MET. | Current production fixes, billing/Inbox/Founder owners; schemas before UI. | Reviewed base/merge plan, no duplicated foundation, authoritative billing/metric contracts, focused negative tests, explicit live blockers. |
| **G1 · First value to first week** | G1.1 consentful Post Doctor continuation; G1.2 guided/resumable week and exact review; G1.3 bounded intake adapter. R-FWR. | G0 entitlement and command contracts; reuse existing source/Weekly services. | Same source through signup, accepted draft, approved week and real artifacts; paid route quoted, Free boundary preserved. |
| **G2 · Follow-through and outcomes** | G2.1 manual relationships/follow-ups; G2.2 declarations and signed first-party receiver; G2.3 association/coverage in existing Growth views. R-REL, R-OUT. | Integrated Inbox interfaces and shared result/metric definitions. | Thread→follow-up; signed event→scoped outcome→proof, with replay, correction and uncertainty tests. |
| **G3 · Reusable content and visual delivery** | G3.1 Signature Series/expiry/lineage; G3.2 editable six-slide pack and exact export/Queue handoff. R-SER, R-VIS. | Source/version/asset contracts from G1; stable credit quotation. | New series episode plus genuinely usable pack, not only plans; final asset and mobile review evidence. |
| **G4 · Useful return loop and release** | G4.1 bounded opportunities/quiet delivery; G4.2 evidence proof and adopted next-plan action; G4.3 integrated quality/cost/metric verification; G4.4 authorized release and operational handoff. R-BRF, R-PROOF, R-MET, R-NFR. | Earlier canonical events and artifacts; live source/notification permissions where used. | End-to-end loop, approved next-week change, exact-version release receipt, per-capability live status and rollback evidence. |

### 14.1 Shared-file ownership

One coordinator owns the integration branch, migration sequence, API schemas, lockfiles, billing hooks, common metric dictionary, notification catalog and final release. Independent workers may own scoped UI/series/visual tests after shared contracts stabilize. Assign mutually exclusive file areas and integrate one slice at a time. Do not create competing global coordinators or edit another active worktree.

Founder changes are an adjacent dependency, not permission to restart that project. Agree on projection/definition contracts and contribute the minimal reviewed patch through its owner. Do not wait for every unrelated Founder/voice/marketplace feature before completing standalone growth work.

### 14.2 Execution method

First produce a short repo-specific task checklist mapped to the requirement IDs and the actual files. Then implement. Use failing regression tests for defects and focused tests for each slice; reuse unchanged fixtures where valid. Record small implementation decisions and continue instead of asking for approval of every component choice.

After each stage, demonstrate its vertical path and update status. Run expensive whole-branch gates on integration/release candidates, not after every tiny text edit. Independent work may continue around an external activation blocker. Do not stop after a new audit, a scaffold, a mockup or G0 while other approved implementation work remains.

---

## 15. Acceptance matrix and quality gates

A case is passed only with current evidence, not because a historical receipt lists a test. Test names below are acceptance IDs, not assertions that scripts already exist. The implementer maps them to actual tests/browser evidence in `STATUS.md`.

| Case | Requirement | Minimum observable result |
|---|---|---|
| AC01 | R-COM-01 | Free and Creator alone appear for new v2 sale; default 59/3,500; 49/59/79 share entitlements; hidden tiers/top-ups cannot checkout. |
| AC02 | R-COM-01 | Legacy paid renewal remains valid; existing trial expires to correct Free state; downgrade preserves content. |
| AC03 | R-COM-02, R-COM-03 | Second Free-funded paid operation, alternate route and insufficient budget are denied before paid I/O; permitted first-value use is recorded once. |
| AC04 | R-COM-02 | One invoice grants credits once; duplicate task/resume creates no second charge; failed/unknown/over-max outcomes follow the v2 contract. |
| AC05 | R-COM-04 | Public/app/checkout/API catalog agree; v2 users do not see stale writing-batch allowances; legacy users see valid legacy terms. |
| AC06 | R-FWR-01 | Anonymous analysis stores no raw source server-side; explicit continuation preserves selected text through signup into the selected workspace. |
| AC07 | R-FWR-01 | Expired state, blocked browser storage, wrong-account login, duplicate import and cross-workspace replay have safe recovery. |
| AC08 | R-FWR-02 | A real source produces an editable first draft and a bounded reviewable week, with missing inputs and source provenance visible. |
| AC09 | R-FWR-03 | Refresh/cancel/reconnect resumes existing IDs and reservations; content edits invalidate affected approvals. |
| AC10 | R-FWR-03 | Accepting content never silently publishes; UI scheduling/publication state is read back from the existing Queue. |
| AC11 | R-FWR-04 | One supported raw audio and one text-PDF case traverse a genuine adapter; unsupported/over-limit/scanned input is handled truthfully. |
| AC12 | R-FWR-04, R-NFR-01 | Embedded source instructions, unsafe URLs, malformed MIME and cancelled intake cannot execute tools or leak data. |
| AC13 | R-REL-01 | Permitted thread/manual record becomes an assigned reversible follow-up; wrong-tenant refs and non-member assignment fail. |
| AC14 | R-REL-02 | Reply uses exact approval and fenced sender; changed digest/revoked account is denied; uncertain outcome is not resent. |
| AC15 | R-REL-02 | Unsupported DM/channel is labelled assisted/unsupported; it is never represented as a direct successful reply. |
| AC16 | R-OUT-01 | User-declared, first-party-reported and provider-native results remain distinguishable; null is not zero and currencies are not summed. |
| AC17 | R-OUT-02, R-OUT-03 | Approved signed producer→receiver→own campaign works; signature, body cap, rate budget, key rotation and wrong-tenant cases pass. |
| AC18 | R-OUT-03 | Duplicate events are once-only; conflicting payloads are rejected/quarantined; late events and reversals update versioned views correctly. |
| AC19 | R-OUT-02, R-OUT-03 | Unsafe tracking destination is rejected; unmatched/expired association stays unattributed; click counts do not claim unique people. |
| AC20 | R-SER-01 | Existing Evergreen behavior still passes; series adds distinct episodes/source refs without a second reshare engine. |
| AC21 | R-SER-02 | Exact duplicate, expired claim, deleted source and rejected angle prevent inappropriate reuse; originals remain unchanged. |
| AC22 | R-VIS-01, R-VIS-02 | Six editable slides produce actual ordered 1080×1350 files, caption/alt text and hash manifest with no clipping or missing glyphs. |
| AC23 | R-VIS-02, R-VIS-03 | Editing updates final render/manifest and invalidates approval; Direct Queue and assisted export have distinct truthful receipts. |
| AC24 | R-BRF-01 | A qualified edition has at most three sourced opportunities; zero/unsupported coverage does not fabricate results or trigger paid reads on GET. |
| AC25 | R-BRF-02 | Quiet hours, DST, mute/unsubscribe and material-change dedupe hold; operational priority is not displaced by growth items. |
| AC26 | R-PROOF-01 | Weekly/monthly proof reconciles accepted work, actual distribution, outcomes, cost and time-confidence categories to the same evidence. |
| AC27 | R-PROOF-02 | Accepted next-week strategy is applied with a recorded reason; rejected/revoked strategy does not silently recur or alter identity. |
| AC28 | R-ENG-01, R-ENG-02 | Agent/text/voice use the same typed permissions; read operations cannot create paid work or external effects. |
| AC29 | R-ENG-02, R-ENG-03 | Revision/idempotency conflicts, cross-tenant assets and pagination boundaries pass against an actual disposable database. |
| AC30 | R-ENG-03 | Additive migrations apply/reapply/upgrade with expected grants, RLS and unique numbering; previous deployed readers remain compatible. |
| AC31 | R-MET-01 | Two views of the same metric/period use one definition and receipt; workspace/user/event denominators do not mix. |
| AC32 | R-MET-02 | Active-without-payment, zero invoice, failed payment, top-up and fixture never create subscription paid conversion; real qualifying payment does. |
| AC33 | R-MET-02 | D30/D60/D90 use checkpoint history, not current status; Free/trial, paid cancellation, grace, refunds and incomplete history are explicit. |
| AC34 | R-MET-01, R-MET-02 | Future/immature cohort cells stay unavailable; completed-week scope changes and assisted exports cannot inflate verified-publish counts. |
| AC35 | R-MET-03 | Total task cost includes failed/platform-funded attempts; unknown cost remains visible; settlement lineage does not become “other” by prefix error. |
| AC36 | R-NFR-01, R-NFR-02 | Tenant/Founder isolation, source injection, secret masking, membership revocation and deletion propagation pass. |
| AC37 | R-NFR-03 | Core flow works at 390/768/1440 with keyboard, reduced motion and EN/zh-Hant; no serious/critical axe findings in changed flows. |
| AC38 | R-NFR-04 | Bounded reads and long-job timeout/recovery are measured; interruption does not lose state, duplicate spending or strand a spinner. |
| AC39 | R-COM, R-FWR, R-PROOF | Integrated source→week→approved handoff→qualified proof→next-week decision path uses real application/DB records, not frontend stubs. |
| AC40 | Release contract §16 | Deployed SHA/alias/config/capability receipts match; flag rollback stops new work and preserves pending/uncertain financial and delivery evidence. |

### 15.1 Four verification groups

**A. Code and contracts:** focused unit/regression tests, typecheck, lint, build, secret/dependency checks and shared-schema compatibility. Run current required repository CI gates on the release head. Historical failures are evidence to investigate, not a reason to disable tests.

**B. Real data path and faults:** disposable PostgreSQL, actual API/repository paths, RLS, migration replay, duplicate/out-of-order events, time windows, budget/revocation/cancellation and uncertain external side effects. Synthetic providers are labelled synthetic. Webhook signature/replay handling follows the relevant provider's current documented contract [E05].

**C. Browser and content quality:** real Next/API/DB journey on desktop/tablet/mobile; final rendered assets, editable state, focus, empty/error/loading states and source-grounded writing. Use a fixed, versioned review set of at least 20 permitted input cases covering EN/zh-Hant, factual material, long/missing input, corrections and adversarial text. Hard failures are fabricated facts/results/quotes, wrong identity, broken export, unreadable text, unauthorized action or data leakage. User acceptance rates are measured, not assumed from model self-scoring.

**D. Hosted qualification:** protected staging plus an authorized customer-like production workspace and named provider/account operations. Keep actual model output, provider read, actual publication/reply and payment test/live status separate. Prove at least one core supported distribution path and separately the assisted-export path. Broader platform readiness is a per-capability matrix, not inherited from one successful connection.

For each group, record command/version, environment, SHA, fixture/live classification, run time, pass/fail/skips and evidence location. Browser emulation is not a physical iPhone test. CI “Ready” is not a successful customer workflow. A failed gate must be fixed, reproduced and assigned if outside scope, or explicitly remain blocking; it cannot be declared green by omission.

### 15.2 Concrete payment history examples

Golden fixtures must include: active subscription with no successful payment; a zero-dollar discounted first invoice followed later by a positive invoice; duplicate paid notification; an invoice covered by non-cash credit; one payment allocated across invoices without double counting; cancellation with a paid period still covering D30; unpaid grace at D60; a refund after acquisition; an invalid/misattributed event correction; and a late renewal event received after the displayed checkpoint.

First cash-paid origin does not move merely because a later refund occurs. Historical milestone coverage is evaluated using service-period/payment facts effective at that milestone, with later-known corrections labelled as restatements. Refund-adjusted retention is a separately named definition. If the source lacks the needed allocation or correction semantics, the fixture expects unavailable, not a guessed number.

---

## 16. Rollout, production readiness and rollback

### 16.1 Release-state vocabulary

Track each requirement/capability across separate states:

`not_started → implemented → local_verified → staging_verified → production_deployed → production_verified`

Attach `blocked`, `failed` or `not_run` with a reason instead of advancing it. Data mode (`demo`, `synthetic`, `live`) is separate from environment (`local`, `staging`, `production`). A production-hosted Demo is still Demo. “Production implementation shipped” and “live commercial activation complete” must not be conflated.

The **whole program is production-verified only when all in-scope requirements and advertised launch capabilities have the relevant real-environment evidence**. Optional deferred features do not block it. A safe partial release may be useful, but its missing scope is explicit.

### 16.2 Smallest safe release sequence

1. Re-read production/default refs, current owner work and any drift since §3. Reconcile the release candidate and required migration/configuration order.
2. Complete code, affected regression tests, whole-branch review and CI. Reuse valid unchanged evidence with an explicit SHA/scope binding; rerun affected paths.
3. Apply approved additive changes in a qualified staging environment; keep new external effects off. Execute the integrated journey with real storage/API and controlled providers.
4. Produce an activation manifest containing exact project/environment, migration filenames/checksums, source SHA, flag names, workspace allowlist, per-operation capabilities, budget/consent references, approval owner and rollback conditions. Use existing flag names when available; newly proposed names are recorded before deployment, not invented as already set.
5. Under actual release authority, deploy to the existing project and verify candidate SHA, alias, authentication, new path and unchanged critical flows. Do not promote a stale branch merely because it has green CI.
6. Enable only the named internal/customer-like workspace and explicitly approved operations. Verify authorized paid generation and source→draft→week→approved distribution/assisted export→proof. For reply or first-party adapters being advertised as live, capture their separate receipts.
7. Review observed errors, costs, queue backlog, data freshness and user-facing state. Expand only inside the agreed permission/budget and after the initial path passes. Ship a runbook and exact rollback reference.

A generic PRD approval does not activate live Stripe checkout, apply production DDL, create privileged identities or send a social message. Where S03/S04 require separate approval, preserve that condition. Prepare the exact bounded action and continue other work; do not describe a permissions blocker as a technical completion.

### 16.3 Minimum operational receipt

The release receipt binds: repository/branch/commit; pull request and merge status; deployment ID/URL/alias; active catalog version; migrations and apply status; feature flags without secret values; approved workspace and provider operation refs; real and synthetic tests separately; verified artifacts/Queue/job/payment/result IDs; known limitations; monitoring source/time; and rollback target.

Store sensitive evidence in the existing private evidence path. Public reports contain only opaque references and sanitized summaries. Never copy customer content or secrets into a public GitHub receipt.

### 16.4 Rollback behavior

First disable admission of new affected work using existing feature/provider flags. Do not erase pending jobs, ledger holds, webhook events, approvals or receipts. In-flight/uncertain operations remain reconcilable; switching a feature off cannot provoke a second send or charge.

Revert to the last compatible deployment only after confirming additive schema and API compatibility. Preserve legacy subscriber entitlements; disabling new Creator sale is not an unannounced downgrade of existing customers. Pause external collection/notifications independently from read-only history. No destructive down-migration or bulk data deletion as ordinary rollback.

Trigger rollback for tenant leakage, incorrect charging, duplicate external effects, materially false verification/metric claims, unusable core flow or a release regression that exceeds the approved operational budget. Preserve evidence and distinguish mitigation from resolution.

---

## 17. Agent execution, living documentation and handoff

### 17.1 Single working specification

Preserve S01 and this delivered v2.0 file as input snapshots. At implementation start, copy this specification into the agreed owned branch at `docs/design/rafii-product-growth/PRD.md` and record its source SHA-256. That repo copy becomes the active engineering specification; do not silently edit the original audit or a neighboring team's PRD.

Keep a small package alongside it:

- `IMPLEMENTATION_PLAN.md`: actual files, owners, dependency order and acceptance mapping; no second broad research report.
- `STATUS.md`: each requirement's implementation/verification state, code SHA, test/evidence refs, environment, blocker and exact next step.
- `DECISIONS.md`: short dated decisions, scope/definition changes and cross-owner agreements.
- `RELEASE.md` plus `evidence/`: release/activation/rollback and sanitized verification references.

One coordinator owns shared contracts. Reuse equivalent existing project tracking files instead of creating duplicate logs. Every material code change updates the corresponding requirement status; every spec change states what changed and why. Never mark a requirement complete merely because documentation was updated.

### 17.2 Iteration loop

`Read latest status and source → identify first incomplete requirement → implement smallest complete slice → run focused tests/read-back → fix defects → update evidence and version → continue.`

Routine implementation choices use the smallest design consistent with this PRD and are logged without repeated clarification. A discovered missing prerequisite is implemented or coordinated, not used to restart the project. A proposed commercial, privacy, permission or external-spend expansion is isolated for owner decision; do not self-approve it.

Preserve all required scope. Do not quietly relabel a difficult feature “future,” loosen tests, add synthetic production fallbacks or replace a real backend with a demo to claim completion. If current code already satisfies a requirement, verify and reuse it rather than reimplementing it.

### 17.3 Completion report

Report: shipped behavior; each G-stage's actual state; branch/commit/PR/merge/deployment identity; evidence for the complete customer loop; test commands and failures/skips; data/provider/catalog/credit status; open blockers with one exact required owner action; and rollback location.

Use separate headings for **production verified**, **implemented but not live-qualified**, and **remaining/blocking**. Do not label the entire effort finished when only source or preview work is complete. Conversely, do not withhold completed independent work because one provider or commercial activation remains blocked.

### 17.4 Version history

| Version | Date | Change |
|---|---|---|
| 2.0 | 2026-10-01 | Consolidated audit + six chat investments; preserved Pricing v2/Inbox ownership; added First Week continuity, results/relationships, Signature Series, bounded visual delivery, relevant briefs, shared paid-cohort definitions and G0–G4 production acceptance. |

The v2.0 label denotes this consolidation. It is not a claim that every proposed feature has shipped or that a previous product-growth v1 document exists.

---

## 18. Source and provenance index

### 18.1 Local sources read in full

**S01 · Primary audit**
- Path: `/Users/ouxianxing/Downloads/RAFII-Repo-Market-Growth-Audit-2026-10-01.md`
- SHA-256: `be869f31d067c795162f4e41b0a3bd3fe2c4ad404fc3b6a09e20a81e3c7fbe84`
- Read: all 232 lines. The audit's historical test/HTTP observations were not rerun by this document task.

**S02 · Current conversation**
- Six investment recommendations immediately preceding James's consolidation request.
- No attachment hash; advisory input, with the pricing/Free/evergreen corrections explicitly reconciled in §1.

**S03 · Pricing v2 handoff**
- Path: `/Users/ouxianxing/.codex/worktrees/rafii-pricing-credits-v2/James-Au-Studio/docs/superpowers/handoffs/2026-09-28-rafii-pricing-credits-v2-worker-handoff.md`
- SHA-256: `4ef98a32546193b2d357060af6761817b794cde40ee9296b3cefcdf63e3f3f66`
- Read: all 333 lines. Linked design/implementation documents must be read by the implementer before modifying billing; this task did not independently re-audit every linked file.

**S04 · Inbox local completion**
- Path: `/Users/ouxianxing/.codex/worktrees/rafii-inbox-completion/James-Au-Studio/docs/superpowers/handoffs/2026-09-28-rafii-inbox-v1-local-completion.md`
- SHA-256: `c271f76a1a848a8ebd279827283000754dafcb7ff191433309161cb5acc64456`
- Read: all 57 lines. Local/synthetic receipts are historical, not fresh live-provider verification.

**S05 · Founder Admin PRD and implementation addenda**
- Path: `/Users/ouxianxing/Documents/D Festival Website Migration/Rafii-Admin-Handoff-2026-10-01/Rafii-Founder-Admin-Intelligence-PRD-v2.0.md`
- SHA-256: `07e7bf6e23278d17abaf9f9e6ff34215460bc49c32b464757eacd0b08cf3c97d`
- Read: all 915 lines. Use for dependency/ownership awareness, not as current proof for every provider/model/price or financial policy discussed there. D Festival is only a storage location.

Hashes were obtained from the Mac at `2026-10-01T16:22:18Z`. Originals were not changed by this document task.

### 18.2 Fresh repository/deployment checks

**S06**
- PR #84 metadata: https://github.com/dev-james0723/PostRiff/pull/84
- PR #86 metadata: https://github.com/dev-james0723/PostRiff/pull/86
- Founder P0 contracts excerpt at refreshed head: https://github.com/dev-james0723/PostRiff/blob/cb40a7274db096954279a890afbade921a9ee9d6/docs/design/founder-admin/CONTRACTS.md
- Vercel connected deployment lookup for `postriff-phase2-private.vercel.app`, team `team_PgXY5VdAYKcsv0RLoDPHscNq`, project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`; result ID/SHA in §3.
- Read-only `git log -1` and branch reads on canonical, pricing, Inbox and Founder worktrees; no checkout, fetch, code change, test or deployment in this document task.

**S07 · Direct source verification**
- https://github.com/dev-james0723/PostRiff/blob/dcb5bcdcd76577835a6944f50310e25f16be9de8/src/postriff_phase2/coworker/growth.py
- The payment/cohort defect is in `fleet`; the current implementation's generic weekly-return metric also counts event-active users, not completed-work workspaces. This PRD specifies a separate, accurately named completion metric.

Other module references in §3 are carried from the inspected audit and prior turn. They are integration anchors to re-open at execution time, not assertions that every function was freshly re-read for this document.

### 18.3 Official external verification used narrowly

**E01 · Buffer pricing**, read 2026-10-01: https://buffer.com/pricing
Used only for the inexpensive AI/scheduling reference point in §4, not customer-outcome claims.

**E02 · Blaze pricing page**, reopened 2026-10-01: https://www.blaze.ai/pricing
Parsed response did not provide a readable current price table. No fresh Blaze price claim is made here; historical comparison remains in S01.

**E03 · Stripe subscription webhooks**, read 2026-10-01: https://docs.stripe.com/billing/subscriptions/webhooks
Used to distinguish subscription lifecycle and payment events. Implementation must respect the pinned API version and actual invoice/payment payloads.

**E04 · Stripe subscription analytics**, read 2026-10-01: https://docs.stripe.com/billing/subscriptions/analytics
Used to identify definition choices and the difference between operational recurring metrics and cash-based conversion. This PRD's product cohort rules are explicit decisions, not represented as mandatory Stripe defaults.

**E05 · Stripe webhook handling**, read 2026-10-01: https://docs.stripe.com/webhooks
Used for signature/duplicate/event-order considerations in payment integration. The generic first-party contract in §7 is a proposed RAFII contract, not a claim that every provider uses its exact replay window.

**E06 · W3C WCAG 2.2**, read 2026-10-01: https://www.w3.org/TR/WCAG22/
Accessibility target for changed flows. Automated checks and this PRD do not certify conformance.

### Evidence limit

No real customer conversion dataset, customer interviews, live checkout, authenticated production journey, real social send, paid model execution or benchmark was run for this specification. Requirements, UX defaults, performance targets and business hypotheses are proposals to implement and verify. Fresh state observations and inherited historical evidence are separated above.
