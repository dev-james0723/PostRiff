# PostRiff migration numbering

Owner decision, 2026-09-25. It covers `migrations/postriff/NNN_*.sql` on every branch. Pick numbers from this file, and update it in the same change that adds a migration.

## Reserved numbers

| Number | Files | Owner | State |
|---|---|---|---|
| 001–019 | existing chain (003 is local-only) | — | See "Production shape" below: not every one of them is applied in production. |
| 020–022 | `020_credit_quotes`, `021_credit_purchases`, `022_credit_payment_lifecycle` | credits (PR #2) | **Applied in production** (according to the release session and its local runner logs). Permanently occupied. |
| 023 | none | — | Retired; never reuse it. The runner accepts gaps. |
| 024–025 | `024_notification_core`, `025_coworker_evidence_growth` | Rafii Adaptive Social Coworker (`ecb3ff3`) | Local only. Do not renumber them unless a real dependency requires it. |
| 026–029 | ai-routing's four migrations, renumbered from 020–023 | ai-routing | Reserved. The files still carry 020–023 on `ai-routing` and must be renamed before that branch lands (checklist below). |
| 030 and up | — | next new migration | Free. |

## Inventory (scan of 2026-09-25, after `git fetch origin`)

- 020–022 (credits): `origin/consumer-saas`, `origin/raffi/agent-runtime-merge`, `origin/raffi/launch-final`, `origin/raffi/site-agent-release`, `origin/fix/channel-lifecycle` and their local branches, plus `feat/time-back-mvp`, `release/pr2-reconcile`, `release/pr2-update` and `rafii/integration-runtime-coworker`.
- 020–023 (ai-routing's own files, same numbers): only the local `ai-routing` branch and its worktree. There is no remote branch.
- 024–025: only `rafii/coworker-wp0-wp11` and `rafii/integration-runtime-coworker`.
- 026–035: unused on every local and remote ref, in every worktree's `migrations/postriff/` (tracked or not) and in the stash.

Re-run this before choosing or applying any number:

```sh
git fetch origin
for ref in $(git for-each-ref --format='%(refname:short)' refs/heads refs/remotes); do
  git ls-tree --name-only "$ref" migrations/postriff/ | sed "s#migrations/postriff/##" | grep -E '^0(2[0-9]|3[0-9])_' | sed "s#^#$ref #"
done | sort -k2
git worktree list --porcelain | awk '/^worktree /{print $2}' | while read wt; do ls "$wt/migrations/postriff" 2>/dev/null | grep -E '^0(2[0-9]|3[0-9])_' | sed "s#^#$wt #"; done
```

## How the runner treats numbers

`scripts/postriff_migrate.py`:
- refuses two files with the same number in one tree ("Duplicate migration numbers");
- applies pending files in file-name order and accepts gaps;
- refuses a database whose ledger lists a migration the branch lacks, or whose checksum differs from the file. Never rename or edit an applied file;
- refuses a database that has the schema but **no ledger** ("explicit reviewed baseline adoption is required").

**Production has no ledger** (`docs/design/rafii-v9/migrations-review.md`). So production migrations do not go through `postriff_migrate.py`. They go through one-off, never-aliased runners pinned to each file's sha256, the way 018, 019 and 020–022 were applied. Build the next runner from the post-fix 020–022 runner: prepared statements off, one transaction per file, sha256 pins, snapshots before and after.

## Production shape (as recorded)

- 001, 002 and 004–013 are treated as present: 010–012 are not listed as missing in the 2026-09-24 check, and 013 had no legacy rows left to rewrite. Verify read-only before the next production migration.
- 014 and 015 policies: absent. 016 (`pr_api_tokens`): absent on purpose, pending the API-token decision. 017: not widened.
- 018 and 019: applied with one-off runners. 020–022: applied, per the release session.
- `docs/launch-20260923/FINAL-BILLING-MATRIX.md:7` still says 020–022 are applied nowhere. It is stale; its owner should correct it.

## Apply order (each step needs the owner's authorization)

1. **Coworker:** 024, then 025. Staging first, then production, and **before** any build containing the coworker code is deployed there. Account deletion deletes from the 024/025 tables whatever the flags say. Production-shaped rehearsal (2026-09-25, disposable PostgreSQL 17 without 014–017 and without a ledger, with 018–022):
   - both apply cleanly, and applying both again is a no-op;
   - the 10 new tables have forced row-level security and no `anon` or `public` grants;
   - `pr_reply_drafts_origin_check` becomes `manual | ai_fixture | copilot`;
   - the credit tables are untouched.
2. **ai-routing:** 026, 027, 028, 029, only after the renumbering below, and before deploying its code.

## Test loader (`tests/phase2/rls.sql`)

It loads 001, 002, 004–012, 018, 019, then 024 and 025 (and later 026–029). **Never** add 020–022: the credit PostgreSQL tests and `scripts/launch_credit_fixture.py` apply those themselves.

## ai-routing renumbering checklist (later, when that stage is authorized)

1. Re-run the inventory above. If 026–029 are no longer all free, use the next free contiguous range and update this file.
2. Confirm that ai-routing's 020–023 were never applied to any shared database (staging or production ledger, or the runner records).
3. `git mv` the files: `020_ai_routing` → `026_ai_routing`, `021_ai_connections` → `027_ai_connections`, `022_mcp_connector` → `028_mcp_connector`, `023_companion_relay` → `029_companion_relay`.
4. Update every in-file reference:
   - `tests/phase2/rls.sql` lines 26–29 on ai-routing: `\ir` 026–029, after 025;
   - `docs/ai-routing/README.md:40` ("migration 020");
   - `src/postriff_phase2/ratelimit.py:4` ("migration 022", which becomes 028);
   - the untracked ai-routing docs in its worktree (`migration-rollback.md`, `route-contract.md`, `developer-setup.md`).
5. Run the full chain 001–029 on a disposable PostgreSQL, and the production-shaped rehearsal. Then staging, then production.
6. ai-routing is a stale fork (September 17–20) of lines already merged into `consumer-saas`, so bring it up to date before any of this.
