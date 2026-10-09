# Blockers (updated 2026-10-09 ~01:50Z)

## Resolved by James's approval (2026-10-09)

- Production steps 1–3 approved (migrations, merge+auto-deploy, flags).
  037/038 and 103 are applied and verified (RELEASE-RECEIPT.md).
- Growth caps approved: US$10/day global, US$4/day per workspace.
- Self-serve cohorts approved: 10 Trends, 10 Growth measurement.
- QA account `hinsingau.pianist+rafii-qa1@gmail.com` approved.
- Bluesky cross-workspace sharing: conditional; review done
  (BLUESKY-SOURCE-RIGHTS-REVIEW.md) → stays DENIED until conditions 1–6 are
  verified.

## Open — needs a human / external platform

### B1. Production auth email delivery is in testing mode (pre-existing, affects all new users)

Supabase Auth sends through a custom SMTP provider that only delivers to one
address. Auth log 2026-10-09T01:20:48Z for the QA sign-up:
`gomail: could not send email 1: 550 "You can only send testing emails to your
own email address (james0723code@gmail.co…)"`. Consequences:
- email one-time-code sign-up and sign-in fail for every other address,
  including the approved QA alias (an unconfirmed auth user row was created by
  the attempt; no workspace);
- Google sign-in still works.
Fix (dashboard + DNS, not reachable from this session — no provider key exists
in the deployment env): verify a sending domain with the SMTP provider
(e.g. rafii.io), add its DNS records (I can add them in Vercel DNS once the
records exist), then set the Supabase Auth SMTP sender to an address on that
domain. Until then the ordinary-user QA runs with the existing non-founder
account that is already signed in (below), not the new alias.

### B2. Founder UI journey needs a founder sign-in

Your Chrome is signed in on the legacy host as the non-founder account
Hin Sing Au (`hinsingau.pianist@gmail.com`, workspace "My agency", owner) —
this is the account the audit screenshots came from. There is no session on
rafii.io and no founder session. Founder-workspace results are verified by
database/API evidence; a founder UI walkthrough needs you to sign in (Google +
MFA) or is left UNVERIFIED.

### B3. Ordinary-user Trends evidence (rights conditions)

See the review. Engineering items 1–4 are in progress or listed; items 5–6
(public Art. 14 privacy notice, legitimate-interest assessment) need your
sign-off as public legal text.

### B4. Editor/viewer live accounts

Invites rely on email delivery (B1). Role boundaries are proven in CI
(disposable Postgres + browser harness). Live editor/viewer checks wait for B1.

### B5. External, not solvable by launch

- Meta App Review Advanced Access (`instagram_business_manage_insights`,
  `instagram_business_manage_comments`) — ordinary users' Instagram readings
  and comments.
- Threads OAuth client ID/secret are not configured.
- Real iPhone Safari check needs your device.

### B6. Instagram 1h reading

Uses an existing eligible post if one exists; a new public QA post needs your
explicit approval of the exact account and content before publishing.

## Not doing

- No manual cursor reset; no early purge of the 344 stale observations
  (retention purges them 2026-10-11T01:19Z).
- No wildcard allowlists, RLS changes, or consent on anyone's behalf.
- No admin-API magic links or other auth shortcuts for QA.
