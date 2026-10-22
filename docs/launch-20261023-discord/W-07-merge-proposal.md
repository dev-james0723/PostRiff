# W-07 Proposal: stop re-deriving the release candidate every time

Proposal only. Nothing here is a merge, a push to a shared branch or an instruction to another lane. It needs the owner's decision and each lane's own agent.

## The problem this launch exposed

Production has been served by CLI builds of whichever lane deployed last. In five days the alias moved from a Discord-repair build (10-19, 10-20) to a LinkedIn build, then to Mastodon builds (10-21, 10-22), each shipping one lineage and dropping the others (`S-01-lineage-report.md`). `rafii.io` today has no Discord v2 code although the database has its migrations. Every lane's branch forked from a different point of `consumer-saas`, so no single branch contains what customers had a day earlier. The release candidate for Discord therefore had to be derived by hand (a merge of the live line and the Discord line with eleven conflicted files).

## Proposed rules, cheapest first

1. **One production alias, one release owner.** Only the release owner runs `vercel promote`. Lanes deliver SHA-pinned candidates (as the cost-control policy already says); nobody deploys a lane head to production directly.
2. **A candidate must contain the live commit.** Before any promotion run `scripts/rc_superset_proof.py --live <live sha> --rc <candidate>`. It fails on a dropped file, a lost line, a missing route, cron, migration, flag name or test. It reads git objects only and costs seconds. Add it to the promotion checklist (and, if wanted, as a required check on candidate branches).
3. **Record the live SHA.** CLI builds carry no git metadata and `/api/health` reports `sourceRevision: null` on the live lineage. Pass `--meta rafiiSourceSha=<sha>` on every build, and port the provenance stamp that exists in the LinkedIn lineage (`release_provenance.py`, `runtime/stamp_release_source.py` and the health reader) so the answer is in the product, not in a fingerprint exercise.
4. **Land the lanes in one order on one integration branch.** Suggested order after the Discord candidate is accepted: (a) the Discord candidate onto the live Mastodon line (this branch already is that merge); (b) the Bluesky head (a descendant of the live commit, 4 commits ahead) on top; (c) the LinkedIn lane (#218, live on 10-20 and 10-21 and currently NOT live); (d) Pinterest and the rest. Each step is a merge commit, never a rebase of another lane's branch, and each step reruns the superset proof against the previous head.
5. **Retire stale numbering hazards.** The Mastodon migrations numbered 131 to 133 are retired and 131 now belongs to Discord. Keep the migration-number test (`tests/test_migration_numbers.py`) on every candidate.
6. **Fix inherited gate failures once.** Four gates fail on the live commit itself, whichever lane builds on it, and each lane would otherwise fix them separately and conflict:
   - the offline secret scan (174 digests in Mastodon fixtures; on this candidate 171 allowlist entries with reasons in `docs/consumer-ready/secret-allowlist.json`; a lane can take that file as is);
   - `npm audit` (since 2026-10-22: `next` 16.3.8 and `@sentry/nextjs` 10.74.0; on this candidate `next` 16.4.2 and `@sentry/nextjs` 10.76.2, a lockfile written with npm 11);
   - `pip-audit` (since 2026-10-22: `pypdf` 6.20.1 has four advisories; this candidate and the Telegram lane use 6.21.1);
   - the generic PostgreSQL step of `consumer-ready.yml`, which runs the Mastodon management fixtures without their explicit opt-in (`POSTRIFF_MASTODON_AFTER134_FIXTURE=1`); the candidate sets it on that step.
   Land these four once on the integration branch; the other lanes then merge it.

## What stays out of scope

No merge into `consumer-saas`, no change to Vercel's Git settings, no change to other lanes' branches. PR #222 is a draft titled "DO NOT MERGE" and is based on a branch that points at the live commit so reviewers see only the Discord delta.
