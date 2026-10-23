# Tester session script (X-02 to X-06, about 20 minutes of the owner)

Run only on the dark build D1 promoted at `rafii.io` (gate closed except the tester workspace). Needs the Authorization Block filled (tester user, test server, public test channel, private channel the bot cannot see, tester workspace) and AUTH-9 ticked: at most three real Discord messages, only in the test server, only with text the owner approves in the product at that moment, mentions suppressed. Nothing is typed into any chat on the owner's behalf; the agent only reads stored outcomes.

Rules for the agent during the session: read-only queries (counts and states), no customer content, no tokens, no Discord requests of its own, stop at any trigger in `RUNBOOK-INCIDENT.md`. Evidence goes into `RC-RECEIPT.md` as states and counts.

## Before the owner joins (agent, 5 minutes)

| Check | How | Expected |
|---|---|---|
| D1 serves `rafii.io` | alias readback | D1 deployment id |
| Cron answering | runtime logs for `/api/cron/worker` | one 200 per minute for 5 minutes |
| Baseline | `monitoring.sql` Q7, Q9, Q10, Q11 | zero in-flight installs, no open circuits (Q3), no uncertain sends (Q5), policy more than 14 days left (Q6) |
| A second, non-allowlisted workspace exists for the closed-state check | owner or agent | has no Discord footprint |

## Steps

| # | Item | Owner does | Agent verifies afterwards (own-workspace readbacks only) | Pass when |
|---|---|---|---|---|
| 1 | Closed state (G-01, 1 min) | In the non-allowlisted workspace open Channels, Connect, Discord | catalog entry `discordAccess.status = closed`, no OAuth transaction was created for that workspace | the closed wording is shown, no Discord redirect happens |
| 2 | Real OAuth and bot install, PRD A08 (X-02, 5 min) | In the tester workspace: Connect Discord, link the profile (first Discord consent), pick the test server, add the bot (second consent), return to Rafii | two OAuth transactions with outcome `exchanged` (one code exchange each, no duplicate POST in the logs), one credential row with the bot scopes, one channel record for the server, capability rows as expected, Q9 `servers_counted` up by one | Rafii shows the server as connected and the stored outcome says so (a click alone is not proof) |
| 3 | Destinations (1 min) | Authorize the public test channel; look for the private channel | destination list contains only channels the tester can see; the private no-bot channel is absent or refused | exactly the public channel is authorized |
| 4 | One real send and read-back, PRD A09 (X-03, 3 min) | Write a short test post, review the exact text, sender, channel and time, approve and send now | one job reaches `verified` with provider reference and URL; digest of the approved text equals the stored manifest; no mention parsed; Q1 shows one publish observed | the message exists in the channel with the approved text, read-back verified, no ping |
| 5 | Unattended schedule and cancel, PRD A10 (X-04, 7 min) | Schedule one post at least 5 minutes ahead and do nothing. Schedule a second and cancel it before it is due | the cron sends the first within one budget window and the read-back verifies; record the delay; the second job is `canceled` and Q1 shows no publish for it | the first arrives by itself, the second never does |
| 6 | Revoke and reconnect (X-05, 3 min) | Remove Rafii's bot from the test server (server settings), then try to publish again, then reconnect | the next job is held with a reconnect message and there is no retry storm (Q1 count flat, Q3 clean); after reconnect the connection works | clear message, one hold, reconnect succeeds |
| 6b | Revoked personal grant (A-01 follow-up, no message, 2 min) | In the tester's Discord user settings (Authorized Apps) remove Rafii's authorization, then press Verify on the channel card | the card shows reconnect (not an outage message); record only the HTTP status and the JSON key names of Discord's 401 answer to the identity check (never values); Q1 count flat | the real answer carries `message` and an integer `code`; if not, the A-01 classification assumption is wrong and the fix is reopened |
| 7 | Permission failure (X-06, 1 min) | Try to authorize or post to the private channel the bot cannot see | job held with a clear reason, no message | held, nothing sent |
| 8 | Tenant isolation spot check (Q-05) | From the second workspace try to open the first workspace's Discord connection or destination list by its address | 403 or 404, no data | denied |

Message budget: step 4 uses one, step 5 uses one, one spare. If a step needs a fourth message, stop and ask.

## After the session (agent)

1. Write the stored outcomes into the ledger as counts and states: transactions, credential rows, capability rows, job states, delays, monitor values before and after.
2. Compare Q11 with the baseline: no capability row changed that should not have.
3. X-09: only if X-03, X-04 and X-05 are VERIFIED recommend opening the capped gate; otherwise NO-GO and fallback F-02 (D1 stays promoted).
4. Remove nothing from the test server and ask the owner whether to keep the bot there.

## If something fails

Do not retry a failed send. Record the state, run the incident ladder only if a trigger fired, and report. A failure in steps 2, 4 or 5 is a NO-GO unless fixed and re-qualified on a new frozen SHA with a new D1.
