#!/usr/bin/env bash
# Re-render the Welcome loop and encode the files the web app serves.
#
#   ./build.sh              # both themes
#   ./build.sh dark         # one theme
#   SKIP_RENDER=1 ./build.sh  # re-encode existing renders/<theme>-frames only
#
# Output: web/public/onboarding/welcome-loop-<theme>.{webm,mp4,jpg}
set -euo pipefail

HF="npx --yes hyperframes@0.8.43"
FFMPEG="${FFMPEG:-ffmpeg}"
FPS=60
CRF_H264="${CRF_H264:-14}"   # lower = better; 8s of flat UI stays far under 1.2 MB
CRF_VP9="${CRF_VP9:-22}"
MAX_BYTES=1200000

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$(cd "$PROJECT_DIR/../.." && pwd)/web/public/onboarding"
mkdir -p "$OUT_DIR"

# Render in the RGB frame space, convert with the BT.709 matrix, and tag it,
# so browsers show #FAFAFA / #0A0A0A as authored.
VF="scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
TAGS=(-colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv)

themes=("$@")
[ ${#themes[@]} -eq 0 ] && themes=(light dark)

cd "$PROJECT_DIR"
for theme in "${themes[@]}"; do
  case "$theme" in light|dark) ;; *) echo "unknown theme: $theme" >&2; exit 1 ;; esac
  frames="renders/${theme}-frames"
  base="$OUT_DIR/welcome-loop-${theme}"
  # 1. Lossless master: one opaque PNG per frame.
  if [ "${SKIP_RENDER:-0}" != "1" ]; then
    rm -rf "$frames"
    $HF render . --strict --strict-variables --quality high --fps "$FPS" \
      --format png-sequence --variables "{\"theme\":\"${theme}\"}" -o "$frames"
  fi

  # 2. H.264 MP4 (yuv420p, faststart, no audio).
  "$FFMPEG" -v error -y -framerate "$FPS" -i "$frames/frame_%06d.png" -an \
    -vf "$VF" -c:v libx264 -preset veryslow -tune animation -crf "$CRF_H264" \
    "${TAGS[@]}" -movflags +faststart "$base.mp4"

  # 3. VP9 WebM (yuv420p, no audio).
  "$FFMPEG" -v error -y -framerate "$FPS" -i "$frames/frame_%06d.png" -an \
    -vf "$VF" -c:v libvpx-vp9 -crf "$CRF_VP9" -b:v 0 -row-mt 1 -deadline good -cpu-used 1 \
    "${TAGS[@]}" "$base.webm"

  # 4. Poster: the first frame (identical to the last, so the loop is seamless).
  "$FFMPEG" -v error -y -i "$frames/frame_000001.png" -vf format=yuvj444p -q:v 2 -frames:v 1 "$base.jpg"

  for f in "$base.mp4" "$base.webm"; do
    size=$(wc -c < "$f" | tr -d ' ')
    if [ "$size" -gt "$MAX_BYTES" ]; then
      echo "warning: $(basename "$f") is $size bytes (budget $MAX_BYTES); raise CRF_H264 / CRF_VP9" >&2
    fi
  done
  ls -l "$base".{webm,mp4,jpg}
done
