# P-01 Privacy notice and terms: Discord wording for your approval (H-08)

Status: drafted and committed on the release candidate branch as its own commit, so it can be edited or dropped without touching the rest. Nothing is live. The pages keep their "Draft - pending qualified legal review" banner; this is factual wording, not legal advice.

Why: Discord's developer terms (5a) ask for a public privacy policy that accurately and fully describes what an app collects and how a person can have it deleted (`P-02-discord-policy-compliance.md`, gaps 1 and 2). The public pages did not name Discord, and the generic sentence "revoked with the platform where supported" is not true for Discord on this code line.

## What changes

| File | Change |
|---|---|
| `web/src/app/(marketing)/privacy/page.tsx` | New `Discord` subsection under Connected platforms (below). |
| `web/src/app/(marketing)/data-deletion/page.tsx` | One Discord exception under "Disconnect one platform" and in the "Provider tokens" row. |
| `web/src/content/legal-shared.ts` | Sub-processor row now reads "Social providers (LinkedIn, Threads, Instagram, Discord)"; new retention row "Discord request records". |
| `src/postriff_phase2/privacy.py` | The same retention row; the Discord sentence added to `providerAccess`. (Discord was already in the in-app sub-processor list.) |

## The wording (English; the legal pages are English only)

> **Discord.** Rafii uses Discord in two separate steps, each with its own Discord consent screen. In the first you link your Discord profile: Discord tells Rafii your user id and display name and, with the server-list permission that adding a bot needs, lets Rafii ask Discord for the servers you belong to so you can pick one. Rafii shows only servers where you can manage the server and does not keep that list. The access and refresh tokens for the link are encrypted before storage. In the second you add Rafii's bot to one server you manage; Rafii then stores that server's id and name, the channels you choose (their ids and the names Discord shows) and the permissions the bot holds there.
>
> The bot is one shared bot for all Rafii customers. Rafii posts to a Discord channel only the text and image you approve for that exact post, with mentions switched off: it never pings @everyone, @here, roles or people. After posting, Rafii reads back the message it posted to confirm delivery and keeps the message id, its link and the confirmation as your receipt. That is the only reason Rafii holds the read-message-history permission. Rafii does not read other messages in your server, does not send direct messages and does not use Discord's message-content access. Discord comments and replies are not enabled.
>
> Disconnecting Discord in Rafii deletes Rafii's stored copy of your Discord tokens and stops Rafii from using that connection. It does not ask Discord to revoke the authorization and it does not remove the bot from your server. To end that access on Discord's side, remove Rafii in your Discord Authorized Apps and remove the bot in your server's settings. Deleting your Rafii account deletes the same stored data with your workspace; the bot likewise stays in the server until a server manager removes it. Rafii also keeps technical records of its requests to Discord (identifiers, digests, status codes and timing; no message text, tokens or names) to operate and protect the service. There is no deletion schedule for those records yet.
>
> Your use of Discord is subject to the Discord Terms of Service and the Discord Privacy Policy.

Data-deletion page, Discord exception: "Rafii deletes its stored copy of your Discord tokens but does not ask Discord to revoke them, and it does not remove its bot from your server. To end Rafii's access on Discord, remove Rafii in your Discord Authorized Apps and remove the bot in your server's settings."

## Every claim against the code

| Claim | Evidence |
|---|---|
| User id and display name; server list only with the server-list permission | `discord/oauth.py` `user_guilds()` refuses without the `guilds` scope; identity record holds user id and label |
| Only servers you can manage are shown; the list is not kept | `user_guilds()` filters on owner, Administrator or Manage Server and returns id and name to the caller; nothing writes it to state |
| Link tokens encrypted | `CredentialVault` (Fernet) in `oauth.py`; `upsert()` in `discord/oauth.py` stores ciphertext only |
| Server id and name, channel ids and names, permissions stored | `LABELS = ('guildName', 'channelName', 'kind')` in `discord/authorization.py`; the channel record keeps the server name as account |
| Only approved text and image, mentions off | frozen manifest and approval digest in `authorization.py`; `allowed_mentions {'parse': []}` on every send path (`authorization.py`, `hosted_social.py`, `interactions.py`) |
| Read-back of its own message and receipt | worker reconciliation reads the message by id; the job keeps reference, URL and verification |
| No other messages read, no DMs, no message-content access | no Gateway connection, no DM channel path, engagement flag OFF, Message Content intent not used (`P-02`, sections A and C) |
| Disconnect and account deletion behaviour | `disconnect_identity()` returns `remoteRevocation: 'not_requested'` and says the bot stays; account deletion skips remote revocation for every Discord credential (`account_deletion.py`) |
| Technical request records without deletion schedule | `pr_discord_request_admissions` keeps workspace id, publication and intent ids and digests with no cascade and no prune rule (`124_discord_rate_limits.sql`; `P-02` D4) |

## What I did not change, for you to decide

- `/channels/discord` still says "publishing opens after testing" (`web/src/config/channels.ts`). Change it only when the gate opens, to what is true that day.
- The Terms still contain placeholders (governing law, refund policy), the pages are drafts, and the privacy mailbox is a personal webmail address. These need you or counsel; Discord reviewers read these pages.
- The product does not revoke the personal Discord token at Discord on disconnect, and the shared bot is never removed from a server. Changing that is engineering work for Wave 2 (`P-02` gap 2); the wording above says what happens today.
- Traditional and Simplified Chinese versions of the legal pages do not exist; the in-app Discord screens are already localized.

## Your decision

`APPROVE P-01 as written`, `APPROVE with edits: ...`, or `DROP`. The build waits for this answer because the pages are part of it.
