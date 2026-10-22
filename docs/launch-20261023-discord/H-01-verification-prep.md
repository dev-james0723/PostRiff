# H-01 Discord app verification: what it needs and what to prepare

Prepared 2026-10-22 (UTC) for the 2026-10-23 launch. Checklist item H-01 (HUMAN, MUST). Companion files in this folder: `PORTAL-AUDIT-SHEET.md` (H-02), `P-02-discord-policy-compliance.md`, `W-03-webhook-server-limit.md`.

**Update 23:00Z (owner):** the owner showed the verified-app check mark on the production bot's tag and confirmed it is the production app. Sections below on how to start verification are kept for the record; they are not needed now. Re-check only if Discord flags the app.

Status: preparation notes only. Nothing here submits, saves or changes anything in the Discord Developer Portal.

This repository is public. Never paste tokens, secrets, Discord IDs of real servers or people, ID documents, or Portal screenshots into this file or the ledger.

## How to read the tags

- `[read]` I retrieved the page text in this session and the statement comes from that text. The official docs site (docs.discord.com) and the Discord help center (support-dev.discord.com) did not resolve from this sandbox, so I read the source files of Discord's official docs repository (github.com/discord/discord-api-docs) through the fetch tool. The fetch tool extracts and short-quotes; it does not hand over raw page text. Rendered URLs below are the public pages these files belong to.
- `[summary]` Only a web-search summary of the page. The page text was not retrieved. Treat it as a lead, not as evidence.
- `[code]` Read from the repo line `origin/codex/discord-personal-account-20261019`, tip `b960bfe0` (PR #216 line).
- "not stated in anything found" means exactly that; it does not mean "no".

## 1. Short answer

1. **When it is needed.** Discord's developer docs say verification is required for apps in 100 or more guilds (guild = server) `[read]` (https://docs.discord.com/developers/events/gateway, quoted in the table below). Older Discord announcements say the same in plainer words: an unverified bot cannot grow past 100 servers `[summary]`. Wave 1 is capped at 90 servers (D-01), so Wave 1 does not need verification. Wave 2 does.
2. **Only the owner can do the identity step.** The team owner confirms identity through Stripe, Discord's identity partner `[summary]`. Discord's Discovery guide says the team owner must "complete identity and application verification" `[read]` (https://docs.discord.com/developers/discovery/enabling-discovery). An agent cannot do this.
3. **Where.** Developer Portal, open the app, **App Verification** in the left menu `[read]`. The requirement list is shown there. The **Verify App** button becomes clickable only when every requirement is met `[summary]`. The list of requirements is not published in anything I could read.
4. **How long.** Not stated in the Discord docs I read. One search summary of an older FAQ says about 4 to 5 business days `[summary]`, single source, not confirmed by a second search. Plan for "unknown".
5. **Open question that changes today's plan.** Whether an app well under 100 servers may submit at all is not stated in anything found. In 2020 Discord said developers could start from 76 servers `[summary]`, and that Discord sends a Discord message when a bot is ready `[summary]`. So "start verification today" may be impossible. Step 1 is only to look at the tab and write down what it says (row g of `PORTAL-AUDIT-SHEET.md`).
6. **Fast growth can block it.** Discord has an app flag that marks unusual growth and prevents verification `[read]` (https://docs.discord.com/developers/resources/application, quoted in the table below). What counts as unusual is not stated in anything found. Release Wave 1 in batches from the waitlist; do not open 90 servers in one hour.
7. **Rafii's legal pages exist but are drafts, and they never mention Discord.** Discord's terms require a privacy policy whose public link is kept in the Developer Portal `[read]`. See section 6 and `P-02-discord-policy-compliance.md` gap 1.
8. **Privileged intents are a separate process and Rafii needs none.** Since 2026-06-10 Discord split App Verification from Privileged Intent review `[read]`. Rafii uses REST only, no Gateway, no privileged intent `[code]` (`src/postriff_phase2/discord/engagement.py:1`, `:31`).

## 2. What Discord says (facts table)

| # | Topic | What Discord says | Tag | Source |
|---|---|---|---|---|
| 1 | 100-server rule | Verified apps are "required for apps in 100+ guilds". | read | https://docs.discord.com/developers/events/gateway (file `developers/events/gateway.mdx`) |
| 2 | Same rule, older wording | Verification became mandatory for bots in 100 or more servers; until verified a bot cannot grow past 100 servers (2020 announcement). | summary | https://discord.com/blog/the-future-of-bots-on-discord and https://support.discord.com/hc/es/community/posts/360050817314-Discord-Bots-Info |
| 3 | Early start and notice | Bots may start from 76 servers; Discord messages the developer when the bot is ready to verify. Whether this still holds: not stated in anything found. | summary | https://support-dev.discord.com/hc/en-us/articles/6275923204375 (older FAQ, page not readable here) |
| 4 | Where to click | Developer Portal, select the app, App Verification in the left menu to see the requirements, complete them, then submit. | read | https://docs.discord.com/developers/discovery/enabling-discovery |
| 5 | Submit button | The Verify App button is clickable once all requirements are met. | summary | https://support-dev.discord.com/hc/articles/23926564536471 ("Getting Your App Verified", page not readable here) |
| 6 | Who verifies | The team owner confirms identity through Stripe and may be asked to re-verify periodically. | summary | same article as row 5 |
| 7 | Teams | A team has one owner; creating or joining a team needs 2FA on the Discord account; Transfer App to Team is one-way: "Once an app has been transferred to a team, it cannot be transferred back." | read | https://docs.discord.com/developers/topics/teams |
| 8 | Privacy policy | Developer Terms section 5(a): you must provide a privacy policy that fully describes what data you collect, how you use and share it, and how users can ask for deletion, and "You will maintain publicly available, up-to-date links to your privacy policy in the Developer Portal". | read | Developer Terms (see sources below) |
| 9 | Profile accuracy | Developer Terms section 1(b): keep application information accurate and keep a clear description of the app in its user-facing profile; do not misrepresent who you are. | read | Developer Terms |
| 10 | Terms of Service URL | The app profile has Terms of Service and Privacy Policy URL fields. For an App Directory listing Discord says the app needs a connected, publicly available privacy policy and terms of service. Whether the verification checklist itself asks for both: not stated in anything found. | read (fields), summary (directory) | https://docs.discord.com/developers/resources/application ; App Directory help-center articles such as https://support-dev.discord.com/hc/en-us/articles/9489299950487 (the search summary did not say which article holds the sentence) |
| 11 | Review time | Not stated in the docs I read. The intent guide gives the developer a window to apply: "You will have 90 days from the date of the notification to apply." That is the developer's deadline, not Discord's review time. Older FAQ summary: about 4 to 5 business days. | read / summary | https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review ; FAQ in row 3 |
| 12 | Verification vs intents | "With this change, we have separated App Verification and the Privileged Intent review process." (2026-06-10). Intent review is now triggered at 10,000 unique users across servers; below that, intents are a Portal toggle. Before that date the trigger was 100 servers, and some older doc text (the application-flag descriptions) still describes the intents for bots in 100 or more servers. | read | https://docs.discord.com/developers/change-log |
| 13 | Growth flag | Application flag VERIFICATION_PENDING_GUILD_LIMIT: "Indicates unusual growth of an app that prevents verification". | read | https://docs.discord.com/developers/resources/application |
| 14 | After approval | Developer Terms section 6: once an app is approved it may not materially change its functionality without resubmitting for review. (Extracted by the fetch tool; exact wording to be confirmed on the live page.) | read | Developer Terms |
| 15 | Age rule | Discord changed who may supply the ID because its identity partner raised legal concerns about the age of verified developers. Details not readable here. | summary | https://support-dev.discord.com/hc/en-us/articles/6275923204375 |
| 16 | Exact checklist and form questions | Not stated in anything found. The Portal tab is the only authority. | n/a | n/a |

Sources for the two policies:

- Developer Terms of Service, effective 2024-07-08, last updated 2024-06-06. Official page: https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service (not readable here). I read the copy in the official docs repo at commit `fe5a389`, file `docs/policies_and_agreements/Developer_Terms_of_Service.md`, which carries the same dates.
- Developer Policy, same dates. Official page: https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy . The current docs file `developers/policies/developer-policy.mdx` is only a pointer to that page `[read]`.
- Re-check both live pages on the day verification is submitted; a later edit would not show up in what I read.

## 3. What the owner must prepare

| Done | Item | Why | Notes |
|---|---|---|---|
| [ ] | The Discord account that owns the app (or its team) is identified | The team owner is the person Stripe verifies `[summary]` | Teams have exactly one owner `[read]`. Tick "Team" or "Personal account" in the header of the audit sheet. |
| [ ] | 2FA is on for that account | Needed to be on a team `[read]` | |
| [ ] | A valid government photo ID is at hand | Discord's FAQ says verification asks for a government ID `[summary]` | Accepted document types and countries: not stated in anything found. Never store the ID or a photo of it in this repo, the ledger or a chat. |
| [ ] | The team owner's email and Discord messages are watched | Questions go to the email tied to the team owner `[summary]` | |
| [ ] | `https://rafii.io/privacy` and `https://rafii.io/terms` are final, public and mention Discord | Developer Terms 5(a) `[read]` | They are drafts today; see section 6. Needs P-01 plus owner approval H-08. |
| [ ] | A support or report URL is ready: `https://rafii.io/contact` | Discord policy expects a way for users to report issues `[read]` | The page route exists `[code]`. Confirm someone answers (H-07). |
| [ ] | App name, icon and description are final | Terms 1(b) `[read]` | Draft description in section 5.2. |
| [ ] | A plain description of how Rafii uses Discord is approved by you | The form likely asks; exact questions not stated in anything found | Draft in section 5. Every claim in it was checked against the PR #216 code, with the other modes OFF. |
| [ ] | You decided which features to declare now | Terms 6: material changes after approval need re-review `[read]` | Webhook mode, User Install, slash commands (Interactions Endpoint) and engagement are OFF for Wave 1. Decide whether to declare them as "planned". |
| [ ] | A growth plan is written | Fast growth can block verification `[read]` | Waitlist, batches of N servers per day, cap 90 until verified. |
| [ ] | Time is blocked | The Stripe step plus the form | Duration not stated in anything found; allow an hour. |

Do not click **Transfer App to Team** casually. It cannot be undone `[read]`.

## 4. Where to click (owner)

1. Sign in to the Developer Portal with the account that owns the Rafii app or team. (Portal address from general knowledge: https://discord.com/developers/applications . I could not open it from this sandbox.)
2. Click the Rafii application.
3. Left menu, **App Verification** `[read]`. Write down: the status line, the server count if one is shown, every requirement and whether it is ticked. Paste that into row g of `PORTAL-AUDIT-SHEET.md`. Do not click Verify App yet.
4. Fix each unmet item on the tab that owns it. The audit sheet lists the tabs: General Information, Bot, OAuth2, Installation.
5. When every item is met, **Verify App** becomes clickable `[summary]`. Click it only after you have read section 5 and approved the wording.
6. The identity step opens at Stripe for the team owner `[summary]`. Only you can do it. Keep the ID document out of every repo, ledger and chat.
7. If a form asks how the app works, paste from section 5 after editing.
8. Write down the date, time and any reference text Discord shows. Do not paste IDs or screenshots into the ledger. Keep watching the team owner's email and Discord messages.

If the tab says the app is not eligible yet: copy that sentence into the audit sheet, then check again when the real server count nears 76 (the 2020 figure) and ask Discord support in writing what the current threshold is. Keep section 3 ready so you can submit the same day.

## 5. Pre-fill kit (drafts for your approval)

Everything below is a draft. Claims were checked against the PR #216 code with Webhook mode, User Install, the Interactions Endpoint and engagement all OFF (checklist D-03, AUTH-3). Re-check against the release candidate when it exists.

### 5.1 Values that can be set in the Portal now

| Portal field | Value to use | Basis |
|---|---|---|
| Redirect (OAuth2) | `https://rafii.io/api/oauth/discord/callback` | `[code]` `src/postriff_phase2/oauth.py:450` builds `{origin}/api/oauth/discord/callback` |
| Terms of Service URL | `https://rafii.io/terms` | `[code]` `web/src/app/(marketing)/terms/page.tsx`, `web/src/config/site.ts` |
| Privacy Policy URL | `https://rafii.io/privacy` | `[code]` `web/src/app/(marketing)/privacy/page.tsx` |
| Interactions Endpoint URL | leave empty | PING and User Install are out of scope (H-02) |
| Install contexts | Guild Install only | User Install is out of scope (H-02) |
| Scopes and permissions | `bot` (+ `identify` in Rafii's own link); permissions `101376` | `[code]` `src/postriff_phase2/social_connectors.py:220`; arithmetic in the audit sheet |
| Privileged intents | all OFF | `[code]` engagement.py `LIMITS['gateway'] = False`; Rafii has no Gateway client |

Note: the Terms of Service and Privacy Policy URLs are not among the fields Discord's edit-application API accepts `[read]` (https://docs.discord.com/developers/resources/application), so they are set by hand in the Portal.

### 5.2 Draft app description (owner to approve)

> Rafii helps people who manage a Discord server write, review and schedule announcements. Rafii's bot posts only in the one channel the server manager chooses, and only after a person approves each exact post. It never sends direct messages and never mentions @everyone, @here or roles. Help and data requests: rafii.io/contact

Claim check `[code]`: one channel per authorization and live permission re-check before each send (`social_connectors.py`, `destinations()` and `authorize_destination()`); per-post approval (`EXPLAIN` text at `social_connectors.py:222-223`); no code path creates a direct-message channel (searched `src/`, `web/src/`, `skills/`); mentions are suppressed in every message (`discord/authorization.py:121`, `hosted_social.py:405`).

Do not claim "does not read your server's messages". The bot has Read Message History and fetches its own posted message to confirm delivery (`hosted_social.py:515`). Say what it does instead: "checks only its own posts".

### 5.3 Draft: why each permission

| Permission | Number | Why Rafii needs it `[code]` |
|---|---|---|
| View Channel | 1024 | to see the chosen channel and verify it can post there (`social_connectors.py` `destinations()` requires it) |
| Send Messages | 2048 | to post the approved text |
| Attach Files | 32768 | to attach at most one approved image (`discord/authorization.py:110`) |
| Read Message History | 65536 | to look up its own sent message and confirm delivery (receipt check, `hosted_social.py:515`) |
| Total | 101376 | bits 10, 11, 15 and 16 set; checked by running the expression from the code and against Discord's bit table `[read]` |

Not requested: Administrator, Manage Server, Manage Webhooks, Manage Roles, Mention Everyone, Embed Links, any voice or moderation permission.

Permission note: the older code line (the consumer-saas lineage) asked for `52224`, which is View Channel + Send Messages + Embed Links + Attach Files, and no Read Message History (`git show HEAD:src/postriff_phase2/social_connectors.py`, line 218). The PR #216 line changed this in commit `17e3844c`. If the Portal or any existing install still shows 52224, say so in the audit sheet.

### 5.4 Draft: data Rafii handles for Discord

| Data | Why | Where | Kept until `[code]` |
|---|---|---|---|
| Discord user ID and display name of the person who connects (`identify`, no email) | show who authorized, bind to the workspace member | workspace record | the link record stays until the workspace is deleted; token ciphertext is wiped on disconnect (`discord/oauth.py:698`) |
| Person's access and refresh token (identity step only, scope `guilds` to list servers they manage) | list their servers; re-verify before sending | encrypted (Fernet) credential table, key from server secrets | wiped on disconnect; row deleted with the workspace |
| Server ID and name; channel IDs and names | choose the destination and check permissions | workspace record | revoked flag on disconnect; deleted with the workspace |
| Permission numbers (bot and manager, per channel) | prove the bot may post | workspace record | same |
| Text and at most one image of each approved post | publish it | workspace record and private storage | until the customer deletes it or the workspace is deleted |
| Message ID and link of each post sent | delivery receipt | workspace record | same |
| Bot token | post | server environment variable, never in the database | until rotated |

Not collected `[code]`: Discord email, direct messages, other members' message text (engagement is OFF), presence, voice.

Two honesty points for the form: after Rafii disconnects a server (PR #216 line) the bot stays installed and the person must remove it in Discord (`discord/oauth.py:701`, `account_deletion.py:17-19`); the older line made the bot leave when no workspace used it (`git show HEAD:src/postriff_phase2/social_connectors.py`, `revoke()` at lines 372-374).

### 5.5 Draft: what is OFF at launch

Gateway connection and privileged intents; direct messages; slash commands and the Interactions Endpoint; incoming webhooks (`webhook.incoming`); User Install; reading channel messages, analytics, comments and replies (engagement). All default OFF in code (`social_connectors.py` `DiscordProvider.__init__`, flags set False) and listed OFF in the launch plan (D-03, AUTH-3).

### 5.6 Draft answers to questions Discord might ask (my guesses, not Discord's list)

| Likely question | Draft answer |
|---|---|
| Do you read message content? | No Gateway, no Message Content intent. Rafii only fetches its own posted message to confirm delivery. |
| Do you store message content? | Only the post text a customer wrote and approved. Other members' messages are not read or stored at launch. |
| Do you contact users? | No direct messages. Posts go to one chosen channel; mentions are suppressed. |
| How do users delete data? | Disconnect in Channels; delete the account in Account, Privacy and data; https://rafii.io/data-deletion . |
| How is the bot token protected? | Server environment secret; not in code or database; the repo has a secret-scan test. |
| How do you handle abuse? | Per-post human approval; a kill switch; contact page. |
| How will you grow? | Waitlist and a cap of 90 servers until verified. |

## 6. Rafii's public legal URLs (from the repo)

Base address: `web/src/config/site.ts` sets `url` to `process.env.NEXT_PUBLIC_APP_URL ?? 'https://rafii.io'`, with `links.privacy = '/privacy'`, `links.terms = '/terms'`, `links.dataDeletion = '/data-deletion'`, `links.security = '/security'`, `links.contact = '/contact'` `[code]`.

| Page | Public URL | Route file `[code]` | Notes |
|---|---|---|---|
| Privacy Policy | https://rafii.io/privacy | `web/src/app/(marketing)/privacy/page.tsx` | Use as the Portal Privacy Policy URL |
| Terms of Service | https://rafii.io/terms | `web/src/app/(marketing)/terms/page.tsx` | Use as the Portal Terms of Service URL |
| Data deletion | https://rafii.io/data-deletion | `web/src/app/(marketing)/data-deletion/page.tsx` | Link it in the verification answers |
| Security | https://rafii.io/security | `web/src/app/(marketing)/security/page.tsx` | |
| Contact | https://rafii.io/contact | `web/src/app/(marketing)/contact/page.tsx` | Use as the support or report URL |
| Discord channel page | https://rafii.io/channels/discord | `web/src/app/(marketing)/channels/[slug]/page.tsx`, content in `web/src/config/channels.ts:207-217` | Currently says "publishing opens after testing". Update at launch (G-03). |
| Signed-in privacy and data | https://rafii.io/app/account/privacy | `web/src/app/app/account/privacy/page.tsx` | Not public; do not use in the Portal |

Problems a reviewer will notice, all `[code]`:

- Discord is not named on any of these public pages. Privacy section 5 names "LinkedIn, Threads, Instagram and other platforms"; the public sub-processor row is "Social providers (LinkedIn, Threads, Instagram)" (`web/src/content/legal-shared.ts:31`). The in-app notice names Discord only inside a long list (`src/postriff_phase2/privacy.py:33`). Fix: P-01 and gap 1 in `P-02-discord-policy-compliance.md`.
- Every legal page shows a "Draft - pending qualified legal review" banner (`web/src/config/legal.ts`, `LEGAL_REVIEW_STATUS = 'draft'`, last updated 2026-10-09).
- The Terms still contain placeholders for governing law and refund policy (`terms/page.tsx` section 6 and `legal.ts` `GOVERNING_LAW`).
- The legal pages name an individual as operator (privacy section 1) and give a consumer webmail address as the privacy mailbox (`legal.ts` `LEGAL_CONTACT_EMAIL`). `web/src/config/site.ts` also has a TODO to confirm the support mailbox. Consider a role-based address before these pages are linked from a public Discord app profile. I have not copied either value here.
- I could not open https://rafii.io from this sandbox, so whether these pages are live and public today is not verified. Open each in a private window before relying on them.
- The redirect route `/api/oauth/discord/callback` is served by the Python API through the `/api/(.*)` rewrite in `vercel.json`, and it only forwards `state` and `code` to the signed-in app; the code exchange happens later (`src/postriff_phase2/hosted_app.py:784-815`) `[code]`.

## 7. Risks and unknowns (ranked)

1. **Verification cannot be started or is slow.** Eligibility rules and review time are not stated in anything found. Wave 2 depends on it. Start the look today.
2. **Legal pages block approval or break the rules.** Terms 5(a) needs an accurate public privacy policy `[read]`. Fix before submitting.
3. **Growth flag.** A burst of new servers may set the "unusual growth" flag `[read]`. Pace Wave 1.
4. **Real server count can exceed Rafii's count.** On the PR #216 line, disconnecting or deleting an account never removes the bot `[code]` (`discord/oauth.py:701`, `account_deletion.py:17-19`; contrast the older line above). Use Discord's own count, not Rafii's connection count, when checking the cap. W-03 describes how to read it.
5. **Material changes after approval.** Enabling Webhook mode, User Install, slash commands or engagement later may need re-review `[read]`.
6. **Identity step failures.** Stripe may not support every country or document `[summary]`, single unofficial forum source. Not confirmed.
7. **Policy text may have moved.** I read the 2024-07-08 policy and terms; the live pages could not be opened.

## 8. What to record for the ledger (H-01 evidence)

- Date and time (UTC), who looked.
- The exact status sentence from the App Verification tab, and each requirement line (short words).
- Server count as shown, or "not shown".
- Submitted: yes or no, with the time. Reference text Discord shows, if any.
- Never: ID documents, photos, screenshots with tokens, secrets or IDs of real servers or people.
