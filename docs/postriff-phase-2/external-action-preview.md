# External-action preview

**State: the hosted foundation and complete synthetic lifecycle are validated on Production.** Deployment `dpl_3cA573dgFvhXipWn4KxjfZLe6tY4` is Ready at `https://postriff-phase2-private.vercel.app`, all five runtime values are configured, and the interface truthfully identifies the hosted private beta. No invitation was sent. No live image generation, new OAuth consent, credential transfer or social publication was performed.

## Production foundation executed

- Exact Vercel target: `jamesau0723-6572s-projects/postriff-phase2-private`.
- Exact Supabase target: project `buoyhkbodnhzngaotoel` in East US (`us-east-1`).
- Schema and storage: additive migrations 001 and 002, forced tenant RLS, lifecycle tombstones/session revocations, and private bucket `postriff-private`.
- Runtime: five Production-scoped values with public Config visibility only for the project URL and publishable key; database, service-role and cron values remain server-only.
- Validation: two temporary users passed refresh, same-workspace restore, private export, mutation, tenant/media isolation, media deletion, logout/refresh denial, account deletion and trial-tombstone retention. Cleanup removed both Auth users and all temporary rows.
- Worker: Vercel registered authenticated `GET /api/cron/worker` at `* * * * *`. Five successive scheduled requests on the final deployment returned HTTP 200. The adapter remained fail-closed with `externalExecution: false` and submitted no post.
- Cost and data boundary: synthetic data only. Existing local social tokens, founder data, private skills, interview notes and customer data were not uploaded.

Evidence: [production lifecycle validation](evidence/production-lifecycle-validation.jsonl), [cron logs](evidence/production-cron-logs.txt), and [production status](evidence/production-promotion-status.json).

## Live image candidate requiring approval

The current Vercel AI Gateway catalog lists `google/gemini-3.1-flash-image-preview` as image-capable. Its observed 1K image price is $0.067. The bounded candidate is:

- Target: this PostRiff Vercel project through Vercel AI Gateway, authenticated by deployment OIDC; no provider API key in the browser or source.
- Model and count: `google/gemini-3.1-flash-image-preview`, exactly one 1K image.
- Maximum authorized spend: $0.08 total for the validation request. Stop before generation if a project budget at that ceiling cannot be applied or the current estimated charge exceeds it.
- Prompt: `Abstract editorial artwork about a calm creative system moving from scattered ideas to clarity; layered paper texture, indigo ink, muted moss and warm amber; balanced negative space; no people, faces, logos, brands, readable text, locations or identifiable objects.`
- Data: this constant prompt only. No profile text, sources, account identifiers, customer content or interview material.
- Result handling: decode the returned image, strip metadata, create an immutable JPEG rendition in the private `postriff-private` bucket, persist its provider/model/hash/consent evidence, verify authorized read and cross-workspace denial, then delete the synthetic validation asset after evidence capture.
- Failure boundary: one request only. Do not retry an uncertain response or exceed the cap.

Current documentation: [Vercel AI Gateway image generation](https://vercel.com/docs/ai-gateway/modalities/image-generation) and the [live model catalog](https://ai-gateway.vercel.sh/v1/models). The approved `$0.08` budget command was attempted once and rejected before mutation because Vercel enforces a `$1` minimum. A follow-up budget listing remains empty, so no paid call has been made. The next choice is either a `$1` project budget with a one-request application guard and expected spend below `$0.08`, or no live generation.

## Instagram OAuth candidate requiring private handoff and approval

- Intended account: `@jamesaucreates`.
- Exact scopes: `instagram_business_basic` and `instagram_business_content_publish`.
- Connection action: complete Meta login/consent in the user's browser, verify the returned Instagram professional account ID and capability, store the token server-side with refresh/revocation handling, and never expose it in browser state, logs or exports.
- Publication authority: none during connection. Connecting the account does not authorize a post.
- Current state: Meta accepted the callback URI and `@jamesaucreates` accepted the Instagram tester invite. The local James Au Studio broker now holds a verified Media Creator grant and its read-only identity/quota check is `publish_ready`. Hosted PostRiff has no Instagram grant or token vault yet. A new hosted OAuth consent and hosted route qualification are still required; no local token will be uploaded to Vercel.

## LinkedIn hosted-token candidate requiring approval

- Intended account: the currently verified James Au member identity.
- Existing local scopes: `openid profile email w_member_social`; local readiness reports identity and posting capability.
- Proposed action: move a newly consented production grant into server-side hosted custody with refresh/revocation handling and verify identity/capability through the hosted application. Do not upload or reuse the existing local broker token without exact approval.
- Publication authority: none during connection or qualification.

The request contracts use LinkedIn's Posts and Images APIs with `w_member_social`; official references: [Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api) and [Images API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api).

## Exact public test-post candidate requiring separate approval

- Destinations: James Au's verified LinkedIn member profile and Instagram `@jamesaucreates`, one public post on each.
- Timing: immediate only after both exact account IDs, capabilities and immutable image rendition hash are reverified.
- Text: `PostRiff Phase 2 validation: a small systems test for a calmer, more intentional creative workflow. Built and reviewed by James Au Studio.`
- Alt text: `An abstract indigo and amber composition suggesting a calm creative system moving from scattered ideas to clarity.`
- Media: the single approved generated validation rendition, with its exact SHA-256 hash, rights basis and provider receipt bound into each immutable manifest before approval.
- Recovery: reconcile provider evidence and permalink before any retry. Never resubmit an uncertain response automatically.

## Production onboarding follow-ups

- Email OTP still needs an approved sending domain, sender identity, recipient policy and cost ceiling before provisioning a messaging provider and configuring Supabase SMTP.
- Google sign-in needs an approved OAuth client/consent-screen/callback allowlist change and secure credential transfer. Local possession of a client credential does not configure the production Supabase project.
- A custom domain remains optional; the stable generated Vercel production alias is active.

## Actions actually performed

Read-only official-document and live-catalog research; local source/configuration edits/builds/tests; additive Supabase migrations; protected Preview and configured Production deployments; synthetic user/media lifecycle tests; authenticated fail-closed cron execution; and verified cleanup. No participant contact, new OAuth consent, email/SMS delivery, paid image request, customer-data upload, real social post or billing action occurred.
