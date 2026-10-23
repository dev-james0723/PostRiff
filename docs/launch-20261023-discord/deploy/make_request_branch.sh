#!/usr/bin/env bash
# Build one request branch: an orphan commit that holds only the reviewed workflow and deploy/REQUEST.json.
# usage: make_request_branch.sh <preflight|d1|d2> <suffix> <40-hex RC sha> [cap] [--push]
# Without --push nothing leaves this machine; the commit and branch name are printed.
set -euo pipefail
mode="${1:?mode: preflight, d1 or d2}"
suffix="${2:?a short lower-case suffix}"
sha="${3:?the 40 hex SHA of the release candidate}"
cap=""
push=""
for extra in "${@:4}"; do
  case "$extra" in
    --push) push=yes ;;
    *) cap="$extra" ;;
  esac
done
[[ "$mode" =~ ^(preflight|d1|d2)$ ]] || { echo 'mode must be preflight, d1 or d2'; exit 2; }
[[ "$suffix" =~ ^[a-z0-9]{1,12}$ ]] || { echo 'suffix must be 1 to 12 lower-case letters or digits'; exit 2; }
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'sha must be 40 lower-case hex characters'; exit 2; }
if [ -n "$cap" ]; then [[ "$cap" =~ ^[1-9][0-9]{0,5}$ ]] || { echo 'cap must be 1 to 999999'; exit 2; }; fi
if [ "$mode" != preflight ] && [ -z "$cap" ]; then echo 'd1 and d2 need a cap (the code default on production is 90)'; exit 2; fi

here="$(cd "$(dirname "$0")" && pwd)"
branch="claude/discord-launch-rc-deploy-${mode}-${suffix}"
work="$(mktemp -d "${TMPDIR:-$here}/request-branch-XXXXXX")"
git init -q "$work"
git -C "$work" checkout -q --orphan "$branch"
mkdir -p "$work/.github/workflows" "$work/deploy/cli"
cp "$here/rc-staged-build.yml" "$work/.github/workflows/rc-staged-build.yml"
cp "$here/cli/package.json" "$here/cli/package-lock.json" "$work/deploy/cli/"
# Belt and braces: a push of this branch must never start a hosted Git deployment (the project setting already forbids it).
printf '{\n  "git": {\n    "deploymentEnabled": false\n  }\n}\n' > "$work/vercel.json"
if [ -n "$cap" ]; then printf '{"sha":"%s","cap":"%s"}\n' "$sha" "$cap"; else printf '{"sha":"%s"}\n' "$sha"; fi > "$work/deploy/REQUEST.json"
fingerprint="$(sha256sum "$work/.github/workflows/rc-staged-build.yml" | cut -c1-16)"
lockprint="$(sha256sum "$work/deploy/cli/package-lock.json" | cut -c1-16)"
git -C "$work" add -A
git -C "$work" -c user.name=Claude -c user.email=noreply@anthropic.com commit -q -F - <<EOF
request(${mode}): stage-build request for release candidate ${sha:0:8}

Holds only the reviewed workflow (sha256 ${fingerprint}...), deploy/REQUEST.json, the reviewed CLI lock file (sha256 ${lockprint}...)
and a vercel.json that keeps Git deployments off. The job waits for the owner's approval in the rafii-rc-deploy environment
before any step runs.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E9guaNuzCqsXR8cbB5CRhv
EOF
commit="$(git -C "$work" rev-parse HEAD)"
echo "branch:      $branch"
echo "commit:      $commit"
echo "workflow:    sha256 ${fingerprint}..."
echo "lock file:   sha256 ${lockprint}..."
echo "files:       $(git -C "$work" ls-files | tr '\n' ' ')"
echo "request:     $(cat "$work/deploy/REQUEST.json")"
echo "work tree:   $work"
if [ -n "$push" ]; then
  git -C "$work" remote add origin https://github.com/dev-james0723/PostRiff
  git -C "$work" push origin "HEAD:refs/heads/${branch}"
  echo "pushed"
fi
