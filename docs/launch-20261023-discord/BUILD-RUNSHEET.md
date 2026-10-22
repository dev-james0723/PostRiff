# BUILD-RUNSHEET: D1 and D2 on a machine that has the Vercel CLI

Only the two `vercel deploy` commands, the read-only name list (packet row 8) and the Portal look (row 7) need a machine with the Vercel CLI or a logged-in browser: the owner's MacBook Pro through the paired computer, or the owner pasting the same commands. Everything else (env batch, readbacks, fingerprints, promotion, rollback) is done by the agent through the Vercel API tools and needs no machine.

The agent has no Vercel CLI and no token. The API tool that can create a deployment has no `--skip-domain` and no per-deployment `--env`, so it must not be used for D1 or D2: a production-target deployment made that way would take over `rafii.io` at once.

## Do not start unless all of these are true

1. Every row of `RC-RECEIPT.md` section 3 is green on the frozen SHA, the superset proof passes on it, and the SHA is written in the packet.
2. Packet rows 1 to 4 are applied or ready as written, and the env batch (rows 1 to 3) and the policy (row 2) were read back by name and value after the last change to them.
3. The cost note is posted: previous builds took about 2.5 minutes; approval cap $5 per build; at most two builds in total (D1, then D2); no retry without a written reason and a new yes.
4. The tester workspace id is known (D1 gate value).
5. No other release candidate of this lane is in flight (`list_deployments` shows none building or staged).

## A. Look around (read-only, nothing is changed)

```
uname -sm; git --version; node --version; vercel --version; vercel whoami
```

`vercel whoami` prints a user name, no token. Stop if `vercel` is missing or the scope is not the team below.

## B. Row 8: names only

```
vercel env ls production --scope team_PgXY5VdAYKcsv0RLoDPHscNq --project prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L 2>&1 | awk '$1 ~ /^[A-Z][A-Z0-9_]*$/ {print $1}' | sort -u
```

Only the first column leaves the machine. Never `env pull`, never `--json`, never a value. The agent looks for: the Discord client id, client secret and bot token names, `POSTRIFF_PUBLIC_BASE_URL`, `POSTRIFF_CREDENTIAL_KEY`, `CRON_SECRET`, and for the absence of any engagement, webhook, user-install, `..._DISABLED` or `..._RATE_POLICY` name that should not be there.

## C. Clean checkout of the frozen SHA (a fresh directory; never an existing worktree)

```
set -euo pipefail
SHA=<frozen sha>
WORK="$(mktemp -d /tmp/rafii-rc-XXXXXX)" && cd "$WORK"
git init -q src && cd src
git remote add origin https://github.com/dev-james0723/PostRiff.git
git fetch -q --depth 1 origin "$SHA"
git checkout -q --detach FETCH_HEAD
test "$(git rev-parse HEAD)" = "$SHA"
test -z "$(git status --porcelain)"
mkdir -p .vercel
printf '{"projectId":"prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L","orgId":"team_PgXY5VdAYKcsv0RLoDPHscNq"}\n' > .vercel/project.json
grep -c '"deploymentEnabled": false' vercel.json
```

The repository is public, so the clone needs no credentials. The last line must print 1: the candidate keeps Git deployments off. `.vercel/` is local and ignored by git.

## D. D1 (dark twin)

```
vercel deploy --prod --skip-domain --yes --scope team_PgXY5VdAYKcsv0RLoDPHscNq \
  --meta rafiiSourceSha="$SHA" --meta rafiiTwin=dark \
  --env 'POSTRIFF_DISCORD_CONNECT_WORKSPACES=<tester workspace uuid>' \
  --env 'POSTRIFF_OAUTH_DISCORD_REVIEWED=true' \
  --env 'POSTRIFF_DISCORD_GUILD_CAP=10000'
```

The cap line is mandatory: the owner chose a cap of 10,000 (`AUTHORIZATION-RECORD.md` replies 4 and 5) and the code default on production is 90. Use 10000 minus the difference when the Portal count was higher than monitoring Q9 (packet section 2). `--yes` only suppresses prompts. Run it once. Paste back the deployment URL line and nothing else.

## E. What the agent checks after D1 (through the API; READY alone is not acceptance)

1. Deployment found by `list_deployments`: state READY, target production, **no alias to `rafii.io`**, metadata `rafiiSourceSha` equal to the frozen SHA, `rafiiTwin` dark, created by the owner's CLI.
2. `get_alias rafii.io` still names `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`.
3. Fingerprint of the deployed files against the frozen tree (the S-01 method). Exact match required, otherwise stop.
4. Runtime env names present on the deployment; the gate value class is `tester workspace`, not `*`.

## F. D2 (open twin): only after the tester session passes

Same commands with `--meta rafiiTwin=open` and `--env 'POSTRIFF_DISCORD_CONNECT_WORKSPACES=*'`, and the same cap line (10000). Quote the star: unquoted, zsh stops with "no matches found". The same checks, plus a fingerprint match against D1. D2 is never promoted before T0 and before the GO.

## G. Promotion and rollback (agent, API tools, no machine needed)

| Step | Call | Readback |
|---|---|---|
| Dark promotion (AUTH-5) | `request_promote` D1 for `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L` | `get_alias rafii.io` names D1; one cron 200 per minute in the runtime logs |
| Open at T0 (AUTH-6, only on GO) | `request_promote` D2 | alias names D2; a second test workspace sees Discord as open |
| Close again (primary abort) | `request_promote` D1 | alias names D1 |
| Code defect (rare) | `request_promote` `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` after in-flight Discord jobs are drained | alias readback |

Every row is also written to `RC-RECEIPT.md` (project, SHA, deployment id, ready state, acceptance, cost if observed, rollback target).
