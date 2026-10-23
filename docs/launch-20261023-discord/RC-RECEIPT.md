# RC-RECEIPT: Discord capped Wave 1 release candidate

Status: **candidate FROZEN at `2a5a523d788eef67a5c7dbed609a98efa6650eef` (2026-10-22T22:37Z), nothing built, nothing deployed, nothing promoted.** A dash means the event has not happened. Each cell is filled by whoever performs the step and verified by the agent from a readback, never from a command's own success message. No secret, token, customer content or exact production usage figure belongs in this file.

## 1. Identity

| Field | Value |
|---|---|
| Project (Production) | `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, team `team_PgXY5VdAYKcsv0RLoDPHscNq` |
| Candidate branch | `claude/discord-launch-rc-20261023` (draft PR #222, "DO NOT MERGE") |
| Candidate SHA | `2a5a523d788eef67a5c7dbed609a98efa6650eef` (**frozen** 2026-10-22T22:37Z; the branch tip is unchanged) |
| Frozen by, when | the agent, 2026-10-22T22:37Z, after exact-SHA CI went green on all ten workflows (fourteen check runs: eleven success, three skipped by design), the superset proof passed on this SHA, both independent review rounds closed and the owner approved the packet (including the H-08 wording). Any further change to the branch voids the freeze and the approvals that name this SHA |
| Live commit it must contain | `c5fc1fd10350f3142ec6f34b2c373139e85abb39` (derivation: `S-01-lineage-report.md`) |
| Live deployment when written | `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`, `rafii.io` alias unchanged since S-01 (read 2026-10-22) |
| Delta against live | 180 files, +27,817 / -637; migrations in the delta need nothing applied (`S-05-migration-reconciliation.md`). Not Discord code: `web/package.json` and `web/package-lock.json` carry a security patch (next 16.3.8 to 16.4.2, @sentry/nextjs 10.74.0 to 10.76.2), `requirements.txt` moves pypdf 6.20.1 to 6.21.1, and `.github/workflows/consumer-ready.yml` sets one opt-in on the PostgreSQL step (section 2) |
| Settings carried in the repo | `vercel.json` `git.deploymentEnabled: false` (stricter than the live commit's per-branch list); one cron `/api/cron/worker` every minute |

> **Correction, 2026-10-23 about 05:05Z (customer-impact inventory, `claude/discord-impact-20261023`, first findings):** the row "Delta against live" above says the non-Discord part of the delta is only the Next.js/Sentry patch and pypdf. That is incomplete. RC1 also carries (a) **a regression for Facebook** (FB-1): the integration commit `17e3844c` took two of the three pieces of `381ac2d0`, so in RC1 a Facebook review is born stale and cannot be approved and an already approved Facebook post is held at the next invalidation; the live build is unaffected. A fix (make Facebook behave exactly as live) is being made on `claude/discord-rc2-fixes-20261023` for RC2; (b) other non-Discord changes that existing customers can see or that change behaviour: a "Save as draft" button on Home, review preparation no longer requiring a live publishing entitlement, composer input handling, the billing Storage line, accessible names, Facebook and Google Business Profile destination-picker wording, Pillow 12.3.0 to 13.0.0 (major), pypdf 6.19.0 to 6.21.1, and a new `psycopg-pool` dependency; (c) side effects with Discord switched off for the customer: an extra database transaction and an extra Supabase Auth call on every Channels read (CH-1), a new background claim attempt and report query per minute (BG-1), a public Discord interactions route that logs 5xx at ERROR level (PR-1), and the worker budget variables set on 2026-10-23 (25 jobs, 40 seconds) that apply to every provider on any new build (WB-1). RC1 stays frozen as the object of the existing approvals; none of this is hidden: `RC2-EVIDENCE-PACKET.md` and the inventory carry the ranked list.

## 2. Provenance checks on the candidate

| Check | Result | Evidence |
|---|---|---|
| Superset of live (`scripts/rc_superset_proof.py --live c5fc1fd1 --rc 2a5a523d --base 7dc95e2e`) | **PROVEN** at `2a5a523d`: ancestry, 6,301 live paths, every line the live line added (29 deliberate rewrites, each with a reason in `superset-allowlist.json`), API routes, crons, git settings, migrations, flag names, tests | re-run required on the frozen SHA |
| Dependency advisories (`npm --prefix web audit --audit-level=high`, `pip_audit -r requirements.txt`) | **npm 0 vulnerabilities, pip-audit clean** at `29bc8ab2` (no dependency file differs at `2a5a523d`; both pass again in CI on the exact SHA: local-gates Dependency audits, library run). Before: 2 critical + 1 high in next 16.3.8 and @sentry/nextjs 10.74.0 (GHSA-2464-fhr4-w9xw, GHSA-673q-mjm6-r5xr, GHSA-p3m5-59mp-jv5r, GHSA-mchm-gjx6-7h55) and four in pypdf 6.20.1 (CVE-2026-113786, -113789, -113790, -113791), in a lockfile and pin identical to the live commit's. Local `tsc`, `oxlint` (0 errors), 1,010 of 1,010 web node tests, `next build` with Sentry on and off, offline secret scan PASS | passes in CI on the exact SHA |
| Candidate adds no migration that production lacks | PASS | `S-05-migration-reconciliation.md` |
| Offline secret scan | fixed on the candidate (171 reviewed digests, scanner untouched); **passes in CI on the exact SHA** (local-gates step 15, library run) | PR #222 |
| Real-PostgreSQL cap tests (race of 12 for 5 slots with 2 held; every start holds its own slot; one account starting ten different servers; at most three starts in flight per person; a reconnect takes no slot; a known server at a full house) | 11 tests OK locally on PG16 with uuid columns like production, including a no-lock control that overshoots; 9 of them fail on `29bc8ab2`. They skip under the qualification's synthetic transport fence (it refuses any database but the guarded runner's) and run in the unfenced full-suite step of both workflows on PostgreSQL 17, and in the `ci-python` step of local-gates | `tests/test_discord_launch_cap_race.py` |
| Independent review of the gate and cap (code only), two rounds | Round 1: 2 serious and several smaller defects found and fixed with tests that fail on the previous code. Round 2 (re-review of those fixes): one blocker for opening the gate, a flaw in my own round-1 fix (one account could start many different servers for the price of one slot), now fixed (exact count plus three starts in flight per person), and Discord's own 429 on a login-token refresh no longer revokes. 24 of the 105 tests in the four review-related files fail on `29bc8ab2`. A narrow re-verification of round 2 then confirmed the fixes: nothing blocking, five low residuals (aggregate hoarding across many accounts, the capacity wording shown for three unfinished starts, scan cost at a million never-purged rows, a fixed five-minute wait on Discord's 429, test gaps), recorded in `RUNBOOK-LAUNCH.md` section 7 and `monitoring.sql` | the review reports are kept outside the repository |
| Generic PostgreSQL step on this tree | **Passes in CI on the exact SHA** (local-gates step 9, 22:08 to 22:23Z, with the Mastodon opt-in). Before the fix the 14 scripts that fail locally also failed on the live commit in the same environment; 5 were permission artefacts of running as another user and the 3 Mastodon scripts pass with the opt-in set | `consumer-ready.yml`, commit `0bce18dd` |
| Whole Python suite | 6,141 OK, 391 skipped without PostgreSQL, on `2a5a523d` (local); the fenced Discord batch as the qualification runs it: 473 OK, 11 skipped. **In CI on PostgreSQL 17 the suite passes** (local-gates step 8 and the qualification's full-suite step) | CI |

## 3. CI on the exact SHA `2a5a523d788eef67a5c7dbed609a98efa6650eef` (one row per workflow; complete at 22:34Z)

| Workflow | Event | Result | Run URL |
|---|---|---|---|
| Rafii local release gates | pull_request | success (22:34Z; PostgreSQL step, Discord P0-P4 runner, web, build, copy audit, function archive, secret scan, dependency audits and the real browser step all passed) | https://github.com/dev-james0723/PostRiff/actions/runs/39861627345 |
| Rafii browser scenes | pull_request | success (22:12Z) | https://github.com/dev-james0723/PostRiff/actions/runs/39861627327 |
| Founder admin browser | pull_request | success (22:13Z) | https://github.com/dev-james0723/PostRiff/actions/runs/39861627394 |
| Growth Studio browser acceptance | pull_request | success (22:03Z) | https://github.com/dev-james0723/PostRiff/actions/runs/39861627341 |
| Growth metrics acceptance | pull_request | success (22:06Z) | https://github.com/dev-james0723/PostRiff/actions/runs/39861627318 |
| Discord composer input regression | pull_request | success (22:11Z) | https://github.com/dev-james0723/PostRiff/actions/runs/39861627395 |
| Universal Library release validation | workflow_dispatch | success (22:10Z; secret scan and npm audit included) | https://github.com/dev-james0723/PostRiff/actions/runs/39861627453 |
| Rafii Generative UI (agent-ui) | workflow_dispatch | success (22:10Z; the WebKit check that failed once on the previous head passed) | https://github.com/dev-james0723/PostRiff/actions/runs/39861633071 |
| Discord multi-mode exact-source qualification (35 min, PG17) | workflow_dispatch | success (22:13Z) | https://github.com/dev-james0723/PostRiff/actions/runs/39861637389 |

A cancelled or missing run is not a pass. A run on an earlier SHA is not evidence for this one.

Earlier runs, kept for the record (none is evidence for the frozen SHA): the qualification dispatched on `610d0a56` was **cancelled by its 35-minute job timeout while still in the apt prerequisites step** (its earlier successful runs on the Discord line took 14 to 17 minutes), so it proves nothing either way and gets one re-run on the frozen SHA because it died before any test body ran. The library validation on `610d0a56` failed at the offline secret scan (fixed in `0c6a9c36`); on `0c6a9c36` it failed only at `npm audit` (fixed in `cd0ff8d0`). agent-ui passed on `610d0a56`. On `29bc8ab2` (superseded by the push of `2a5a523d`): local-gates passed the PostgreSQL step (the Mastodon opt-in works) and the Discord P0-P4 runner, its later steps were cancelled by the push; qualification failed only because the multi-mode batch's fence ended the real-PostgreSQL cap tests (fixed by skipping them under the fence); the composer-input run was cancelled while installing Chromium; agent-ui-browser failed one WebKit check (`scope-switch-aborts`, "Target page, context or browser has been closed", chromium 16 of 16 passed); document-runtime, growth-studio, founder and native-learning-browser passed. None of that is evidence for the current head.

## 4. Builds (twin builds of one SHA, see `RUNBOOK-LAUNCH.md` section 0)

| Field | D1 (dark twin) | D2 (open twin) |
|---|---|---|
| Built by, when (UTC) | GitHub Actions run 39883169905, request commit `a2a1070` (route A, `BUILD-VIA-GITHUB-ACTIONS.md`), approved by the owner 2026-10-23 01:19Z; created 01:19:41Z, READY 01:23:47Z | - |
| Command (flags only, no values): `vercel deploy --prod --skip-domain --meta rafiiSourceSha=<sha> --env ...` | `vercel deploy --prod --skip-domain --yes --scope <team> --meta rafiiSourceSha=<sha> --meta rafiiTwin=dark --env POSTRIFF_DISCORD_CONNECT_WORKSPACES=<tester workspace, a GitHub secret> --env POSTRIFF_OAUTH_DISCORD_REVIEWED=true --env POSTRIFF_DISCORD_GUILD_CAP=10000` | - |
| Deployment ID | `dpl_25ihHyiZCzZXAjVsJqJiYcCWA51n` | - |
| Deployment URL | `postriff-phase2-private-hldzoymdu-jamesau0723-6572s-projects.vercel.app` (login-protected: anonymous requests get 403) | - |
| Target / state | production (staged) / READY | - |
| Build duration, cost note | 4 min 3 s (estimate was 2.5 min; cap $5 per build); billable duration and CPU minutes: unavailable through the CLI, so cost is not observed | - |
| Source fingerprint equals the frozen SHA | 257 of 257 visible source files equal the frozen tree (0 absent, 0 different, 32 of 32 directory listings equal); 7 of 7 deeper files probed by content hash are present (3 exist only in the RC); the 2 RC-only files probed are absent from the live `dpl_47SG`; `/api/health` reports `sourceRevision` `2a5a523d788eef67a5c7dbed609a98efa6650eef`. Visible zone is 11% of the upload set, so this is the same sample-based standard as S-01 | - |
| Env names present (readback, names only) | seven project variables created and read back by name and value (`CHECKLIST.md` C-03); production names list from the preflight run 39882363204 (176 names; the six required present; none of the names that must stay unset) | - |
| Gate value class (`tester workspace` / `*`) | `tester workspace` (passed as a GitHub secret, masked in the log, not readable back); proven by the closed-state check and X-02 after the dark promotion | - |
| Server cap passed | 10000 | - |
| Aliased to `rafii.io` | No: `rafii.io` still names `dpl_47SG…`. Vercel moved the project's internal default domain (`postriff-phase2-private-jamesau0723-6572s-projects.vercel.app`, login-protected) to D1 at 01:23:47Z, as it does for every production build; D1 had no runtime log lines other than the agent's probes and no cron call | - |
| Promoted at (UTC) | - | - |

## 5. Acceptance (hosted, on D1 before any exposure)

| Check | Result | Evidence (states and counts only) |
|---|---|---|
| Alias readback shows D1 | - | - |
| Cron answers each minute for 5 minutes | - | - |
| Closed state for a non-allowlisted workspace (G-01) | - | - |
| Real OAuth and bot install, tester workspace (X-02, PRD A08) | - | - |
| Destinations limited to channels the tester can see (X-02/X-06) | - | - |
| One real send and read-back (X-03, PRD A09) | - | - |
| Unattended schedule and cancel (X-04, PRD A10) | - | - |
| Revoke and reconnect (X-05) | - | - |
| Permission failure held, nothing sent (X-06) | - | - |
| Tenant isolation spot check (Q-05) | - | - |
| Monitors Q1 to Q11 before/after the session | - | - |
| Exposure decision (X-09) | - | - |

## 6. Rollback and abort

| Situation | Action | Target | Note |
|---|---|---|---|
| Anything wrong after opening | `vercel promote` D1 again (closes the gate, no rebuild) | D1 | primary abort |
| Provider-level emergency | break-glass hold on the policy row, `RUNBOOK-INCIDENT.md` | n/a | pre-authorised step only if AUTH-7 is ticked |
| Code defect in the candidate | promote `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` | live today | has no Discord v2 code; drain Discord jobs first |

## 7. Cost

No Vercel build has been made. GitHub-hosted CI for this public repository is free. Observed build cost per deployment: - (record from the usage page if the owner reads it; otherwise state "not observed").

## 8. Handoff notes

- The release status in `LAUNCH-READINESS-REPORT.md` is **NO-GO** until the human items (H-01, H-03, H-05, H-07, H-08), the Portal audit, the environment batch and the tester session have evidence.
- The owner's approvals and their conditions are in `AUTHORIZATION-RECORD.md`; the exact steps for the two builds are in `BUILD-RUNSHEET.md`. This session cannot run `vercel deploy` (no CLI, no token); the owner's MacBook was last seen online 2026-10-22 14:52Z.
- Nothing in this receipt may be filled from memory. If a cell cannot be read back, write "unverified" and the reason.
