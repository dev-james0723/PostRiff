# Q-05 cross-tenant isolation probe — plan and hosted run-sheet

Gate **G4** of `docs/launch-20261023-discord/RELEASE-DEFINITION-v2.md`: before Discord opens to
every customer, two accounts **A** and **B** must show that, in **both directions**, **every
read and every write** aimed at the other tenant is **denied** and has **no side effect**. This
adds the write tests that step 8 of `TESTER-SESSION-SCRIPT.md` lacked, and makes the whole thing
repeatable. No waiver, no deferral past opening (ledger reply 12).

The probe is `scripts/q05_tenant_probe.py` (standard library only). The local validation harness
is `tests/q05_backend.py` + `tests/test_q05_tenant_probe_local.py`; the probe's self-test
(mutation detection) is `tests/test_q05_tenant_probe_mutations.py`; the router coverage tripwire
is `tests/test_q05_probe_coverage.py`.

## 1. The attack matrix

For **each direction** (A attacks B, and B attacks A) the probe runs READ cases and WRITE cases,
using three attack styles:

- **(i) workspace-scope** — the *victim's* workspace id in the path, with the *attacker's* token.
  Hits the shared membership gate (`PostgresWorkspaceRepository.transaction`), expected 403.
- **(ii) IDOR** — the *attacker's own* workspace id in the path but a *victim* object id
  (connection / destination / identity / job). Membership passes; the object is not in the
  attacker's workspace, expected 404/409.
- **(iii) body-field** — a victim workspace/object named in the body (the OAuth `state` of a
  victim transaction; a victim job's approval digest).

Expected result for every attack case: HTTP **403 or 404** (409 is accepted and recorded as a
deny), **no 5xx**, **no victim marker** in the response body (checked in memory against values
learned from the victim's own reads; never printed), and **no change** to either tenant's
before/after snapshot.

| family | method | style | kind | blast | expected |
|---|---|---|---|---|---|
| workspace state (`/workspaces/<id>`) | GET | i | read | — | 403 |
| members / audit / invitations / export / analytics / memory | GET | i | read | — | 403 |
| channel list (`/channels`) | GET | i | read | — | 403 |
| destinations (`/channels/<victim.conn>/destinations`) | GET | ii | read | — | 404/409 |
| discord identity guilds / private-review | GET | ii | read | — | 404/409 |
| mutate `mode` (settings/profile/posts write) | POST `/actions` | i | write | state | 403 |
| mutate `p2_refresh` | POST `/actions` | i | write | **inert** | 403 |
| invite member | POST `/invitations` | i | write | state | 403 |
| remove member | DELETE `/members/<victim.member>` | i | write | state | 403 |
| approve (`p2_approve`) / cancel-pause (`p2_cancel`) | POST `/actions` | i | write | state | 403 |
| discord connect start | POST `/channels/discord/oauth/start` | i | write | state | 403 |
| choose destination | POST `/channels/<victim.conn>/destination` | ii/iii | write | state | 404/409 |
| disconnect connection | DELETE `/channels/<victim.conn>` | ii | write | state | 404/409 |
| remove destination | DELETE `/channels/<victim.conn>/destinations/<victim.dest>` | ii | write | state | 404/409 |
| disconnect identity | POST `/discord/identities/<victim.id>/disconnect` | ii | write | state | 404/409 |
| job execute (publish-now) | POST `/jobs/<victim.job>/execute` | i and ii/iii | write | **send** | 403 / 404 |
| OAuth state completion | POST `/channels/discord/oauth/complete` | iii | write | state | 404/409 |

**Positive controls** (owner succeeds through the same route, so a 404 on an attack can never be
a "route is broken" false pass): workspace GET, members, audit, channels, own destinations, own
identity guilds, and an inert write (`p2_refresh`). A missing or failed control makes that family
**INCONCLUSIVE = failure of the run**.

**No-side-effect proof**: snapshots before and after the attack set, per tenant, through that
tenant's own reads (workspace revision, state projection, and counts of connections, identities,
destinations, jobs, reviews, members, audit). They must be identical. The local harness **also**
takes a database-level snapshot (row counts + `revision` + `max(updated_at)` + revoked counts per
tenant-scoped table) and asserts the mock Discord transport received **zero** message sends.

**Blast labels** — every write case is `inert` (cannot change or send anything even if isolation
failed), `state` (would change victim data), or `send` (could cause an outbound Discord message).
WRITE cases run only with `--allow-writes`; `send` cases additionally need `--allow-send-risk` and
are refused unless the victim is declared synthetic with `--victim-is-synthetic`. **The default
hosted plan (no flags) runs reads only and can never cause a Discord message.**

Routes deliberately not live-attacked are listed, each with a written reason, in
`EXCLUDED_FAMILIES` in the probe (feature flags off at launch — User-Install, engagement,
connection-health, phone, agent, coworker; generic workspace routes that share the one membership
gate; and non-workspace/self routes). `tests/test_q05_probe_coverage.py` fails if any hosted
`/api/workspaces/<id>/…` family is neither in the matrix nor excluded with a reason.

## 2. What needs no Discord connection, and what needs real Discord objects in BOTH tenants

- **No Discord connection required**: every style-(i) workspace-scope case (state, members, audit,
  invitations, export, analytics, memory, actions, invite) and the control reads. These prove the
  membership gate in both directions and can run the moment A and B exist.
- **Needs real Discord objects in BOTH tenants**: the IDOR and body-field cases (destinations,
  identities, private-review, job execute, OAuth state). Each is discovered from the victim's own
  reads; **a case whose victim object cannot be discovered is reported NOT RUN (never PASS)** and
  the run does not meet G4. Full G4 therefore needs each of A and B to have: a linked Discord
  identity, an installed server, an authorized destination, and a draft/scheduled Discord job.
  That requires a build whose connect gate admits A and B
  (`POSTRIFF_DISCORD_CONNECT_WORKSPACES` = `*` or the two workspace ids) and the owner to complete
  the Discord consents for both accounts.

## 3. How the hosted run is performed

The probe is stdlib-only and talks HTTP to one base URL. It is configured **only** through
environment variables; it prints no tokens or ids.

| variable | meaning |
|---|---|
| `Q05_BASE_URL` | the serving deployment origin (e.g. the promoted production URL) |
| `Q05_TOKEN_A`, `Q05_TOKEN_B` | a fresh signed-in access token for each account |
| `Q05_WORKSPACE_A`, `Q05_WORKSPACE_B` | each account's workspace id (from `GET /api/workspaces`) |
| `Q05_EXTRA_HEADER_NAME` / `Q05_EXTRA_HEADER_VALUE` | optional deployment-protection bypass header (never printed) |
| `Q05_VICTIM_A_OAUTH_STATE` / `Q05_VICTIM_B_OAUTH_STATE` | optional: a pending OAuth `state` owned by that account, for the state-binding case; absent ⇒ that case is NOT RUN |

Run it on GitHub Actions or another runner with the `Q05_*` values held as secrets in a protected
**Environment** (not in the repo, not on a build command). Invocation:

```
# default, read-only, both directions:
python scripts/q05_tenant_probe.py --out-md q05-receipt.md --out-json q05-cases.jsonl
# full G4 run (writes), victims are the two throwaway accounts:
python scripts/q05_tenant_probe.py --allow-writes --victim-is-synthetic \
    --out-md q05-receipt.md --out-json q05-cases.jsonl
```

`--allow-send-risk` stays **off** for the hosted gate run: the `send`-blast cases (job execute)
are denied before any dispatch anyway, and the default plan must never be able to send. Enable it
only if the release owner explicitly authorizes it against the declared-synthetic accounts.

Exit code is 0 only if every case that ran passed, no control was inconclusive, and no case that
should have run was skipped for a missing victim object. The receipt says loudly when writes were
not covered or when any case was NOT RUN.

This run must not be done through `vercel deploy` previews or any ad-hoc host; it runs against the
already-promoted, authorized deployment (CLAUDE.md on-demand deployment policy). Opening a hosted
Preview only for this is a last-resort exception the release owner coordinates, with controls
restored immediately after.

## 4. Accounts, cleanup, evidence

- **Accounts**: two throwaway ordinary accounts A and B, each with its own workspace, created by
  the owner through **normal sign-up with no manual allowlisting** (this also exercises the
  open-connect requirement). Reuse the existing tester workspace only as one of them if the owner
  prefers; the second must be a brand-new workspace with no Discord history (H-03).
- **Cleanup**: when isolation holds the probe changes nothing (snapshots identical — that is the
  proof). Afterwards the owner deletes the two throwaway accounts/workspaces and removes Rafii's
  bot from the two test servers (Discord → Authorized Apps), per the tester-session norms.
- **Evidence**: the JSONL (one line per case) and the Markdown receipt — case id, method, route
  **template** (ids masked to `<A.workspace>`, `<B.connection>`, …), direction, kind, blast,
  expected, observed status, verdict, and the aggregate counts. No bodies, tokens, or full ids.
  File the receipt and the exit code in the ledger as the G4 evidence.
