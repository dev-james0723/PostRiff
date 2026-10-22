# Discord Developer Portal audit sheet (checklist H-02)

For the owner. About 10 minutes. Prepared 2026-10-22 (UTC) for the 2026-10-23 launch. Answer boxes are blank on purpose.

LOOK ONLY. Do not click Save Changes, Reset Token, Reset Secret, Verify App, Transfer App or Delete. Do not write, paste or screenshot any token or secret. This repository is public: fill in a private copy or paste your answers into the ledger, and leave out server IDs and personal IDs.

Filled in by: ______________   Date and time (UTC): ______________
Application name shown in the Portal: ______________   The app belongs to: [ ] a Team  [ ] my personal account

Open the Developer Portal, click the application Rafii uses, then check each row.

| # | Portal path | Expected | Your answer | It is wrong if you see |
|---|---|---|---|---|
| a | OAuth2 > Redirects | Exactly one row: `https://rafii.io/api/oauth/discord/callback` | [ ] OK  [ ] Not OK<br>Rows seen: ____ | a second row; `http://`; a trailing `/`; `www.`; any `vercel.app`, staging, preview or `localhost` address; a typo; no row at all |
| b1 | Bot > Public Bot | ON | [ ] ON  [ ] OFF | OFF: customers cannot add the bot |
| b2 | Bot > Requires OAuth2 Code Grant | ON | [ ] ON  [ ] OFF | OFF: the bot can be added without going through Rafii's connect step |
| c | General Information > Interactions Endpoint URL | EMPTY | [ ] empty  [ ] has an address | any address in the box |
| d1 | General Information > Terms of Service URL | `https://rafii.io/terms` | [ ] OK  [ ] Not OK<br>Opens in a private window: [ ] yes  [ ] no | blank; another address; the page is a 404, a sign-in page or empty |
| d2 | General Information > Privacy Policy URL | `https://rafii.io/privacy` | [ ] OK  [ ] Not OK<br>Opens in a private window: [ ] yes  [ ] no | same as d1 |
| e1 | General Information > Name | The name customers should see (Rafii) | Seen: ____ | default or placeholder name; a name that imitates Discord or another company |
| e2 | General Information > App Icon | Your real icon | [ ] OK  [ ] Not OK | the default grey icon |
| e3 | General Information > Description | Says only what Rafii does at launch (draft: `H-01-verification-prep.md` section 5.2) | [ ] OK  [ ] Not OK | promises DMs, reading messages, analytics, comments or replies, webhooks, slash commands, or "keeps your server active" |
| f0 | Installation > Install Link | Write down the setting: Discord Provided Link, Custom URL or None | Seen: ____ | record only. Discord's own link lets people add the bot without Rafii's connect step, which weakens the 90-server cap |
| f1 | Installation > Installation Contexts | Guild Install ticked. User Install NOT ticked | [ ] OK  [ ] Not OK | User Install ticked (User Install is out of scope for launch) |
| f2 | Installation > Default Install Settings (Guild Install) > Scopes | `bot` only. `applications.commands` may show beside it because Discord adds it with `bot`. Rafii's own connect link adds `identify` itself. | Scopes seen: ____ | anything else, for example `webhook.incoming`, `guilds.join`, `email` |
| f3 | Installation > Default Install Settings (Guild Install) > Permissions | Exactly four ticked: View Channel(s), Send Messages, Attach Files, Read Message History. Total `101376` | Ticked: ____<br>Total: ____ | Administrator ticked; any extra box (Manage Server, Manage Webhooks, Mention Everyone, Manage Roles, ...); Embed Links ticked and Read Message History missing (that is the old total `52224`); any total except `101376` |
| g | App Verification | Record only. Do not click Verify App. | Verified: [ ] Yes  [ ] No<br>Servers shown: ____ (or "not shown")<br>Unmet requirements, short words: ____ | not verified and servers 90 or more; any unmet requirement; any banner about unusual growth, a block or action required; identity step not done |
| h1 | Bot > Token | DO NOT RECORD the value. Only "last rotated" if the Portal shows a date | Last rotated: ____ (or "not shown") | the token was ever pasted in chat, email, a ticket, a screenshot or a commit; nobody can say when it was last reset |
| h2 | OAuth2 > Client Secret | DO NOT RECORD the value. Only "last rotated" if shown | Last rotated: ____ (or "not shown") | same as h1 |
| i | Bot > Privileged Gateway Intents | Presence, Server Members and Message Content all OFF (Rafii uses none) | [ ] all OFF  [ ] some ON | any ON |

Rows that are wrong: ______________________________

What to do with a wrong row: tell the agent the row letter and what you saw. Portal edits are yours to make, one at a time, and the agent re-checks after. Never click Reset Token or Reset Secret just to see a date: a reset breaks Rafii until the new value is set in the server environment and redeployed, so a rotation is a planned change with its own approval, not a quick fix.

---

# Reference (not for filling in)

Tags: `[read]` page text retrieved this session (docs.discord.com did not resolve from the sandbox, so I read the source files of Discord's official docs repository, github.com/discord/discord-api-docs, through the fetch tool, which extracts and short-quotes); `[summary]` search-result summary only; `[code]` repo line `origin/codex/discord-personal-account-20261019`, tip `b960bfe0` (PR #216 line).

## R1. Permission arithmetic (checked)

| Permission | Bit | Decimal | Hex |
|---|---|---|---|
| View Channel (VIEW_CHANNEL) | 1<<10 | 1024 | 0x400 |
| Send Messages (SEND_MESSAGES) | 1<<11 | 2048 | 0x800 |
| Attach Files (ATTACH_FILES) | 1<<15 | 32768 | 0x8000 |
| Read Message History (READ_MESSAGE_HISTORY) | 1<<16 | 65536 | 0x10000 |
| Total | | 101376 | 0x18C00 |

- 1024 + 2048 + 32768 + 65536 = 101376. I also ran `(1<<10)|(1<<11)|(1<<15)|(1<<16)` in Python and got 101376 (binary 11000110000000000, set bits 10, 11, 15, 16).
- Bit values match Discord's permission table `[read]` (https://docs.discord.com/developers/topics/permissions): VIEW_CHANNEL 0x400, SEND_MESSAGES 0x800, ATTACH_FILES 0x8000, READ_MESSAGE_HISTORY 0x10000.
- Matches the code: `DiscordProvider.PERMISSIONS = (1 << 10) | (1 << 11) | (1 << 15) | (1 << 16)` `[code]` (`src/postriff_phase2/social_connectors.py:220`). It is put in Rafii's authorize link as `permissions=101376` (`social_connectors.py:407`, `src/postriff_phase2/discord/oauth.py:236`).
- Administrator is bit 3 (value 8) `[read]`. `101376 AND 8 = 0`, so Administrator is not included. Also not included: Manage Server (bit 5), Manage Webhooks (bit 29), Mention Everyone (bit 17), Embed Links (bit 14).
- Discord's February 2026 permission split touched Pin Messages, Bypass Slowmode, Create Expressions and Create Events, not these four `[read]` (https://docs.discord.com/developers/change-log).
- The older code line (the consumer-saas lineage this branch is based on) asked for `52224` = 1024 + 2048 + 16384 (Embed Links) + 32768, with no Read Message History (`git show HEAD:src/postriff_phase2/social_connectors.py`, line 218). The PR #216 line changed it in commit `17e3844c`. If the Portal still shows 52224, it matches the older line, not the release candidate. Servers that installed the bot under 52224 may lack Read Message History for the bot; PR #216's channel check requires it (`social_connectors.py`, `destinations()`), so those servers might show no usable channel until the permission is granted or the bot is re-authorized. This is `[code]` reasoning, not tested.

## R2. What Rafii asks Discord for at runtime (code)

Scopes are chosen per request by Rafii's code. They are not set in the Portal. The Portal's Default Install Settings only matter for Discord's own install link.

| Step | Scopes requested | Other parameters | Where `[code]` |
|---|---|---|---|
| Link a personal account, with server list (connections v2) | `identify guilds` | none | `src/postriff_phase2/discord/oauth.py:47`, `:183` |
| Link a personal account, no server list | `identify` | none | same |
| Install the bot in one chosen server | `identify bot` | `permissions=101376`, `integration_type=0` (guild install), `guild_id`, `disable_guild_select=true` | `discord/oauth.py:183`, `:236` |
| Older one-step flow (connections v2 OFF) | `identify bot` | `permissions=101376`, `integration_type=0` | `social_connectors.py:403-407` |
| Incoming webhook (OFF at launch) | `identify webhook.incoming` | none | `discord/oauth.py:183`; `discord/webhooks.py` `require_enabled` |

- In connections v2 the server install needs a fresh personal link with the `guilds` scope first (`discord/oauth.py`, `start()` and `user_guilds()`), so customers are asked for `identify guilds` and then `identify bot`. "Only bot plus identify" is true of the install step, not of the whole funnel. The privacy notice and the verification answers should say so.
- `integration_type` 0 means guild install `[read]` (https://docs.discord.com/developers/topics/oauth2). `identify` returns the user without `email` `[read]` (same page); Rafii never asks for `email`.

## R3. Where each expectation comes from

| Row | Basis |
|---|---|
| a | Rafii builds `{origin}/api/oauth/discord/callback` (`src/postriff_phase2/oauth.py:442-450`); origin is `POSTRIFF_PUBLIC_BASE_URL` unless `POSTRIFF_OAUTH_DISCORD_CALLBACK_ORIGIN` pins another one (`src/postriff_phase2/providers.py:260-263`). The code compares the redirect string exactly (`discord/oauth.py`, `validate_context`) and the public-launch gate requires the callback to equal the approved one (`src/postriff_phase2/connection_review.py`). Discord's docs: `redirect_uri` is "whatever URL you registered when creating your application" `[read]` (https://docs.discord.com/developers/topics/oauth2). The agent checks the environment values separately by name; you only check the Portal. |
| b1, b2 | Application fields `bot_public` (if false only the app owner can add the bot) and `bot_require_code_grant` ("When `true`, the app's bot will only join upon completion of the full OAuth2 code grant flow") `[read]` (https://docs.discord.com/developers/resources/application). The checklist records both ON as of 2026-10-21 (H-02). |
| c | PING and User Install are out of scope (H-02). The only endpoint path the repo would ever expect is `/api/discord/interactions` (`scripts/discord_user_install_config.py`), used only if that mode is switched on later. |
| d1, d2 | Developer Terms 5(a): keep a public, up-to-date link to the privacy policy in the Developer Portal `[read]`. URLs from the repo: `web/src/config/site.ts`, `web/src/app/(marketing)/terms/page.tsx`, `.../privacy/page.tsx`. Not opened live: the sandbox cannot reach rafii.io. |
| e1 to e3 | Developer Terms 1(b): keep the app's user-facing profile accurate; do not misrepresent identity `[read]`. |
| f0 to f3 | Permissions and scopes: R1 and R2. Installation tab labels from Discord's tutorial `[read]` (https://docs.discord.com/developers/tutorials/developing-a-user-installable-app): Installation page, Install Link, Default Install Settings, Installation Contexts with User Install and Guild Install. Discord's changelog (2024-06-27) says newly created apps default to having both contexts `[read]`, partial text, so a User Install tick is plausible on an older app. |
| g | "Select App Verification from the left-hand menu to see the requirements" is Discord's own instruction `[read]` (Discovery guide). The Verify App button and the Stripe identity step are `[summary]` (https://support-dev.discord.com/hc/articles/23926564536471). The 90-server cap is checklist D-01; the 100-server limit for unverified apps is in `H-01-verification-prep.md`. |
| h1, h2 | Developer Terms 2(d): treat credentials as confidential, keep them encrypted where third parties can reach them, never embed them in open source `[read]`. The bot token is read from a server environment variable and never stored in the database `[code]` (`social_connectors.py:261`). |
| i | Rafii has no Gateway client and keeps the Message Content intent off `[code]` (`src/postriff_phase2/discord/engagement.py:1`, `:31`). Intents live on the Bot page under Privileged Gateway Intents `[read]` (https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review). |

## R4. One thing to settle in the tester session (X-02)

Discord's field description says that with Requires OAuth2 Code Grant ON the bot joins only on completion of the full code grant flow `[read]`. The launch plan says the bot joins at Discord's consent screen, before Rafii's callback runs. If the docs are right, Rafii can enforce the 90-server cap by refusing the code exchange. If the plan is right, the cap must be enforced at connect start. The tester session should observe which one is true. Not tested.

## R5. How sure am I of the Portal labels

- Confirmed in Discord's docs `[read]`: App Verification (left menu); Installation page with Install Link, Default Install Settings and Installation Contexts; the Bot page with Privileged Gateway Intents; General Information page (where Transfer App to Team lives).
- From unofficial guides only `[summary]`: OAuth2 page holding Redirects and Reset Secret; Bot page holding Reset Token.
- Not confirmed in this session (general knowledge): Public Bot and Requires OAuth2 Code Grant sit on the Bot page; Terms of Service URL, Privacy Policy URL, Interactions Endpoint URL, Description and App Icon sit on General Information. If a label is not where the sheet says, look at the neighbouring tabs and write what you see. Discord can move labels.
- The Application object does have these fields: `bot_public`, `bot_require_code_grant`, `terms_of_service_url`, `privacy_policy_url`, `interactions_endpoint_url`, `install_params`, `integration_types_config` `[read]` (https://docs.discord.com/developers/resources/application).
