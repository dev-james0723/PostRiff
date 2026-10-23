# Discord custody fixes (G2 early review, lane G2A): operator notes

Branch `claude/discord-rc2-g2a-fixes-20261023`. Source of the findings: the two independent early reviews of `150ab4fa`
(IDs `G2E-A-nn` and `G2E-C-nn`). This file is for whoever runs, reviews or merges the lane; it adds no runbook step that
changes production by itself, and nothing here was run against production.

## 1. Migration 126: the owner of the projection objects must bypass row-level security (G2E-A-10)

`pr_discord_workspace_projection_trg` fires AFTER every INSERT or UPDATE OF state, revision on `public.pr_workspaces`. Its
function and `pr_discord_projection_refresh` are `SECURITY DEFINER` and write `public.pr_discord_worker_projection`, a table
with `ENABLE` and `FORCE ROW LEVEL SECURITY` and a policy for `service_role` that grants SELECT only. A definer function runs
as its owner, and a FORCE-RLS table applies its policies to the table owner too, so the INSERT succeeds only when the owner
is a superuser or has BYPASSRLS. On Supabase the `postgres` role has BYPASSRLS, so the migration is sound there if the objects
were created by that role. If they were created or later re-owned by a role without BYPASSRLS, EVERY update of a workspace's
`state` or `revision` fails ("new row violates row-level security policy"): no post, no approval, no connection change, for
every tenant. Whether the production owner is correct has not been verified (no production access in this lane).

Read-only check to run once against the target database before the launch and after any migration or role change:

```sql
SELECT 'table ' || c.relname AS object, r.rolname AS owner, r.rolsuper, r.rolbypassrls
  FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
 WHERE c.relnamespace = 'public'::regnamespace AND c.relname = 'pr_discord_worker_projection'
UNION ALL
SELECT 'function ' || p.proname, r.rolname, r.rolsuper, r.rolbypassrls
  FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
 WHERE p.pronamespace = 'public'::regnamespace
   AND p.proname IN ('pr_discord_projection_refresh', 'pr_discord_workspace_projection_trigger');
```

Every row must show `rolsuper` or `rolbypassrls` true. If one does not, stop: fixing it needs `ALTER ... OWNER TO` by a role that
can, which is a database change this lane did not write (no migration was added). The check and the failure mode are
reproduced on a disposable cluster by `tests/phase2/postgres_discord_custody.py` (`a10_*`): with the objects re-owned to a
role without BYPASSRLS a workspace update fails and the query above flags it.

## 2. Rotating `POSTRIFF_CREDENTIAL_KEY` forces every tenant to reconnect (G2E-A-12)

`CredentialVault` holds ONE Fernet key. Each ciphertext is stored with `key_id`, the first 12 hex characters of the SHA-256 of
the key. `decrypt` refuses any other `key_id` with 409 "This account needs to be reconnected." There is no key ring and no
re-encryption path. Setting a new `POSTRIFF_CREDENTIAL_KEY` therefore makes every stored credential of every provider
undecryptable at once: Discord identities, installations and webhook tokens, and every other connected account; open
connect-flow state (`pr_oauth_transactions.verifier_ciphertext`) as well. Workers hold the affected posts; each customer must
reconnect each account, and a Discord installation also needs its identity linked again first. Treat a key change as a
product-wide incident, never as routine hygiene:

- rotate only for a suspected key compromise, announce it first, and expect support load proportional to the connected accounts;
- a safe rotation needs code that does not exist yet (a read ring keyed by `key_id` that decrypts with the old key and
  re-encrypts under the new one); it is not part of this lane;
- the old key must stay recoverable until the last row is re-encrypted, otherwise nothing can be restored.

## 3. What the lane changes that an operator can observe

| Finding | Behaviour now | Where to look |
|---|---|---|
| A-01 | Only Discord's own JSON refusal (its `{message, code}` error, or `invalid_grant`) revokes an identity and its servers. An HTML/WAF page, a 5xx or a lost connection changes nothing (503). A 5xx or lost connection DURING the rotating refresh closes the identity (`reconnect_required`) and SUSPENDS its servers: `capabilityVerified=false`, `discordSuspended=true`; credentials untouched. | `DiscordProvider.is_discord_denial`, `_fresh_identity` |
| A-01 resume | The same Discord user linking again restores the identity's consent generation and unsuspends its servers; each still needs one Verify. | `save_identity` |
| A-04 | A refresh claim older than 360 s (`REFRESH_CLAIM_TTL`, above the 300 s function limit) is reaped into the same suspension on next use, with no Discord request. A spent token's settle is retried 3 times, then made visible. | `_fresh_identity` |
| A-02 | Re-verification checks the authorizer before any Discord request. A gone authorizer flips the card once (`discordAuthorizerGone`) and later passes do nothing. | `reverify_installation`, `_authorizer_gone` |
| A-03 | Removing a member, a member leaving, or dropping below `manage_connections` disconnects their identities and zeroes their credentials in the same transaction. A manager may disconnect an identity whose authorizer is no longer an active manager. | `disconnect_member`, `hosted._drop_member_discord` |
| A-05 | Reads that reach Discord are limited to 30/min per member and 120/min per workspace (counted before any request); one read per connection at a time; channel list and re-check answers reused for 45 s (10 s while the connection is unhealthy). Limits are constants at the top of `discord/oauth.py`. | `admit_read`, `read_through` |
| C-03 | Manual drafts: 60,000 characters per save (text length x destinations), 2,000 manual variants and 12 MB of state per workspace, 30 saves/min/workspace. | `manual_drafts.py` |
| C-05 | At most 30 servers per workspace and 15 per member (a disconnected server still counts). | `DiscordConnections.server_ceiling` |

Read-only queries for an incident (workspace JSON; run with the usual read access):

```sql
-- identities waiting for their person to link again, and servers suspended behind them
SELECT w.id, l->>'id' AS identity, l->>'status' AS status
  FROM public.pr_workspaces w, jsonb_array_elements(coalesce(w.state#>'{phase2,discordIdentityLinks}','[]')) l
 WHERE l->>'status' = 'reconnect_required';
SELECT w.id, c->>'id' AS card
  FROM public.pr_workspaces w, jsonb_array_elements(coalesce(w.state#>'{phase2,channels}','[]')) c
 WHERE c->>'discordSuspended' = 'true' OR c->>'discordAuthorizerGone' = 'true';
```

## 4. Half-carried code reviewed for deletion (G2E-C-11): nothing deleted

Both candidates are dead, and neither is "clearly unused and unreferenced", so neither was removed:

- `src/postriff_phase2/connection_review.py`. Its only caller is a guard in `DiscordConnections.adapter` that cannot fire:
  `adapter.connection_review` is never assigned in `src/` (the producer was not carried; `login_configs` likewise). Deleting
  the module and that two-line guard is behaviour-neutral. It is pinned deliberately by the RC2 team:
  `tests/test_rc2_shared_path_fixes.py::test_no_other_facebook_code_differs_from_live` asserts the file exists as the only
  Facebook line left in the difference to live, and `docs/RC2-SHARED-PATH-FIXES.md` item 7 records it as inert. Deleting it
  means changing that test and that document.
- `nativeScheduleAt`. Never written. Readers: `store.py` (approval's `nextAt`) and `hosted_worker.py` (the worker's
  `native_scheduled` branch), plus a frozen copy of the worker in `tests/phase2/fixtures/hosted_worker_2a5a523d.py.txt`. The
  worker file belongs to the W-02 successor, so only the `store.py` reader could be removed from this lane, which would
  leave the pair half-removed.
- Related and also inert (RC2 document item 4): `linkedin_reverify = False` without its setter.

Suggested follow-up, one commit by whoever owns the RC2 document: remove all three together with their pinning assertions.
