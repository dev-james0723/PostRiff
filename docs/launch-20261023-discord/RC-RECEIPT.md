# RC-RECEIPT: Discord capped Wave 1 release candidate

Status: **candidate, not frozen, nothing built, nothing deployed, nothing promoted.** A dash means the event has not happened. Each cell is filled by whoever performs the step and verified by the agent from a readback, never from a command's own success message. No secret, token, customer content or exact production usage figure belongs in this file.

## 1. Identity

| Field | Value |
|---|---|
| Project (Production) | `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, team `team_PgXY5VdAYKcsv0RLoDPHscNq` |
| Candidate branch | `claude/discord-launch-rc-20261023` (draft PR #222, "DO NOT MERGE") |
| Candidate SHA | `29bc8ab2b46ae9fec6701ecdf1ea092fff90fc74` (head when this receipt was last updated; **frozen:** -) |
| Frozen by, when | - (needs Approval Packet 1 rev B answered, exact-SHA CI green, H-08 wording decided) |
| Live commit it must contain | `c5fc1fd10350f3142ec6f34b2c373139e85abb39` (derivation: `S-01-lineage-report.md`) |
| Live deployment when written | `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`, `rafii.io` alias unchanged since S-01 (read 2026-10-22) |
| Delta against live | 180 files, +27,817 / -637; migrations in the delta need nothing applied (`S-05-migration-reconciliation.md`). Not Discord code: `web/package.json` and `web/package-lock.json` carry a security patch (next 16.3.8 to 16.4.2, @sentry/nextjs 10.74.0 to 10.76.2), `requirements.txt` moves pypdf 6.20.1 to 6.21.1, and `.github/workflows/consumer-ready.yml` sets one opt-in on the PostgreSQL step (section 2) |
| Settings carried in the repo | `vercel.json` `git.deploymentEnabled: false` (stricter than the live commit's per-branch list); one cron `/api/cron/worker` every minute |

## 2. Provenance checks on the candidate

| Check | Result | Evidence |
|---|---|---|
| Superset of live (`scripts/rc_superset_proof.py --live c5fc1fd1 --rc 29bc8ab2 --base 7dc95e2e`) | **PROVEN** at `29bc8ab2`: ancestry, 6,301 live paths, every line the live line added (29 deliberate rewrites, each with a reason in `superset-allowlist.json`), API routes, crons, git settings, migrations, flag names, tests | re-run required on the frozen SHA |
| Dependency advisories (`npm --prefix web audit --audit-level=high`, `pip_audit -r requirements.txt`) | **npm 0 vulnerabilities, pip-audit clean** at `29bc8ab2`. Before: 2 critical + 1 high in next 16.3.8 and @sentry/nextjs 10.74.0 (GHSA-2464-fhr4-w9xw, GHSA-673q-mjm6-r5xr, GHSA-p3m5-59mp-jv5r, GHSA-mchm-gjx6-7h55) and four in pypdf 6.20.1 (CVE-2026-113786, -113789, -113790, -113791), in a lockfile and pin identical to the live commit's. Local `tsc`, `oxlint` (0 errors), 1,010 of 1,010 web node tests, `next build` with Sentry on and off, offline secret scan PASS | CI on the exact SHA pending; the library run on `cd0ff8d0` passed (audit included) |
| Candidate adds no migration that production lacks | PASS | `S-05-migration-reconciliation.md` |
| Offline secret scan | fixed on the candidate (171 reviewed digests, scanner untouched); CI result below | PR #222 |
| Real-PostgreSQL cap tests (race of 12 for 5 slots with 2 held; one slot per person; a known server at a full house) | 8 tests OK locally on PG16, including a no-lock control that overshoots; CI evidence: `ci-python` in local-gates ran the 4 original tests on PostgreSQL 17 and passed on `cd0ff8d0`; the 4 added tests run there on this head | `tests/test_discord_launch_cap_race.py` |
| Independent review of the gate and cap (code only) | 2 serious and several smaller defects found and fixed with tests that fail on the previous code (`tests/test_discord_rate_denial_refresh.py`, `tests/test_discord_launch_hardening.py`); a re-review of the fixes is pending | the review report is kept outside the repository |
| Generic PostgreSQL step on this tree | The 14 scripts that fail locally also fail on the live commit in the same environment; 5 were permission artefacts of running as another user, the 3 Mastodon scripts pass with the opt-in set; the CI job's own log does not print the failing script (it is in the uploaded artifact, which this session cannot download) | `consumer-ready.yml`, commit `0bce18dd` |
| Whole Python suite | 6,123 OK, 388 skipped without PostgreSQL, on `29bc8ab2` (local); CI runs it with PostgreSQL 17 | CI |

## 3. CI on the exact SHA (fill from the run page, one row per workflow)

| Workflow | Event | Result | Run URL |
|---|---|---|---|
| Rafii local release gates | pull_request | - | - |
| Rafii browser scenes | pull_request | - | - |
| Founder admin browser | pull_request | - | - |
| Growth Studio browser acceptance | pull_request | - | - |
| Growth metrics acceptance | pull_request | - | - |
| Discord composer input regression | pull_request | - | - |
| Universal Library release validation | workflow_dispatch | - | - |
| Rafii Generative UI (agent-ui) | workflow_dispatch | - | - |
| Discord multi-mode exact-source qualification (35 min, PG17) | workflow_dispatch | - | - |

A cancelled or missing run is not a pass. A run on an earlier SHA is not evidence for this one.

Earlier runs, kept for the record (none is evidence for the frozen SHA): the qualification dispatched on `610d0a56` was **cancelled by its 35-minute job timeout while still in the apt prerequisites step** (its earlier successful runs on the Discord line took 14 to 17 minutes), so it proves nothing either way and gets one re-run on the frozen SHA because it died before any test body ran. The library validation on `610d0a56` failed at the offline secret scan (fixed in `0c6a9c36`); on `0c6a9c36` it failed only at `npm audit` (fixed in `cd0ff8d0`). agent-ui passed on `610d0a56`.

## 4. Builds (twin builds of one SHA, see `RUNBOOK-LAUNCH.md` section 0)

| Field | D1 (dark twin) | D2 (open twin) |
|---|---|---|
| Built by, when (UTC) | - | - |
| Command (flags only, no values): `vercel deploy --prod --skip-domain --meta rafiiSourceSha=<sha> --env ...` | - | - |
| Deployment ID | - | - |
| Deployment URL | - | - |
| Target / state | - | - |
| Build duration, cost note | - | - |
| Source fingerprint equals the frozen SHA | - | - |
| Env names present (readback, names only) | - | - |
| Gate value class (`tester workspace` / `*`) | - | - |
| Server cap passed | - | - |
| Aliased to `rafii.io` | - | - |
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
- Nothing in this receipt may be filled from memory. If a cell cannot be read back, write "unverified" and the reason.
