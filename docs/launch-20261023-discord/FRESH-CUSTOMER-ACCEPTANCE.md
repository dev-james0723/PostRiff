# FRESH-CUSTOMER ACCEPTANCE (gate G7) and its receipt, with the real-flow session (gate G3)

Written 2026-10-23 about 03:57Z for `RELEASE-DEFINITION-v2.md`. **Release status: NO-GO.** This repository is public: the receipt below is filled with states and counts only, never with workspace ids, e-mail addresses, Discord ids, tokens or message text. Real values live in a private copy.

## 1. Two sessions, in this order

| Gate | When | Where | Who | What it proves |
|---|---|---|---|---|
| **G3 real flow** | before the opening | the dark build of the final SHA, `rafii.io` serving it, connect gate limited to named workspaces (the tester workspace, plus the Q-05 accounts A and B) | owner + agent | the real Discord flow works once, with the approved tester account and approved content: `TESTER-SESSION-SCRIPT.md` steps 2 to 7 (consent, destination, immediate publish, schedule and cancel, revoke and reconnect, permission failure). Step 8 (the old read-only isolation spot check) is replaced by the Q-05 probe |
| **G7 fresh customer** | right after the opening | the open build of the same final SHA, gate `*`, cap 10,000 | owner + agent | a brand-new ordinary workspace with no Discord history and **no allowlist anywhere** connects and uses every Discord feature of this release |

G3 comes first so the first real Discord flow never happens on an opened production. G7 cannot happen earlier: until the open build serves `rafii.io`, a new workspace is refused by design.

## 2. G7 preconditions (the agent checks them before the owner joins)

| # | Check | How | Expected |
|---|---|---|---|
| 1 | Serving build | alias read-back for `rafii.io`; `/api/health` `sourceRevision` | the open build's deployment id; the final SHA |
| 2 | Open setting | the build request commit and its run log (the value `*`, the cap line, the reviewed flag are not secrets); the connect page for workspace F | `POSTRIFF_DISCORD_CONNECT_WORKSPACES=*`, cap 10,000, reviewed flag on; F's catalog entry reads open ("open to all") |
| 3 | Rollback ready | the dark twin and the previous live build still READY; the stop method of `RELEASE-DEFINITION-v2.md` section 7 rehearsed once | promote-back path known; coordinator hold statement prepared |
| 4 | Baseline | `monitoring.sql` Q3, Q5, Q6, Q7, Q9, Q10, Q11 | no in-flight installs, no open circuits, no uncertain sends, rate policy has more than 14 days left, servers used vs 10,000 recorded; the owner compares the Developer Portal's own server count |
| 5 | Account F | the owner signs up through the normal sign-up page; the agent only reads afterwards | a new workspace with zero Discord rows; no list was edited anywhere (with `*` there is no list) |
| 6 | Discord side | the owner | the approved tester Discord account; **a new, empty Discord server S2** (free, one minute) where the owner has Manage Server, with one public channel (and, optional, one private channel the bot cannot see). A new server exercises the path that takes a cap slot; reusing the tester server would take the "already known" path |

## 3. G7 steps

| # | Item | Owner does | Agent verifies afterwards (own-workspace read-backs, counts and states only) | Pass when |
|---|---|---|---|---|
| F1 | Entry | F opens Channels and Discord | catalog entry `discordAccess` = open, reason "open to all"; zero Discord rows for F | the Connect button works; no "not open yet" wording |
| F2 | Connect, PRD A08 | Connect Discord, first consent (profile), pick S2, second consent (add the bot), return to Rafii | two OAuth transactions `exchanged`; one identity link; one credential row for (F, S2); in-flight count back to baseline; servers used +1 | back in Rafii, connected, no error |
| F3 | Destination | authorize the public channel; look for the private one | exactly one destination; the private channel absent or refused | only the public channel is authorized |
| F4 | Publish now, PRD A09 | write the short test post, check the exact text, sender, channel and time, approve, publish now (**message 1**) | one job `verified` with a provider reference; the digest of the approved text equals the stored digest; coordinator counters show about six requests for the post | one message appears once, with the approved text |
| F5 | Schedule | schedule a post at least five minutes ahead and do nothing (**message 2**) | the cron sends it unattended; the read-back verifies; lateness recorded against the standard; no duplicate | one message appears, on time within the standard |
| F6 | Cancel or pause | schedule another post and cancel it before it is due; if the product offers pause for the item, pause and resume it; the agent notes exactly what the product offers (in the code, "pause" belongs to automations; a single post is cancelled) | job `cancelled` (paused and resumed states if offered); nothing sent; no retry | no message appears |
| F7 | Reconnect, PRD A12 | remove Rafii's bot from S2 in Discord; try to publish; then reconnect in Rafii | the next job is `held` with a reconnect message and there is no retry storm (Q1 flat, Q3 clean); after the reconnect the credential generation moved on and a publish is allowed again | held, then restored |
| F8 | Disconnect | disconnect S2 in Rafii | the credential is revoked in Rafii; a publish is refused; nothing sent. The shared bot stays in S2 by design (the owner may remove it); the server still counts toward the cap, by design | refused, no message |
| F9 | Isolation spot check | from F, open the tester workspace's connection by its address | 403 or 404, no data (the real evidence is the Q-05 receipt) | denied |

**Message budget.** F4 and F5 use two real messages with text the owner approves at that moment. G3 on the dark build has its own three-message allowance (`TESTER-SESSION-SCRIPT.md`). The owner's reply 12 says real sends reuse the account and content already explicitly approved; the extra messages of G7 are therefore **asked for in Packet 3**, not assumed. A failed send is never retried; a fourth message in one session needs a new yes.

## 4. Abort and rollback (works with the Mac offline)

Triggers are in `RUNBOOK-INCIDENT.md`. In order: (1) set the operator hold on the shared request coordinator (stops every Discord request in seconds; statement prepared in the runbook); (2) promote the dark twin (closes new connections) or the previous live build through the Vercel API or the Vercel dashboard on a phone; (3) tell the owner. An abort is a NO-GO for the full opening: record the failure, fix it on a new frozen SHA, and go through the packet again.

## 5. Receipt template (filed in `RC-RECEIPT.md`, states and counts only)

| Field | Value |
|---|---|
| Production URL | |
| Commit SHA (final) | |
| Deployment ID, ready state | |
| Open setting: name, value, where it is set, evidence | `POSTRIFF_DISCORD_CONNECT_WORKSPACES`, `*`, build request run and commit, F1 read-back |
| Server cap, servers used before and after | 10,000, |
| Reviewed flag | |
| Build run, approver | |
| G3 receipt, Q-05 receipt, capacity receipt (ids) | |
| F1 to F9: time, status, evidence | |
| Cost observed, if any | |
| Rollback target (deployment id) and the stop method rehearsed (date) | |
| Release Captain sign-off | |

A step that was not run is written NOT RUN, never PASS. CI green, a READY build or deployed code are not the receipt.
