#!/usr/bin/env bash
# Run on an already-authorized Linux NVIDIA CUDA host. This script never provisions a host.
set -euo pipefail

RAFII_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOULX_REPO_PATH="${SOULX_REPO_PATH:?Set SOULX_REPO_PATH to the official SoulX-FlashHead checkout}"
SOULX_ENV_DIR="${SOULX_ENV_DIR:-$HOME/.venvs/rafii-soulx-lite}"
SOULX_MODELS_DIR="${SOULX_MODELS_DIR:-$HOME/models/rafii-soulx-lite}"
SOULX_SOURCE_REVISION=9bc03de06bb0de82cd6bc477804512ae06144bf2
SOULX_MODEL_REVISION=59119b6c681230c3eeee157e224ae1941746711e
SOULX_WAV2VEC_REVISION=22aad52d435eb6dbaf354bdad9b0da84ce7d6156
export SOULX_MODEL_REVISION SOULX_WAV2VEC_REVISION

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo 'SoulX Lite setup requires Linux x86_64 with NVIDIA CUDA.' >&2; exit 1
fi
if ! command -v nvidia-smi >/dev/null || ! nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null; then
  echo 'No accessible NVIDIA GPU was detected.' >&2; exit 1
fi
if [[ "$(git -C "$SOULX_REPO_PATH" rev-parse HEAD)" != "$SOULX_SOURCE_REVISION" ]]; then
  echo "SoulX source must be at $SOULX_SOURCE_REVISION" >&2; exit 1
fi

case "${1:-}" in
  install)
    python3.10 -m venv "$SOULX_ENV_DIR"
    "$SOULX_ENV_DIR/bin/python" -m pip install --upgrade 'pip==25.2'
    "$SOULX_ENV_DIR/bin/python" -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
    "$SOULX_ENV_DIR/bin/python" -m pip install -r "$SOULX_REPO_PATH/requirements.txt"
    "$SOULX_ENV_DIR/bin/python" -m pip install ninja 'flash_attn==2.8.0.post2' --no-build-isolation
    "$SOULX_ENV_DIR/bin/python" -m pip install 'fastapi==0.115.12' 'uvicorn[standard]==0.34.2' 'huggingface_hub==0.35.3'
    "$SOULX_ENV_DIR/bin/python" -m pip freeze > "$SOULX_ENV_DIR/rafii-soulx-installed-freeze.txt"
    ;;
  download)
    [[ -x "$SOULX_ENV_DIR/bin/python" ]] || { echo 'Run install first.' >&2; exit 1; }
    mkdir -p "$SOULX_MODELS_DIR"
    available_kib="$(df -Pk "$SOULX_MODELS_DIR" | awk 'NR==2 {print $4}')"
    if (( available_kib < 20 * 1024 * 1024 )); then
      echo 'At least 20 GiB of free space is required for weights and transfer cache.' >&2; exit 1
    fi
    SOULX_MODELS_DIR="$SOULX_MODELS_DIR" "$SOULX_ENV_DIR/bin/python" - <<'PY'
import os
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(os.environ["SOULX_MODELS_DIR"])
snapshot_download("Soul-AILab/SoulX-FlashHead-1_3B", revision=os.environ["SOULX_MODEL_REVISION"],
                  allow_patterns=["Model_Lite/*", "VAE_LTX/*"],
                  local_dir=root / "SoulX-FlashHead-1_3B")
snapshot_download("facebook/wav2vec2-base-960h", revision=os.environ["SOULX_WAV2VEC_REVISION"],
                  allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors"],
                  local_dir=root / "wav2vec2-base-960h")
PY
    ;;
  check)
    for path in \
      "$SOULX_MODELS_DIR/SoulX-FlashHead-1_3B/Model_Lite/config.json" \
      "$SOULX_MODELS_DIR/SoulX-FlashHead-1_3B/Model_Lite/diffusion_pytorch_model.safetensors" \
      "$SOULX_MODELS_DIR/SoulX-FlashHead-1_3B/VAE_LTX/config.json" \
      "$SOULX_MODELS_DIR/SoulX-FlashHead-1_3B/VAE_LTX/diffusion_pytorch_model.safetensors" \
      "$SOULX_MODELS_DIR/wav2vec2-base-960h/config.json" \
      "$SOULX_MODELS_DIR/wav2vec2-base-960h/preprocessor_config.json" \
      "$SOULX_MODELS_DIR/wav2vec2-base-960h/model.safetensors"; do
      [[ -s "$path" ]] || { echo "Missing $path" >&2; exit 1; }
    done
    echo 'All required Lite, LTX VAE, and wav2vec files are present.'
    ;;
  run)
    "$0" check
    export SOULX_REPO_PATH
    export SOULX_CHECKPOINT_DIR="$SOULX_MODELS_DIR/SoulX-FlashHead-1_3B"
    export SOULX_WAV2VEC_DIR="$SOULX_MODELS_DIR/wav2vec2-base-960h"
    export RAFFII_AVATAR_REFERENCE="${RAFFII_AVATAR_REFERENCE:-$RAFII_ROOT/web/public/raffi/avatar-256.png}"
    [[ -s "$RAFFII_AVATAR_REFERENCE" ]] || { echo 'Missing Rafii reference image.' >&2; exit 1; }
    exec "$SOULX_ENV_DIR/bin/python" "$RAFII_ROOT/scripts/rafii_soulx_worker.py"
    ;;
  *) echo 'Usage: setup_rafii_soulx_lite.sh install|download|check|run' >&2; exit 2 ;;
esac
