# Bot-free Webhook permission evidence — engineering candidate

This candidate allows an ordinary Rafii customer to publish through an authorized
incoming Webhook without installing Rafii's Bot in that server, when Discord
currently confirms that the selected customer account owns the server or has
`ADMINISTRATOR`. Other members retain the existing Bot permission witness.
All new modes remain OFF. This document records source behavior, not live acceptance.

## Why this proof is sufficient

Discord's [current-user guild endpoint](https://docs.discord.com/developers/resources/user#get-current-user-guilds)
returns the OAuth subject's guild membership, `owner` and base `permissions` with
the separately consented `guilds` scope. Discord's
[permission rules](https://docs.discord.com/developers/topics/permissions#permission-overwrites)
give the owner all permissions and let `ADMINISTRATOR` bypass channel overwrites.
`MANAGE_GUILD`, `MANAGE_WEBHOOKS` and ordinary base send permission are insufficient
for this path. A Webhook token alone proves resource custody, not authorizer rights.

Rafii therefore checks the exact Webhook/application/guild/channel resource,
fresh OAuth application/subject/scopes, and current owner/admin status. These
reads use the existing rate coordinator and read-authorization guard. There is
no cached permission result. Missing proof fails closed or uses the existing
Bot's full current channel-permission proof. No arbitrary personal token or
personal-user sender is accepted.

## Custody and customer flow

1. A customer explicitly links a personal identity, optionally consenting to the
   existing server-list scope. No new OAuth scope was added by this change.
2. The Webhook connection sheet optionally selects a linked identity that already
   has server-list consent. EN, Traditional Chinese and Simplified Chinese copy
   explains the owner/admin boundary and Bot fallback.
3. The existing Webhook OAuth consent must match that identity. The encrypted
   Webhook envelope records only the selected identity ID and consent generation.
   Its bearer/refresh token stays in the separate encrypted identity credential.
4. Each permission check resolves this binding in the same workspace, checks the
   original Rafii authorizer's active management permission, refreshes expiring
   OAuth outside SQL locks, and rechecks custody after provider I/O. Reconnect,
   unlink, grant generation change and membership removal fence the path.
5. Existing exact-channel authorization, frozen approval, scheduler, cancellation,
   rate permit, uncertain-result retention and known-message receipt checks still
   apply. Only the Webhook sends the approved text. No messages are sent by the
   linked personal account or the Bot on this path.

Existing independent Webhooks and old envelopes continue using their previous
Bot witness. Reconnecting a legacy selected-identity Webhook is an explicit new
OAuth operation, never an automatic scope upgrade or remote Webhook creation.
Forum/media channels and threads remain unsupported: payloads cannot create a
thread, and a provider rejection must not be retried as a different effect.

## Verification and rollout

Regression coverage includes owner/admin, demotion, subject/application/scope
mismatch, malformed/duplicate guild evidence, identity generation/member/revoke
fencing, expired-token refresh outside locks, transient-token custody, Bot fallback,
one synthetic Webhook dispatch and exact known-message receipt. The cloud browser
checks optional identity selection and explicit OAuth start at 390px and 1280px.
These tests use synthetic provider transport. PostgreSQL/RLS, complete CI and the
running browser must pass on the final source before engineering qualification.

Real customer OAuth, Bot-free live publish, unattended scheduling, physical mobile,
migration 131, Discord commands/PING and Release Captain sign-off remain required.
No new provider consent, send, command registration, paid action, production write,
merge or deployment is authorized by this candidate.

Rollback: keep Webhook mode disabled, or revert this scoped commit. No new schema,
production configuration or hosted data is introduced. Do not remove replay rows,
resend uncertain messages or reverse previously approved provider effects.
