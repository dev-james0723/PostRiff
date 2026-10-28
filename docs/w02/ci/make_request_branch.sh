#!/usr/bin/env bash
# Build one capacity-run request branch: an orphan commit holding only the workflow, capacity/REQUEST.json and a
# vercel.json that keeps Git deployments off. Nothing in it is secret; the run uses synthetic data only.
# usage: make_request_branch.sh <smoke|s0|s1|s2|faults|release|lockbench|baseline|s1levers|s2sizes|devset|s0100|fdb|fcrash|f429|s1lane56|sens> <suffix> <tree sha> <harness sha> [options] [--push]
#   (lockbench: only the shared request coordinator under K processes; --pools gives the pool size, --latency is unused)
#   (baseline: the frozen minute worker on the --baseline tree, default RC1, for its posts per minute)
#   (s1levers: S1 as control, then S1 with the lane loop budget at 58 s and 70 s, and S1 with warm invocations)
#   (s2sizes: S2 with a hot workspace of 100, 300 and 1,000 posts; the 3,000-post S2 stays its own profile, s2)
#   (devset: the development measurement set, S1, S0-100, Fdb, Fcrash and F429, on separate runners at once)
#   (s0100, fdb, fcrash, f429: one scenario of the devset alone, to run it again after a failure or a change)
#   (s1lane56: S1 with each lane loop budgeted 56 s instead of 50, the duty-cycle lever alone; compare with the S1 of the same tree)
#   (sens: S1 with 12 lane loops and S1-24 with 24, for the database round trip sensitivity: one request for each --latency, e.g. 5 and 10)
#   --pools 20          one to four pool sizes of 15 to 120, comma separated (default 20)
#   --latency 2         database round trip in ms, 0 to 99.9 (default 2)
#   --baseline <sha>    frozen tree for the baseline scenario (default RC1 2a5a523d...)
# Without --push nothing leaves this machine; the commit and branch name are printed.
set -euo pipefail
profile="${1:?profile: smoke, s0, s1, s2, faults, release, lockbench, baseline, s1levers, s2sizes, devset, s0100, fdb, fcrash, f429, s1lane56 or sens}"
suffix="${2:?a short lower-case suffix}"
sha="${3:?the 40 hex SHA of the tree under test}"
harness="${4:?the 40 hex SHA of the harness commit (branch claude/discord-w02-capacity-20261023)}"
shift 4
pools=20
latency=2
baseline=2a5a523d788eef67a5c7dbed609a98efa6650eef
push=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pools) pools="${2:?--pools needs a value}"; shift 2 ;;
    --latency) latency="${2:?--latency needs a value}"; shift 2 ;;
    --baseline) baseline="${2:?--baseline needs a value}"; shift 2 ;;
    --push) push=yes; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
done
[[ "$profile" =~ ^(smoke|s0|s1|s2|faults|release|lockbench|baseline|s1levers|s2sizes|devset|s0100|fdb|fcrash|f429|s1lane56|sens)$ ]] || { echo 'profile must be smoke, s0, s1, s2, faults, release, lockbench, baseline, s1levers, s2sizes, devset, s0100, fdb, fcrash, f429, s1lane56 or sens'; exit 2; }
[[ "$suffix" =~ ^[a-z0-9]{1,12}$ ]] || { echo 'suffix must be 1 to 12 lower-case letters or digits'; exit 2; }
for value in "$sha" "$harness" "$baseline"; do
  [[ "$value" =~ ^[0-9a-f]{40}$ ]] || { echo 'every SHA must be 40 lower-case hex characters'; exit 2; }
done
[[ "$pools" =~ ^(1[5-9]|[2-9][0-9]|1[01][0-9]|120)(,(1[5-9]|[2-9][0-9]|1[01][0-9]|120)){0,3}$ ]] || { echo 'pools: one to four sizes of 15 to 120, comma separated'; exit 2; }
[[ "$latency" =~ ^(0|[1-9][0-9]?)(\.[0-9])?$ ]] || { echo 'latency: 0 to 99.9 ms'; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
branch="claude/discord-capacity-run-${profile}-${suffix}"
work="$(mktemp -d "${TMPDIR:-/tmp}/capacity-request-XXXXXX")"
git init -q "$work"
git -C "$work" checkout -q --orphan "$branch"
mkdir -p "$work/.github/workflows" "$work/capacity"
cp "$here/discord-lane-capacity.yml.txt" "$work/.github/workflows/discord-lane-capacity.yml"
# Belt and braces: a push of this branch must never start a hosted Git deployment (the project setting already forbids it).
printf '{\n  "git": {\n    "deploymentEnabled": false\n  }\n}\n' > "$work/vercel.json"
printf '{"profile":"%s","sha":"%s","baseline_sha":"%s","harness_sha":"%s","pools":"%s","db_latency_ms":"%s"}\n' \
  "$profile" "$sha" "$baseline" "$harness" "$pools" "$latency" > "$work/capacity/REQUEST.json"
fingerprint="$(sha256sum "$work/.github/workflows/discord-lane-capacity.yml" | cut -c1-16)"
git -C "$work" add -A
git -C "$work" -c user.name=Claude -c user.email=noreply@anthropic.com commit -q -F - <<EOF
request(capacity-${profile}): W-02 lane capacity run for ${sha:0:8}

Holds only the workflow (sha256 ${fingerprint}...), capacity/REQUEST.json and a vercel.json that keeps
Git deployments off. Synthetic data only: no secret, no environment, read-only token, nothing deployed.
Harness ${harness:0:12}, pools ${pools}, database round trip ${latency} ms, baseline ${baseline:0:12}.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E9guaNuzCqsXR8cbB5CRhv
EOF
commit="$(git -C "$work" rev-parse HEAD)"
echo "branch:      $branch"
echo "commit:      $commit"
echo "workflow:    sha256 ${fingerprint}..."
echo "files:       $(git -C "$work" ls-files | tr '\n' ' ')"
echo "request:     $(cat "$work/capacity/REQUEST.json")"
echo "work tree:   $work"
if [ -n "$push" ]; then
  git -C "$work" remote add origin https://github.com/dev-james0723/PostRiff
  git -C "$work" push origin "HEAD:refs/heads/${branch}"
  echo "pushed"
fi
