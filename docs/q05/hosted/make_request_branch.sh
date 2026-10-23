#!/usr/bin/env bash
# Build one Q-05 hosted-probe request branch: an orphan commit holding only the reviewed workflow,
# probe/REQUEST.json and a vercel.json that keeps Git deployments off. The run waits for the owner's
# approval in the rafii-q05-probe environment before any step runs.
# usage: make_request_branch.sh <generic|gate> <suffix> <40-hex probe-branch sha> [--push]
# Without --push nothing leaves this machine; the commit and branch name are printed.
set -euo pipefail
mode="${1:?mode: generic or gate}"
suffix="${2:?a short lower-case suffix}"
sha="${3:?the 40 hex tip SHA of claude/discord-q05-probe-20261023}"
push=""
for extra in "${@:4}"; do
  case "$extra" in
    --push) push=yes ;;
    *) echo "unexpected argument: $extra" >&2; exit 2 ;;
  esac
done
[[ "$mode" =~ ^(generic|gate)$ ]] || { echo 'mode must be generic or gate'; exit 2; }
[[ "$suffix" =~ ^[a-z0-9]{1,12}$ ]] || { echo 'suffix must be 1 to 12 lower-case letters or digits'; exit 2; }
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'sha must be 40 lower-case hex characters'; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
branch="claude/discord-q05-run-${mode}-${suffix}"
work="$(mktemp -d "${TMPDIR:-$here}/q05-request-XXXXXX")"
git init -q "$work"
git -C "$work" checkout -q --orphan "$branch"
mkdir -p "$work/.github/workflows" "$work/probe"
cp "$here/q05-hosted-run.yml" "$work/.github/workflows/q05-hosted-run.yml"
# Belt and braces: a push of this branch must never start a hosted Git deployment.
printf '{\n  "git": {\n    "deploymentEnabled": false\n  }\n}\n' > "$work/vercel.json"
printf '{"sha":"%s","mode":"%s"}\n' "$sha" "$mode" > "$work/probe/REQUEST.json"
fingerprint="$(sha256sum "$work/.github/workflows/q05-hosted-run.yml" | cut -c1-16)"
git -C "$work" add -A
git -C "$work" -c user.name=Claude -c user.email=noreply@anthropic.com commit -q -F - <<EOF
request(q05-${mode}): hosted isolation probe for probe-branch ${sha:0:8}

Holds only the reviewed workflow (sha256 ${fingerprint}...), probe/REQUEST.json and a vercel.json that
keeps Git deployments off. The job waits for the owner's approval in the rafii-q05-probe environment
before any step runs. Credentials are the environment's single-use OTP codes (or short-lived tokens);
none are in this commit.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E9guaNuzCqsXR8cbB5CRhv
EOF
commit="$(git -C "$work" rev-parse HEAD)"
echo "branch:    $branch"
echo "commit:    $commit"
echo "workflow:  sha256 ${fingerprint}..."
echo "files:     $(git -C "$work" ls-files | tr '\n' ' ')"
echo "request:   $(cat "$work/probe/REQUEST.json")"
echo "work tree: $work"
if [ -n "$push" ]; then
  git -C "$work" remote add origin https://github.com/dev-james0723/PostRiff
  git -C "$work" push origin "HEAD:refs/heads/${branch}"
  echo "pushed"
fi
