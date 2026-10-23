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

## Reply 4, received 2026-10-22 about 23:09Z (an explicit decision that changes rows 5 and 6; the webhook question is delegated)

> Go for 開放版直接用較大上限, [and] Webhook direction - you need to decide for me

**Decision 1, taken by the owner (option 3 of the question in reply 3):** the open build is made with a larger cap and the first opening is not staged. The owner did not name a number; the question gave "for example 300", so **the cap is 300**, and the agent states it here so the owner can change it before the build. Both builds carry the same line, `--env 'POSTRIFF_DISCORD_GUILD_CAP=300'` (minus any difference between the Portal's server count and monitoring Q9), because the code default on production is 90 and an omitted line would silently cap at 90. They then differ only in the gate value. Nothing else in rows 5 and 6 changes: the open build is still made only after the tester session passes, the promotion still needs T0, every MUST item VERIFIED and no abort trigger, and **only these two builds are approved** (raising the cap again would be a third build and a new yes).

**The agent's disagreement, on the record:** it advised a staged ramp. The risk of opening at 300 at once is that the first real customers are the test of a flow no real Discord account has used yet, with scheduled posts draining at about 5 to 12 a minute. Controls that stay and do not contradict the decision: the 20-minute tester session must pass first; the abort ladder (promote the dark twin, seconds) and the monitors; someone on call at the opening (H-07); the per-person limit and the exact count.

**Decision 2, delegated to the agent: the webhook route stays OFF for this launch.** Bot route only; the two webhook flags are not set on either build; the webhook track starts after the opening (the safe counting experiment is no longer needed to get past 100 servers, now that the app is verified; what remains is a real qualification with the owner, then it ships as an optional bot-free mode for server owners and administrators). Reasons: it has never run against real Discord and needs its own qualification flag; with no staged ramp the launch should have the fewest moving parts; the tester session is the only real test before the opening and should not be split between two routes; the bot route already serves every customer who can add an app. Strongest argument against: some customers will not install a bot, and they wait days for the webhook mode. What would change this: the tester session or the first customers showing that most cannot add the bot.

## Reply 5, received 2026-10-22 about 23:13Z (corrects the number in reply 4)

> 唔係，我開放版本要成千上萬嘅 user 都用到喎。 [No: my open version must be usable by thousands to tens of thousands of users.]

**Reading:** the 300 in reply 4 was only the example number in the agent's question, and it is too low for what the owner wants. **The cap on both builds is now 10,000** (`--env 'POSTRIFF_DISCORD_GUILD_CAP=10000'`). The owner can name a higher number before the build; a later change is a third build and needs a new yes. The cap is a safety valve, not capacity.

**What the cap does not give (stated to the owner, no change to the decision):** the system sends Discord posts through one worker that runs once a minute: about 12 posts a minute when only Discord has work and about 6 when other providers are busy too (with the approved budget of 25 jobs and 40 seconds), so roughly 360 to 720 posts an hour. Thousands of customers can connect; they cannot all post at the same time. A backlog makes posts late, and a post whose approval expires before it can be sent is held for a fresh approval, not sent late. Real step latency is not measured, so the true figure may be lower. The follow-up engineering step is worker parallelism (checklist W-02); it is a new release candidate and is not part of the frozen build. The agent starts it only if the owner says so.


## Reply 6, received 2026-10-22 about 23:50Z (three short confirmations to the three asks in the agent's last message)

> 「token ready」、「OK 推 workflow 分支」。仲有「OK 查」

**Reading, by the agent:**

1. **"token ready"** means the owner says GitHub Environment `rafii-rc-deploy` exists and holds the secret `VERCEL_TOKEN`. The agent has not seen, asked for or printed the token. It cannot read the environment's protection settings, so the first run proves them: a `preflight` run must stop at "Waiting for review" before any step starts. If it runs without waiting, the agent stops, tells the owner and requests no build until it is fixed (a preflight is read-only, so that first run is the safe one to learn this on). The conditions the agent asked for are: required reviewer = the owner, "Prevent self-review" off, deployment branches limited to `claude/discord-launch-rc-deploy-*`, the secret added only after those, and the variable `TESTER_WORKSPACE_ID` (not a secret) before D1.
2. **"OK 推 workflow 分支"** is permission to push request branches named `claude/discord-launch-rc-deploy-{preflight,d1,d2}-*`, each holding only `.github/workflows/rc-staged-build.yml` and `deploy/REQUEST.json` (an orphan commit; no other workflow exists on that branch, and no existing workflow triggers on those names). The first push is `preflight`, which only reads (CLI flags, token accepted, environment variable NAMES). A `d1` or `d2` request is pushed only when the conditions of its approved row hold, and every run still needs the owner's own approval in GitHub, against a commit number the agent names in chat. The agent told the owner it would not use the workflow before an independent review of it was closed, and keeps to that.
3. **"OK 查"** is permission for one read-only query on the production database to find the tester workspace id. The query selected, per workspace that has a Discord bot installation: the workspace id, the number of distinct servers, the first and last connection dates and whether any is live. It did not select any credential text, email, name or content, and changed nothing. Result: exactly one workspace has a Discord bot installation (one server, connected 2026-10-19 15:36Z, live). The id was given to the owner in chat to confirm and is **not** written in this repository (the repository is public).

**Not changed by this reply:** the rows, the two builds, the cap of 10,000, the bot-only decision, and everything under "Not covered by this reply" above. H-05, H-07 and H-03 remain the owner's own acts. The tester session still needs the tester Discord user id, the test server id, a public test channel id and a private channel id the bot cannot see.

**Facts the agent noticed while preparing this (not owner decisions):** the repository is public, so workflow logs are public; the workflow therefore prints no user name, no secret, and masks the tester id. The first attempt by the agent to push an inert test workflow was refused by the session's safety layer as a deploy-path action; the agent did not work around it and asked the owner, whose reply above is the permission.

## Replies 7 to 10, received 2026-10-23 between about 00:30Z and 01:20Z (short confirmations and approval taps)

> "1. I confirm  2. Added TESTER_WORKSPACE_ID" ... "Done" ... "Done" ... "Done go"

**Reading, by the agent:** (7) the owner confirmed that the single workspace with a Discord installation is the tester workspace and added its id to the environment (the id is not in this repository). (8) after the first preflight showed that Vercel rejected the token's scope, the owner replaced `VERCEL_TOKEN` with a wider-scope token and moved the tester id to an environment secret. (9) the owner approved the second preflight run (commit `9dd6b1b`) in GitHub, which is the owner's own act and is what the environment gate records. (10) the owner approved the D1 build run (commit `a2a1070`) after asking whether `rafii.io` still naming the old build was a problem (answered: it is intended, it changes only at promotion).

**Process note:** the agent applied the seven project variables (rows 1 to 3) and pushed the D1 request after posting the preflight result to the owner but before the owner had replied "go". Both were covered by the owner's approval of rows 1 to 5 and the build itself still needed the owner's approval tap; the agent told the owner and offered to delete the variables.

**Question, not an approval (about 01:25Z):** whether Discord can be served without a bot (webhooks) and whether 100,000 to 200,000 users could post at the same minute. Answered in chat: webhooks are possible but not faster by themselves; today's sender is about 6 to 12 posts a minute, `W-02-parallel-sending-plan.md` applies. **No approved row changes.** The agent asked for W-02 yes or no and the expected first-week volume.

## Reply 11, received 2026-10-23 about 02:05Z

> 做

**Reading, by the agent:** the owner's answer to "W-02 yes or no" (parallel Discord sending, `W-02-parallel-sending-plan.md`). It starts **engineering only**: a new branch `claude/discord-w02-parallel-20261023` from the frozen head, in its own worktree, behind a flag that is off by default, with tests and an in-process capacity simulation. It does **not** approve any build, deployment, environment change, promotion, merge or pull request. The frozen release candidate and its approvals are untouched. Everything the work needs afterwards is a separate yes: a new freeze and exact-SHA CI, an independent review, the owner-run Depot capacity run (packet row 9), a new approval packet and new builds (the current approvals cover D1 and D2 of `2a5a523d` only). It does **not** answer decisions 1 to 6 of `APPROVAL-PACKET-2.md` (H-05, the Q-05 waiver, H-07, M-03, the tester assets, T0 and GO_TIME), and those remain open; the expected first-week volume was not given.

## Reply 12, received 2026-10-23 about 03:00Z ("芝麻開門": the release is redefined as open to every new customer)

> 芝麻開門。更新 Rafii Discord 今次發佈要求：正式部署完成後，要向所有新客戶開放，唔採用 D1 暗版、邀請制或指定 workspace 白名單作為交付。
> 請接續現有 release ledger、最新凍結版本及發佈流程，保留所有活躍 Agents，完成以下工作：
> 1. 全面開放入口：核實 Production 使用 POSTRIFF_DISCORD_CONNECT_WORKSPACES=* 或等效設定。全新、從未連接 Discord 嘅普通客戶 workspace，亦必須可以開始連接及完成 OAuth。
> 2. 驗收實際功能：使用新客戶身份，驗證連接、目的地授權、立即發佈、排程、暫停／取消、重連及斷開。真實發送測試沿用已明確批准嘅帳戶及內容。
> 3. 處理容量限制：核實 Discord Bot verification、server cap 同速率限制。如果會阻止新客戶使用，先處理並交代實際容量；保留權限隔離、防重複發送及停發保護。
> 4. 維持發佈範圍：使用既有正式 Production postriff-phase2-private 及其正式資料庫。W-02 等尚未驗收工程維持獨立，唔混入今次發佈。
> 5. 交付可核實證據：提供 Production URL、commit SHA、部署 ID、全面開放設定及全新客戶實測收據。CI 通過、build READY 或程式已部署，都唔等於完成。
>
> 完成標準係：新客戶毋須人工加入白名單，就可以自行連接並使用今次正式發佈嘅 Discord 功能。 如仍有阻塞，繼續完成可做嘅修復，再具體列出餘下問題，唔好以暗版取代目標。
>
> 1. H-05：誰放行？ James 作 Release Captain。獨立 AI review 必須對應最終發佈 SHA，附安全修復證據；真實流程、隔離及容量驗收通過後，批准全面開放。刪除「只批准 D1 受控驗收」嘅定位。
> 2. Q-05：跨租戶豁免？ 不豁免，亦不延至公開後。 全面開放前，完成 A／B 帳戶雙向讀寫拒絕及無副作用驗證，補齊原腳本缺少嘅寫入測試。
> 3. H-07：誰值班？ 要求維持：填實際操作者、覆蓋時段、警報入口，以及 Mac 離線時可執行嘅停發／回退方法。未確認就保持未完成。
> 4. M-03：備份／PITR？ 要求維持：核實正式資料庫嘅可用備份、還原點及 compute。PITR 按實際狀態填寫，再評估備份是否足夠，毋須為填表自動購買。
> 5. H-03：測試資料？ 重用既有 tester workspace，補齊 IDs 及時段；另加入全新、無 Discord 連接紀錄嘅普通客戶 workspace，驗證毋須白名單亦能完成連接及使用功能。
> 6. T0／GO_TIME？ 改為全面開放嘅目標時間。必要驗收、容量及值班未完成就順延；D1 READY 不算交付完成。
>
> 另外要補一項容量放行標準：按既定 5,000 條同分鐘到期情景，在與正式部署一致嘅架構量度遲到時間、排空時間、公平性及重複發送，並先寫清楚可接受延遲。
> 我頭先個 prompt 亦要補返：W-02 可以獨立開發；如果全面開放所需容量依賴 W-02，就要等佢驗收、整合並重新凍結版本後，先正式全開。

**Reading, by the agent** (the working definition is `RELEASE-DEFINITION-v2.md`):

1. **The deliverable changes.** The release is done when a new customer, with no manual allowlisting, can connect and use the Discord features of this release on the formal Production deployment. The dark build D1, invitations, workspace allowlists, a green CI, a READY build and deployed code are verification steps or evidence, never the delivery. The earlier framing of D1 as the thing being accepted ("controlled acceptance", `APPROVAL-PACKET-2.md` sections 4 and 5) is withdrawn.
2. **Scope.** Existing Production project `postriff-phase2-private` and its production database. W-02 and other unaccepted work stay separate. Because the capacity standard in the last paragraph cannot be met by the frozen head (see the facts below), the formal full opening waits for W-02 to be accepted, integrated and the version re-frozen, as the owner wrote.
3. **H-05.** The owner (James) is the Release Captain. The independent AI review must be of the final release SHA with the security-fix evidence. Real flow, isolation and capacity acceptance come first; then the full opening is approved. The agent reads "批准全面開放" as the Release Captain's intent to approve once those three pass, **not** as a signed approval of any build, SHA, deployment or setting today.
4. **Q-05.** No waiver and no deferral past opening. A/B accounts, both directions, reads **and writes**, denied, with no side effects, before the full opening. The agent adds the write tests the original step 8 of `TESTER-SESSION-SCRIPT.md` lacked.
5. **H-07, M-03.** Kept as requirements; unconfirmed items stay open. M-03 is filled from what the tools can read; PITR is recorded as it really is, sufficiency is assessed, nothing is purchased.
6. **H-03.** Reuse the tester workspace; add a brand-new ordinary workspace with no Discord history. The ids and the time slot are still the owner's to give.
7. **T0 and GO_TIME** are now the target time of the full opening and move back whenever acceptance, capacity or on-call is incomplete.
8. **Capacity release standard.** 5,000 posts due in the same minute, measured on an architecture consistent with the formal deployment: lateness, drain time, fairness, duplicates; the acceptable latency is written first (`RELEASE-DEFINITION-v2.md` section 4, a proposal for the owner to accept or tighten).
9. **Real sends** in the new-customer test reuse the account the owner explicitly approved earlier and content the owner approves at that moment; the cap of three messages in `TESTER-SESSION-SCRIPT.md` is unchanged.
10. "保留所有活躍 Agents": the independent W-02 reviewer keeps running; no agent is stopped to save a build.

**Not approved or changed by this reply:** any build, deployment, promotion, environment-variable change, merge or publication beyond the rows already approved (those name D1 and D2 of `2a5a523d` only; a new frozen SHA, W-02 integrated, needs its own packet and its own approval taps); creating accounts or rows in the production database; reading Discord or Supabase dashboard values only the owner can see; buying point-in-time recovery or more compute; making the open setting durable as a project variable. T0 is not set.

**Facts the agent found while reading it (code read on `2a5a523d`, not run against a real fresh account) [Likely]:**

- Production today does not satisfy item 1: `rafii.io` still serves `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`, which has no Discord v2 code and no gate variable; D1 (`dpl_25ihHyiZCzZXAjVsJqJiYcCWA51n`, not promoted) has the gate set to the tester workspace only. Nothing is open to anyone.
- With `POSTRIFF_DISCORD_CONNECT_WORKSPACES=*` the gate returns "open to all" for every workspace (`launch_gate.py`). After it, the start path asks only for: a signed-in member with the connections permission in their own workspace, a linked Discord identity that manages the chosen server, at most three starts in flight per person, the server cap, 20 starts per ten minutes per workspace, and the Discord switches (connections v2 and authorization v2 on, provider not paused). The identity admission at the callback applies to YouTube only. No other allowlist was found on the Discord connect path.
- The open setting lives on the build command (the gate and the cap). A later production build that omits it would silently close Discord again, and a build without the cap line falls back to the code default of 90 servers. Making it a project variable is a separate step and needs the owner's yes.
- Capacity: on the frozen head one Discord post costs six requests and the worker budget is about 6 to 12 posts a minute, so 5,000 same-minute posts take roughly 7 to 14 hours; the standard cannot be met without W-02 (simulated about 23 minutes at the reviewed 25 requests a second).
