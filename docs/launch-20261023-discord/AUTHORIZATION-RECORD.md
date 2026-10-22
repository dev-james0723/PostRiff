# AUTHORIZATION RECORD

What the owner has authorized, in the owner's words, how the agent reads it, and which conditions still apply. Authority comes only from the Authorization Block and direct owner messages (`AGENT-HANDOFF-PROMPT.md` section 1.2); this file records the second kind. Written 2026-10-22T22:12Z (06:12 Hong Kong, 23 Oct). No secret, token or customer content belongs here.

## Reply 1, received 2026-10-22 after `APPROVAL-PACKET-1.md` rev D (RC head `2a5a523d788eef67a5c7dbed609a98efa6650eef`)

> Approve all from 1 to 15 and rev B+

**Reading, stated back to the owner (tell me if it is wrong):** rows 1 to 15 of the packet, each as written in rev D with the option the row recommends, plus the last row of the table, the one labelled "(rev B+)" (promote D1 dark, open the capped gate at T0 by promoting D2). "B+" also means the yes is not tied to rev D: while the rows keep the same meaning, a later revision that only moves the head SHA does not need a new answer. A new action, a new cost, a different env name or value, or a different scope still does.

## What each row now covers

| Row | AUTH | Approved as | Conditions that still apply | State |
|---|---|---|---|---|
| 1 | AUTH-3 | Four non-secret flags in Production env, one batch, type `plain`, read back | Applied just before the D1 build, not earlier (env is project-wide and other lanes build too); names and values exactly as in the packet | not applied |
| 2 | AUTH-4 | New rate policy in Production env, type `plain`, generated at apply time, old value never read | Same moment as row 1; the tool prints the renew-by date | not applied |
| 3 | AUTH-3 | `POSTRIFF_WORKER_MAX_JOBS=25`, `POSTRIFF_WORKER_MAX_SECONDS=40` (project-wide, all providers) | Same batch as row 1; new builds only | not applied |
| 4 | D-04 | `POSTRIFF_OAUTH_DISCORD_REVIEWED=true` on the two build commands only, never in project env | Opening is a separate step (rev B+ row) | decision taken |
| 5 | AUTH-1 | Staged dark build D1 of the frozen SHA | Frozen SHA only, and only once every row of `RC-RECEIPT.md` section 3 is green on it; clean checkout linked to `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`; needs the tester workspace id for the gate value; cost note first; READY is not acceptance | waiting for CI, freeze, tester id, a machine with the Vercel CLI |
| 6 | AUTH-1 (deviation) | Second staged build D2 of the SAME SHA, gate open (`*`) | After the tester session passes; fingerprinted against the SHA and against D1; **these two are the only builds approved: an infrastructure retry would be a third and needs a new yes** | not built |
| 7 | AUTH-10 | Read-only look at the Developer Portal through the paired computer | No Save, no Verify, no reset, no edit; never open or capture a token or secret | blocked: paired computer offline |
| 8 | new | Names-only list of Production env variables through the paired computer | `vercel env ls production ...`, names column only, never values, never `env pull`, never `--json` | blocked: paired computer offline |
| 9 | AUTH-2 | Capacity Stage A, ceiling $4.32 | The existing harness is on the unmerged #197 branch (`.depot/workflows/discord-capacity-stage-a-*`) and runs through the owner's Depot account; not a Wave 1 gate | deferred, see below |
| 10 | AUTH-8 | Nothing to do | Production already has the five migrations | n/a |
| 11 | none | Owner supplies backup and PITR facts | M-03 is a MUST gate | owner input needed |
| 12 | AUTH-7 | Abort actions pre-authorised for Vercel: promote D1; `manual_hold` on the policy row; roll back to `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` only for a code defect after in-flight Discord jobs are drained | Only when an abort trigger in `RUNBOOK-INCIDENT.md` fires; report at once | armed once D1 exists |
| 13 | AUTH-9 | Up to three real Discord test messages | Tester server only; only the exact text the owner approves in the product UI at that moment; mentions suppressed; needs the Authorization Block ids | owner input needed |
| 14 | H-08 | Privacy, deletion and in-app wording for Discord, as drafted (`P-01-privacy-terms-diff.md`, commit `4680efce` on the RC) | Pages keep their "draft, pending legal review" banner | approved |
| 15 | decision | Recommended path: no separate patch release; the candidate carries the Next.js and Sentry patch | A `PATCH-ONLY` reply was not given | approved |
| rev B+ | AUTH-5, AUTH-6 | Promote D1 dark (gate closed); at T0 open the capped gate by promoting D2 | Dark promotion: Q-01 to Q-07 VERIFIED and the H-05 sign-off exists. Opening: X-02 to X-05 VERIFIED in the tester session, every Wave 1 MUST item VERIFIED, no abort trigger fired, T0 reached. If one fails the answer is NO-GO and D1 stays promoted | not started |

Decisions taken by default and not objected to: D-01 to D-03, D-06, D-07, and D-08 (broad footprint reading; no `NARROW 8` reply).

## Not covered by this reply

- Merging anything, changing `git.deploymentEnabled`, preview settings, Build Machine size, Spend Management, billing, domains, credentials, secrets; any Portal change; "Verify App"; registering commands; Wave 2; engagement, webhook, user-install or PING modes.
- Any build other than D1 and D2 of one frozen SHA; any Discord message other than the three in row 13.
- **H-05 (Release Captain and security-review decision), H-07 (on-call), H-03 (the tester session itself) and H-01 (verification status)** are the owner's own acts. An approval of packet rows does not sign them, and the promotion row names H-05 as a condition.

## What I still need from the owner

1. The paired computer online (the MacBook Pro was last seen 2026-10-22 14:52Z). I have no Vercel CLI or token; the build, rows 7 and 8, and the read-only checks need it, or the owner runs the commands from `BUILD-RUNSHEET.md`.
2. Tester Rafii workspace id (gate value of D1) and, for the session, the tester Discord user id, test server id, public test channel id and private no-bot channel id.
3. H-05: who is Release Captain, and whether the 2026-10-20 independent AI security review is enough.
4. Row 11: PITR enabled or not, latest restore point, compute size.
5. T0 and GO_TIME (UTC and Hong Kong). Without them I keep the packet's assumption: T0 = 2026-10-23 17:00Z (2026-10-24 01:00 Hong Kong), GO_TIME 14:00Z.
6. H-07: who watches alerts and answers customers during the window.

## Order from here

Exact-SHA CI green and the independent re-verification closed, then freeze (S-08) and the superset proof on the frozen SHA. Then, in this order and each with a readback: Production env batch (rows 1 to 3) and policy (row 2); pre-flight (Q-01, cost note); D1 (Q-02); provenance, smoke, tenant probe, rollback target, OAuth URL audit (Q-03 to Q-07, C-05); Packet 2 with the evidence; H-05; dark promotion (X-01); tester session (X-02 to X-06); D2; soak; GO or NO-GO at GO_TIME; opening only on GO. A failed or missing gate at any step is reported as NO-GO, not worked around.

## Reply 2, received 2026-10-22 about 22:41Z (a statement of direction; it changes no approved row)

> 最重要係將「帳號直連」同「以本人身份發佈」分開。 [Certain] Discord 官方容許用戶透過 OAuth 直接連接 Rafii，再授權 Rafii App、Bot 或 Webhook 喺指定 Channel 發佈。但一般 OAuth 唔提供第三方 SaaS 自動以普通 Discord 用戶本人身份發訊息嘅通用權限；使用 Self-Bot 繞過限制亦違反 Discord 規則。所以我會將 Agent 嘅必達目標定為：用戶直接連接自己嘅 Discord → 選擇有權管理嘅 Channel → 正式授權 → Rafii 幫佢發佈、排程、取消、驗證及管理。用戶唔需要自己建立 Bot；優先完成官方支援嘅 Webhook 直連路線，同時保留 Bot 模式。Webhook 顯示嘅仍然係 Webhook 身份，唔會假扮個人帳號。

**Reading (the agent's, to be confirmed):** the first half matches the product as built: Rafii's one shared bot posts, never the person, and nobody creates a bot. The last sentence asks to make the webhook route the priority. That is a scope change: packet row 1 keeps the webhook flags unset on purpose, the webhook mode has never run against real Discord, and it needs a second flag that attests a real qualification. Whether a webhook-only install counts toward Discord's 100-server rule is not documented (`W-03-webhook-server-limit.md`). **No build command, env value or approved row changes until the owner answers the question below.**

Question put to the owner (one line to answer):

1. keep the first launch as the capped bot route and start the webhook track in parallel (the agent's recommendation): the safe counting experiment first, then qualification; or
2. also try the webhook route once in the tester session on the dark build (needs two extra flags on that build only, so a new yes); or
3. make the webhook route the public launch path (the agent advises against: untested with real Discord, bot-free mode only covers server owners and administrators, and the counting question is open).

## Reply 3, received 2026-10-22 about 23:00Z (new facts from the owner; they change the scale plan, not an approved row)

> I think my Discord app has been verified, actually I remember. [a screenshot of the Developer Portal menu] ... There is a tick. [a screenshot of the Rafii bot's profile in the owner's test server showing the "check mark + APP" tag] ... I am sure [the Rafii in the screenshot is the app the website uses in production].

**Reading:** the check mark on the application tag is how Discord shows a verified app, and the owner states it is the production app (the install message and test server date from 2026-10-17, which matches the first production installs). So H-01 is treated as done on the owner's word, and Discord's 100-server limit for unverified apps does not apply. Not stored in the repository: the screenshots (the H-01 notes say none belongs here). Still to do for certainty and at no cost to the owner: when the staged build exists, compare the `client_id` in the authorize URL (C-05) with the Application ID in the Portal.

**What changes:** the first cap of 90 is no longer Discord's limit; it is a rollout throttle. The limits that remain are Rafii's own: no real Discord flow has been tested, scheduled posts drain at about 5 to 12 per minute, nobody is staffed for support at scale, the rate policy allows 25 requests per second. The plan becomes a staged ramp (first cap 90, then raise in steps), and every raise is a new build, so it needs a yes: question put to the owner (one line): 1) first open at 90 and ask again before each raise; 2) pre-approve up to two more builds of at most $5 each to raise the cap in steps (the agent's recommendation); 3) open with a larger cap at once, for example 300 (the agent advises against). **Nothing changes in the approved rows until the owner answers.**

