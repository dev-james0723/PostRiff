#!/usr/bin/env bash
# Run only on the cloud Linux CI executor. Keep the calling package directory.
# Example from web/: bash ../scripts/cloud-python-bootstrap.sh node --test tests/*.test.cjs
set -euo pipefail

case "${CI:-}" in
  1|true|TRUE) ;;
  *) echo "JCB Python bootstrap requires the cloud CI environment." >&2; exit 64 ;;
esac
if [ "$(uname -s)" != "Linux" ]; then
  echo "JCB Python bootstrap refuses execution on the Mac; use JCB cloud execution." >&2
  exit 64
fi
if [ "$#" -eq 0 ]; then
  echo "Usage: cloud-python-bootstrap.sh COMMAND [ARG ...]" >&2
  exit 64
fi

jcb_python_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
jcb_python_base="${JCB_PYTHON:-python3}"
jcb_python_requirements="$jcb_python_repo_root/requirements-dev.txt"
if [ ! -f "$jcb_python_requirements" ] || [ ! -f "$jcb_python_repo_root/requirements.txt" ]; then
  echo "JCB cloud Python bootstrap requires this repo's pinned Python requirement files." >&2
  exit 66
fi

# Match the repository's Python pin; Ubuntu 24.04 supplies Python 3.12.
"$jcb_python_base" - "$jcb_python_repo_root/.python-version" <<'PY'
from pathlib import Path
import re
import sys
expected = Path(sys.argv[1]).read_text().strip()
if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", expected):
    raise SystemExit("Invalid repository Python version pin.")
actual = ".".join(str(part) for part in sys.version_info[:len(expected.split('.'))])
if actual != expected:
    raise SystemExit(f"Cloud Python {actual} does not match the repository pin {expected}.")
PY

jcb_python_temp_root="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
mkdir -p -- "$jcb_python_temp_root"
jcb_python_venv="$(mktemp -d "$jcb_python_temp_root/jcb-python.XXXXXXXX")"
trap 'rm -rf -- "$jcb_python_venv"' EXIT
if ! "$jcb_python_base" -m venv "$jcb_python_venv"; then
  # Ubuntu's system Python can omit ensurepip until its venv package is installed.
  # Repair only this cloud runner; the platform/CI guard above refuses the Mac.
  jcb_python_venv_package="$("$jcb_python_base" -c 'import sys; print("python%d.%d-venv" % sys.version_info[:2])')"
  if [ "$(id -u)" -eq 0 ]; then
    apt-get -qq update
    apt-get -y -qq install "$jcb_python_venv_package"
  else
    sudo -n apt-get -qq update
    sudo -n apt-get -y -qq install "$jcb_python_venv_package"
  fi
  "$jcb_python_base" -m venv "$jcb_python_venv"
fi

# This directory may be a Depot cache mount. It is cloud-owned and never copied
# from the Mac. --isolated avoids inherited pip configuration or private indexes.
jcb_python_pip_cache="${JCB_PIP_CACHE_DIR:-$jcb_python_temp_root/jcb-pip-cache}"
mkdir -p -- "$jcb_python_pip_cache"
"$jcb_python_venv/bin/python" -m pip --isolated --disable-pip-version-check \
  install --no-input --quiet --index-url https://pypi.org/simple \
  --cache-dir "$jcb_python_pip_cache" -r "$jcb_python_requirements"
"$jcb_python_venv/bin/python" -m pip --isolated --disable-pip-version-check check

# visual-analysis.test.cjs honours this explicit override before considering
# .venv or PATH. Other Python bridges find the same isolated interpreter on PATH.
export TREND_VISUAL_TEST_PYTHON="$jcb_python_venv/bin/python"
export PATH="$jcb_python_venv/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
echo "JCB cloud Python dependencies ready: requirements-dev.txt, isolated venv."

# Run in the original caller directory and preserve command failure. No local
# fallback exists here. Cleanup removes only the mktemp-owned cloud venv.
"$@"
