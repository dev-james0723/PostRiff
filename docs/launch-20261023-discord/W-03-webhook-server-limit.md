# W-03 Do webhook-only installs, or user installs, count toward the 100-server limit?

Prepared 2026-10-22 (UTC) for the 2026-10-23 launch. Checklist item W-03 (AGENT+APPROVAL, SHOULD, Wave 2). Companion files in this folder: `H-01-verification-prep.md`, `PORTAL-AUDIT-SHEET.md`, `P-02-discord-policy-compliance.md`.

This repository is public. Nothing below needs a token, a secret, or a real customer. Never paste any of those into this file or the ledger.

Tags: `[read]` I retrieved the text in this session. docs.discord.com did not resolve from this sandbox, so I read the source files of Discord's official docs repository (github.com/discord/discord-api-docs) through the fetch tool, which extracts and short-quotes; `[summary]` search-result summary only; `[code]` repo line `origin/codex/discord-personal-account-20261019`, tip `b960bfe0` (PR #216 line); `[inference]` my reasoning, not a Discord statement. "not stated in anything found" means exactly that.

## 1. Plain answer

**Not documented in anything found.** Discord's documents describe the 100-server rule only in terms of apps and bots in servers ("guilds"). Nothing I found says whether an app that only holds an incoming webhook in a server (OAuth2 scope `webhook.incoming`) counts as being in that server for the limit, and nothing says it does not. The same is true for user installs.

What follows from that:

- Do not tell anyone that bot-free (webhook) mode lets Rafii pass 100 servers without verification. It might, but nobody has said so.
- Plan as if webhooks could count. Verification (H-01) stays the only documented route to more than 100 servers.
- Wave 1 (cap 90 servers) is not affected either way.

## 2. What Discord does document

| Item | What it says | Tag | Source |
|---|---|---|---|
| Server counter | The Application object has `approximate_guild_count`: "Approximate count of guilds the app has been added to". It does not define "added" and does not mention webhooks. The fields are optional, and how the counts are obtained is not stated in anything found. | read | https://docs.discord.com/developers/resources/application |
| User counters | `approximate_user_install_count` counts users who installed the app by authorizing with `application.commands`; `approximate_user_authorization_count` counts users who have OAuth2 authorizations for the app. These are separate counters from the guild count. | read | same page |
| User-install counter history | Added 2024-08-09: "We've added an approximate user install count to the Application object for user-installable apps." | read | https://docs.discord.com/developers/change-log |
| What `webhook.incoming` does | The scope "generates a webhook that is returned in the oauth token response for authorization code grants"; a new webhook is created each time. No statement about counts or verification. | read | https://docs.discord.com/developers/topics/oauth2 |
| Webhook object | `application_id` is the bot/OAuth2 application that created the webhook. "They do not require a bot user or authentication to use." No limits per guild and nothing about verification or server counts. | read | https://docs.discord.com/developers/resources/webhook |
| Wording of the 100-server rule | Verification is required for apps in 100 or more guilds: "required for apps in 100+ guilds". The application-flag descriptions for the gateway intents are also written for bots in 100 or more servers. | read | https://docs.discord.com/developers/events/gateway ; https://docs.discord.com/developers/resources/application |
| Older wording | Verification became mandatory for bots in 100 or more servers; until verified a bot cannot grow past 100 servers (2020). The help-center article "Getting Your App Verified" says verification is required to scale past 100 servers. | summary | https://discord.com/blog/the-future-of-bots-on-discord ; https://support-dev.discord.com/hc/articles/23926564536471 (page not readable here) |
| Growth flag | An application flag marks unusual growth that prevents verification. It does not say what is counted. | read | https://docs.discord.com/developers/resources/application |
| User installs | The tutorial says apps installed to a user context support only the `applications.commands` scope, and describes no server or install limit. Whether a user install counts toward the server limit: not stated in anything found. | read | https://docs.discord.com/developers/tutorials/developing-a-user-installable-app |
| Searches for an answer | Searches for `webhook.incoming` plus verification, the 100-server limit, or a user-install cap returned nothing relevant. | summary | web search, 2026-10-22 |

Reading of the above `[inference]`: Discord keeps three separate counters (guild adds, user installs, user authorizations). That suggests a webhook-only authorization would raise the authorization count and may leave the guild count alone, but no document says which counter the 100-server gate uses.

## 3. What Rafii's own plan assumes `[code]`

- Webhook mode (`POSTRIFF_DISCORD_WEBHOOK_V1_ENABLED` and the qualification flag) and User Install are OFF and stay OFF for Wave 1 (`src/postriff_phase2/social_connectors.py`, `DiscordProvider.mount`; checklist D-03, AUTH-3).
- Bot-free publishing is limited to a connecting person who owns the server or has Administrator. Everyone else still needs the installed bot as a read-only permission witness (`docs/discord-personal-account-20261019/BOT-FREE-OWNER-AUTHORIZATION-20261021.md` on the PR #216 line; `KYNLO-HYBRID-REPAIR.md` item 2). So even in the best case, webhook mode would only lift the bot-count pressure for some customers.
- Each webhook authorization creates a new webhook (OAuth2 docs above); reconnecting leaves the old remote webhook in place (`discord/oauth.py`, `save_webhook_callback`, comment "New OAuth creates a new remote webhook. Revoke only old local authority.").
- Rafii's own count can undercount Discord's count. On the PR #216 line a local disconnect or account deletion never removes the bot (`discord/oauth.py:701`; `account_deletion.py:17-19`), while the older line made the bot leave when no workspace used it (`git show HEAD:src/postriff_phase2/social_connectors.py`, lines 372-374). `[inference]` Discord's count of servers the bot sits in can therefore exceed the number of active Rafii connections. Use Discord's own number, not Rafii's, when checking the cap.

## 4. Why the answer matters

| If webhook installs do NOT count | If they DO count |
|---|---|
| Bot-free mode (owners and Administrators) could carry Rafii past 100 servers while verification is pending. It still needs its own qualification (the webhook flag also requires a separate qualified flag, `social_connectors.py` `mount`) and decision D-07, and it is limited as in section 3. | No shortcut. Verification (H-01) and worker scaling (W-02) are the only route. |

Either way, Wave 1 stays at 90 and H-01 starts regardless.

## 5. Safe test (owner runs it; about 45 minutes; no production impact)

Idea: read the application's approximate counts before and after one webhook-only install, with a normal bot install as a control, using a throwaway test application. That is the test the checklist describes, made safer.

Rules:

- Use a brand-new throwaway application, not Rafii's. Never use Rafii's bot token, client secret or redirect addresses.
- You run the commands yourself. Keep the test bot token in an environment variable in your own terminal. Never paste it anywhere. Send back only the three integers per reading.
- Do not switch on any Rafii flag. Do not use real customers' servers.
- Use two throwaway servers that you own: S1 and S2.

Steps:

1. Create the test application. Add a bot to it. Register a redirect address you control for the test (for example a local address). Copy nothing into the repo.
2. Reading R0 (baseline), with your own terminal and the test bot token in `$TEST_BOT_TOKEN`:

   ```
   curl -sS -H "Authorization: Bot $TEST_BOT_TOKEN" https://discord.com/api/v10/applications/@me \
     | python3 -c 'import sys,json; d=json.load(sys.stdin); print({k: d.get(k) for k in ("approximate_guild_count","approximate_user_install_count","approximate_user_authorization_count")})'
   ```

   The endpoint is "Get Current Application" (`GET /applications/@me`) `[read]`. If the response leaves these fields out, this test cannot answer the question; go to section 6.
3. Control: add the test bot to S1 with the `bot` scope, using a link of this shape (placeholders only): `https://discord.com/oauth2/authorize?client_id=<TEST_APP_ID>&scope=bot&permissions=1024`. Read again.
4. Treatment: authorize the test app in S2 with scope `webhook.incoming` only (no `bot` scope), choosing a channel, using a link of this shape: `https://discord.com/oauth2/authorize?client_id=<TEST_APP_ID>&response_type=code&scope=webhook.incoming&redirect_uri=<URL_ENCODED_TEST_REDIRECT>`. Check that a new webhook appears in S2 under the server's Integrations settings. If none appears, finish the code exchange on the test app and check again. Read again.
5. Optional, user installs: enable User Install on the test app, install it to your own account with the Discord-provided install link, read again.
6. For each reading take three samples: right away, after 10 minutes and after 60 minutes. The counts are described as approximate and may lag.
7. Optional cross-check `[inference]`: with the same bot token, `GET /users/@me/guilds` lists the servers the bot is a member of (not read in this session). A webhook-only server should not appear there.
8. Clean up: delete the webhook in S2, remove the test bot from S1, remove the test app under your Authorized Apps, delete the throwaway servers and the test application. Never commit the test token or secret anywhere.

Record (no IDs):

| Reading | UTC time | guild count | user install count | user authorization count |
|---|---|---|---|---|
| R0 baseline | | | | |
| R1 after bot added to S1 (control) | | | | |
| R2 after webhook-only authorization in S2 | | | | |
| R3 after user install (optional) | | | | |
| R4 after clean-up | | | | |

How to read the result:

| Observation | What it suggests | What it does NOT prove |
|---|---|---|
| guild count +1 after the bot, unchanged after the webhook | the guild counter ignores webhook-only authorizations | that the 100-server gate uses that counter |
| guild count +1 after the bot and +1 after the webhook | webhook-only authorizations may count as "guild adds" | that they count toward the gate |
| no change after the bot either | the counter lags or is not live; the test is inconclusive | anything |
| only the authorization count moves | authorizations are tracked separately from servers | anything about the gate |

## 6. Ask Discord in writing (the only decisive evidence)

Send through Discord's developer support request form (address not verified here). Keep the reply as evidence in the ledger, without personal data. Draft:

> We run an application that currently uses a bot (guild install). We are considering (1) creating incoming webhooks through the OAuth2 `webhook.incoming` scope without adding the bot user to the server, and (2) user installs. For the limit of 100 servers for unverified applications: (a) does a server in which our application only holds a `webhook.incoming` webhook count as a server the application is in? (b) does a user install count? (c) which counter does the limit use, and does `approximate_guild_count` reflect it? Please answer in writing.

Add the application ID privately when sending. Do not add it to the repo.

## 7. Decision rule

1. Discord says webhook-only installs do not count: record the written reply, then decide on opening bot-free mode as a Wave 2 route (D-07 and the qualification work still apply).
2. Discord says they count, or does not answer by the Wave 2 date: assume they count; verification is the route.
3. Test shows no counter movement but no written answer: treat as "unknown" (rule 2).

## 8. Approval and safety

- This item is AGENT+APPROVAL. The agent prepares and records. The owner approves and runs the test, because the agent must not read or handle bot tokens or secrets.
- A throwaway application needs no production approval item. Using Rafii's production application instead would touch its authorizations and counts; it needs explicit approval, Rafii's webhook flag must stay OFF, and I recommend against it.
- Nothing here changes Rafii's code, flags, credentials, deployments or Portal settings.
