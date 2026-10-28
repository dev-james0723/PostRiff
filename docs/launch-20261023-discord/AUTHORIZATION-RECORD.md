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

## Reply 13, received 2026-10-23 about 04:15Z ("Conditional Approval & RC2 Execution Instructions")

> Reply 13 — Conditional Approval & RC2 Execution Instructions
>
> 芝麻開門。以下係我對六項問題嘅正式決定，請記入 Authorization Record，然後繼續所有已授權嘅工程、測試、修復及獨立審查工作。唔需要每完成一個普通步驟就停低問我。
>
> 1. 容量標準：暫時同意，作為 RC2 壓測驗收門檻。
> * 5,000 條同分鐘到期：P50 ≤12 分鐘、P95 ≤25 分鐘、最大 ≤40 分鐘。
> * 0 duplicate、0 expired approval 後發送。
> * 不超過 25 rps 全域測試預算，同時必須遵守 Discord 實際 global、per-route 及其他適用 rate limits。
> * 小型租戶（≤5 條）即使其他租戶有 3,000 條 backlog，亦須在 15 分鐘內完成。
> * 必須測試公平調度、429、5xx、重試、worker crash、database contention、approval expiry、跨租戶隔離及 backlog recovery。
> * 以上只係極端 spike 嘅內部 release benchmark，唔係對客戶承諾嘅正常排程準確度。請額外制定正常負載 SLO。
>
> 如果 Depot 真實測試不達標，優先優化 request 數量、調度及吞吐量，不要直接降低驗收標準。任何提高 25 rps 政策上限嘅方案，需要重新審查。
>
> 2. H-07：James 暫任 Release Captain，但不代表已有 24/7 值班覆蓋。
> 請先建立可遠端操作嘅監控、警報、停發及回滾方案，確保 Mac 離線仍可執行。
> 必須有 backlog、delivery failures、rate-limit exhaustion、silent halt、跨租戶安全異常等警報，並提供實際演練收據。
> 正式公開前要確認真正可用嘅值班時段與警報接收渠道。未完成不得宣稱 H-07 VERIFIED。
>
> 3. M-03：繼續核實 Supabase 備份與還原。
> 先透過現有授權工具唯讀查詢 PITR、backup status、最新可還原時間、RPO/RTO，以及還原程序。
> 如果無法取得，提供我最簡單嘅 Dashboard 截圖步驟。
> 不准直接修改 Production database，不准在 Production 執行破壞性還原測試。若冇 PITR，請具體評估風險及替代備份方案。
>
> 4. Q-05：批准繼續完整跨租戶隔離測試。
> 批准 RC1/RC2 隔離環境進行 A/B 雙向讀寫探測、negative tests、authorization mutation tests，以及 mock Discord 驗證。
> 故意拆除授權檢查只能在完全隔離嘅測試 fixture 或 branch 進行，絕不可進入可部署 Production 嘅版本。
> Production A/B 帳戶必須透過正常 signup/auth 流程建立，不准直接向 Production Auth 寫入假用戶。如仍需要我開兩個帳戶，先完成所有獨立測試，再提供最少步驟。
> Test credentials 應使用受保護、短期、最小權限嘅 secrets，不能輸出到 logs。
>
> 5. Release 次序：原則同意 Dark → Private Verification → Public，但附帶嚴格條件。
> 請將 AUTH-5 明確分開：
> * Pre-promotion：本地及隔離環境跨租戶安全驗證、獨立 code review、CI、安全配置檢查全部通過。
> * Private canary：只有在我另行批准 Production promotion 後，先可用 tester-only gate 驗證真實 Discord 物件。
> * Pre-public：真實 A/B 跨租戶驗證、Discord 功能測試、容量測試、監控、rollback drill 全部 VERIFIED，先可以開放所有 workspace。
> 任何一關失敗都係 NO-GO。
> 不能用「暗版已 promote」代替安全驗證。請確認未啟用功能對現有 Production 客戶冇可觀察嘅回歸或副作用。
> Production build、promotion、環境變數修改及正式全開，仍然需要我逐項明確批准。
>
> 6. H-03：OK 查。
> 批准唯讀查詢現有 tester workspace 嘅 Discord user/server/channel metadata，包括可見及不可見 channel 嘅測試所需識別資料。
> 不可讀取 tokens、message contents 或其他用戶私隱資料。
> 同意規劃使用新嘅空白 Discord server 測試全新客戶 onboarding、server cap 及 permission flows。
> 真實 Discord 發送必須使用先前已批准嘅測試帳戶及具體訊息，最多 3 條；如果既有批准未涵蓋內容、目的地或時段，請先提出精確批准請求，唔可以自行擴大範圍。
>
> 額外 P0：必須先修復 W-02 Silent Halt。
> 禁止並行 flag 開啟但 rate-limit configuration 缺失時靜默停發。必須有 configuration validation、明確 fail-safe 行為、alert、health indication、recovery 及 rollback tests。
> 另外，請提出將 Discord 開放配置及 server cap 持久化至正式 project settings 嘅修復方案，避免每次 build 遺漏設定而意外關閉服務。未獲另行批准不得直接修改 Production 設定。
>
> 執行要求
> 繼續 W-02 修復、獨立審查、Q-05、RC2 整合準備、CI、隔離測試及 Depot 壓測準備。保留所有既有 Agents，不干擾其他工作，不覆寫成果。
> 每個階段更新 Ledger，提供 commit SHA、test receipts、PASS/FAIL、剩餘風險與 blocker。
> 不要因為非關鍵決定反覆停工。對可逆、已授權嘅低風險工作，自行完成並驗證。
> 最終目標係 Discord v2 可安全支援所有符合資格嘅 Rafii workspace，而唔係只限 tester。但必須真正通過 G1–G7，先能宣告 PUBLIC RELEASE GO。
> 目前狀態仍然係 NO-GO。請繼續工程工作，直到形成完整 RC2 release evidence packet，再提交需要我批准嘅 Production 操作。

**Reading, by the agent:**

1. **Capacity standard.** Accepted provisionally as the RC2 stress-test acceptance threshold, with the numbers of `RELEASE-DEFINITION-v2.md` section 4 (5,000 posts due in the same minute: median at most 12 minutes, 95th percentile at most 25, maximum at most 40; zero duplicates; zero sends after approval expiry; small tenants of at most 5 posts done within 15 minutes while another tenant has 3,000 queued). The test budget is 25 requests a second and the run must also obey Discord's real global, per-route and other limits. It is an internal benchmark for an extreme spike, not a promise to customers; a normal-load SLO is to be written. A miss on Depot is answered by optimizing requests per post, scheduling and throughput, **not** by lowering the standard; any proposal that raises the 25 requests a second ceiling is reviewed again. Scenarios that must be tested: fairness, 429, 5xx, retries, worker crash, database contention, approval expiry, cross-tenant isolation, backlog recovery.
2. **H-07.** The owner (James) is Release Captain for now, which does not mean 24/7 on-call exists. Required before public: remotely operable monitoring, alerts, stop and rollback that work with the Mac offline; alerts for backlog, delivery failures, rate-limit exhaustion, silent halt and cross-tenant security anomalies; real drill receipts; confirmed on-call hours and alert receiving channels. H-07 is not VERIFIED until then.
3. **M-03.** Read PITR, backup status, latest restorable time, RPO and RTO and the restore procedure with the authorized read-only tools; if not obtainable, give the owner the simplest dashboard screenshot steps; no change to the production database and no destructive restore test; without PITR, assess the risk and alternatives.
4. **Q-05.** Approved: A/B both-direction read and write probes, negative tests, authorization-mutation tests and mock Discord validation on RC1 and RC2 in isolated environments. The deliberate removal of authorization checks happens only in isolated fixtures or branches and never in a deployable version. **Production A/B accounts are created through the normal sign-up and sign-in flow; nothing is written into Production Auth.** Test credentials are protected, short-lived, least-privilege secrets that never reach a log. The owner opens the two accounts only after every independent test is done, with a minimal-steps sheet. The earlier plan of dashboard-created users with passwords is withdrawn (it was never used).
5. **Release order.** Dark, then private verification, then public, in principle, with `AUTH-5` split into three separate approvals (`RELEASE-DEFINITION-v2.md` section 2A): pre-promotion (local and isolated cross-tenant verification, independent code review, CI, security configuration checks), private canary (only after the owner separately approves the Production promotion; tester-only gate; real Discord objects), pre-public (real A/B cross-tenant verification, Discord function tests, capacity test, monitoring, rollback drill, all VERIFIED). Any failed gate is NO-GO. A promoted dark build never stands in for security verification, and the agent must show that the features left off have no observable regression or side effect for existing customers (`CUSTOMER-IMPACT-INVENTORY.md`, to be written). Every Production build, promotion, environment-variable change and the final full opening still needs the owner's explicit approval, item by item.
6. **H-03.** "OK 查" approves a read-only query of the existing tester workspace's Discord user, server and channel metadata, including the identifiers needed for visible and invisible channels, without tokens, message contents or other users' private data. Done (result in chat and in a private file, not in this repository). A new empty Discord server is approved for planning the fresh-customer onboarding, server-cap and permission tests. Real Discord sends use the previously approved test account and the specific approved messages, at most three; anything the existing approval does not cover (content, destination or time slot) is asked for precisely first.
7. **P0, silent halt.** The W-02 lane flag with missing rate-limit configuration must never stop sending silently: configuration validation, an explicit fail-safe, an alert, a health indication, and recovery and rollback tests. (Fixes in progress on the W-02 branch; see the status log in `RELEASE-DEFINITION-v2.md`.) A proposal to persist the Discord open configuration and the server cap in the Production project settings is to be written; **Production settings are not changed without a separate approval.**
8. **Working mode.** Continue W-02 fixes, independent review, Q-05, RC2 preparation, CI, isolated tests and Depot preparation without stopping at ordinary steps; keep every existing agent; update the ledger at each stage with commit SHA, test receipts, PASS or FAIL, remaining risks and blockers; finish a complete RC2 evidence packet and only then ask for the Production operations. The state stays NO-GO until G1 to G7 pass.

**Authorized by this reply and being carried out:** engineering, tests, fixes and independent reviews; the isolated Q-05 work above; RC2 integration preparation and exact-SHA CI of branches; the real-time capacity harness and Depot preparation; the read-only reads named in 3 and 6; written proposals.

**Still NOT authorized (each needs its own explicit approval):** any Production build or promotion; any environment-variable or project-setting change, including persisting the open gate and cap; the full opening; any write to the Production database or Auth; any restore test; raising the 25 requests a second ceiling; any real Discord message outside the earlier approval (at most three, approved account and messages); a Depot run beyond the cost ceiling approved earlier (the packet will state the cost).

## Reply 14, received 2026-10-23 about 04:50Z ("Goal-Driven Autonomous Execution")

> 芝麻開門。繼續 Rafii Discord RC2 Release Qualification，採用 Goal-Driven Autonomous Execution。
> 我授權你自主安排工程工作、選擇工具、分配 Agents、處理阻塞、驗證結果及保存證據。除真正涉及高風險或未授權操作外，不需要反覆要求我批准普通嘅 Continue、Fix、Verify 或 Run。
>
> 1. 更新 Discord 測試環境授權
> 我正式同意：如果現有 Discord Tester Server 唔足以完成隔離測試，你可以自行建立一個全新、空白、私人 Discord Server。
> 此授權包括：按實際測試需要建立 Server；建立必要嘅測試 Channels 及基本權限配置；自行決定合理嘅測試隔離結構；保留現有 Tester Server、連接、使用者及資料；將新 Server ID、測試用途及建立結果寫入私人測試紀錄。
> 不需要先向我請示，但亦不需要為咗用盡授權而建立新 Server。
> 本授權不包括發送 Discord 訊息、邀請真實用戶、授權新 Bot/App、修改現有 Production Server 或建立付費資源。上述操作若尚未獲獨立授權，仍須取得批准。
>
> 2. M-03：自主完成 Supabase 備份審計
> 目標：建立可信、可重複核實嘅 Backup/PITR Evidence，而唔係一定要我影四張截圖。
> 你可以自由選擇：Supabase MCP、Management API、已授權 Browser、Supabase CLI、其他安全、有效嘅唯讀方法。自行比較不同方法嘅可用性、效率同證據質量。
> 需要核實 PITR 啟用狀態、可還原範圍、備份有效性、RPO/RTO 及 Discord 發文重複風險。
> 如某項無法直接驗證，主動尋找等效證據或替代核實方法；不得將推論當成已驗證結果。
> 如必須由我操作，先整理成最少步驟，唔好一開始就要求截圖。
>
> 3. RC2 其餘工作繼續並行
> 保留並協調現有五個 Agents，繼續：W-02 Worker Reliability、Degraded Recovery；RC2 Capacity／Load／Fault-injection Testing；Q-05 Hosted Cross-Tenant Isolation；H-07 Monitoring、Alerting、Rollback；Customer Impact／Regression Verification。
> Agent 可以自行調整測試次序、工具及任務分配，避免重複工作、互相衝突或無必要等待。
> 可自主完成隔離環境嘅程式修改、測試、模擬、分析、證據收集同修復。
>
> 4. 安全及授權邊界
> 維持目前 NO-GO，但 NO-GO 不代表停止所有工程工作。
> 以下操作仍需另外批准：Production build、promote、deployment 或 env changes；Production DB/Auth 寫入或還原；真實 Discord 訊息發送；新增費用或付費服務；對外發佈、真實客戶影響；其他不可逆或高風險操作。
> 無須為普通唯讀查詢、可逆嘅非 Production 修復、隔離測試、既有 Agents 協調反覆請示。
>
> 5. 自主處理阻塞
> 遇到問題時：1. 判斷係工具限制、權限問題、技術問題定係真正需要授權。2. 主動尋找安全替代方法。3. 可以並行處理其他獨立任務。4. 只有超出授權範圍，或所有合理替代方法失敗，先向我提出阻塞。5. 不得繞過身份驗證、權限或安全保護。
>
> 6. 交付標準
> 沿用現有 Authorization Ledger、Release Definition、Evidence Pack。只更新有實際變化嘅內容，避免重複產生文件。
> 提供：已完成及已驗證結果；未完成項目與證據缺口；可繼續自動修復嘅問題；真正需要我授權嘅事項；更新檔案路徑與 commit SHA；RC2 Release Readiness 結論。
> 核心原則：最大化安全有效嘅自主執行，最小化人手介入；不要以流程取代成果，也不要以效率為理由突破授權。
> 繼續工作，直到所有授權範圍內可完成嘅任務均有驗證結果，再報告真正阻塞 Release 嘅問題。

**Reading, by the agent:**

1. **Working mode.** The agent decides the order of work, the tools and the agent assignments, handles blockers itself, verifies, and saves evidence. Ordinary continue, fix, verify and run steps (read-only queries, reversible non-Production fixes, isolated tests, coordination of the existing agents) need no further approval. The state stays NO-GO. The agent reports when everything inside this authorization has a verified result, then lists what really blocks the release.
2. **Discord test server.** If the existing tester server is not enough for the isolated tests, the agent may create one new, blank, private Discord server, with the test channels and basic permissions it needs, keep the existing tester server, connection, users and data untouched, and write the new server id, purpose and result to the **private** test record (not this public repository). The agent does not create a server just to use the permission. Excluded and still needing a separate approval: sending any Discord message, inviting real users, authorizing a new bot or app, changing the existing Production server, creating any paid resource.
3. **M-03.** Establish credible, repeatable backup and PITR evidence without defaulting to four screenshots: any safe read-only method (Supabase MCP, Management API, an authorized browser, the CLI, other); compare the methods; verify PITR state, restorable range, backup validity, RPO and RTO, and the risk of duplicate Discord posts after a restore; where something cannot be verified directly, find equivalent evidence or an alternative check and **never record an inference as verified**; if the owner must act, the minimal steps first, no screenshot request up front.
4. **RC2 work in parallel.** The existing agents (W-02 reliability and degraded recovery; RC2 capacity, load and fault injection; Q-05 hosted cross-tenant isolation; H-07 monitoring, alerting and rollback; customer impact and regression) continue and may re-order their work to avoid duplication, conflicts and idle waiting. The agent may change code in isolated environments, simulate, analyse, collect evidence and repair.
5. **Boundaries unchanged.** Still needing a separate approval: any Production build, promotion, deployment or environment change; any Production database or Auth write or restore; any real Discord message; any new cost or paid service; any external publication or real customer impact; any other irreversible or high-risk operation. Blockers: classify (tool limit, permission, technical, or truly needing authorization), look for a safe alternative, work on other independent tasks in parallel, raise a blocker only when it is outside the authorization or every reasonable alternative failed, and **never bypass authentication, permissions or security protections**.
6. **Deliverable.** Reuse the ledger, the release definition and the evidence pack; update only what actually changed; report what is completed and verified, what is unfinished and the evidence gaps, what can still be repaired automatically, what truly needs the owner's authorization, the updated paths and commit SHAs, and an RC2 release-readiness conclusion.

**What this reply does not change:** reply 13 stays in force (capacity standard, release order 5a/5b/5c, Q-05 accounts through the normal sign-up flow only, the three-message limit for real sends, no Production setting changes). It supersedes only the part of reply 13 that said the owner would be asked for four screenshots for M-03 and for a new empty Discord server: the agent tries to establish both itself first.

## Reply 15, received 2026-10-23 about 06:05Z (the owner titled it "Reply 14 — RC2 Scope Expansion + H-07 On-call Decision")

> 我決定：
>
> A. 將 Sender Name 功能一併納入 RC2
>
> 正式批准將 codex/discord-sender-name-20261023（commit 97b3956a）納入 RC2 候選範圍。
>
> 我希望 Rafii Public Release 第一版已經支援顧客自訂 Discord 發送者名稱，包括 Webhook Sender Name 及適用情況下的 Bot Nickname。
>
> 請完成以下工作：
>
> 1. 將現有分支安全整合到 RC2 candidate，保留原有功能，不覆寫未合併工作。
> 2. 重新執行 Security Review、Code Review、A/B Verification、Multi-tenant Isolation、Capacity Test 及 CI。
> 3. Webhook 使用每次發送的 Sender Name Override，避免跨客戶名稱污染。
> 4. Bot Nickname 必須遵守 Guild-level 限制，只有具備相應權限的 Server 管理員可以授權修改；不得讓不同 Rafii 用戶互相覆蓋名稱。
> 5. 驗證不同 Workspace、Guild、Channel、Webhook 的名稱隔離、權限、並行發送及回退行為。
> 6. 同時測試 Sender Name ON/OFF、Bot/Webhook 兩種模式、5,000 筆排程負載及 W-02 兼容性。
> 7. 提供 UI 驗收，讓用戶設定名稱、預覽 Discord 實際顯示效果，並清楚知道何時無法修改 Bot 暱稱。
>
> RC2 Freeze 可以合理延後，但不可以因趕進度而跳過驗收。
>
> 如 Bot Nickname 存在無法安全解決的跨租戶衝突，必須隔離該能力；Webhook 自訂發送者名稱仍應優先完成。所有例外須清楚記錄，不得虛報整項功能通過。
>
> B. H-07 — On-call Coverage and Alert Channels
>
> 我選擇以下正式運作政策：
>
> On-call Coverage
>
> * P0 Critical：24/7，包括週末及假期。
> * 日常事故處理：每日 09:00–23:00，America/New_York 時區。
> * 非日常處理時段：維持自動監控，P0 由當值人員處理。
> * 必須指定 Primary On-call 與 Backup On-call，並確保有人實際承接警報。
>
> Alert Channels
>
> * Push Notification：主要即時警報渠道。
> * Email：同步記錄事故、狀態及處理結果。
> * Phone Call：P0 Critical 緊急升級渠道。
>
> Escalation Policy
>
> * P0：立即 Push + Email；5 分鐘未確認即電話升級，10 分鐘未確認轉 Backup。
> * P1：Push + Email，值班時間內 15 分鐘確認。
> * P2：Email / Dashboard，按正常維護流程處理。
> * 必須支援去重、警報抑制、事故確認、升級及 Audit Trail。
>
> 以上係正式採用的目標政策，唔代表目前已完成配置。
>
> 請先核實實際值班人員、通知目的地、手機 Push、電話渠道及端到端測試。只有排班、路由、送達、確認與升級測試全部成功，H-07 先可以標記 VERIFIED。
>
> 如欠缺真正 24/7 P0 人手，必須標記 BLOCKED 並提出可執行替代安排，不得紙面通過。
>
> Execution Authorization
>
> 可以自主進行上述非 Production 工程、整合、審查及隔離測試，盡量並行推進，唔需要每完成一項就停下來等我。
>
> 但今次批准不包括 Production Deployment、正式公開發文、變更 Production 環境變數、付費服務或正式 Public Release。
>
> 完成後提供更新版 RC2 Scope、H-07 Evidence、測試結果、Commit SHA、剩餘 Blockers，以及最後 GO/NO-GO 建議。
>
> 目標：RC2 包含安全、可靠、真正支援多客戶的 Custom Sender Name，並具備可驗證的 Incident Response 機制。

**Reading, by the agent:**

1. **Scope.** RC2 now contains the customer-chosen Discord sender name: the incoming-webhook sender name (applied per send, so a name can never leak from one customer to another) and, where it applies, the bot's per-server nickname. The upstream commit is `97b3956a` on `codex/discord-sender-name-20261023` (built on RC1 `2a5a523d`; it merges cleanly with the W-02 head). It is integrated into the RC2 line without overwriting unmerged work and every gate applies to it as to the rest of RC2: independent security review and code review, the A/B probe with sender-name cases, multi-tenant isolation (workspace, server, channel, webhook), concurrent sends and fallback behaviour, sender name ON and OFF, bot and webhook modes, the 5,000-post load and W-02 compatibility, exact-SHA CI, and an interface acceptance (set the name, preview how Discord shows it, a clear statement of when the bot nickname cannot be changed). **The freeze moves; no acceptance is skipped.** If the bot nickname has a cross-tenant conflict that cannot be solved safely it is isolated (switched off) and the webhook sender name is finished first; every exception is recorded and the feature is not reported as passing as a whole.
2. **H-07 policy adopted as the target, not as a fact.** P0 Critical 24/7 including weekends and holidays; routine incident handling every day 09:00 to 23:00 America/New_York; outside those hours automatic monitoring continues and P0 goes to the person on call; a Primary and a Backup on-call must be named and someone must actually receive the alerts. Channels: push (main, immediate), e-mail (record of incident, status and outcome), phone call (P0 escalation). P0: push and e-mail at once, phone after 5 minutes without acknowledgement, Backup after 10 minutes. P1: push and e-mail, acknowledge within 15 minutes during duty hours. P2: e-mail or dashboard, normal maintenance. Deduplication, suppression, acknowledgement, escalation and an audit trail are required. **H-07 becomes VERIFIED only when the roster, routing, delivery, acknowledgement and escalation tests all succeed** against real people and real destinations. With no real 24/7 P0 cover it is marked BLOCKED with executable alternatives.
3. **Working mode.** Non-Production engineering, integration, review and isolated tests, in parallel, without stopping at each item. Final package: updated RC2 scope, H-07 evidence, test results, commit SHAs, remaining blockers and a GO/NO-GO recommendation.

**Authorized by this reply and being carried out:** the sender-name integration, fixes, tests, UI and reviews described above (non-Production); building the alert pipeline (routing, deduplication, suppression, acknowledgement, escalation, audit trail) and its isolated end-to-end tests with fake providers; the written H-07 evidence and alternatives; everything in replies 12 to 14 that is still in progress.

**Still NOT authorized (each needs its own explicit approval):** any Production build, promotion or deployment; any change of a Production environment variable or project setting (so the alert and call settings, the lane flags and the gate cannot be set); any Production database or Auth write, including a migration that the alert pipeline or the sender name may need; any paid service (a phone-call provider, an on-call or paging service, more database compute); any real Discord message outside the earlier approval; any public announcement; the Public Release. Real delivery tests of push, e-mail and phone call go to the owner's real destinations through Production services, so they are Production operations and will be listed in Packet 3.

**What the agent needs from the owner for H-07 and cannot invent:** the names of the Primary and the Backup on-call, and for each of them the e-mail address, the mobile number for calls and the device for push; whether a phone-call provider is already available; and whether a person really covers P0 at night and on weekends. Until then H-07 stays NOT VERIFIED (BLOCKED if no 24/7 P0 person exists).

## Reply 16, received 2026-10-28 about 14:17Z ("I approve all")

Context: the owner had asked for a plain-language explanation, then for it in Traditional Chinese. The agent answered with the state of the release, three real problems and the list of decisions it needs, pointing to the one-page brief `OWNER-BRIEF-20261028.md`, and said it would not deploy, change settings, send real Discord messages or spend money without approval for each item. The owner then wrote, verbatim:

> I approve all

**Reading, by the agent (stated back to the owner in the same turn so that it can be corrected):**

1. **Approved: the six decisions in the brief, as recommended there.** (1) D-12: no candidate that contains Discord RC1 (`2a5a523d`), including `claude/mastodon-scale-on-live-20261027` and the staged D1, is promoted unless it also carries the RC2 shared-path fixes; the Mastodon release uses the isolated dependency hotfix (PR #225) instead. (2) D-2 option (1): the person's own user-bearer calls (the grant check `GET /oauth2/@me`) are charged to a separate bearer budget while bot-token requests stay at 25 a second. (3) D-16: "25 requests a second" is read as the coordinator's own admission line (never more than 25 stamps in any sliding second); arrival at Discord is reported, not failed, and must stay far under Discord's real limit of 50; the slot guard goes from 0.1 s to 0.05 s. (4) D-4: a workspace may have at most 300 approved Discord posts scheduled in any one hour; beyond that the post is refused with a clear message instead of queued. (5) D-14: the coordinator keeps read records for 1 hour and publish records for 48 hours. (6) D-1 and D-11: sender names ship built, reviewed and OFF (nothing customer-visible at the opening); the seven customer-visible behaviours of the security fixes stay as built.
2. **Not covered by "approve all" (each still needs its own explicit approval, as in replies 13, 14 and 15):** any Production build, promotion or deployment; any change of a Production environment variable or project setting (including the lane-seconds setting `POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS`, the sender-name switches, the lane and gate settings, the worker-budget variables of D-5); any real Discord message; any paid service or machine (Depot); any Production database write (migrations 140, 141 and the retention index are written, not applied); any change of a customer-facing promise (D-3). Packet 3 will list these item by item.
3. **Not covered because they were not in the brief:** D-3 (the normal-load promise), D-5 (WB-1 and SC-1, shared-path settings that change what existing customers get), D-6 to D-10. They stay open and will be asked before the freeze.
4. **Data the owner still has to provide (an approval cannot supply it):** primary and backup on-call names, e-mail addresses, mobile numbers, which phones receive push, a phone channel and whether night cover exists (H-07); the one sentence on Supabase backups (M-03); public and private test channel ids and a time slot (tester session); two throw-away accounts A and B with short-lived sign-in codes (hosted isolation run).
5. **If the owner meant a wider "all"** (for example the Production operations), the owner must say so item by item; the agent will not infer it.

**Carried out from this reply (non-Production engineering):** guard 0.05 s with its pin test, the bearer budget, retention with the 1 h / 48 h windows, the per-workspace per-hour ceiling of 300 with its stable error code and UI text, a hosted measurement with the lane set to about 56 s, then the combined measurement; the alerts round 3 reads the new fields.

## Reply 17, received 2026-10-28 about 14:28Z ("Approve all these")

Context: after reply 16 the agent had listed what "approve all" did not cover. The owner pasted those three bullets (the agent's own wording, in Traditional Chinese) and wrote, verbatim:

> 任何 Production 操作：建置、升級、改環境變數（包括把 lane 工作時間調到約 56 秒的設定）、真實 Discord 訊息、付費服務，以及套用資料庫遷移。這些仍然會在 Packet 3 逐項問你。你之前定的規則也是逐項批准，我不會自行擴大解讀。
> 簡報裡沒有列出的項目，例如對客戶的正常負載承諾（D-3）、共用路徑設定（D-5）。它們在凍結前會再問你。
> 需要由你提供的資料：值班人員姓名、電郵、手機、推送與電話渠道，Supabase 備份那一句說明，測試頻道編號與時段，兩個測試帳戶。批准本身無法替你提供這些。
>
> Approve all these

**Reading, by the agent (stated back to the owner in the same turn so that it can be corrected):**

1. **Approved in category: the Production operations of Packet 3** (build, promotion, project-variable changes including the lane-seconds setting of about 56 s, real Discord messages, paid services, applying database migrations), as its rows define them, **once each row's prerequisites hold**. This does not waive any gate: G1 to G7 still need their evidence, a failing gate stays NO-GO, and an approved operation never turns a gate into a pass. The GitHub Environment tap on each build run (the workflow waits for the owner's approval of the named request commit) remains the owner's technical gate; the agent cannot do it.
2. **Execution rules the agent adopts inside the approval:** (a) each operation is done exactly as its Packet 3 row says (frozen SHA, variable names and values, rollback target `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`, read-back receipts), with prerequisites checked and recorded before and after; (b) before a promotion the agent sends the owner a short notice naming the SHA, the deployment id and the evidence, and proceeds when the prerequisites hold (row 7); (c) **the full opening (row 15: promote D2' and make the open setting durable) additionally waits for the owner's explicit word "GO" after the final evidence report**, because it is the step that changes what real customers get and the evidence will be new to the owner; the owner may waive this by replying "GO without asking"; (d) paid services: the agent states the price before first use and does not exceed US$50 for one run or US$150 in total without telling the owner first; the owner has to put any access token into the GitHub Environment (the agent cannot); (e) real Discord messages only in the owner's own test server and channels, at most the counts of Packet 3 rows 9 and 9b, with the text approved by the owner at that moment as in reply 6; no customer server, no public announcement; (f) database migrations: the retention index (142) before the first promotion; 140 and 141 only when the on-call engine is wired and the "before wiring" findings of the H-07 review are closed; each with a read-back and a rollback statement.
3. **D-3 and D-5 are approved as recommended:** the promised normal load is **100 posts a minute** (250 stays a measured capacity figure); WB-1: remove `POSTRIFF_WORKER_MAX_JOBS=25` and `POSTRIFF_WORKER_MAX_SECONDS=40` at build preparation, after a read-only check that no other candidate of the project depends on them; SC-1: strip UI-8 (Facebook/Business Profile picker wording) and UI-21 (LinkedIn receipt text) for exact parity, and consciously accept the capped "Save as draft" (UI-12/API-9), API-8 and UI-10 (they are entangled with Discord fixes or too large to strip safely near the freeze).
4. **Data the owner still has to provide** (an approval cannot supply it): on-call names, e-mail addresses, mobile numbers, push devices and a phone channel (H-07); the Supabase backups sentence (M-03); public and private test channel ids and a time slot; two throw-away accounts A and B with short-lived sign-in codes; any paid-service token (for example Depot) in the GitHub Environment; for the real-database capacity run the connection secret in the GitHub Environment.
5. **Still open, not covered:** D-6 to D-10 (D-7 lower initial cap, D-8 restore procedure, D-9 real-database capacity, D-10 end items) and the owner's reading of the sender-name opening (D-1 default stays OFF).


## Reply 18, received 2026-10-28 about 16:56Z (after the schedule question)

Context: the owner had asked, verbatim: "所以你仲需要做啲咩工作？幾時先可以完成？幾時先可以 make sure 個 Discord 系 in hype, in production？大概仲要幾耐？" (a question, not an authorization). The agent answered with a four-phase estimate (fastest about 5 days, likely 8 to 12 days, longer if the capacity gate needs a redesign or the weekly usage limit is hit again) and the list of owner inputs. The owner then wrote, verbatim:

> 你要用另一個方式給我。你而家太浪費 credits 了。你要用一個更加 intelligent、最快速嘅方式將 Discord put 到 production。Make sure 所有用戶都可以 connect 到佢哋嘅 account。你而家唔好嘥咁多時間去 test。

**Reading, by the agent (stated back to the owner in the same turn so that it can be corrected):**

1. **The priority changed: credits and calendar time now outrank further assurance work.** The goal is unchanged: every eligible new customer can connect their Discord account and use the Discord features on the formal release.
2. **What this authorizes without asking again (inside the existing delegation, reply 14):** stop the running agents after their current step; cancel work that only raises assurance beyond the launch need (the lock round-trip cuts, the FOR SHARE design note, 16 loops, the real-database staging run, the `release` capacity profile and S2 sizes, the sender-name hosted qualification and the Q-05 sender-name delta, further on-call engine work, repeated delta reviews); keep at most one or two agents at a time and use cheaper models for mechanical steps; do the integration, freeze and CI personally.
3. **What it does not authorize:** it does not waive the owner's written gates. The two gates whose written standard cannot be met cheaply, G5 (5,000 posts due in one minute, median 12 / p95 25 / max 40 minutes) and G6's H-07 (named on-call roster, confirmed channels, drill receipts), need the owner's explicit word to be relaxed; they are put to the owner as D-18 and D-19 with a recommendation. The other gates stay but in their cheapest honest form: ONE consolidated independent final-SHA security review (G2), exact-SHA CI and the offline secret scan (G1), the tester session (G3), ONE hosted A/B isolation run with the already reviewed probe pair at `0ddb144e` (G4), and the fresh-customer connect test after the opening (G7). Consent, tenant isolation, the rollback target and the kill switch are not traded for speed. Every Production operation still follows reply 17's guardrails (the owner's GitHub taps, notice before promotion, the owner's explicit GO before the full opening).
4. **Plan and estimate:** `LEAN-PLAN-20261028.md`.

**Carried out from this reply:** the limiter, capacity and Q-05 agents were told to wrap up within the hour (limiter: finish the web multi-read item and a small observability commit, then one short report; capacity: collect the running hosted cells into one table, no new runs; Q-05: stop and report what is done); the safety-net check-in was rewritten for the lean plan.
