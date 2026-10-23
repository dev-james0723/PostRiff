# Q-05 probe — local validation results

What was run locally, against the exact RC1 source, to show the probe works and can see a hole.
The hosted run against the promoted deployment is a separate step (see `PLAN.md`); it is **not**
part of this local validation.

- **Source under test**: RC1 = commit `2a5a523d788eef67a5c7dbed609a98efa6650eef`
  (branch `claude/discord-launch-rc-20261023`), read unmodified from this worktree's `src/`.
- **Database**: a throwaway PostgreSQL 16 cluster (binaries `/usr/lib/postgresql/16/bin`) in a
  temp dir, loaded with `tests/phase2/rls.sql` plus the Discord migrations rls.sql omits
  (124, 125, 126, 128, 131). No hosted credentials are read; the cluster is deleted on exit.
- **Application**: the real `HostedWorkspaceService` + `HostedApplication`, served over loopback
  HTTP (`wsgiref`), with stub authentication (two bearer tokens → two Supabase principals, the
  pattern the existing `tests/phase2/postgres_isolation.py` and `postgres_discord_authorization.py`
  use) and a mock Discord transport (`LifecycleWire` from the existing Discord tests; no real
  network).
- **Tenants**: A and B, each created through the app's own code paths — `bootstrap` → Discord
  identity link → server installation → authorized destination → a scheduled Discord job — plus a
  pending OAuth transaction per tenant for the state-binding case.

## How to run

```
# full local run (spins its own disposable cluster; ~10s):
python -m unittest tests.test_q05_tenant_probe_local

# mutation detection (~30s) and the no-DB coverage tripwire:
python -m unittest tests.test_q05_tenant_probe_mutations
python -m unittest tests.test_q05_probe_coverage

# no-DB unit tests (redirect safety, A!=B guard, strict scope scoring) — run everywhere:
python -m unittest tests.test_q05_probe_unit
# no-DB: the real probe against a loopback fake of two FRESH accounts (no Discord identity, members
# ordered like the app) — smoke passes, gate fails as undiscovered, member_remove targets only the owner:
python -m unittest tests.test_q05_probe_fresh

# or drive the backend directly and read the JSON result:
python tests/q05_backend.py run --allow-writes --allow-send-risk --victim-is-synthetic

# any other checkout (e.g. a detached export of the RC2 integration tip):
#   git archive <sha> src tests migrations | tar -x -C <dir>; echo <sha> > <dir>/SOURCE_SHA
Q05_TARGET_ROOT=<dir> python -m unittest tests.test_q05_tenant_probe_local tests.test_q05_tenant_probe_mutations
```

Use a Python that has `psycopg` (this work used `/opt/prvenv/bin/python`; any venv with psycopg 3
works). The database-backed modules **skip cleanly** (not error) when the PostgreSQL 16 binaries or
psycopg are absent, so they run under `python -m unittest discover -s tests`; `test_q05_probe_unit`
and `test_q05_probe_fresh` need no database and always run.

## Result on clean RC1 source

Full run (`--allow-writes --allow-send-risk --victim-is-synthetic`): **probe exit 0**.

- 66 cases, **66 PASS, 0 FAIL, 0 NOT RUN, 0 INCONCLUSIVE**.
- Reads 22, writes 28 (blast: 22 state, 4 send, 4 inert across kinds), controls 14 + 2 snapshot.
  By attack scope: **32 workspace-scope + 18 IDOR/body-field** cases, the rest controls/snapshots.
- Both directions (A→B and B→A) covered.
- **Strict scoring held** on clean RC1:
  - every **workspace-scope** attack got **403 `Workspace unavailable.`** *and* was **differential**
    — the 16 ws-scope writes each re-sent the byte-identical request as the attacked workspace's
    **owner**, who got **past** the gate (a stale-revision `409`, owner-cannot-be-removed `409`, or
    success); no case passed on a bare 403;
  - every **IDOR / body-field** attack got **404 / 409** with a known object-scoping deny body;
  - no 2xx, no 5xx, no victim marker in any body; nothing scored INCONCLUSIVE.
- **A≠B guard**: the probe refused to start when the two tokens resolved to the same `sub` or the
  same workspace (checked in `tests/test_q05_probe_unit.py`).
- No-side-effect proof: both tenants' before/after snapshots identical (the owner `p2_refresh`
  control bumps only its own workspace revision by 1, which is not a tenant-data change).
- **Database-level** snapshot: no row-count, `updated_at`, `max(updated_at)`/newest-audit-id, or
  revoked-count change on either tenant.
- **Mock Discord transport: zero message sends** for the whole run.

Read-only default run (no flags): exit 0; every write case **NOT RUN (gated)**; zero Discord
sends — confirming the default plan cannot cause a Discord message.

## Mutation table (probe self-test)

Each mutation disables/weakens one control in a throwaway copy of `src/` on `sys.path` (no tracked
file edited), then the full probe runs against the mutated app. Observed:

| mutation | control removed | probe exit | cases that turned FAIL | how detected |
|---|---|---|---|---|
| **M1** | workspace membership gate (`transaction` WHERE → `OR TRUE`) | 1 | **30 FAIL** = 16 ws-scope reads + 12 ws-scope writes + 2 snapshot controls (the remaining ws-scope writes score INCONCLUSIVE, never PASS) | HTTP 200 + victim marker on reads; 2xx / state change on writes; the differential flips (attacker now gets *past* the gate just like the owner); no-side-effect snapshot (API + DB) fires |
| **M1b** | same gate removed, writes on / send off — **invariant check** | 1 | **0 of 32** workspace-scope cases PASS; 28 of 30 non-send ws-scope cases FAIL, the other 2 INCONCLUSIVE | proves the old bug is gone: no ws-scope read or write may silently PASS on an object check when the gate is removed (`test_m1b_gate_removed_fails_every_workspace_scope_case`) |
| **M2** | connection/credential → workspace binding (every credential read on the path) | 1 | `read.idor.destinations.A→B`, `…B→A` | destinations IDOR returns HTTP 200 leaking the victim's connection — probe flags 2xx + marker |
| **M3** | OAuth transaction → workspace+member binding (`complete` SELECT + `row[1]!=actor` + `validate_context` + `save_identity`) | 1 | `snapshot.no_side_effect.A`, `…B` | cross-tenant completion advances far enough to commit a side effect (victim OAuth transaction consumed + an audit row); the no-side-effect proof (API + DB) catches it although the HTTP status is 409 |
| **M5** | atomicity of a denied write — a committed workspace-blind credential revoke that then returns 404 | 1 | DB-side-effect flagged on both tenants (+ the victim-owner's own control breaks) | the HTTP status looks denied and the **state JSON is unchanged, so the API-level snapshot alone misses it**; the **DB-level** snapshot (`revoked`/`updated_at`) catches it — exactly the case the harness DB proof exists for |
| **M4** | intra-workspace permission requirement (`permissions.require` → no-op) — **negative control** | 0 | none (correctly) | cross-tenant isolation does not depend on intra-workspace RBAC; the probe correctly does not flip. Intra-workspace RBAC is covered separately by `tests/phase2/postgres_isolation.py` §4 |

Every substantive mutation (M1, M2, M3, M5) is detected on at least one read and/or write and via
the no-side-effect proof where relevant; the probe is not a no-op that always passes. M4 is a
deliberate negative control documenting the probe's scope.

A notable positive finding while building the mutations: the connection/credential → workspace
binding and the OAuth completion are enforced **redundantly** (several independent
workspace-scoped checks + the fact that Discord objects live in per-workspace state JSON). A
single-line fault does not open cross-tenant access; M2 and the full M3 each had to remove the
binding at **every** enforcement point to create a visible hole. This defence-in-depth is good,
but it also means a reviewer must not assume one check is "the" gate.

## Honest limits — what this local run does NOT prove

- **Supabase RLS / roles**: `rls.sql` builds a minimal role harness and the local database role is
  an owner/superuser that **bypasses row-level security**, so the local run cannot test RLS as the
  `authenticated` pooler role enforces it in production. (`rls.sql` has its own in-SQL RLS block for
  the two seed users; this probe does not re-exercise it.) RLS through the real Supabase
  transaction pooler must be verified on the hosted run.
- **The Vercel / edge layer**: the origin/app-guard, deployment-protection bypass, forwarded host
  and proto handling, and any edge rewrites are not exercised locally (served by bare `wsgiref`).
- **Production configuration**: real Discord flag values, the shared rate coordinator (P4),
  production env, and the promoted build's gate value are not what the local harness sets. The
  local harness turns Discord v2 flags on with a mock transport to exercise the connect/IDOR paths;
  the launch build has several Discord sub-features off (see `EXCLUDED_FAMILIES`).
- **Stub auth**: tombstone/revocation/MFA checks in the real Supabase verifier are stubbed out
  locally; the local run proves the workspace membership + object-binding isolation, not the
  identity verifier.
- **Not all object-id families are live-attacked locally**: library, media, ideas, audience,
  connectors, and YouTube take object ids but are excluded with reasons (resolved only inside
  `repository.transaction(workspace, token)`); they are recommended as additional live IDOR cases
  for defence in depth (see `PLAN.md` / `EXCLUDED_FAMILIES`).

The hosted run (PLAN.md) is what closes G4; this local run shows the probe is correct and
sensitive before it is pointed at the real deployment.
