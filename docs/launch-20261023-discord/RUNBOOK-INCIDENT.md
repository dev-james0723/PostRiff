# RUNBOOK-INCIDENT: Discord

Read `RUNBOOK-LAUNCH.md` section 0 first. Rules that never bend: stop first and investigate second; never resend a delivery whose outcome is uncertain; never print, paste or commit a secret; evidence is counts, states and ids you own, never message text or customer content; report to the owner immediately.

## 1. The abort ladder

Use the first step that is enough. Steps 1 and 2 are reversible in seconds and are pre-authorised by AUTH-7 (Approval Packet 1, row 12).

| Step | Action | Effect | Speed | Undo |
|---|---|---|---|---|
| 1 | **Close the gate**: `vercel promote <D1 url or id> --scope team_PgXY5VdAYKcsv0RLoDPHscNq` (the dark twin of the same SHA) | No new Discord connections for workspaces outside the allowlist. Existing connections, queued posts, reads and the worker keep running. A connect already in progress can still complete. | seconds | `vercel promote <D2>` |
| 2 | **Stop every Discord request**: `UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy'` (the application-wide row that every reservation touches) | Every reservation raises "request coordination unavailable" before any HTTP request is built: connect, destination lists, reads and posts all stop with nothing sent. Queued posts wait; they are not lost and not resent. A person's Discord login token that expires while the hold lasts is NOT revoked: the refresh is refused before any request and tried again later (`tests/test_discord_rate_denial_refresh.py`; this holds only on a build that contains commit `29bc8ab2` or later, so never use this step on an earlier build of this project). | seconds | `... SET manual_hold = false WHERE kind = 'policy'`, then wait one budget window. The code path is covered by `test_an_operator_hold_on_the_application_scope_stops_every_route_and_can_be_lifted`; the SQL itself is not rehearsed on a copy. |
| 3 | **Kill switch**: build a third twin of the same SHA with `--env POSTRIFF_OAUTH_DISCORD_DISABLED=true --env POSTRIFF_DISCORD_CONNECT_WORKSPACES=` and promote it | Connect start, callback, destinations and publish refuse. With Discord paused (this kill switch, a provider flag unset, or authorization off) a post is a wait, not a hold: the lane stops before any claim (stoppedBy discord_paused), the minute tick leaves Discord alone, posts stay scheduled, nothing is held or demoted, no destination goes to verification_required, and no customer has to authorize again (W-02 K1; AS-BUILT 'A paused Discord is a wait'); lifting the switch resumes the same posts. Existing grants stay stored. Composition with the gate is tested (`KillSwitch` in `tests/test_discord_launch_gate.py`). | one build (about 3 minutes) plus promote | promote D1 or D2 |
| 4 | **Roll back the code** to `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` (live before the RC) | Removes the whole Discord v2 code from production. Only for a code defect, and only after in-flight Discord jobs are drained or held (monitoring Q7 shows none in a non-terminal state), because the old build does not know the v2 job manifests. | seconds to promote, but think first | promote the RC twin |

After any step: tell the owner at once, record the time, the trigger and the step in the ledger, and keep the evidence (below).

## 2. Triggers and first action

Stop and report immediately on any of these. "Q" numbers are statements in `monitoring.sql`.

| Trigger | How you see it | First action |
|---|---|---|
| Cross-tenant exposure of any kind | report, test, log | step 2, then step 1; privacy path (section 4.H) |
| A secret appears in a log, diff or output | review, scanner | step 2; rotate the secret (owner only); privacy path |
| Any unexpected real Discord send (wrong server, channel or text, or no approval) | report, Q1 publishes with no matching approval | step 2; do not delete messages without the owner's decision |
| Three or more uncertain sends in 15 minutes | Q5 | step 2; reconcile by read-back only; never resend |
| Cloudflare 1015 block or more than 1,000 invalid requests in 10 minutes | Q2, HTML 429 in the coordinator state (Q3 manual holds) | step 1, then section 4.B |
| A rate circuit (global, policy, invalid or credential) open for more than 5 minutes | Q3 `open_over_5_min` | check Discord's status page; do nothing destructive; section 4.A |
| Server errors above 2 percent of Discord responses for 5 minutes | Q4 | section 4.A |
| Rate policy expires within 24 hours | Q6 | section 4.C; treat as the next build/promote cycle, start it now |
| A duplicate OAuth code exchange | two Discord token POSTs for one transaction in the logs | step 1; section 4.I |
| The deployed files do not match the frozen SHA | fingerprint mismatch | step 1, then promote the verified twin; section 4.I |
| Stored capability rows changing unexpectedly | Q11 against the ledger baseline | step 1; section 4.I |
| Many accounts each holding three installation starts while few installs complete (a real customer is told there is no room) | Q9 `installs_in_flight` above 300 for 10 minutes, Q13, Q8 | step 1; the holds expire by themselves after ten minutes; no data is touched |

## 3. Evidence to keep (aggregate only)

Time of detection and of each action (UTC); the deployment ID serving `rafii.io` before and after; the monitoring results as counts; the job states from Q7; the coordinator rows from Q3; the Vercel runtime-log line counts by status. Do not copy message text, Discord ids, tokens or customer names into the repository or the chat.

## 4. Scenarios

### 4.A Discord outage or sustained 5xx
Nothing is wrong on our side. The coordinator opens a circuit after three consecutive server errors on a route (30 seconds in the policy) and posts wait. Customers see queued items as delayed, not failed. Do not roll back. Tell the owner, post the customer notice (section 5), and watch Discord's status page. Uncertain deliveries stay uncertain; they are reconciled by read-back after recovery.

### 4.B Cloudflare 1015 or an IP restriction
Discord restricts an IP that sends too many invalid requests (more than 10,000 in 10 minutes; Vercel egress addresses are shared with other customers, so the budget is not ours alone). Symptoms: HTML bodies with status 429, no usable retry hint. The coordinator turns each such response into an operator hold on that route (`test_a_ban_page_holds_the_route_for_operator_review`) and does not retry; the policy's invalid-request budget (2,000 per 10 minutes) is meant to stop us well before the limit. Steps: close the gate (step 1); read Q2 and Q3; do not clear any hold until the restriction is over; to check, wait and let the owner decide, never probe from here. Clearing holds is `UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE manual_hold` only with the owner's written word. If bans repeat, the owner decides on a static egress address or a proxy (paid; W-05). A person's login-token refresh that Discord answers with 429 is not revoked on this candidate (the claim is freed and it is tried later); every other answer to that refresh still revokes, because the rotating token may be spent.

### 4.C Rate policy expired or about to expire
Symptom: every Discord request fails with "request coordination unavailable" and no request is sent (HTTP 503). Nothing is lost, and no connection is revoked by it on this candidate (a refresh of a person's login token that is refused this way is retried later; on builds without commit `29bc8ab2` the same refusal revoked the identity and its servers, which is why the policy renewal date matters even more there). Steps: generate a new policy with `scripts/discord_rate_policy.py generate` and check it with `check`; set `POSTRIFF_DISCORD_RATE_POLICY` (owner or approved batch); then a new build of the current SHA and `vercel promote`, because env applies to new builds only. Keep the renew-by date in a calendar (7 days before expiry). Never extend validity beyond 31 days: the parser rejects it.

### 4.D Bot token compromised (owner only; affects every customer)
The shared bot is one identity for all customers. Order: (1) step 2, so a 401 storm does not burn the invalid-request budget; (2) the owner resets the token in the Developer Portal (Bot > Reset Token); the old token is invalid at once; (3) the owner updates `POSTRIFF_DISCORD_BOT_TOKEN`; the agent never touches it; (4) new build of the current SHA and `vercel promote` (the credential fingerprint is new, so the old 401 hold does not carry over); (5) lift the hold (step 2 undo); (6) tester check with one read-only action; (7) customer notice. Installs stay in place: they belong to the application, not to the token. Post-incident: how it leaked, where it appeared, and the next rotation date.

### 4.E Client secret compromised (owner only)
Portal > OAuth2 > Reset Secret. Code exchange fails until `POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET` is updated and a new build is promoted. Existing grants are untouched. Close the gate first so customers are not sent into a failing flow.

### 4.F Wrong destination, wrong text, or a send without approval
Step 2 immediately. Identify the job by id from the ledger, not by text. Check the frozen manifest digest against the approval (`discord/authorization.py` binds destination, text, mentions and expiry). Do not delete the Discord message unless the owner asks. Root cause before lifting the hold.

### 4.G Uncertain deliveries
State `uncertain` means the request may have reached Discord and the outcome is not proven. The worker never reposts. Two kinds (final review, 2026-10-28):

1. **With a message id** (Discord answered and the read-back could not confirm yet): the worker keeps reading back; do nothing. (An image post used to stay here for ever; since `a2d7055e` it verifies when Discord returns the approved file's name and size.)
2. **Without a message id** (the request timed out, the connection was reset, or the function died after Discord may have accepted it): nothing can be read back by id. Look in the destination channel. If the post is there, leave the job: it stays `uncertain` and blocks approving the same text again (change the text slightly to post again). If it is not there, the customer approves a new post. There is no tool to resolve these yet (follow-up).

Three in 15 minutes is a stop condition. Do not edit job rows by hand.

### 4.H Cross-tenant exposure, a secret in a log, or any suspected data breach
Step 2 and step 1; preserve evidence; the owner decides on notification duties (the privacy notice and Discord's developer terms both matter; there is no automated path to tell Discord, so the owner uses Discord developer support). If a database restore is considered it is the owner's decision with the PITR facts from M-03; restoring loses everything after the restore point, including credentials and OAuth state.

### 4.I Duplicate code exchange, provenance mismatch, unexpected capability changes
Step 1. Compare the serving deployment with the frozen SHA (fingerprint). For a duplicate exchange look at the transaction outcome (`exchange_started`, `exchanged`) in the database, counts only; a one-use code must not be exchanged twice. Reopen only after the cause is found and tested.

### 4.J Database restore (point in time or backup)
A restore in place brings back jobs as they were at the restore point, including jobs that were already sent, so the lane would send them again. The restore-proof stop (a Discord-paused build kept ready, Packet 3 row 12b) is not built for the opening. Before any restore: set the operator hold (step 2 of the abort ladder) and keep it set; tell the owner in plain words that Discord stays paused until the jobs due since the restore point have been compared with the destination channels (counts from the health snapshot, then the channels themselves); lift the hold only after that. This is slow by design: a restore is the last resort, and the owner decides it with the PITR facts from M-03.

### 4.K After a Discord outage
A post that was due while Discord answered with errors or timeouts for more than about 13 seconds is marked `failed` with 'create a new exact approval': nothing was sent. The customer approves it again once Discord is back. No operator action is needed beyond the customer notice below if many customers are affected. (Known limit RA-2 of the final review; the follow-up release lets a post wait for the outage instead.)

## 5. Customer notices (short; adapt, do not promise dates)

English: "Discord connections are temporarily unavailable while we fix an issue. Nothing was posted that you did not approve, and your connected servers are safe. We will update this notice when connecting works again."

繁體中文：「Discord 連接暫時無法使用，我們正在處理。你沒有批准的內容不會被發佈，已連接的伺服器也安全。恢復後我們會更新此通知。」

简体中文：“Discord 连接暂时无法使用，我们正在处理。你没有批准的内容不会被发布，已连接的服务器也是安全的。恢复后我们会更新此通知。”

Not open yet (fallback F-02): use the product copy already shipped in the connect sheet ("Discord isn't open to new connections for this workspace yet. Connections you already have keep working." and its Chinese versions).

## 6. After the incident

Write a short entry in the ledger (what happened, when, the step taken, counts), lift holds only on the owner's word, record which monitors fired late or not at all, and add a regression test for the cause before the next build.
