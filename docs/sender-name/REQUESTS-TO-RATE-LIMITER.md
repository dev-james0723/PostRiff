# Requests to the owner of `discord/rate_limits.py` (sender names)

The sender-name branch (`claude/discord-rc2-sendername-20261023`) does not edit `rate_limits.py`. Every item below has a tested
fallback on the sender-name side, so none of them blocks the release; R1 and R2 are the ones worth taking.
"Measured" = the independent reviewer on a disposable PostgreSQL (SNR-2, SNR-5, SNR-6); "read" = exact code reading of 5a94b4f2.

The only Discord write the feature makes is `PATCH /guilds/{id}/members/@me` (the shared bot's server nickname), through
`DiscordProvider._bot` -> `_discord_http` -> `reserve` -> `consume` -> transport -> `observe`. The webhook name needs no extra request.

## R1 (needed): admit the nickname route only while its capability is on

`route_identity()` allows `'PATCH:/guilds/{id}/members/@me'` unconditionally (line 156); the product ships with the capability OFF.
Change: that one template is admissible only when `os.environ.get('POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED') == 'true'`, read at
call time (no import-time read, no cache, only the exact string `true`); otherwise `raise RateCoordinatorUnavailable()` like any
non-allowlisted route. Do not apply the flag in `observe`, `abandon_unsent_nickname`, `reconcile_nickname` or R2: they act on
admissions that already exist and flag-off must not strand them. Test: unset, `false`, `1`, `True` raise; `true` returns the template.

## R2 (needed): retire a nickname admission by id, independent of the bot token

`reconcile_nickname(cur, permit, guild_id)` goes through `_admission()`, which compares `auth_key` and `credential_key` (a digest of
the bot token). After a token rotation it raises forever, so an uncertain nickname admission can never be retired (read). The route
keeps the admission id in the connection's edit claim and already prefers this method when it exists
(`getattr(limiter, 'reconcile_nickname_by_id', None)` in `SenderNames._resolve_admission`).

```python
def reconcile_nickname_by_id(self, cur, admission_id: str, guild_id: str) -> None:
```

* `admission_id` a UUID string, `guild_id` matching `_ID`; anything else: `RateCoordinatorUnavailable`.
* `SELECT ... FROM ADMISSIONS WHERE id=%s::uuid AND application_key=%s FOR UPDATE`; no `auth_key`/`credential_key` comparison.
* Require `method='PATCH'`, `NOT is_publish`, `credential_kind='bot'`, `binding_hash IS NULL`, `intent_id IS NULL`,
  `route_key=_digest('PATCH:/guilds/{id}/members/@me')`, `path_key=_digest(f'/guilds/{guild_id}/members/@me')`; else `RateCoordinatorUnavailable`.
* Idempotent: state `observed` or `blocked` returns without writing.
* State `reserved`, `sent`, `uncertain`: only when `reserved_at + 120 s <= now` and `expires_at <= now` (the conditions already in
  `reconcile_nickname`), then the existing `UPDATE ... SET state='observed', outcome_at=clock_timestamp(), status_code=NULL,
  rate_scope='unknown'`; too young: `RateCoordinatorUnavailable`.
* Tests: rotated token resolves; wrong guild refused; a publish admission refused; `observed` and `blocked` return silently; a young `sent` refused.

Without R2 the route abandons its local claim after `expiresAt + 900 s` (audit `discord.sender_name_claim_abandoned`) and the
admission stays `uncertain` (R3).

## R3 (wanted): a non-publish admission must not count as pending forever

`_pending()` / `_alias_pending()` count every admission in state `sent` or `uncertain` with no expiry bound (read). A nickname PATCH
whose response is lost (transport exception -> `uncertain`, or a crash after `consume`) keeps subtracting one slot from the
application window and holds the server's discovery scope (measured: application window 25 -> 24, cold route blocked). Requested: an
age bound (for example `expires_at + 1 hour`) that retires such a non-publish row, keeping the no-refund property (the slot stays spent
through its window) and leaving publish admissions untouched. Not nickname-specific, but the nickname route is the first one a
customer can trigger from a settings page.

## R4 (wanted; say no if it needs redesign): a 403 on the nickname PATCH should not embargo the server for the policy lifetime

`_observe_once` sets `row['circuit'] = max(row['circuit'] or 0, self.policy.expires_at)` for any 403/404 on a route row (lines 851-852).
Measured: one 403 on the nickname PATCH leaves that route's circuit open for the whole policy lifetime (86,339 s in the test, up to 31
days) for the server, so after the customer fixes the permission every retry answers `discord_rate_delayed`. Requested for the nickname
PATCH route only: a 403 opens a short circuit (`policy.circuit_seconds`). Mitigation already in place: every foreseeable 403 is refused
before the PATCH (`person_missing_manage_nicknames`, `person_role_below_bot`, `bot_missing_change_nickname`), so a real one is a race.

## Please keep (the route relies on them)

* `abandon_unsent_nickname(permit)`: silent for `observed`/`blocked`, retires `sent` as `blocked`.
* `reserve()` failing without leaving an admission row; `consume()` leaving the admission `reserved` when it raises
  `RateDelayed(permit_expired)`. An escaping `RateDelayed` is treated as proven unsent ("Denied before HTTP") and the claim is released at once.
* `Permit` as a frozen dataclass `(id, application_key, method, path_key, identity, binding_hash, expires_at)`.
