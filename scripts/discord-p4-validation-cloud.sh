#!/usr/bin/env bash
# PREPARED ONLY. Requires a new explicit approval for ONE cloud job and disposable SQL.
set -euo pipefail
if [[ "$(uname -s)" != Linux || "${CI:-}" != true ]]; then
  echo 'P4 requires separately approved Linux CI; no local fallback' >&2
  exit 64
fi
discord_p4_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# One controller, one Python gate, one owned PG17 cluster, prior SQL chain once.
# Local wrapper correction separately approved; this does not execute that run.
exec bash "$discord_p4_root/scripts/discord-validation-cloud.sh"
