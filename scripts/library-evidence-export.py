#!/usr/bin/env python3
"""Carry remote browser screenshots back through the CI log (JCB returns logs, not artifacts).

Remote (release validation, after the browser harness):
  python scripts/library-evidence-export.py emit <evidence-dir> [glob]   (default glob: *.png)
    For each PNG: SHA-256 of the original bytes, then a JPEG re-encode (ffmpeg, max 960 px wide) printed as base64 in
    fixed-size chunks: `LIBRARY_EVIDENCE <name> <index>/<count> <sha256> <chunk>`.
Local (from a downloaded `depot ci logs` file):
  python scripts/library-evidence-export.py collect <log-file> <out-dir>
    Reassembles every complete image, writes <name>.jpg and a manifest.json with the original SHA-256 per image.
The JPEG is a review copy; the manifest's hash identifies the exact remote screenshot it was made from.
"""
import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CHUNK = 6000
LINE = re.compile(r"LIBRARY_EVIDENCE (\S+) (\d+)/(\d+) ([0-9a-f]{64}) ([A-Za-z0-9+/=]+)")


def emit(directory, pattern="*.png"):
    images = sorted(Path(directory).rglob(pattern))
    print(f"LIBRARY_EVIDENCE_BEGIN {len(images)}", flush=True)
    for png in images:
        raw = png.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            jpg = Path(tmp) / "review.jpg"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(png),
                            "-vf", "scale='min(960,iw)':-2", "-q:v", "5", str(jpg)], check=True)
            body = base64.b64encode(jpg.read_bytes()).decode()
        chunks = [body[i:i + CHUNK] for i in range(0, len(body), CHUNK)] or [""]
        name = png.relative_to(directory).as_posix().replace("/", "__")[:-4]
        for index, chunk in enumerate(chunks, 1):
            print(f"LIBRARY_EVIDENCE {name} {index}/{len(chunks)} {digest} {chunk}", flush=True)
    print("LIBRARY_EVIDENCE_END", flush=True)
    return 0


def collect(log_file, out_dir):
    parts = {}
    for line in Path(log_file).read_text(errors="replace").splitlines():
        match = LINE.search(line)
        if match:
            name, index, count, digest, chunk = match.groups()
            parts.setdefault((name, digest, int(count)), {})[int(index)] = chunk
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest, incomplete = {}, []
    for (name, digest, count), chunks in sorted(parts.items()):
        if len(chunks) != count:
            incomplete.append(name)
            continue
        (out / f"{name}.jpg").write_bytes(base64.b64decode("".join(chunks[i] for i in range(1, count + 1))))
        manifest[name] = {"originalPngSha256": digest, "reviewCopy": f"{name}.jpg"}
    (out / "manifest.json").write_text(json.dumps({"source": str(log_file), "images": manifest, "incomplete": incomplete}, indent=2) + "\n")
    print(json.dumps({"written": len(manifest), "incomplete": incomplete}))
    return 1 if incomplete or not manifest else 0


if __name__ == "__main__":
    if len(sys.argv) in (3, 4) and sys.argv[1] == "emit":
        sys.exit(emit(*sys.argv[2:]))
    if len(sys.argv) == 4 and sys.argv[1] == "collect":
        sys.exit(collect(sys.argv[2], sys.argv[3]))
    print(__doc__, file=sys.stderr)
    sys.exit(2)
