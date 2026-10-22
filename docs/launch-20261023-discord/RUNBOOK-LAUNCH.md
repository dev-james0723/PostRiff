# RUNBOOK-LAUNCH: Discord capped Wave 1

Status: draft for the owner. Commands marked OWNER need the Vercel CLI or dashboard login that this agent does not have; the agent can run them through the owner's paired computer only after a written yes. UTC everywhere; the owner is in Hong Kong (UTC+8).

## 0. The model in one paragraph

Vercel applies environment variables to **new deployments only**. So the launch uses two staged builds of one frozen SHA and switches between them with `vercel promote` (no rebuild, seconds, reversible):

- **D1, dark twin.** Gate allowlist = the tester workspace (plus workspaces that already have a live Discord server card or linked identity, who are never locked out). Promoted first, so real OAuth works on `rafii.io` and the cron runs, while the public sees "Discord isn't open to new connections for this workspace yet".
- **D2, open twin.** Same SHA, `POSTRIFF_DISCORD_CONNECT_WORKSPACES=*`, server cap 10,000 (the owner's decision, `AUTHORIZATION-RECORD.md` replies 4 and 5; the code default on production is 90). Built early, promoted only at T0 when every MUST gate is VERIFIED.
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
| 10 | The Developer Portal's server count compared with `monitoring.sql` Q9 `servers_counted`; if Discord shows more servers than Q9, the cap passed to both builds is 10,000 minus the difference (the bot stays in a server after a disconnect, and deleted workspaces take their rows with them) | OWNER number, both figures in the ledger |

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
  --env 'POSTRIFF_DISCORD_CONNECT_WORKSPACES=<tester workspace uuid>' \
  --env 'POSTRIFF_OAUTH_DISCORD_REVIEWED=true' \
  --env 'POSTRIFF_DISCORD_GUILD_CAP=<10000 minus the difference from precondition 10; 10000 when there is none; never leave this line out, the code default on production is 90>'

# D2: same SHA, gate open, same cap line as D1
vercel deploy --prod --skip-domain --scope team_PgXY5VdAYKcsv0RLoDPHscNq \
  --meta rafiiSourceSha=<frozen sha> --meta rafiiTwin=open \
  --env 'POSTRIFF_DISCORD_CONNECT_WORKSPACES=*' \
  --env 'POSTRIFF_OAUTH_DISCORD_REVIEWED=true' \
  --env 'POSTRIFF_DISCORD_GUILD_CAP=<same value as D1>'
```

Notes:

- `--meta` attaches the frozen SHA and the twin name to the deployment record, because a CLI build has no git metadata and `/api/health` reports `sourceRevision: null` on this lineage. The file fingerprint is still the proof; the metadata is a label.
- `--skip-domain` stages a production-target build without moving `rafii.io`. Crons run on the deployment that serves the production domain, so a staged build runs none [Likely, confirm in the first minute after promoting D1].
- Quote every `--env` assignment. The wildcard in `'POSTRIFF_DISCORD_CONNECT_WORKSPACES=*'` is a shell glob character: unquoted, zsh (the macOS default) stops with "no matches found" and other shells may expand it. After the build, read the value back from the deployment (names and values of these non-secret variables) before promoting.
- If a flag is silently ignored the result is closed, not open: an unset gate on production means nobody (except workspaces that already have a Discord footprint), and an unset reviewed flag shows Discord publishing as Unsupported. A mistyped Discord v2 flag (the code reads only the exact string `true`) leaves the v2 flows OFF and the original Discord flow ON; the original flow is behind the same gate and, on this candidate, under the same cap. A failed readback at the promotion step is therefore a stop, not a risk.
- If the CLI does not accept `--env`, set the same names in project env for the build, then remove them again afterwards; every production build of any lane made in between would inherit them, so tell the lanes first.
- Cost: previous builds of this project took about 2.5 minutes. The approval cap is $5 per build. Post a cost note before building.
- Do not rebuild a SHA that already has a READY twin of the same kind. An infrastructure failure is the only reason for a retry, with a written reason.

## 4. Reading the state during the launch

| Question | How |
|---|---|
| Which deployment serves `rafii.io`? | alias readback (`get_alias` on `rafii.io`) and compare the deployment ID with D1, D2 or the rollback target |
| Is the gate open for workspace W? | the provider catalog entry for Discord has `discordAccess.status` (`open` or `closed`, with a reason) |
| Servers in use against the cap | `monitoring.sql` Q9, read with Q12 and the Developer Portal's server count (section 6) |
| Is the worker draining Discord jobs? | `monitoring.sql` Q7 (queue depth, oldest eligible lag, held, uncertain, dead letters) |
| Are we near a Discord restriction? | `monitoring.sql` Q2 (invalid requests in 10 minutes, page above 1,000) and Q3 (open circuits and manual holds) |
| When does the rate policy expire? | `monitoring.sql` Q6 and the renew-by date printed by `scripts/discord_rate_policy.py` |

## 5. Customer-facing states

| State | What the customer sees | How it is produced |
|---|---|---|
| Closed (before T0, after an abort) | "Discord isn't open to new connections for this workspace yet. Connections you already have keep working." (also in Traditional and Simplified Chinese) | gate closed |
| Full (at the cap, 10,000 on this plan) | "Discord has no room for another server right now. Nothing was connected or posted. Try again later." | cap reached, HTTP 409 `discord_capacity_reached` |
| Delayed | the existing "delayed" state on the queue item | rate coordinator hold or backoff; nothing was sent |
| Busy or paused while connecting | "Discord is busy right now ..." / "Connecting to Discord is paused for a moment ..."; after Discord's consent screen the wording is different on purpose: "... could not finish connecting. If the bot already appears in your server, start again from Channels ..." | HTTP 429 `discord_rate_delayed` / 503 `discord_rate_coordinator_unavailable`; no connection is revoked by either |

Neither refusal promises a waitlist or a date. Do not add one unless something records it.

## 6. Keeping the server count honest after opening

The cap counts the servers Rafii holds a row for. Discord counts the servers the bot is in. They differ in ways Rafii cannot see (`launch_gate.py` lists them): a person who picks another server on Discord's screen than the one reserved, who closes the tab after consenting, whose callback fails, a deleted workspace, anyone who adds the public bot by hand.

| When | Who | Check | Act |
|---|---|---|---|
| Before opening (precondition 10), then every 2 hours on day 1, then daily for a week | OWNER (Portal) + AGENT (queries) | Portal server count minus `monitoring.sql` Q9 `servers_counted` = D; Q12 four numbers summed = U | D at most U plus 2: normal. D above U plus 2: someone adds the bot outside Rafii, lower the cap by D and rebuild the twins, or close the gate (promote D1). D at 5 or more: stop opening further. |
| Portal count reaches 85 | OWNER | Portal | If the app were not verified: close the gate (promote D1) and start verification (H-01); 100 is a hard Discord limit for an unverified app. The owner reports the app is verified (check mark on the bot tag), so on this build the row is a prompt to decide the next cap, not a stop. |

The first opening is at cap 10,000 (the owner's decision). Raising it again is a third build and needs the owner's yes. Verification (H-01) is reported done by the owner, so Discord's own limit is not what stops a raise: readiness, rate limits and support are.

## 7. Behaviour to know about before opening

- Workspaces with a Discord footprint (an unrevoked server card, or a linked identity including one that must be reconnected) pass the gate even when it is closed, and may start any kind of connection, including a new server, which then takes a cap slot. The public sees the closed message. Decision D-08 (packet section 4): kept broad; the narrow reading (reconnect only) is a small change if you want it.
- Every install start in flight holds its own slot for up to ten minutes (a double click is two, a reconnect start is one), because each is a server the bot may join. One person (workspace and member) may have at most three in flight: a fourth is refused with the capacity message until one finishes or expires. A server that already has a stored bot credential holds its slot for good, so reinstalling after a disconnect needs no second one; a reconnect takes no slot but counts as a start.
- With the cap at 0 or misspelt, servers that already have a stored credential can still be reinstalled (they take no new slot). The original (non-v2) flow cannot name the server before the person picks it on Discord's screen, so at a full house it also refuses a legacy reconnect.
- At a full house, a person whose callback was delayed by Discord's busy minute and who starts again may be refused for up to ten minutes, because their earlier start still counts; "start again and it will finish" is only guaranteed while there is room. It matters only when the Portal count is already near the cap.
- One account can hold three slots for ten minutes and many accounts can hold more; `monitoring.sql` Q13 shows the distribution. If the in-flight count is high and few installs complete, close the gate (promote D1). The independent re-check reproduced it with 30 workspaces of three starts each (about 88 live rows): availability only, and it needs many sign-ups; it is why Q9 has a threshold on in-flight starts.
- Known low items, left as they are on purpose so the frozen build does not move: a person with three unfinished starts sees the same "no room" wording as a full house (their own code would be a web copy change); a Discord 429 on a login-token refresh waits a fixed five minutes and ignores Retry-After, and the worker holds the post for review after repeated ones; the two count statements scan about 100 ms at a million never-purged transaction rows under the global lock (today's table is tiny; revisit above about 100,000 rows).
- The original (non-v2) connect flow also adds the bot to a server of the person's choice, and is capped.
