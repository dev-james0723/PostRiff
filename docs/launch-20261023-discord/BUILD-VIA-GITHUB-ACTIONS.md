# BUILD VIA GITHUB ACTIONS (route A): D1 and D2 when no machine has the Vercel CLI

The owner's laptop cannot be turned on, so the two approved builds (D1 dark, D2 open; `AUTHORIZATION-RECORD.md`, rows 5 and 6) are made by a GitHub Actions workflow instead of the commands in `BUILD-RUNSHEET.md`. Nothing about the rows changes: same frozen SHA, same two builds, same `--prod --skip-domain`, same cap line, same read-backs and acceptance. Only the machine that runs `vercel deploy` is different. **This repository is public: every log line, step summary and file here is world-readable.**

Files: `deploy/rc-staged-build.yml` (the workflow; inert here, it only runs from a request branch), `deploy/run_tests.py` (offline tests), `deploy/make_request_branch.sh`, `deploy/cli/` (the reviewed CLI lock file), `deploy/vercel-deploy-help.txt` (the real `vercel deploy --help` of the pinned CLI).

## 1. What the owner set up (once)

GitHub, repository settings, Environments, `rafii-rc-deploy`. In this order:

1. Required reviewers: the owner. **Prevent self-review: off** (the owner's account is also the pusher; with it on, nobody can approve).
2. Deployment branches and tags: selected, pattern `claude/discord-launch-rc-deploy-*`.
3. Environment **secret** `VERCEL_TOKEN`: a Vercel token scoped to the one team, expiring in one day, added only after steps 1 and 2. Never a repository-level secret (those are visible to every workflow).
4. Environment **secret** `TESTER_WORKSPACE_ID` (the tester workspace id; used by the D1 build only). A secret and not a variable, because a variable is printed in clear in the step header of a public log. The id itself is deliberately **not** in this repository.

What is proven by the first run, not assumed: a pushed request branch shows a run in the state `waiting` (the required-reviewer gate), and nothing runs until the owner approves it.

## 2. A request branch

`claude/discord-launch-rc-deploy-{preflight,d1,d2}-<suffix>`: an orphan commit made by `make_request_branch.sh` that holds exactly five files: `.github/workflows/rc-staged-build.yml`, `deploy/REQUEST.json` (`{"sha": <40 hex>, "cap": "<n>"}`; no cap for preflight), `deploy/cli/package.json` and `package-lock.json`, and a root `vercel.json` with `git.deploymentEnabled=false` (belt and braces: a push of this branch must never start a hosted Git deployment). No other workflow exists on that branch and no existing workflow triggers on those branch names.

## 3. What a run does, in order (and what it refuses)

| Step | Behaviour |
|---|---|
| Job `if` | only in `dev-james0723/PostRiff`, only for the actor `dev-james0723`; then waits for the environment's reviewer |
| Read the request | refuses re-runs (`run_attempt` must be 1) and a request commit older than twelve hours; reads `sha` and `cap` and accepts them only as whole-string matches (40 lower-case hex; 1 to 999999); the SHA must be the current tip of `claude/discord-launch-rc-20261023`; CI on that SHA is read once: 14 check runs, none unfinished or red, the 11 named jobs must be `success` (a skipped job cannot stand in), the list must equal its total and not be cut at 100; names missing are printed |
| Install the CLI | `npm ci --ignore-scripts` from the reviewed lock file (390 packages, integrity on every entry, registry only); the exact tree that was reviewed, no install scripts |
| Fetch the frozen SHA | manual exact-SHA fetch (the repository has two orphan vendor gitlinks that the generic checkout cannot survive; the repo's own workflows do the same) |
| `preflight` | read-only; every check is reported and the step fails at the end if any failed: token shape, CLI version, deploy flags exist, token accepted for the team scope (never prints whose), production env **names** only (never values), the six required names present, names that must not exist yet, tester secret set and UUID-shaped (yes or no only), tree and `vercel.json` checks, and `vercel deploy --dry --json` with the build's flags (reads the project and the files, uploads nothing, creates nothing), with a guard on the upload set |
| `d1` / `d2` | validates again, then exactly one `vercel deploy --prod --skip-domain --yes --scope <team> --meta rafiiSourceSha=<sha> --meta rafiiTwin=dark\|open --env POSTRIFF_DISCORD_CONNECT_WORKSPACES=<tester id>\|* --env POSTRIFF_OAUTH_DISCORD_REVIEWED=true --env POSTRIFF_DISCORD_GUILD_CAP=<cap>`; no retry; prints the deployment URL and id only; fails if the CLI wrote into the tree or if the inspect text shows a production alias (`rafii.io`, the project's two `vercel.app` production names) |

Never done by the workflow: promote, alias, change an env variable or a project setting, merge, or touch the live deployment.

## 4. Reviews and tests

- **First independent review** (a separate agent, read-only, 2026-10-22/23): found two certain first-run failures (the CLI's `--help` exits with status 2; the generic checkout fails on the repository's orphan gitlinks), a log leak (a variable is printed in clear), an unlocked dependency tree that would run with the token, a default branch that built the open twin, log greps that did not match this CLI version, a weak CI gate, no re-run guard and more (14 findings). All were fixed.
- **Delta re-review** of the fixed file: all 14 resolved; it confirmed from the CLI source that `--dry` has no network write, no upload, no prompt and no tree write, and that no install script is needed on the paths used. New findings (named jobs in the log, the real dry-run JSON shape, a preflight check of the tester secret, a twelve-hour age limit, `--yes` kept because the earlier builds used it, an alias-lines-only tripwire, `.vercel` assertions) were applied in the second version.
- **Tests**: `python3 deploy/run_tests.py` (needs PyYAML, `jq`, `git`, `bash`): 138 offline checks against stub `gh` and `vercel` binaries and local git repositories (the stub CLI mimics what was observed in 59.23.2: `--version` prints two lines, `--help` exits 2, progress lines carry no colon). A mutation run (12 deliberate weakenings of the workflow) is caught 10 times; the two survivors are equivalent changes. The schema validator (`action-validator`) and `shellcheck` report nothing.
- **Fingerprints**: first version (`pf1`, the preflight that was pushed first) `7c8d30facf16c183…`; second version `7c9677359b4755fc…`; lock file `7dc4bca4d2ed2af5…`. Every request commit message carries the workflow and lock hashes it was built with.

## 5. What cannot be proven offline (so it is watched on the first runs)

Header masking of the secret in a real Actions log; job-level `concurrency` order against the environment approval (a push by anyone else should show a skipped run and leave the owner's waiting run alone); the live check-run names (they matched the 14 seen on PR #222 when the list was written); whether the server accepts the `services` project settings without `skipAutoDetectionConfirmation` (the build keeps `--yes` for that reason); `--skip-domain` also covering the `*.vercel.app` production alias (the inspect text is checked in the job and the agent reads the aliases through the API afterwards); Deployment Protection still being `all_except_custom_domains` (read through the API).

Known and accepted: the pinned CLI tree includes `tar@7.5.7`, which npm reports as deprecated with published vulnerabilities in extraction. The deploy path packs and does not extract untrusted archives. Not fixable here without leaving the reviewed tree.

## 6. How each run goes

1. The agent checks the RC tip and CI, builds the request branch, pushes it, and reads the run state until it is `waiting`.
2. The agent gives the owner the run link, the request commit (short SHA) and the title. The owner compares them and approves in GitHub.
3. The agent reads the job log (public, so it is short by design), then checks the result through the Vercel API (project, SHA, target, state, aliases, files), not through the workflow.
4. D1 and D2 are the only builds (`AUTHORIZATION-RECORD.md`, row 6). A failed build is reported; a third build needs a new yes. The token is revoked by the owner after D2, and the request branches are deleted.
