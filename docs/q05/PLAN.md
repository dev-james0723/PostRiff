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

Expected result for every attack case, scored **strictly** (a denial must be the *isolation*
control denying, not any refusal):

- **workspace-scope (style i)** passes **only** on **403** whose body is the membership-gate
  message `Workspace unavailable.` — and only if the case is also **differential**: the owner of
  the attacked workspace, sending the byte-identical request, gets **past** the gate (a different
  error, e.g. a stale-revision `409`, or success). If the owner is *also* gated the route is
  simply broken and the case is **INCONCLUSIVE**, not a pass. A `404`/`409` on a ws-scope attack is
  a **FAIL** (the gate was not the thing that denied).
- **IDOR / body-field (styles ii, iii)** pass **only** on **404** or **409** whose body is one of
  the known object-scoping denials (`Connection unavailable.`, `This item is not available in your
  workspace.`, `This Discord identity is unavailable to this workspace member.`, `Connection
  request unavailable.`). Any other body is **INCONCLUSIVE**.
- A **2xx**, or a response carrying a **victim marker** (checked in memory against values learned
  from the victim's own reads; never printed), is a **FAIL**.
- **401 / 429 / 400 / 405 / 410 / 415 / any 5xx / a 3xx / HTML** are **INCONCLUSIVE — never a
  deny** (they mean auth expired, rate-limited, step-up, or the route misbehaved; none of them
  proves isolation). A run with any INCONCLUSIVE case does not meet G4.

And, for every attack: **no change** to either tenant's before/after snapshot.

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

**Differential ws-scope writes.** For every workspace-scope **write** the probe also sends the
byte-identical request as the **owner of the attacked workspace**. The attack passes only if the
attacker is stopped at the membership gate (`403 Workspace unavailable.`) *while the owner gets
past it* (a different outcome — a stale-revision `409`, an owner-cannot-be-removed `409`, or
success). If the owner is blocked too, the route itself is broken and the case is **INCONCLUSIVE**,
never a pass — this is what stops a blanket `403` (WAF, auth, a disabled route) from masquerading
as working isolation. A≠B is enforced up front: the probe refuses to run if the two tokens resolve
to the **same user (`sub`)** or the **same workspace**.

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

### Customer Discord sender names (RC2)

`GET`/`POST /api/workspaces/{ws}/channels/{conn}/discord-sender-name` (contract:
`docs/sender-name/UI-API-CONTRACT.md` on the sender-name branch), both directions, per sender kind
(incoming webhook, bot installation), scored like the rest of the matrix:

- **read, write, clear, replay** of the victim's settings through the victim's workspace id (the
  membership gate) and through the attacker's own workspace with the victim's connection id (the
  connection lookup): `ws_scope`/`idor` reads and writes, a write and a **clear** (`reset`) carrying the
  victim's REAL current fingerprint, mixed ids, malformed connection and workspace ids;
- **learn**: every gate and IDOR case is compared with a never-existing id (same status, code and the
  WHOLE body, so no extra field, reason or retry time differs), sender-name reads also on timing (a few
  alternating pairs; a case fails only if every victim-id answer is slower than every twin answer by more
  than 25 ms), victim markers in any response, and the attacker's own audit after the attacks;
- **same workspace**: viewer and editor (refused before anything is read), removed member (the gate),
  connection manager and admin who did not install the bot (bot nickname: read-only, refused; webhook
  name: any connection manager may edit per the contract, a never-current fingerprint is refused);
  these need other members and run in the local harness; a hosted run reports them NOT RUN (local-only);
- owner controls after the attack phase (own read, stale fingerprint, a reserved-word name, save /
  stale replay / restore), which also serve as the deferred owner differentials.

Locally the probe marks its attack phase and the harness proves that in exactly that phase neither
tenant changed (revision delta 0) and the mock Discord saw no request at all. After the probe the
harness runs four send-level scenarios through the real app and two concurrent real workers against the
mock Discord (`tests/q05_sender_scenarios.py`): name pollution, switch-off hold, single-installation
nickname authority (both directions and three concurrent orders), and the nickname hold after an
admin-side rename. Mutations S1 to S5 in `tests/test_q05_tenant_probe_mutations.py` delete each guard
and must be detected.

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
  - **The Discord objects must not be sendable while the probe runs.** Use drafts and
    pending-review objects wherever possible, and make any scheduled Discord job **not due** —
    schedule an approved job **at least 7 days out** and **cancel it after the run** — so that even
    a mistakenly-accepted cross-tenant write (which the probe would catch as a FAIL) still cannot
    post a real message. `--allow-send-risk` remains off regardless; this is defence in depth for
    the one route (`job execute`) whose blast is `send`.

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
# writes, both directions (no send; the hosted gate run uses exactly this):
python scripts/q05_tenant_probe.py --allow-writes \
    --out-md q05-receipt.md --out-json q05-cases.jsonl
```

`--allow-send-risk` (and its guard `--victim-is-synthetic`) stay **off** for the hosted run: the
`send`-blast case (job execute) is denied before any dispatch anyway, and the hosted runner must
never be able to send a Discord message. Those two flags exist for a **local**, owner-authorized
run against declared-synthetic accounts only; the hosted workflow never passes them.

Exit code is 0 only if every case that ran **passed**, **no case was INCONCLUSIVE**, no control
was inconclusive, and no case that should have run was skipped for a missing victim object. The
receipt says loudly when writes were not covered or when any case was NOT RUN or INCONCLUSIVE.

### The hosted path (`docs/q05/hosted/`)

`docs/q05/hosted/q05-hosted-run.yml` is an **inert** GitHub Actions workflow (it lives only under
`docs/`, never under `.github/`, until the owner installs it) that runs the probe against the live
site under owner approval. It does **not** deploy, build, promote or change any setting. Its
hardening, relevant to this plan:

- **Credentials are single-use e-mail OTP codes only** — no password grant, no dashboard-created
  users, no pasted session tokens. The owner requests a code on the website, puts it in a
  short-lived Environment secret, and the workflow exchanges it at the fixed Supabase
  `POST /auth/v1/verify`. The base URL and Supabase URL are **hard-coded in the workflow**; a
  request branch carries only a SHA and a mode, so editing a request can never redirect credentials.
- **The probe is SHA-pinned and pinned to its REVIEWED hash.** Every probe change gets an
  independent delta review; the review record carries the probe's full sha256. The request maker
  **requires** that value as `--reviewed-probe-sha256 <64 hex>` (the Release Captain supplies it; it
  is never derived from the request's own SHA) and refuses to build when the probe at the SHA
  differs. The workflow accepts only a full 64-hex `probeSha256` and refuses a fetched probe whose
  hash is not exactly that value.
- **The probe runs under a minimal environment** (only `PATH` and the `Q05_*` it needs, built with
  shell builtins and self-checked) and `python3 -I`, so no inherited secret or local module can
  reach or influence it.
- **No secret on a command line.** E-mails, codes, the key and session tokens reach `curl` and `jq`
  only through private header files (`-H @file`) and stdin, never argv.
- **Key and e-mail hygiene are enforced in the workflow too**: the key is an allowlist — only the
  publishable key (`sb_publishable_…`) or a JWT whose role is `anon`, after trimming; anything else
  (a secret key, a `service_role` or `authenticated` JWT, an unknown shape) is refused before any
  request. Both throwaway e-mails must carry the `q05` marker. In gate mode the serving build is
  checked **before** any one-time code is spent, and the sign-out trap is installed before minting.

**generic vs gate mode (M6).** A **generic** run is a `--smoke` run of **whatever build is serving
right now**; the step summary prints that build's `/api/health` `sourceRevision`. On the build live
today (`c5fc1fd1`) `sourceRevision` is **`null`** (no Discord v2), so a generic run smoke-tests
*that* build and is **not** G4 evidence for RC1/RC2. A **gate** run pins the promoted build's
`expectSourceRevision` in the request; the workflow reads `/api/health` and **refuses to run** if
the serving build does not match, so gate evidence is always tied to the exact reviewed build. The
serving `sourceRevision` is read **before and after** the run; if it changes mid-run the result is
void.

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
