# What the sender-name feature needs from `discord/rate_limits.py`

For the agent that owns `src/postriff_phase2/discord/rate_limits.py` (the sliding-ceiling work). The sender-name branch
(`claude/discord-rc2-sendername-20261023`) does not edit that file and does not depend on any request below being
accepted: every request has a tested fallback on the sender-name side (listed per request). "Measured" means observed by
the independent reviewer on a disposable PostgreSQL (the reviewer's notes, SNR items 2, 5, 6); "read" means exact
code reading of the file at 5a94b4f2.

Why the coordinator is involved at all: the only Discord write the feature makes is
`PATCH /guilds/{id}/members/@me` (the Rafii bot's server nickname), through `DiscordProvider._bot` ->
`_discord_http` -> `reserve` -> `consume` -> transport -> `observe`. The webhook name needs no extra request (it rides in the
body of the execute the post already makes).

## R1 (needed): admit the nickname route only while its capability is on

`route_identity()` allows `PATCH:/guilds/{id}/members/@me` unconditionally (`rate_limits.py:156`). The product ships with the
nickname capability OFF (`POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED` unset). Requested: that one template is admissible only
when `os.environ.get('POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED') == 'true'`, read at call time (never at import, never cached,
exactly like the other Discord flags: only the string `true`). Otherwise raise `RateCoordinatorUnavailable` like any
non-allowlisted route. The file imports no `os` today.

* Do NOT apply the flag in `observe`, `abandon_unsent_nickname`, `reconcile_nickname` or R2 below. They act on admissions that
  already exist; switching the capability off must not strand them.
* Test to add: `route_identity('PATCH', '/guilds/123456789012345678/members/@me')` raises for flag unset, `false`, `1`, `True`
  and returns the template for `true`; `GET:/guilds/{id}/members/{id}` is unaffected.
* Sender-name fallback if declined: the routes and the transport guard (`write_guard`) already refuse before any provider
  call when the capability is off (tests `Switches` in `tests/test_discord_sender_name_routes.py`). R1 is the second layer.

## R2 (needed): resolve a nickname admission by its id, independent of the bot token

`reconcile_nickname(cur, permit, guild_id)` rebuilds a `Permit` whose `identity` is `adapter._rate_identity('bot')`, and
`_admission()` then compares `auth_key` and `credential_key` (a digest of the bot token, `RequestIdentity.make`). After a bot
token rotation (or a changed application id) the comparison fails with `RateCoordinatorUnavailable`, so an uncertain
nickname admission can never be retired (read). The sender-name side keeps the admission id in the connection's edit claim
(`rateAdmissionId`) and can already call a by-id method when it exists (`SenderNames._resolve_admission` uses
`getattr(limiter, 'reconcile_nickname_by_id', None)` first).

Requested method on `SharedPostgresBudget`:

```python
def reconcile_nickname_by_id(self, cur, admission_id, guild_id):
    """Retire one nickname PATCH admission by id after a later live read of the member. No credential comparison."""
```

* Validate `admission_id` as a UUID string and `guild_id` with `_ID`; anything else: `RateCoordinatorUnavailable`.
* `SELECT ... FROM ADMISSIONS WHERE id=%s::uuid AND application_key=%s FOR UPDATE` (no `auth_key`/`credential_key` test).
* Require `method='PATCH'`, `NOT is_publish`, `credential_kind='bot'`, `binding_hash IS NULL`, `intent_id IS NULL`,
  `route_key=_digest('PATCH:/guilds/{id}/members/@me')` and `path_key=_digest(f'/guilds/{guild_id}/members/@me')`. The caller
  is the connection that owns the claim, so a mismatch is a bug or an attack: `RateCoordinatorUnavailable`.
* Idempotent: state `observed` or `blocked` (the terminal states) returns without error and without writing.
* State `reserved`, `sent` or `uncertain`: allowed only when `reserved_at + 120 s <= now` and `expires_at <= now` (the
  existing conditions in `reconcile_nickname`); then the existing `UPDATE ... SET state='observed', outcome_at=clock_timestamp(),
  status_code=NULL, rate_scope='unknown'`. Too young: `RateCoordinatorUnavailable` (the caller retries later).
* `reconcile_nickname(cur, permit, guild_id)` can stay, or delegate here after its own permit checks.
* Tests to add: rotated token resolves; wrong guild refused; a publish admission id refused; an already `observed` and an
  already `blocked` admission return silently; a young `sent` admission refused.
* Sender-name fallback if declined: after `expiresAt + 900 s` the route abandons the local claim (audit
  `discord.sender_name_claim_abandoned`) and leaves the admission to the coordinator. That is the orphan R3 asks you to bound.

## R3 (wanted): a non-publish admission must not count as pending forever

`_pending()` and `_alias_pending()` count every admission in state `sent` or `uncertain` with no expiry bound (read:
`state IN ('sent','uncertain') OR state IN ('reserved','sealed') AND expires_at>...`). A nickname PATCH whose response is lost
(transport exception -> `note_transport_failure` -> `uncertain`, or a process crash after `consume`) therefore subtracts one
slot from the application window and holds the guild's discovery scope until somebody resolves it. The reviewer measured
25 -> 24 for the whole application and a blocked cold route for the guild. The same holds for any other non-publish
request whose response was lost, so this is not nickname-specific, but the nickname route is the first one a customer can
trigger from a settings page.

Requested: an age bound that retires a non-publish `sent`/`uncertain` admission older than, say, `expires_at + 1 hour`
(or the policy's longest window), by whichever mechanism fits the new sliding ceiling (a bounded UPDATE at the start of
`_pending`, or a janitor called from the existing tick). It must keep the "no refund" property: the slot stays spent through
its window; only the open-ended pending count goes away. Publish admissions must stay untouched (they carry intents).

## R4 (wanted, may be out of scope): a 403 on the nickname PATCH should not embargo the guild for the policy lifetime

`_observe_once` sets `row['circuit'] = max(row['circuit'] or 0, self.policy.expires_at)` for any 403/404 on a `route` row
(`rate_limits.py:851-852`). The reviewer measured: one 403 on the nickname PATCH leaves the route circuit open for the whole
policy lifetime (86,339 s in the test; the policy allows up to 31 days) for every request in that guild, including after
the customer has fixed the permission, so the next attempt answers `discord_rate_delayed` for days. A 404 on a member lookup
does the same to `GET:/guilds/{id}/members/{id}`, which is also the bot-member read a post makes (existing behaviour).

Requested for the nickname PATCH route only: a 403 opens a short circuit (the policy's `circuit_seconds`) instead of the
policy lifetime. If that is not possible without redesign, say so and the sender-name side will tell customers that a
refused nickname change can take long to become retryable (it already releases its own claim and never retries by
itself).

* Sender-name mitigation already in place: every foreseeable 403 is refused before the PATCH (person lacks Manage
  Nicknames, role below the bot, bot lacks Change Nickname -> reasons `person_missing_manage_nicknames`, `person_role_below_bot`,
  `bot_missing_change_nickname`), so a 403 on the PATCH itself is a race (the permission changed between the reads and the
  write).

## What the sender-name side relies on that already exists (please keep it)

* `abandon_unsent_nickname(permit)` returning silently for an `observed`/`blocked` admission and retiring a `sent` one as `blocked`.
* A `reserve()` that fails leaving no admission row, and a `consume()` that leaves the admission `reserved` when it raises
  `RateDelayed(permit_expired)`. The route treats an escaping `RateDelayed` as proven unsent (the class docstring says
  "Denied before HTTP") and releases the edit claim at once.
* `Permit` as a frozen dataclass `(id, application_key, method, path_key, identity, binding_hash, expires_at)`: the fallback
  path in `SenderNames._resolve_admission` constructs one.
