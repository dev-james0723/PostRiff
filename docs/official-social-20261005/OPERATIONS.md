# Candidate operation and live release gates

No commands in this file authorize a deployment, new app review submission, credential transfer, metered request or social publication. Existing user instructions govern every external action. Test accounts, destinations, exact content/assets, visibility, spending ceiling and cleanup actions must be explicitly approved before real writes.

## Cloud validation

Use the internal installed CLI from this worktree:

```sh
PATH=/Users/ouxianxing/.local/bin:$PATH jcb --repo /Users/ouxianxing/Documents/James-Au-Studio doctor
PATH=/Users/ouxianxing/.local/bin:$PATH jcb --repo /Users/ouxianxing/Documents/James-Au-Studio ci
PATH=/Users/ouxianxing/.local/bin:$PATH jcb --repo /Users/ouxianxing/Documents/James-Au-Studio test
PATH=/Users/ouxianxing/.local/bin:$PATH jcb --repo /Users/ouxianxing/Documents/James-Au-Studio e2e
```

`ci` includes full web audit/lint/typecheck/tests/build and selected backend/SQL suites. `test` currently passes `--backend-only` for affected Python/SQL validation. `e2e` is the synthetic browser acceptance suite, not live provider execution. The adapter and generated workflow must match; use JCB setup to regenerate after an intentional adapter edit. Never bypass workflow/compute guards. Do not repeat already-passed checks on unchanged source.

## Provider configuration

Existing credential names use `POSTRIFF_OAUTH_<PROVIDER>_CLIENT_ID` and `_CLIENT_SECRET`. Do not export values into reports, snapshots or chat. Runtime adapters accept operator-owned `_PRODUCT_APPROVALS_JSON`, `_APPROVED_SCOPES`, `_E2E_EVIDENCE_JSON`; X additionally `_BUDGET_POLICIES_JSON`, Facebook `_LOGIN_CONFIGS_JSON`, TikTok `_VERIFIED_MEDIA_DOMAINS`. Exact parsing lives in `src/postriff_phase2/providers.py`. `POSTRIFF_OFFICIAL_SOCIAL_ENABLED` opts into the candidate engine and must not be enabled merely because CI passed.

Product proof is keyed by the catalogue product. A valid approval record contains `state: approved`, the real matching `appId`, and an inspectable `evidenceRef`. LinkedIn restricted scope approval is separate from an OAuth token's actual scopes. Facebook Login for Business configuration keys match the sorted selected scope set. Do not reuse an all-permissions login configuration for identity-only connection.

E2E evidence is keyed by the actual account/destination binding used by OAuth channel qualification. Eligibility keys refer to individual catalogue capability names. Each live feature receipt must contain `state: passed`, `kind: live_api`, exact `accountId`, `destinationId`, `appId`, `implementationRevision`, SHA-256 of JSON-encoded sorted actual scopes as `grantHash`, an `evidenceRef` and timestamp `at`. Current implementation requires evidence at most 30 days old. A new grant, destination, app or relevant implementation invalidates it. Never insert fabricated fixture evidence into this store.

X policies are keyed by `<workspaceId>:<connectionId>` and contain approved `currency: USD`, `approvalRef`, `limitMicros`, `perRequestMicros`, `expiresAt`, and `allowedEndpoints` such as `GET /2/users/me` or `POST /2/tweets`. A policy is a user-approved upper ceiling, not a quote or invoice. Identity lookup is metered too; approve its scope/cost before connecting. Each actual dispatched request reserves again, including reads/polls/error outcomes.

## Reviewable live test manifest

Before execution, populate a separate secure operator manifest with:

1. Provider/app ID and official product/review evidence, actual access tier/limits and approved permission groups.
2. Ordinary account ID and eligible destination ID: LinkedIn member plus approved organization; Threads profile; Instagram professional type; managed Facebook Page/tasks; X account/access/cost policy; owned YouTube channel/audit; TikTok creator/domain/audit; Pinterest business/board/ad/merchant prerequisites.
3. Exact text, media hash and rights, optional alt/caption/disclosure/poll values, visibility, native reply parent/root ID and schedule timestamp for each write. Start with private/unlisted/SELF_ONLY only when the provider permits it and approval specifies it. Ordinary text publishing may have no private mode.
4. Explicitly authorized cleanup IDs/actions and retention of provider receipts. Delete/edit/moderation and live broadcast transitions are separate effects.
5. Maximum cost/resource call budget and reconciliation policy. Use approved test comments/accounts; do not generate engagement on unrelated people.

The current manifest is deliberately unpopulated: no real test account, content or cost approval was supplied. The required cases and their exact NOT_RUN states are in `live-e2e-matrix.json`. Provider credentials/consent and app-review/manual steps are external blockers; scripts cannot substitute for them.

## Native action and read lifecycle

Workspace-authenticated APIs use `native-read`, `native-action`, and `native-action/{id}/approve` under the selected connection routes. Reads require explicit operation IDs/options; permitted operations are fixed in `official_operations.py`. Writes prepare a 600-second immutable preview/manifest before approval. Unknown submission remains uncertain and cannot be approved again. Confirm the native IDs/parent/root and exact body in the preview; do not assume a successful HTTP transport proves publication.

Advanced YouTube live/caption/podcast/reporting, Pinterest commerce and X Article actions currently have these API contracts. Their complete consumer editors are not in this candidate. Instagram Insights is intentionally stopped before provider dispatch pending the primary audit. Messaging/DM is separately modeled and not exposed as a side effect of publishing.

## Schedule and recovery

Approved drafts freeze payload, ordered asset IDs/hashes/rights, destination, options, approver, timing and idempotency key. Rafii workers revalidate token/account/role, persist intent before each forward mutation, wait for media usability and reconcile receipts. LinkedIn/Threads/Instagram/X/TikTok/Pinterest use Rafii timing. Supported Facebook feed paths and YouTube use native future publishing. A revoked permission can make cancellation impossible even when a native future post already exists; report that held/unknown state rather than promising cancellation.

Provider-native scheduling cancellation requires current valid management scope and fresh eligibility. Network timeout after create/publish does not authorize a new duplicate submission. TikTok inbox means creator handoff; it cannot promise final publish time. TikTok file-upload chunk continuation is a current implementation limit; URL cancellation is an explicitly approved best-effort native action and cannot delete an already published post. YouTube resumable byte recovery is implemented and queries the documented session status first.

## Release checklist

Retain exact grant/product/account/evidence for every READY feature; run only its approved live cases; preserve processing/error/rate/cost receipts and permission-loss/reconnect cases. Re-audit inaccessible or changed contracts before requesting scopes. Deploy only an approved candidate through the existing release path, then verify production independently. All eight providers remain NOT PRODUCTION READY until these gates pass.
