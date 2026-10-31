#!/usr/bin/env bash
# Native, local-only Pinterest review recording. No remote transfer, publication or frame fabrication.
set -euo pipefail
umask 077

usage() {
  printf 'Usage: %s record <seconds:1-300> </absolute/path/recording.mp4>\n' "$0" >&2
  printf '       %s verify </absolute/path/recording.mp4>\n' "$0" >&2
  exit 2
}
[[ $# -ge 2 ]] || usage
action="$1"
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && command -v python3 >/dev/null || {
  echo 'ffmpeg, ffprobe and python3 are required.' >&2
  exit 69
}
case "$action" in
  record)
    [[ $# -eq 3 && "$2" =~ ^[0-9]+$ && "$2" -ge 1 && "$2" -le 300 ]] || usage
    seconds="$2"
    output="$3"
    ;;
  verify)
    [[ $# -eq 2 ]] || usage
    output="$2"
    ;;
  *) usage ;;
esac
[[ "$output" == /* && "$output" == *.mp4 ]] || usage
if [[ "$action" == record ]]; then
  [[ ! -e "$output" ]] || { echo 'Refusing to overwrite existing recording.' >&2; exit 73; }
  source_mov="${output%.mp4}.source.mov"
  [[ ! -e "$source_mov" ]] || { echo 'Refusing to overwrite existing MOV source.' >&2; exit 73; }
  mkdir -p "${output%/*}"
  echo 'Before recording: hide passwords, OTP, OAuth code/state, account secrets and unrelated windows.'
  echo 'Native capture is local-only; the complete video still requires manual privacy review.'
  /usr/sbin/screencapture -x -v -V "$seconds" "$source_mov"
  [[ -s "$source_mov" ]] || { echo 'Native recording produced no MOV.' >&2; exit 1; }
  ffmpeg -hide_banner -loglevel error -n -i "$source_mov" -map 0:v:0 -c:v copy -an -movflags +faststart "$output"
fi
[[ -s "$output" ]] || { echo 'Missing or empty MP4.' >&2; exit 1; }
meta="${output%.mp4}.ffprobe.json"
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,avg_frame_rate,nb_frames -show_entries format=duration,size -of json "$output" > "$meta"
python3 - "$meta" <<'PY'
import json, sys
from fractions import Fraction
m=json.load(open(sys.argv[1], encoding='utf-8'))
streams=m.get('streams') or []
if len(streams)!=1: raise SystemExit('FAIL: missing/extra video streams')
v=streams[0]; fps=float(Fraction(v.get('avg_frame_rate') or '0/1'))
width=int(v.get('width') or 0); height=int(v.get('height') or 0)
duration=float(m.get('format',{}).get('duration') or 0)
size=int(m.get('format',{}).get('size') or 0)
print(f'Original measured video: {fps:.2f} fps, {width}x{height}, {duration:.2f} sec, {size} bytes')
if not 20 <= fps <= 60 or min(width,height)<720 or duration<=0 or size>=2_000_000_000:
    raise SystemExit('FAIL: original recording fails Pinterest application format gate; do not upsample.')
print('FORMAT PASS only; actual OAuth/API content and privacy still require manual review.')
PY
shasum -a 256 "$output" > "${output%.mp4}.sha256"
[[ ! -f "${output%.mp4}.source.mov" ]] || shasum -a 256 "${output%.mp4}.source.mov" > "${output%.mp4}.source.sha256"
printf 'Verified local MP4: %s\nSHA-256 receipt: %s\n' "$output" "${output%.mp4}.sha256"
