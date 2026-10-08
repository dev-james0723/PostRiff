# LinkedIn preview pilot — exact approval candidate

Execution state: **CANDIDATE ONLY; no wider consent, configuration activation, post, deletion, push or deployment performed.**

The current verified connection preview remains SHA82b4c282. These publishing repairs are local to branch `codex/linkedin-publishing-recovery-20261008`; candidate source SHA and final remote check receipts will be attached before action.

## Proposed sequence

1. Parent reviews this tested local worker commit and integrates it into the already-authorized recovery branch `codex/social-connection-recovery-20261007` / existing PR131, then updates the existing **preview only** on Vercel project `postriff-phase2-private` at the fixed registered origin below. Existing push/PR/preview authorization is preserved; no new worker-branch push or alias is proposed. Production merge/deployment remains excluded. Activation, optional consent and the exact one-post/cleanup pilot below still require action-time approval.
2. Approve the preview-only product-evidence and LinkedIn workflow configuration candidate in `share-on-linkedin-preview.candidate.json`. The observed app already has Share on LinkedIn Added (Default Tier); this records that evidence with strict environment/client/callback binding. It does not change provider registrations or create approval. Operator first securely checks the actual Python runtime `VERCEL_ENV=preview`, public origin and client match. The existing provider catalog exposes `memberPublishingStatus.runtimeEnvironmentVerified` and the allowlisted runtime label even before a Share record exists. Missing/mismatched runtime evidence stops activation.
3. Tester B, in their own existing Rafii browser session/workspace, confirms the visible destination below and chooses **Channels → LinkedIn → Enable Publish**. The owner completes official consent requesting only `openid profile w_member_social`. No email equality is required between Rafii and LinkedIn. Password/passkey/MFA/consent remain with the owner; no credentials go into chat.
4. Through Rafii's normal draft → review → exact approval → worker journey, create **one immediate PUBLIC organic personal text post** with the exact text below. Do not schedule, attach media, include links/mentions, boost, advertise or create a second post. Stop if the UI selects another destination or requests unrelated permission.
5. Retain the real HTTP201 + `x-restli-id` receipt, app/environment/source revision, actual grants and trace reference. Open only the canonical URL derived from that returned ID; the owner checks the exact text/account in LinkedIn. Capture redacted native inspection evidence separately from API verification. No restricted historical member read is requested merely to inspect this post.
6. Delete **only that newly returned post ID** using the same account and existing exact operation approval. Record the actual deletion response and owner's native disappearance check. If any create/delete outcome is ambiguous, stop and reconcile; never repeat an uncertain create or deletion blindly.

## Exact target, content and effect

- Provider app: **James Studio**, console app **263833009**, OAuth client binding recorded in the secure configuration candidate.
- Environment: preview only; proposed canonical origin `https://postriff-phase2-private-git-c-752940-jamesau0723-6572s-projects.vercel.app`.
- Rafii ordinary Tester B workspace reference: `249fd4ac7489aafd15b4fe6c6cc0b216`.
- LinkedIn account reference: `62c2c6ce86976d46e6c446e3ecefce46`.
- Exact visible destination: **James Au · LinkedIn · member**. The owner must confirm this is their intended profile. Tester A has a similarly named but different subject; never substitute it.
- New scope: **w_member_social**, added to existing `openid profile`. Effect: publish/manage this member's posts. No organization, feed/comment, analytics or historical-read scope requested.
- Visibility: **PUBLIC**. Maximum create count: **1**. Time: **immediately after owner consent and exact draft approval**, no scheduled time.
- Cleanup: delete exactly the returned pilot ID after native inspection. No older posts or other workspace records are affected.
- Cost ceiling: **$0 additional billing authority; no ads, boosts, subscription or metered X calls.** This is an authority limit, not an undocumented provider-price assertion.

Exact post text:

> Rafii integration test: verifying a LinkedIn text post. This test post will be removed after verification.

## What a successful API acceptance shows

A genuine201 + `x-restli-id` yields **Accepted — confirm on LinkedIn**, the retained Post ID, and a strictly validated **Open post to confirm** link. It does not become API verified just because the provider accepted it or the owner inspected it. With no `r_member_social`, reconciliation sends no predictably forbidden historical GET; it retains acceptance, directs native inspection and blocks duplicate resubmission. The existing worker keeps the job in-flight, then backs off after bounded checks. There is currently no owner action that forges terminal API verification. This limitation is visible and does not prevent creating a separately approved new post.

## Evidence needed to advance

Exact source/deployment identity and remote checks; preview-only runtime/client/callback binding; owner's confirmed intended profile and actual write grant; one normal-UI create receipt and native inspection; only-created-ID deletion receipt; no cross-workspace access; a fresh Rafii session retains connection. Each is recorded independently. Publishing public readiness stays unverified until the ordinary-user pilot actually passes. Scheduling, media formats, edits, comments, analytics and organization operations keep their separate tests/permissions/reviews. Real iPhone Safari and time-dependent renewal remain pending.

## Rollback

Restore the previous preview LinkedIn-only flag and `share_on_linkedin` evidence key, preserving OIDC evidence, other product records, existing customer connections, encrypted grants and stable credential key. Restore the approved previous preview source if needed. Never use rollback to rotate secrets, revoke grants, replay a create or alter production.
