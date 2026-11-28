#!/bin/zsh
set -eu
app_dir=${0:A:h}
cd "$app_dir/../web"

# Finder may start Terminal without Homebrew's Node 24 on PATH.
if [[ -x /opt/homebrew/opt/node@24/bin/node ]]; then
  export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
fi
export PATH="$PATH:/opt/homebrew/bin"

port=47632
export NEXT_PUBLIC_APP_URL="http://localhost:$port"
if [[ "${1:-}" == "--local" ]]; then
  export RAFII_STUDIO_LOCAL=1
  shift
fi
if [[ "${1:-}" == "--build-editor" ]]; then
  exec node "$app_dir/build-studio.cjs"
fi
if [[ "${1:-}" == "--build" || "${1:-}" == "--serve-web" ]]; then
  node "$app_dir/build-studio.cjs"
fi
if [[ "${RAFII_STUDIO_LOCAL:-}" != 1 && ( "${1:-}" == "--build" || "${1:-}" == "--serve-web" ) ]]; then
  exec /usr/bin/python3 "$app_dir/staging_studio.py" "$1"
fi
export POSTRIFF_API_ORIGIN="http://127.0.0.1:4331"

if [[ "${1:-}" == "--build" ]]; then
  exec npm run build -- --webpack
fi

if [[ "${1:-}" == "--serve-web" ]]; then
  export NODE_ENV=production
  exec node "$app_dir/serve-studio.cjs"
fi

exec /usr/bin/python3 "$app_dir/launch_studio.py" "$@"
