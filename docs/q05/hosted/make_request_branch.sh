#!/usr/bin/env bash
# Build one Q-05 hosted-probe request branch: an orphan commit holding only the reviewed workflow,
# probe/REQUEST.json and a vercel.json that keeps Git deployments off. The run waits for the owner's
# approval in the rafii-q05-probe environment before any step runs.
#
# usage: make_request_branch.sh generic <suffix> <40-hex probe-branch sha> --reviewed-probe-sha256 <64 hex> [--push]
#        make_request_branch.sh gate    <suffix> <40-hex probe-branch sha> <40-hex expectSourceRevision> \
#                                       --reviewed-probe-sha256 <64 hex> [--push]
#
# --reviewed-probe-sha256 is REQUIRED and must come from the independent review record of the probe
# (the Release Captain supplies it from the reviewed tip), never from the request's own SHA. This
# script refuses to build when scripts/q05_tenant_probe.py at <sha> does not hash to that value, and
# the workflow then refuses a fetched probe whose full sha256 differs — so a request can only run a
# probe that was actually reviewed.
# Without --push nothing leaves this machine; the commit and branch name are printed.
set -euo pipefail
mode="${1:?mode: generic or gate}"
suffix="${2:?a short lower-case suffix}"
sha="${3:?the 40 hex tip SHA of claude/discord-q05-probe-20261023}"
shift 3
expectrev=""
push=""
reviewed=""
if [ "$mode" = gate ]; then
  expectrev="${1:?gate mode needs the 40 hex expectSourceRevision of the promoted build}"
  shift || true
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --push) push=yes; shift ;;
    --reviewed-probe-sha256)
      [ $# -ge 2 ] || { echo '--reviewed-probe-sha256 needs a value' >&2; exit 2; }
      reviewed="$2"; shift 2 ;;
    *) echo "unexpected argument: $1" >&2; exit 2 ;;
  esac
done
[[ "$mode" =~ ^(generic|gate)$ ]] || { echo 'mode must be generic or gate'; exit 2; }
[[ "$suffix" =~ ^[a-z0-9]{1,12}$ ]] || { echo 'suffix must be 1 to 12 lower-case letters or digits'; exit 2; }
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'sha must be 40 lower-case hex characters'; exit 2; }
if [ "$mode" = gate ]; then
  [[ "$expectrev" =~ ^[0-9a-f]{40}$ ]] || { echo 'expectSourceRevision must be 40 lower-case hex characters'; exit 2; }
fi
[[ "$reviewed" =~ ^[0-9a-f]{64}$ ]] || {
  echo 'refusing: --reviewed-probe-sha256 <64 lower-case hex> is required (from the probe review record)'; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
# The probe content at that exact SHA must be exactly what was reviewed (M7 / review N3).
actual="$(git -C "$here" show "${sha}:scripts/q05_tenant_probe.py" | sha256sum | cut -d' ' -f1)" \
  || { echo "could not read scripts/q05_tenant_probe.py at ${sha}; fetch that commit first"; exit 2; }
[ "$actual" = "$reviewed" ] || {
  echo "refusing: scripts/q05_tenant_probe.py at ${sha:0:12} does not match the reviewed probeSha256; get the probe re-reviewed"; exit 2; }
branch="claude/discord-q05-run-${mode}-${suffix}"
# L5: a work directory OUTSIDE the repository, cleaned up on exit.
work="$(mktemp -d "${TMPDIR:-/tmp}/q05-request-XXXXXX")"
trap 'rm -rf "$work"' EXIT
git init -q "$work"
git -C "$work" checkout -q --orphan "$branch"
mkdir -p "$work/.github/workflows" "$work/probe"
cp "$here/q05-hosted-run.yml" "$work/.github/workflows/q05-hosted-run.yml"
printf '{\n  "git": {\n    "deploymentEnabled": false\n  }\n}\n' > "$work/vercel.json"
if [ "$mode" = gate ]; then
  printf '{"sha":"%s","mode":"%s","probeSha256":"%s","expectSourceRevision":"%s"}\n' "$sha" "$mode" "$reviewed" "$expectrev" > "$work/probe/REQUEST.json"
else
  printf '{"sha":"%s","mode":"%s","probeSha256":"%s"}\n' "$sha" "$mode" "$reviewed" > "$work/probe/REQUEST.json"
fi
fingerprint="$(sha256sum "$work/.github/workflows/q05-hosted-run.yml" | cut -c1-16)"
git -C "$work" add -A
git -C "$work" -c user.name=Claude -c user.email=noreply@anthropic.com commit -q -F - <<EOF
request(q05-${mode}): hosted isolation probe for probe-branch ${sha:0:8}

Holds only the reviewed workflow (sha256 ${fingerprint}...), probe/REQUEST.json and a vercel.json that
keeps Git deployments off. Pins the REVIEWED probeSha256 ${reviewed:0:16}... (supplied from the review
record and matched against the probe at ${sha:0:8}). Credentials are the environment's single-use OTP
codes; none are in this commit.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E9guaNuzCqsXR8cbB5CRhv
EOF
commit="$(git -C "$work" rev-parse HEAD)"
echo "branch:        $branch"
echo "commit:        $commit"
echo "workflow:      sha256 ${fingerprint}..."
echo "probeSha256:   ${reviewed} (reviewed; matches the probe at ${sha:0:12})"
echo "files:         $(git -C "$work" ls-files | tr '\n' ' ')"
echo "request:       $(cat "$work/probe/REQUEST.json")"
if [ -n "$push" ]; then
  git -C "$work" remote add origin https://github.com/dev-james0723/PostRiff
  git -C "$work" push origin "HEAD:refs/heads/${branch}"
  echo "pushed"
fi
