# S-02 Preserve-live matrix: what is live now must still work in the candidate

Live build: `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`, source `c5fc1fd1` (`S-01-lineage-report.md`). Candidate: `claude/discord-launch-rc-20261023`. Every row below names where the capability lives, the route or cron that carries it, the tests that exercise it and how the candidate is shown to contain it. Nothing here is a probe of the hosted site: the evidence is structural (the candidate contains the live code) plus the repository's own tests, which CI runs on the exact head.

How the candidate is shown to contain everything live (`scripts/rc_superset_proof.py`, re-run on every head; last pass at `cd0ff8d0`):

| Check | What it compares | Result |
|---|---|---|
| ancestry | `c5fc1fd1` is an ancestor of the candidate | OK |
| files | all 6,301 tracked paths of the live commit exist in the candidate | OK |
| lines | every line the live line added since the merge base survives; 29 deliberate rewrites in 23 files, each listed with its reason in `superset-allowlist.json` | OK |
| routes | every `/api` route of the live tree is still registered | OK |
| crons and git settings | the one cron `/api/cron/worker` every minute; `git.deploymentEnabled` false | OK |
| migrations, flag names, tests | no migration, environment-variable name or Python test module of the live tree is missing | OK (live has 401 test modules, the candidate 430) |

## What is live now and where it lives

| Live capability | Code | Route or cron | Tests that exercise it in the candidate | Changed by the candidate? |
|---|---|---|---|---|
| Worker (every queued post of every provider) | `hosted_worker.py` | cron `/api/cron/worker`, every minute | `test_discord_worker_budget.py` (10), the existing worker and queue suites | yes, minimally: the merge keeps the Mastodon lane (`not youtube_only and not discord_only`), and the Discord lane alternates with the others under the same per-tick budget |
| Mastodon connect, management, inbox replies, native schedule, publishing | `mastodon_*.py` (20 modules) | generic `/api/oauth/{provider}/*` routes and the workspace-scoped Mastodon handler dispatched by path segment in `hosted_app.py` (`mastodon_management.handle`) | `tests/test_mastodon_*.py` (20 files) | no |
| Pinterest agent and Trial | `pinterest_*.py` (6 modules) | `/api/connections/pinterest/*` | Pinterest test files (11) | no |
| Discord Wave 1 provider (bot install, channel posting, assisted flows) | `DiscordProvider` in `social_connectors.py`, `discord_*` modules | `/api/oauth/discord/*` and the Discord connection routes | Discord suites (25 test files, plus the launch gate, cap, rate-policy, ban-handling and worker-budget tests) | **yes, on purpose.** With the four flags off the legacy paths run as before; with them on (Approval Packet row 1) the v2 flows apply. Workspaces that already hold a Discord server card or a linked identity are never locked out by the gate (`test_discord_launch_gate.py`, `Footprint` and `Access`) |
| YouTube, Threads, Instagram, LinkedIn Wave 1 providers | `oauth.py`, `social_connectors.py`, `youtube/` | their OAuth and publish routes | YouTube (32 test files), Threads, Instagram, LinkedIn Wave 1 tests | `oauth.py` and `store.py` are shared files; the merge kept both sides (11 conflicted files resolved as unions, listed in the merge commit message) |
| Product web app, founder admin, Growth Studio, native input, library | `web/` | page routes and `/api/*` through the Python service | web node suite (1,008 pass locally), browser workflows `scenes`, `founder`, `growth-studio`, `native-learning-browser`, `native-input`, `growth-metrics`, `discord-composer-input` | web changes are Discord copy, the refusal mapper and legal pages; the dependency patch (next 16.4.2, @sentry/nextjs 10.76.2) touches the whole web app and is why every browser workflow must pass on the final head |
| Privacy export and deletion | `privacy.py`, `account_deletion.py` | privacy routes and pages | privacy and deletion tests | yes: a retention row and one Discord sentence (H-08) |
| Provider kill switches | `POSTRIFF_OAUTH_<PROVIDER>_DISABLED` handling in `oauth.py` | n/a (build-time env) | `test_discord_launch_gate.py` `KillSwitch` | no behaviour change; composition with the gate is tested |

## What is not live now and is not in the candidate (so nothing to preserve)

- LinkedIn fleet and its cron lane (#218): live on 10-20 and 10-21 in `dpl_Aj8Z`, absent from the current live build.
- The Bluesky lane (#221, head `c8448d75`, four commits ahead of the live commit).
- The release provenance stamp (`release_provenance.py`): `/api/health` still reports `sourceRevision: null`.
- Discord engagement (analytics, comments, reply), bot-free webhooks, User Install and interactions: present as code in the candidate, switched off by absent flags.

## The capability levels the candidate will show for Discord, from `oauth.py` `_capabilities`

These hold only with the Discord flags in `C-01-env-matrix.md` and `POSTRIFF_OAUTH_DISCORD_REVIEWED=true` on the two build commands. [Certain] from the code; not yet observed on a hosted build.

| Capability | Level | Condition in code |
|---|---|---|
| identity | Direct | the account (the installed server) is confirmed |
| publish | Direct | bot scope granted and `adapter.production_reviewed` (the REVIEWED variable). Without REVIEWED it is Unsupported |
| schedule | Direct, "Rafii publishes the approved post at the scheduled time" | publish is Direct and `authorization_v2_enabled and connections_v2_enabled` (`server_schedule`) |
| analytics, comments, reply, moderate | Unsupported | Discord declares no scopes for them in this configuration and the engagement flag is off (decision D-03). Do not describe Discord as equal to the other platforms on these |

## Gaps in this matrix, stated plainly

- It proves the code and tests are present and, on CI green, passing. It does not show that a hosted build behaves like the live one; that is the acceptance session after the dark promotion.
- Per-lane tests that are part of the Python suite run in the "Rafii local release gates" workflow; PostgreSQL-backed ones run in the qualification workflow, which has not yet completed on any head of this candidate.
