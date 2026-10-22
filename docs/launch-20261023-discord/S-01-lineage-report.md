# S-01 Lineage report: which source tree produced the build rafii.io serves

| | |
|---|---|
| Checklist item | S-01, identify the lineage of the build rafii.io serves now |
| Prepared | 2026-10-22 (UTC), by the lineage sub-agent; reviewed and condensed by the Launch Captain agent. Read-only: nothing on Vercel, in git refs or in a working tree was changed |
| Subject | `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`, project `postriff-phase2-private` (`prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`), team `team_PgXY5VdAYKcsv0RLoDPHscNq`, target production, READY, created 2026-10-22T12:48:12Z, uploaded with the CLI (no Git metadata) |
| Repository state | 261 remote-tracking refs and 2,402 commits as fetched in the investigation clone |

## 1. Answer

**The live build was made from `c5fc1fd10350f3142ec6f34b2c373139e85abb39`, the tip of `origin/claude/mastodon-full-prod-candidate`** ("Verify Mastodon Inbox replies whose mention Mastodon shortens", committed 2026-10-22 12:44:32Z, 3 min 40 s before the deployment was created).

- **Match.** 257 of the 257 deployed source files the Vercel API lists are byte-identical to that commit (0 absent, 0 different). The best other branch tip is `claude/rafii-bluesky-launch-20261022` (`c8448d75`) at 250/257; it is a descendant of `c5fc1fd1` committed 5 min 53 s after the deployment, so it cannot be the source. Its 7 differing files are a new `regex` dependency in `requirements.txt`, `web/package.json`, `atproto_oauth.py`, `channels.py`, `publisher.py`, `text_measure.py` and `rafii_control/founder_metrics_ops.py`: the Bluesky lane (draft PR #221) is not live.
- **Tie, broken.** Scanning all 2,402 commits finds exactly one other commit with 257/257: the parent `ae6390d2`. They differ only in `src/postriff_phase2/mastodon_inbox.py` (and a test file that is never uploaded), a file the truncated listing hid. A blob-membership probe settles it: `dpl_47SG` answers 200 for the `c5fc1fd1` version of that file and 404 for the `ae6390d2` version; `dpl_349B` (12:33Z) shows the reverse.
- **Beyond the listing.** 48 of 48 probed files the listing could not show (including 4 that the later Bluesky commits change) are present in the deployment with `c5fc1fd1`'s exact bytes.
- **None of the candidates named in the checklist is the source:** `09b3ab8a` 233/257 (90.66%), `b960bfe0` (#216 head) 232/257 (90.27%), `c4c74777` (#218 head) 226/257 (87.94%), `65d469ae` (#212 head) 231/257 (89.88%), `consumer-saas` `5670ce3c` 234/257 (91.05%).
- **Confidence: high** that the deployed tracked source equals the `c5fc1fd1` tree. Directly verified: 305 of about 2,250 deployable files (257 listed + 48 probed); the rest is inferred from that agreement, the single-commit tie, the timing and equal entry counts in the 32 directories the wrapper cut off (section 6 lists what this does not rule out).

## 2. What this means for the Discord launch (facts)

1. **The Discord repair code is not in production now.** There is no `src/postriff_phase2/discord/` package in the deployed tree and `c5fc1fd1` has none. Blob check: `src/postriff_phase2/discord/worker.py` (the `cc32d03f` version) answers 200 on `dpl_Aj8Z` and 404 on `dpl_47SG`.
2. **It was live earlier, twice:** `dpl_5WWX6PteL7gNYnDJkWcJ6GwXniPp` (Git build of `09b3ab8a`, 2026-10-19T06:48:45Z) and `dpl_Aj8ZqLm1xMe9eMW54WVuyYy9vMJ9` (CLI build of `cc32d03f`, 2026-10-20T17:37:14Z). It dropped out with `dpl_HQHUJrhr53sKDsDMwRJ1pvpsHJjs` (2026-10-21T21:15:47Z) and every deployment after it.
3. **Why.** The Mastodon lane (`75312e78` to `c5fc1fd1`) grew from `7dc95e2e` (2026-10-18), which predates the Discord repair commits; none of `09b3ab8a`, `63864bd6`, `ecbb9e36`, `b960bfe0`, `362666dc` is an ancestor of `c5fc1fd1`. Conversely `dpl_Aj8Z` had no Mastodon connect or management. Each CLI production build since 2026-10-20 shipped one lineage and omitted the other, the failure mode PR #218 warns about.
4. **The newest Discord work has never been in production.** `b960bfe0` (#216 head) and `362666dc` (`discord-ping-runtime`) are separate branches on top of `63864bd6`; neither is in `cc32d03f`, so neither was in `dpl_Aj8Z`. The Discord tables (migrations 124-126, 128, 131) exist in the production database, but the code that uses the #216 flows has not served a production request.
5. **What the live tree does have for Discord:** the original Wave 1 `DiscordProvider` in `social_connectors.py` (bot install, channel posting), the catalogue entries and the post-preview theme. It lacks the `discord/` package, the engagement panel and the Discord worker and rate-limit modules.
6. **Correction to the checklist and the handoff prompt:** "PR #218 said rafii.io served `dpl_yKAToJbv` built from `09b3ab8a`" is not supported. `dpl_yKAToJbvjRdQRmCS3RLKHTYegqUr` was created 2026-10-18T20:13:40Z, about 9 h 41 min before `09b3ab8a` existed; its 251 listed files match `7dc95e2e` (Pinterest production prep) 251/251 and it has no Discord package.
7. **Provenance.** `/api/health` reports `sourceRevision: null` because the live lineage has no provenance mechanism (`release_provenance.py`, `runtime/stamp_release_source.py` and the health reader exist only in the LinkedIn qualification lineage, `cc32d03f` / `c4c74777`). Of the deployments examined only `dpl_Aj8Z` carries a stamp (`release-source.json`, `sourceRevision` `cc32d03f`). The LinkedIn fleet module is also absent from the live tree. For the Discord RC, provenance therefore rests on the file-fingerprint method used here, not on a stamp.

Lane presence at each deployment's best-match commit (marker file in the tree; "-" absent):

| Marker | 47SG | 349B | AkP8 | C57z | HQHU | Aj8Z | yKAT | 5WWX (Git) | 6yes (Git) |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `discord/` package (Discord repair candidate) | - | - | - | - | - | yes | - | yes | yes |
| LinkedIn fleet (`linkedin_fleet.py`) | - | - | - | - | - | yes | - | - | - |
| Release provenance (`release_provenance.py`) | - | - | - | - | - | yes | - | - | - |
| Mastodon connect (`mastodon_connect.py`) | yes | yes | yes | yes | yes | - | - | - | - |
| Mastodon management (`mastodon_management.py`) | yes | yes | yes | yes | - | - | - | - | - |
| Mastodon inbox (`mastodon_inbox.py`) | yes | yes | yes | yes | - | - | - | - | - |
| Pinterest agent (`pinterest_agent.py`) | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| Wave 1 `DiscordProvider` | yes | yes | yes | yes | yes | yes | yes | yes | yes |

## 3. Evidence for `dpl_47SG`

### 3.1 Ranked candidates (top of 46)

Candidates: the tips of the 40 most recently updated remote branches, commit `09b3ab8a`, and five intermediate commits of the winning branch. "Exact" counts deployed source files whose SHA-1 equals the candidate's file at the same path.

| Rank | Candidate | Commit | Committed (UTC) | Exact / 257 | Absent | Mismatch | Hidden-dir counts equal |
|---:|---|---|---|---:|---:|---:|---:|
| 1= | `claude/mastodon-full-prod-candidate` | `c5fc1fd1` | 10-22 12:44 | 257 | 0 | 0 | 32/32 |
| 1= | parent commit | `ae6390d2` | 10-22 12:23 | 257 | 0 | 0 | 32/32 |
| 3= | four earlier commits on the same branch | `75c7a6be`, `f6edf90a`, `d3366822`, `c17d71da` | 10-22 01:13-05:52 | 256 | 0 | 1 | 32/32 |
| 7 | `claude/rafii-bluesky-launch-20261022` | `c8448d75` | 10-22 12:54 | 250 | 0 | 7 | 32/32 |
| 8 | `wip/no-vercel/mastodon-management-cloud-20261018` | `d29e95ef` | 10-18 22:04 | 244 | 2 | 11 | 32/32 |
| 14= | `consumer-saas` | `5670ce3c` | 10-19 03:44 | 234 | 8 | 15 | 32/32 |
| 20= | `codex/discord-repair-production-candidate-20261018` / `09b3ab8a` | `63864bd6` | 10-19 13:40 | 233 | 6 | 18 | 32/32 |
| 23= | `codex/discord-personal-account-20261019` (#216) | `b960bfe0` | 10-21 18:08 | 232 | 6 | 19 | 32/32 |
| 37= | `claude/linkedin-qualification-integration-20261022` (#218) | `c4c74777` | 10-21 20:53 | 226 | 6 | 25 | 32/32 |

The last column is a weak signal (many candidates score 32/32). The full 46-row table and per-deployment tables are kept outside the repository.

### 3.2 Coverage and what the listing is

The `.vercelignore` of the commit keeps `docs/`, `tests/`, `scripts/`, `migrations/`, `.github/`, build output and `node_modules` out of the upload (those directories appear as empty stubs). The commit has 6,303 files of which about 2,248 are deployable; the listing shows 257 (11.4%) because the Vercel MCP wrapper returns three levels below `src/` and cuts one array (`src/postriff_phase2/`, first 50 and last 50 of 165 entries). The 63 files in the cut block (`hosted.py` through `pinterest_agent.py`, including `oauth.py`, `hosted_worker.py` and the Mastodon modules) were checked only by the probes below.

### 3.3 Tie-break between `ae6390d2` and `c5fc1fd1`

The Vercel file endpoint answers 200 only for a file that is part of that deployment (four-way control):

| Deployment | Version of `mastodon_inbox.py` asked for | Answer |
|---|---|---|
| `dpl_47SG` (12:48:12Z) | `c5fc1fd1` | 200 |
| `dpl_47SG` | `ae6390d2` | 404 |
| `dpl_349B` (12:33:51Z) | `ae6390d2` | 200 |
| `dpl_349B` | `c5fc1fd1` | 404 |

### 3.4 Hidden-zone verification

46 files were sampled with a fixed seed from the commit's unlisted deployable files, plus `mastodon_inbox.py` and `mastodon_publishing.py`, and probed on `dpl_47SG` with the SHA-1 of the `c5fc1fd1` bytes: 48/48 present (10 from the cut block, 3 web files changed by `ae6390d2`, 17 random web files, 8 Python sub-package files, 4 skill files, 4 files the post-deployment Bluesky commits modify, plus the two named files).

### 3.5 Independent cross-checks

- Timing: for every CLI deployment examined the best-match commit was made 0 min 39 s to 33 min 52 s before the deployment was created. Times corroborate; they were not used to rank.
- Ground truth for the method: `dpl_Aj8Z` carries a stamp naming `cc32d03fa32300132633d9c324a1cc396fdf14e5`, exactly the commit the fingerprint chose (252/253; the one non-match is the stamp file). The 12 sha256 values the stamp lists match `cc32d03f`'s blobs.
- Vercel's own provenance: the Git deployment `dpl_6yesBpf7svGoXaeV5Z4TvtUAJK88` records `ecbb9e36c48571440bec09333cbfe2956af96075`, created 3 min 19 s after that commit.

## 4. Rollback candidates: what a rollback would return to

"Match" is exact / listed files for the best-match commit. "Live-only commits dropped" are commits reachable from `c5fc1fd1` but not from the target.

| Deployment | Created (UTC) | Source | Best-match commit | Match | Live-only commits dropped | Discord package |
|---|---|---|---|---:|---|:-:|
| `dpl_349BPQoCn1p857TxmQaaKhDb2Lrx` | 10-22 12:33:51 | CLI | `ae6390d2` | 257/257 | 1 | no |
| `dpl_AkP8r1Lfx4nWgCYSJuJxCKWkF3yM` | 10-22 05:43:50 | CLI | `f6edf90a` | 257/257 | 3 | no |
| `dpl_C57zH6ZPWejerDrysB864XDEw3Qo` | 10-22 01:52:20 | CLI | `d3366822` (`c17d71da` identical in deployed files) | 257/257 | 4 | no |
| `dpl_HQHUJrhr53sKDsDMwRJ1pvpsHJjs` | 10-21 21:15:47 | CLI | `75312e78` | 251/251 | 7 | no |
| `dpl_Aj8ZqLm1xMe9eMW54WVuyYy9vMJ9` | 10-20 17:37:14 | CLI with stamp | `cc32d03f` | 252/253 (stamp file) | different lineage (11 live-only, 634 target-only) | yes |
| `dpl_yKAToJbvjRdQRmCS3RLKHTYegqUr` | 10-18 20:13:40 | CLI | `7dc95e2e` | 251/251 | 11 | no |
| `dpl_6yesBpf7svGoXaeV5Z4TvtUAJK88` | 10-19 02:16:03 | Git | `ecbb9e36` (Vercel metadata) | no file tree | different lineage | yes (by commit) |
| `dpl_5WWX6PteL7gNYnDJkWcJ6GwXniPp` | 10-19 06:48:45 | Git | `09b3ab8a` (Vercel metadata) | no file tree | different lineage | yes (by commit) |

What each rollback would return to, relative to the live build: `dpl_349B` loses only the `mastodon_inbox.py` change; `dpl_AkP8` also loses the reply-review and test-fixture commits; `dpl_C57z` also loses text-only Mastodon native-schedule verification; `dpl_HQHU` is Mastodon Connect only (no management, no Inbox replies); `dpl_yKAT` is Pinterest production prep only; `dpl_Aj8Z` is the only CLI production build carrying the Discord repair code, the LinkedIn lane and a stamp, with no Mastodon lane. Compatibility of any rollback with database migrations, queued jobs and worker versions was **not** assessed here.

## 5. Method

1. `list_deployment_files` returns a nested tree (`name`, `type`, `mode`, and `uid` on files). Files under `src/` are the uploaded sources (the repository root minus `.vercelignore`); `out/` holds build outputs.
2. `uid` is the SHA-1 of the raw file bytes (not the git blob id), validated on two small files by fetching their content and hashing it.
3. For each candidate commit, `git ls-tree -r` gave the blob id of every deployed path and the raw bytes were streamed through one `git cat-file --batch` process and hashed (cached by blob id). Nothing was checked out and no ref was touched. The same comparison ran over all 2,402 commits to find every tie, not only branch-tip ties.
4. For files the listing hides, the deployment file endpoint was used as a membership test (200 present, 404 not part of that deployment) after the four-way control above.
5. The other CLI deployments were fingerprinted the same way.

## 6. Limits and caveats

- The listing is truncated by the Vercel MCP wrapper (three levels, one array cut). Not listed: 63 files in the cut directory and about 1,928 files deeper than three levels. These were checked only by the 48 membership probes and by entry counts for the 32 cut-off directories. With 48 of 48 matching, the 95% upper bound for the share of unlisted files that differ is about 6%.
- Commits that differ only in ignored paths (`tests/`, `scripts/`, `docs/`, `.github/`) cannot be separated by content; where that happens (`dpl_C57z`) the timing tie-break is inference. Committer dates can be rewritten.
- If the deployment came from a local commit that was never pushed, it is indistinguishable from `c5fc1fd1` on the 305 files verified. The owner knows what was deployed at 12:48 UTC and can confirm in one line.
- Git deployments have no file tree in this API; their provenance rests on Vercel's recorded `githubCommitSha`.
- Not examined: which deployment the alias served at other times, environment variables, database state, runtime behaviour.

## 7. Decisions taken from this report (Launch Captain)

1. **RC base.** The release candidate is built as a merge of `c5fc1fd1` (live) and the Discord line (`b960bfe0`) plus the launch-gate commits, so that everything live is contained in the RC (superset, S-04). It is not built from `consumer-saas` and not from the Discord line alone.
2. **Rollback target** for the Discord RC is `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` (the live build when the RC is promoted). Because that build contains none of the Discord v2 code and the database already has migrations 124-126, 128 and 131, a rollback to it is a last resort and only after in-flight Discord jobs are drained (see `RUNBOOK-INCIDENT.md`). The primary abort is to promote the closed-gate twin of the RC.
3. **Alias hygiene.** After the RC is promoted, no lane may deploy to production from a branch that does not contain the RC, or the Discord work disappears again (it already did once on 10-21). The release owner has to tell the LinkedIn, Mastodon, Bluesky and Pinterest lanes. The `c8448d75` Bluesky head, for instance, is a descendant of `c5fc1fd1` and not of the RC.
4. **Other lanes' state is not my scope** but is worth the owner's attention: the LinkedIn lane (#218, live 10-20 and 10-21 in `dpl_Aj8Z`) is not in the current live build.
