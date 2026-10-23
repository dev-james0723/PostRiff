# APPROVAL PACKET 2: D1 is built; what the dark promotion needs

Written 2026-10-23 about 01:50Z for RC head `2a5a523d788eef67a5c7dbed609a98efa6650eef`. **Release status: NO-GO.** Nothing is promoted, nothing was sent to Discord, `rafii.io` still serves `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`. This packet asks for the human items that the promotion row (`AUTHORIZATION-RECORD.md`, rev B+) names as conditions. No secret, token or customer id is in this file.

## 1. What exists

| | |
|---|---|
| D1 (dark twin) | `dpl_25ihHyiZCzZXAjVsJqJiYcCWA51n`, production target, staged, READY, built 2026-10-23 01:19 to 01:23Z (4 min 3 s) from the frozen SHA by GitHub Actions run 39883169905 after the owner approved request commit `a2a1070` |
| Settings in the build | connect gate = the tester workspace only (a GitHub secret), server cap 10,000, Direct publishing reviewed flag on; seven project variables set just before (four Discord flags, rate policy valid to 2026-11-22, worker budget 25 jobs and 40 seconds) |
| Customers | unaffected. `rafii.io` and every customer path still run the old build; D1 has had no traffic except the agent's probes and no cron call |
| Not built | D2 (the open twin). It is built only after the tester session passes |

## 2. Checks done on D1 (`CHECKLIST.md`)

| Check | Result |
|---|---|
| Q-01 pre-flight (project, nothing else building, cost note) | VERIFIED |
| Q-02 one staged build | VERIFIED (D1). The GitHub job is red only because the agent's own alarm fired on the project's internal default domain, see section 3 |
| Q-03 provenance | VERIFIED, sample-based: 257 of 257 visible files equal the frozen tree; 7 of 7 deeper files present by content hash; 2 of 2 Discord-only files absent from the live build; `/api/health` reports the frozen SHA |
| Q-04 smoke | VERIFIED for what needs no login (health 200, protected routes 401, no 5xx). The gate state shown on the connect page needs a signed-in user, so it is checked right after promotion (the closed-state check and X-02) |
| Q-05 hosted tenant isolation | **BLOCKED**: needs two real accounts. CI on the exact SHA covers cross-tenant destinations, consent, worker leases and state binding. See decision 2 |
| Q-06 rollback target | VERIFIED: `dpl_47SGx...` (the build now serving `rafii.io`); migrations are additive and already in production |
| C-02 / C-03 env names and batch | VERIFIED |

## 3. One thing learned: the internal domain follows every production build

Vercel moves the project's internal default domain (`postriff-phase2-private-jamesau0723-6572s-projects.vercel.app`) to each new production build even with `--skip-domain`. It is login-protected (anonymous requests get 403) and customers do not use it, so no customer is affected, and D2 will do the same. `rafii.io` only moves when the agent promotes. The workflow now only fails if a customer-facing domain is attached. Also learned: my SHA and twin markers (`--meta`) are not shown by the Vercel API tools, so the deployment id and the health endpoint carry the provenance.

## 4. Decisions needed (a short answer each)

1. **H-05, Release Captain:** who? And the security review: is the 2026-10-20 independent AI review (two P1 findings, repaired) enough, or is a human review required before opening? (PR #216 lists both as open.)
2. **Q-05 waiver:** accept CI evidence for tenant isolation now and run the hosted two-account probe in the tester session right after the dark promotion (needs the tester account plus one second account in another workspace, which also serves the closed-state check)? Yes or no. Without a yes the promotion condition "Q-01 to Q-07 verified" is not met.
3. **H-07:** who watches alerts and answers customers during the opening window and the first 24 hours, and where are updates posted?
4. **M-03:** read the Supabase dashboard: is point-in-time recovery on, what is the latest restore point (time), and the database compute size?
5. **H-03, tester session assets:** tester Discord user id, test server id (where the tester has Manage Server), a public test channel id, a private channel id the bot cannot see; and a 20-minute window.
6. **T0 and GO_TIME:** the default is T0 2026-10-23 17:00Z (2026-10-24 01:00 Hong Kong) and GO_TIME 14:00Z. Keep or change?
7. **Scale (separate message):** W-02 yes or no, and the expected first-week volume.

## 5. What the dark promotion does and does not do

Does: `rafii.io` starts serving D1: the same product plus the Discord v2 code, the framework security patch, and the Discord worker enabled on the one minute cron. The connect gate stays closed for every workspace except the tester's. Does not: open Discord to customers, send any message, change a secret, or run a migration.

Undo: promote `dpl_47SGx...` again (seconds, no rebuild). Abort triggers are in `RUNBOOK-INCIDENT.md`.

## 6. Order from here

H-05 and decision 2 answered → agent checks nothing else changed (tip, CI, `rafii.io` still on the old build) → dark promotion → health, one cron call per minute for five minutes, closed-state check → tester session (X-02 to X-06, the hosted tenant probe, C-05 authorize-link audit) → D2 request (needs the owner's approval tap) → GO or NO-GO at GO_TIME → open at T0 only on GO. A failed or missing gate is NO-GO, not worked around.
