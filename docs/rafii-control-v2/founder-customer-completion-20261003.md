# Founder Control customer workflow continuation — 2026-10-03

This is a scoped continuation of the existing consolidated `/founder` application. The September 30 receipt is historical: PR #85 merged, Founder Control moved into the main web application, the approved projections are present in production, and restricted reader grants were verified on October 3. The current source candidate is on `codex/rafii-founder-acceptance-20261003`, based on the reviewed PR #97 release, with subsequent concurrent releases reconciled through `consumer-saas`.

## Changes

- Live Customer 360 now reads subscriptions, invoices, payment metadata, usage, credit entries, masked support metadata, members, recorded account events and optional connection health through existing approved views. Every query is bound to the selected customer's visible workspace ids. No raw workspace state, support messages, credentials or new financial policy is introduced.
- Histories are limited to 50 records per section with exact totals and truncation coverage. Missing payment/connection configuration is explicit; denied or missing required views produce an error, never empty history. A credit ledger entry is not presented as a verified wallet balance. Unapproved plan prices remain unreported.
- Demo Customer 360 exposes the existing private sandbox rename/reset API with verified revisions, stable retry keys, CSRF and scoped cache invalidation. It never calls a Live mutation. Reset restores sample records, and saved changes reflect in the same linked views.
- Closing the drawer returns keyboard focus to the selected account. Table cell definitions now remain stable when the record URL changes, instead of recreating the opener.
- The local browser runner accepts distinct loopback ports and checks compiled Next rewrites before starting any servers, preventing accidental attachment to concurrent developer APIs. It keeps defaults compatible with CI, strips credentials, and owns only its disposable children. The deployment ignore also excludes a local Control interpreter symlink.

## Qualification and execution boundaries

The focused PostgreSQL suite uses a newly initialized disposable database, real canonical consumer creation, restricted Control roles and real HTTP/session/CSRF boundaries. It verifies creation/readback, rename/retry/restore, linked records, cross-account exclusion, masked private canaries, denied reads and bounded histories. The browser scene uses the main production Next build, real embedded API and PostgreSQL, with synthetic founder/non-founder identities at 1440, 768 and 390 px. It checks linked details, private Demo save/reset and Live isolation, keyboard return and accessibility. Neither harness is authenticated hosted acceptance.

Observed candidate results: 14/14 business database tests, 3/3 runner isolation tests, 142/142 Founder web contracts, 173/173 focused browser checks, and a successful production build/type check. Lint has zero errors and two existing warnings in unrelated navigation/contact-policy code. Full integrated workflows and hosted acceptance remain separate gates.

Commands (Node 24 / Python 3.12 / PostgreSQL 17):

```sh
python scripts/rafii_control_pg.py --pattern test_business_workspace.py
PYTHONPATH=src:tests python -m unittest test_browser_runner_isolation -v
node --test web/tests/founder-*.test.cjs
npm --prefix web run lint
python scripts/consumer_ready_web.py --api-port 4838 --web-port 4839 --prepare npm run build
python scripts/consumer_ready_browser.py --founder --customers --api-port 4838 --web-port 4839 --pg-port 55489 --evidence-dir /private/tmp/rafii-founder-customers
python scripts/consumer_ready_browser.py --founder --api-port 4838 --web-port 4839 --pg-port 55489 --evidence-dir /private/tmp/rafii-founder-full
python scripts/consumer_ready_browser.py --founder --tour --api-port 4838 --web-port 4839 --pg-port 55489 --evidence-dir /private/tmp/rafii-founder-tour
```

The local function archive was built with the qualification-pinned Vercel Python builder and the embedded `workspace.py` bytes were compared with the source. Current source must pass the established PR workflows before merge/deployment. Production migration history and reader access were checked read-only; this candidate contains no migration, grant, provider activation or approved-term change.

## Hosted acceptance still required

Entry: https://postriff-phase2-private.vercel.app/founder

Sign-in: https://postriff-phase2-private.vercel.app/founder/sign-in

Use the designated founder's existing login and enrolled second factor in the browser. Never place passwords/codes in chat. A fresh authenticated browser session and an explicitly approved restricted workspace with its expiring test grant are required for the hosted creation/readback/rename/restore evidence. The designated production operator had no current test-workspace grant at the read-only check. Do not manufacture a grant, bypass fresh MFA or substitute local synthetic evidence.

Broader activation, pricing and original-tenant support work retains its existing owners. This candidate reads the existing masked support projection and does not change support reveal/reply authorization. A READY deployment and this local qualification alone are not a production-readiness claim.
