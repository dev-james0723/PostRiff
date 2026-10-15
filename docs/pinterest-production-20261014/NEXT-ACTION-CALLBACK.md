# Next exact action — Pinterest callback registration

2026-10-15 UTC. **Prepared, not submitted.** The human approved continuing the next phase. Original mission separately gates developer-console changes; the action below needs its specific action-time confirmation.

## Ready action

In Pinterest app **1615884 / Rafii**, add exactly **`https://rafii.io/api/oauth/pinterest/callback`** to Redirect URIs. Preserve every existing URI and other setting. Complete any ordinary Save required for this single URI, then reload/read back the persisted list. Stop on changed app/account/origin or unexpected terms/reauthentication. The visible form is filled, Add has not been clicked. [Actual scoped screenshot](evidence/pilot-callback-review.jpg).

This action does not rotate/copy an app secret, generate a token, grant OAuth consent, publish a Pin, submit Standard Access, migrate Supabase, deploy Rafii, create a resource or change billing. A registered callback alone proves none of those outcomes.

## Proposed test identity

Use only workspace `568699ad-d66e-42b8-a7f1-e86d0c35ab02`, user `b167161d-37f4-4bc3-ae22-2482c982e5a0` (active owner verified), and Pinterest **@jamesaucreates** (signed-in developer profile URL verified). Human selection of this pair is pending. Business/personal API eligibility and numeric provider identity remain unverified until separately approved real OAuth/API testing. A general project approval does not supply live consent or a specific Pin approval.

## Deployment is separately blocked

Vercel team's current plan/status is **Pro / overdue**, confirmed through authenticated read-only CLI. Do not pay, change billing or attempt a deployment until this is qualified. The production callback-origin value is the old `https://postriff-phase2-private.vercel.app`; clientID/secret and quota table are absent. Those are later separately scoped configuration/migration/deployment effects, not this callback-only action.

Latest tested source `b99cf89aef28972a5e9acc2c159fa43d3cb5962f` incorporates live `cab2b288`; [cloud bcz5vdqznw](https://depot.dev/orgs/jf34f85hr0/workflows/bcz5vdqznw) passed270Python/51Node, disposablePG, typecheck/lint/build/browser. No code was pushed or deployed. Preserve new live source drift before any later deployment. All public/Agent/publishing gates remain closed.
