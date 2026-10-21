# X Direct G15: media and connected application acceptance

## Release boundary

This branch is an engineering candidate, **not Public Production Ready**. Local identities, consent pages and X responses in the browser fixture are synthetic. SQL, Rafii permissions, the OAuth state/PKCE exchange, credential vault, operation journal, cost reservations, worker and application pages execute real application code.

No real X uploads, posts, replies, messages or paid reads are authorized by these tests. Do not apply production migrations, enable production flags, merge for release, stage a billable build or promote domains from this document. Preserve the canonical production project `postriff-phase2-private`, database `buoyhkbodnhzngaotoel` and site `rafii.io`; never substitute the old staging database.

## Implemented media workflow

The customer chooses a decoded private workspace image or container-verified Library video. The server resolves its immutable metadata; the client cannot supply a remote URL, storage path or media-ownership assertion. `media.upload` creates a preview without sending bytes. The customer approves the exact account, authorization generation, asset, alternative text and conservative workflow budget.

The existing durable X journal executes one official API operation per claim: simple image upload or video initialization, ordered chunks, finalization, bounded processing checks and optional alternative-text metadata. Each request reserves cost before transport. Each accepted step keeps its own response hash and provider receipt. Cancellation stops unsent steps; unknown write outcomes are not automatically replayed. Storage reads are followed by a final lease check before external I/O.

A subsequent post needs a separate approval. Only a completed, unexpired upload for the same workspace, X account and OAuth generation is attachable. Reconnect, revoked authority, asset deletion/change, mismatching media keys and changed prices block writes. A scheduled post must precede media expiry. Readback checks exact actor, post ID, text, references and attachment keys; media-link suffixes are removed only when the exact URL entity belongs to that post and an approved attachment. Upload expiry after an accepted post does not invalidate the saved post's readback authority.

Current implementation limits are stated as **Rafii limits**, not invented X restrictions: image renditions use the private decoded-image pipeline; video reads are capped at 100 MB and 20 minutes by the verified private storage workflow. A video or animated image is attached alone; up to four verified JPEG/PNG images may be attached. Poll and tagged-user readback remain disabled until separately implemented and verified.

## Pricing is evidence, not a guess

The existing server-only cost policy must be current and explicitly activated. In addition, transfer steps require positive per-request conservative upper bounds in:

`RAFII_X_COST_MEDIA_PRICE_CEILINGS_JSON`

Allowed keys are `media_upload`, `media_initialize`, `media_append`, `media_finalize`, and `media_status`. Include the corresponding keys in the existing allowed-price-key policy. The existing metadata price is independent. No transfer price is inferred from metadata pricing or from an API request count. No default upload price or implicit free allowance is installed.

Every full upload envelope includes a finite allowance for definite pre-acceptance retries, chunks, processing checks and optional metadata. Changed quotes cannot reuse an old cost activation or erase consumed usage. Fixture values are explicitly synthetic and are never production pricing evidence. Application estimates and request counters are not a guarantee of the provider invoice cap. The old US$0.10 identity-only test approval does not cover these operations.

## Candidate migration

Migration `135_x_oauth_provider_identifier.sql` repairs an actual integration failure: the older OAuth transaction constraint allowed provider names of length 2–40, rejecting `x`. The candidate permits exactly `x` or the original 2–40-character names; it does not allow arbitrary one-letter providers and does not weaken tenant policies.

Candidate X migrations 131–135 must be reviewed against the deployment's actual schema and any concurrent migration numbering before a separately authorized rollout. Applying these migrations to a disposable test database is not production migration evidence.

## Reproduce the isolated acceptance

Install the pinned application/dev dependencies and `requirements-x-tests.txt` into a clean virtual environment. Install web dependencies from the lockfile, PostgreSQL 17, and the Playwright Chromium/WebKit versions corresponding to the installed package. Then run:

```sh
POSTRIFF_PG_BIN="$(pg_config --bindir)" \
  python scripts/x_direct_acceptance.py --output /tmp/rafii-x-acceptance-evidence
```

The runner uses an exact source manifest before and after execution, a disposable UNIX-socket PostgreSQL cluster for SQL tests, a separate loopback fixture database for application E2E, lint, all root web contract tests, TypeScript and an optimized Next build. Desktop Chromium and mobile WebKit execute the connected synthetic OAuth → upload approval → upload/metadata receipts → separate post approval → exact readback journey, schedule cancellation and foreign-tenant rejection.

The browser artifact has explicit loopback API routing and **must never be deployed**. The runner terminates only its own fixture processes and PostgreSQL cluster. Fixture control secrets stay outside the repository and are removed; screenshots and logs must retain their synthetic evidence label. The result records source-tree hash, HEAD and per-stage exit codes. A previously green result does not qualify later changes.

`.github/workflows/x-direct-acceptance.yml` uses a standard Ubuntu runner on a public repository, with no paid runner, provider credentials, deployment command, persistent artifact upload or cache upload. Results remain in job logs/summary. Existing repository-wide release gates still apply; this workflow does not bypass them.

## Review and preserved work

The candidate is a separate linked worktree descended from `5325a86eb606971b6be78fba46c91e730e2f4fb2`. Only reviewed X files and X-specific retirement hunks from the shared publisher were transferred. Uncommitted Pinterest, analytics and other platform recovery work remains in its original worktree. The X adapter skill and registry lock are version-aligned, and legacy composer tests require the Direct journal rather than an Assisted fallback.

Review is a self-review in this environment; it does not replace an independent security/release review. Particular review points: client-controlled asset IDs, account generation changes, reservation atomicity, abandoned leases, incomplete upload responses, cross-tenant attachment IDs, post-acceptance readback, and cleanup of synthetic servers.

## Remaining public-release gates

1. A consenting ordinary non-owner customer signs in and personally grants real X OAuth, with verified registered production callback and current developer-app eligibility.
2. Current provider billing evidence and an explicitly approved bounded live-test budget. No existing identity-only authorization is extended silently.
3. Exact approved real content and schedule/cleanup actions, actual media/post provider receipts, scheduled dispatch and reconciliation evidence.
4. All repository release checks, actual production-source preservation, migration/flag review, staged deployment and compatible rollback. Public promotion requires separate authorization.
5. Unsupported or unverified capabilities stay disabled with their actual reason. This media implementation does not establish all 101 catalogue entries as generally available X features.

Official contracts consulted: `https://docs.x.com/openapi.json` (OpenAPI 2.172), the X media upload/initialize/append/finalize/status/metadata reference pages, and `https://docs.x.com/x-api/getting-started/pricing`. Application capability restrictions must be rechecked at release, not inferred from synthetic fixtures.

## CI checkout compatibility

The repository contains an existing vendor gitlink without a corresponding `.gitmodules` entry. The pinned checkout action's credential-removal traversal fails on that unrelated entry. X acceptance therefore performs a public anonymous Git fetch of the exact validated 40-character commit SHA, verifies checked-out HEAD, disables credential helpers and automatic submodule recursion, and asserts no local credential/header configuration. It does not edit or delete vendor content, initialize submodules, persist a token, or substitute branch-tip source for the requested commit.
