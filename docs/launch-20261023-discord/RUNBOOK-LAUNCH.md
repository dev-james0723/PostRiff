# RUNBOOK-LAUNCH: Discord capped Wave 1

Status: draft for the owner. Commands marked OWNER need the Vercel CLI or dashboard login that this agent does not have; the agent can run them through the owner's paired computer only after a written yes. UTC everywhere; the owner is in Hong Kong (UTC+8).

## 0. The model in one paragraph

Vercel applies environment variables to **new deployments only**. So the launch uses two staged builds of one frozen SHA and switches between them with `vercel promote` (no rebuild, seconds, reversible):

- **D1, dark twin.** Gate allowlist = the tester workspace (plus workspaces that already have a live Discord server card or linked identity, who are never locked out). Promoted first, so real OAuth works on `rafii.io` and the cron runs, while the public sees "Discord isn't open to new connections for this workspace yet".
- **D2, open twin.** Same SHA, `POSTRIFF_DISCORD_CONNECT_WORKSPACES=*`, server cap 90 (the default on production). Built early, promoted only at T0 when every MUST gate is VERIFIED.
- **Rollback target** for a code defect: `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` (live today, no Discord v2 code). Primary abort: promote D1 again.

The dangerous values (gate, `POSTRIFF_OAUTH_DISCORD_REVIEWED`) exist only on the build commands, never in project env, so an accidental rebuild can only close things.

## 1. Preconditions (all must be true before T-6h)

| # | Precondition | Evidence |
|---|---|---|
| 1 | Approval Packet 1 answered for rows 1, 2, 4, 5, 6, (3), 11, 12, 13 | reply logged verbatim in the ledger |
| 2 | Frozen SHA named in rev B, exact-SHA CI green on every workflow, `scripts/rc_superset_proof.py` passes | run URLs in `RC-RECEIPT.md` |
| 3 | Production env names confirmed (client id and secret, bot token, public base URL, credential key, cron secret) | OWNER output of `vercel env ls production --scope team_PgXY5VdAYKcsv0RLoDPHscNq --project prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L` (names only) |
| 4 | PITR / latest restore point known (M-03) | OWNER note |
| 5 | Portal audit sheet filled (H-02), App Verification status known (H-01) | `PORTAL-AUDIT-SHEET.md` |
| 6 | Tester assets in the Authorization Block; the owner's 20-minute slot is agreed | block |
| 7 | Release Captain named and the security-review decision recorded (H-05) | note |
| 8 | On-call and customer-support owner named (H-07); privacy and terms wording approved (H-08) | note |
| 9 | Other lanes told not to deploy to production after D1 is promoted | OWNER message |
| 10 | The Developer Portal's server count compared with `monitoring.sql` Q9 `servers_counted`; if Discord shows more servers than Q9, the cap passed to both builds is 90 minus the difference (the bot stays in a server after a disconnect, and deleted workspaces take their rows with them) | OWNER number, both figures in the ledger |

## 2. Timeline (T0 = public opening)

| When | Who | Step | Evidence to record |
|---|---|---|---|
| T-9h | AGENT | Generate the policy: `python3 scripts/discord_rate_policy.py generate` (it prints the renew-by date). Apply rows 1 and 2 (and 3 if approved) as one batch, type `plain`, then read back the newest env records by name and value. | readback table, policy revision and expiry |
| T-8h | AGENT | Freeze: record the SHA; `git status --porcelain` empty in the build worktree; `.vercel/project.json` shows project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, team `team_PgXY5VdAYKcsv0RLoDPHscNq`. | frozen SHA, link check |
| T-7h | OWNER (or AGENT via paired computer) | Build D1 (see 3). Do not run it twice. | deployment ID, URL, build duration, cost note |
| T-7h | AGENT | Fingerprint D1 against the frozen SHA (every listed source file identical), read deployment state (READY, target production, no alias to `rafii.io`), read runtime env names. READY alone is not acceptance. | fingerprint result |
| T-6h | OWNER | Build D2 (see 3), after D1 is READY and fingerprinted. Do not promote it. | deployment ID, URL |
| T-6h | AGENT | Fingerprint D2 against the SHA and against D1. | result |
| T-5h30 | OWNER + AGENT | H-05 sign-off exists. Promote D1: `vercel promote <D1 url> --scope team_PgXY5VdAYKcsv0RLoDPHscNq`. Check the `rafii.io` alias now points at D1, runtime logs show `/api/cron/worker` answering 200 each minute, and a non-allowlisted test account sees Discord as closed. | alias readback, log lines |
| T-5h | OWNER + AGENT | Tester session (X-02 to X-06, about 20 minutes of the owner): real consent for one server, stored outcome read back, destination list, one approved post with read-back, one scheduled post and its cancel, revoke and reconnect. At most three real messages, in the tester server only, mentions suppressed. | outcomes read from the database (counts and states only) |
| T-3h | AGENT | Soak: monitors in `monitoring.sql` every 15 minutes, no abort trigger. M-01 grant and capability re-check. | query results as counts |
| GO_TIME (default T0 minus 3h) | AGENT | `LAUNCH-READINESS-REPORT.md`: every MUST gate with status and evidence link. Recommendation GO or NO-GO. | report |
| T0 | OWNER | If GO and the owner says so: `vercel promote <D2 url> --scope team_PgXY5VdAYKcsv0RLoDPHscNq`. Read back the alias; a second test workspace now sees Discord as open. | alias readback, screenshot of the open state (no ids) |
| T0 to T+24h | AGENT | Watch the thresholds in `monitoring.sql`; reports at T+2h and T+24h (aggregates only). Stop conditions are in `RUNBOOK-INCIDENT.md`. | reports |
| Renew-by date (7 days before the policy expires) | OWNER | Policy renewal: generate, set, then a build and promote cycle of the then-current release, because env applies to new builds only. | calendar entry |

If a MUST gate cannot pass, declare NO-GO at once and keep D1 promoted (gate closed): that is the fallback F-02. Nothing is lost; existing grants keep working.

## 3. Build commands

Both builds come from a clean checkout of the frozen SHA that is linked to the production project. Check `git status --porcelain` is empty and `cat .vercel/project.json` names the project and team above; never build from a dirty tree or from `consumer-saas`.

```
# D1: gate closed except the tester workspace and workspaces that already have a Discord footprint
vercel deploy --prod --skip-domain --scope team_PgXY5VdAYKcsv0RLoDPHscNq \
  --meta rafiiSourceSha=<frozen sha> --meta rafiiTwin=dark \
  --env POSTRIFF_DISCORD_CONNECT_WORKSPACES=<tester workspace uuid> \
  --env POSTRIFF_OAUTH_DISCORD_REVIEWED=true \
  --env POSTRIFF_DISCORD_GUILD_CAP=<90 minus the difference from precondition 10; leave out when there is none>

# D2: same SHA, gate open (cap stays 90 by default on production)
vercel deploy --prod --skip-domain --scope team_PgXY5VdAYKcsv0RLoDPHscNq \
  --meta rafiiSourceSha=<frozen sha> --meta rafiiTwin=open \
  --env POSTRIFF_DISCORD_CONNECT_WORKSPACES=* \
  --env POSTRIFF_OAUTH_DISCORD_REVIEWED=true \
  --env POSTRIFF_DISCORD_GUILD_CAP=<same value as D1>
```

Notes:

- `--meta` attaches the frozen SHA and the twin name to the deployment record, because a CLI build has no git metadata and `/api/health` reports `sourceRevision: null` on this lineage. The file fingerprint is still the proof; the metadata is a label.
- `--skip-domain` stages a production-target build without moving `rafii.io`. Crons run on the deployment that serves the production domain, so a staged build runs none [Likely, confirm in the first minute after promoting D1].
- If a flag is silently ignored the result is closed, not open: an unset gate on production means nobody (except grandfathered workspaces), and an unset reviewed flag shows Discord publishing as Unsupported. A failed readback at the promotion step is therefore a stop, not a risk.
- If the CLI does not accept `--env`, set the same names in project env for the build, then remove them again afterwards; every production build of any lane made in between would inherit them, so tell the lanes first.
- Cost: previous builds of this project took about 2.5 minutes. The approval cap is $5 per build. Post a cost note before building.
- Do not rebuild a SHA that already has a READY twin of the same kind. An infrastructure failure is the only reason for a retry, with a written reason.

## 4. Reading the state during the launch

| Question | How |
|---|---|
| Which deployment serves `rafii.io`? | alias readback (`get_alias` on `rafii.io`) and compare the deployment ID with D1, D2 or the rollback target |
| Is the gate open for workspace W? | the provider catalog entry for Discord has `discordAccess.status` (`open` or `closed`, with a reason) |
| Servers in use against the cap | `monitoring.sql` Q9 |
| Is the worker draining Discord jobs? | `monitoring.sql` Q7 (queue depth, oldest eligible lag, held, uncertain, dead letters) |
| Are we near a Discord restriction? | `monitoring.sql` Q2 (invalid requests in 10 minutes, page above 1,000) and Q3 (open circuits and manual holds) |
| When does the rate policy expire? | `monitoring.sql` Q6 and the renew-by date printed by `scripts/discord_rate_policy.py` |

## 5. Customer-facing states

| State | What the customer sees | How it is produced |
|---|---|---|
| Closed (before T0, after an abort) | "Discord isn't open to new connections for this workspace yet. Connections you already have keep working." (also in Traditional and Simplified Chinese) | gate closed |
| Full (90 servers) | "Discord has no room for another server right now. Nothing was connected or posted. Try again later." | cap reached, HTTP 409 `discord_capacity_reached` |
| Delayed | the existing "delayed" state on the queue item | rate coordinator hold or backoff; nothing was sent |

Neither refusal promises a waitlist or a date. Do not add one unless something records it.
