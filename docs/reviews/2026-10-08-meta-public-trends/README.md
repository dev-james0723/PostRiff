# Meta public discovery — App Review / activation packet

**Date:** 2026-10-08. **Environment:** Rafii production `https://rafii.io` (canonical domain intent; verify current route, actual app domains and OAuth callbacks before submission). **Status: NOT SUBMITTED; no public discovery permission verified.**

This pack is **separate** from `docs/design/growth-phase0/META-APP-REVIEW.md`, which applies only to own-account Instagram/Threads insights and replies and explicitly excludes public search. A successful Meta sign-in or owner analytics call is not public discovery authorization.

## 1. Admin account and Meta app identity gate

- James's previously stated direction: **HINSINGAU** should be the Meta developer/business controlling identity rather than **James Au Creates**, with a proposed Facebook Page called **Rafi** for the Rafii product. These are desired identities, NOT proof of completed ownership transfer or Page creation. Live Meta Console must confirm business ownership, roles, app ID, Page ID, verified domain, mode (Development/Live), and the current reviewer permission status.
- Never paste Meta App Secret, system-user token or user access token into GitHub issues/files/chats. Store service secrets only in approved secret manager. Perform OAuth/App Review/Meta Business Verification through the provider's own interactive consent controls.
- Check redirect URIs for `https://rafii.io`, canonical host and actual route against existing code; do not blindly reuse old `postriff-phase2-private.vercel.app` callbacks.
- Retain existing Instagram Login without Facebook Page for **owned** use. A parallel Facebook Login route is required only when the selected **public hashtag/business-discovery** operation needs that auth model. Never overwrite other users' connected grants.

## 2. New Meta App Review capability requests (independent)

| Operation | User-facing purpose | Exact gate to prove |
| --- | --- | --- |
| Threads Public Keyword Search | Creators find public Threads conversations on a chosen keyword/topic, see a bounded list of original posts and source links, detect changes over time | `threads_basic` + `threads_keyword_search`, official App Review, consent/token scope readback, real other-account result, provider limitation evidence |
| Threads public profile posts (optional follow-on) | Monitor specific public authors after user chooses a handle | `threads_profile_discovery` plus current app review/role and exact permitted fields; separately from keyword |
| Instagram Hashtag Discovery | Search and compare recent public Instagram media tagged with user-selected hashtags; not platform-wide text search | Instagram professional via Facebook Login, `instagram_basic` and approved Instagram Public Content Access feature as required; 30 unique tags / 7 days per professional account tracked durably; fields observed |
| Instagram Business Discovery | Evaluate nominated other business/creator accounts (no private consumer account) | Facebook Login IG professional route, Business Discovery operation allowance and verified relevant grants |
| Facebook public Page content | See public posts of specific eligible Pages and engagement metadata, not private groups or personal timelines | Approved **Page Public Content Access** (PPCA) feature and correctly scoped app/system user token; actual third-party public Page example with source ID |
| Facebook owned Page insights | Show analytics for a Page the user manages | Separate Page role, `pages_read_engagement` and operation-specific permissions; do NOT reuse as public PPCA proof |

### Recommended App Review screencast sequence

1. Sign in as a permitted real Rafii test user; open Channels to prove identity and explicit permission prompt **for the operation being reviewed**.
2. Navigate to Trends → Public Sources; show verified connected-source scope. Enter a harmless keyword/hashtag or nominated Page and show exactly one external API request, source URI and canonical timestamp.
3. Open an actual returned third-party *public* post. Show provider, source link, language, retrieval time, what is not covered, and a clear label "sample, not every post."
4. Show the user-controlled query/selection, source disconnect, rights revocation and data deletion UI.
5. Display rate-limit or unavailable behavior, without fake fallback or fabricated results.
6. For Meta reviewers, provide a working review user and reproducible seeded preview but do not fabricate provider data. Respect real test-user setup constraints and redact PII.

### Suggested short use-case descriptions

**Threads keyword:** "Rafii helps creators research topics before drafting original posts. When a user explicitly searches for a keyword, Rafii requests a bounded, authorized sample of public Threads posts through the official Threads API. The UI displays canonical links, time and source coverage, not unverified platform-wide counts. Raw content is stored only under reviewed processing rights and is deleted according to the source lifecycle."

**Instagram hashtag:** "Rafii enables connected Instagram professional users to explore current public posts by hashtags they select. Hashtag queries use the dedicated Facebook Login/Instagram Public Content Access route after relevant approval. We enforce the per-account rolling seven-day unique hashtag budget in durable storage; no Instagram personal-account history or private content is collected."

**Facebook PPCA:** "Rafii monitors eligible public Facebook Pages chosen for topic research. Public Page post retrieval requires approved Page Public Content Access and returns only the provider-permitted public fields. Managed Page analytics and private user/group content are kept outside this public discovery feature."

## 3. Data rights and pricing review

For each approval entry record as separate immutable evidence: app ID, feature/scope, app approval screenshot/portal status (private), allowed operation, user/workspace scope, token expiry, allowed fields, data retention, derivative/AI processing permission, geographic limits, rate-limit schedule, revocation/deletion contract, and current API version. Do not re-use an IG/Facebook permission for Threads; do not use Meta Content Library API for customer-serving commercial SaaS.

Default rights: `retrieve` only after approved admission; `store_raw`, `display_excerpt`, `llm_process`, `derive_metrics`, `cross_source_combine`, `train_or_finetune` and `share_across_workspaces` are independently denied until reviewed. No model receives an unread or redacted token. Native "likes"/"views"/"shares" are platform-specific.

## 4. Human-only checkpoint

Meta account/business owner must confirm correct target app and submit App Review (and any business verification/permission acceptance). For each required source, **only** provide the relevant provider portal approval and user OAuth interaction. Do not request passwords or access-token copies. Paid commercial feed agreements and billing require their own explicit human approval.

No current action by this branch has submitted an App Review, consented a user, created a Facebook Page or expanded production data access. Treat all such stages as `BLOCKED_PROVIDER_APPROVAL` until provider records are present.

## 5. Acceptance receipts required before any claim of public Meta coverage

- Official app review/feature record and valid permission grant (not a role-only test user).
- Live result from a user-authorized endpoint for an eligible **third-party public** record.
- Source observation stored in the correct workspace with revocation and rights policy, canonical ID and original timestamp.
- Verified user-facing Trends read (not merely 200 from API), honest as-of, coverage and no fabricated totals.
- Required negative tests: unrelated workspace, token revoke, deleted post/Page, missing feature, quota exhausted, 429/403, invalid next-page URL, disallowed text storage, personal/private restrictions.
- Model evaluation only where license/policy permits actual processing, bounded usage and evidence-linked outputs.
