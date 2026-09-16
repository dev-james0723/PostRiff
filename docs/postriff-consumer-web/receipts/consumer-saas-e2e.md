# Receipt — end-to-end journey on the new consumer app (dev harness)

**Date:** 2026-09-16 · **Where:** `web/` (Next.js) at http://localhost:3100 against `scripts/postriff_dev_hosted.py` on :4331 (real hosted code, disposable PostgreSQL, synthetic identity/providers). **Branch:** `consumer-saas`.

## Journey observed in the browser
1. `/auth/sign-in` → "Enter dev workspace" → workspace bootstrapped (`POST /api/auth/verify`).
2. **Channels** → Connect Threads (publish) → permission step with scopes → synthetic consent page (proxied `/dev/consent`) → callback `/api/oauth/threads/callback` → `/channels/connect` → `/app/channels/connect` → `oauth/complete` → **Connected @dev_creator**.
3. **Brand & voice** → Voice setup (personal · purpose · audience · warm) → provisional profile → **Use this voice** → active revision 1.
4. **Ideas** → paste source, LinkedIn + Threads, EN → **Draft 2 previews** (deterministic runtime, $0, 12 safe events) → **Add to my drafts**.
5. **Queue** → **Schedule a draft** → Threads draft · @dev_creator · time · rights + acknowledgement → **Prepare review** (`p2_variant_review` + `p2_review`) → review card with digest.
6. **Approve & schedule** → job `scheduled` → worker: `claimed → submitting → provider_accepted (media id 91000) → verified` ("Provider lookup matched the approved text and account").
7. **Queue** shows `verified`; **Analytics** shows the Threads post with native metrics (likes 7, replies 2, views 128; quotes/reposts/shares "Unavailable", never 0; likes per view 7/128); **Inbox** shows the honest limited state (comments capability Unsupported for a publish-only grant); **Overview** counts 1 published, 1 connected channel.

## Defects found by this run and fixed
| Where | Defect | Fix | Test |
|---|---|---|---|
| `hosted_app._origin` | 403 behind the Next.js dev proxy / Vercel (Host ≠ Origin) | honour `X-Forwarded-Host` (also for the OAuth callback redirect) | route tests |
| new app | no way to create a review from a draft (`p2_review`) | Schedule dialog on Queue + Pipeline | browser |
| new app | scheduling requires an active voice profile the alpha wizard used to create | Voice setup on Brand & voice + prompts | browser |
| `domain.accept_update` | `StopIteration` → 500 for Ideas candidates (hosted run ids are not local runs) | optional local run lookup | `AcceptUpdateFromIdeas` |
| `contracts.LIMITS` | `KeyError: 'Threads'` → 500 at scheduling | Threads limits (500 chars) | `HostedPlatformsHaveLimits` |
| `hosted_app` | unhandled exceptions vanished into a 500 | content-free traceback logging | — |

## Evidence
Unit **229/229**; PostgreSQL suites `repository / safety / isolation / ideas / channels / billing / billing_stripe / migration_008 / phase3` **pass**; `web/` `next build` **82 routes**; `tsc` + `oxlint` clean. Screenshots were taken at desktop (pane) and 375 px; no horizontal overflow on `/`, `/pricing`, `/app`, `/app/channels`, `/app/workspace/members`.

## Not exercised here (needs real providers or founder gates)
Real Supabase sign-in, Stripe test-mode checkout, Resend delivery, a reviewed provider (LinkedIn/Threads/Instagram), comments/replies (needs a comments grant on a reviewed connector), the desktop companion.
