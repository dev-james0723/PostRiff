#!/bin/zsh
set -eu
if [[ "${1:-}" != "--service" ]]; then
  exec "${0:A:h}/Start Rafii Studio.command" --local "$@"
fi
cd "${0:A:h}/.."

# This is the project's local preview workspace with a disposable database.
for port in 4331 55441; do
  if /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
    print -u2 "Port $port is already in use. No new workspace was started."
    exit 1
  fi
done

export LC_ALL=C
export POSTRIFF_DEV_WEB_ORIGIN="http://localhost:47632"
print "Local preview only. Its sample workspace is cleared when this window closes."

if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -u scripts/postriff_dev_hosted.py --port 4331
fi
if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  exec "$VIRTUAL_ENV/bin/python" -u scripts/postriff_dev_hosted.py --port 4331
fi
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
exec uv run --no-project --python 3.12 --with-requirements requirements.txt \
  python -u scripts/postriff_dev_hosted.py --port 4331
