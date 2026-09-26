#!/usr/bin/env python3
"""Manual Storage probe for chat videos (chat-context SPEC §7.4, §14.1). Never runs in CI.

  POSTRIFF_SUPABASE_URL=… POSTRIFF_SUPABASE_SECRET_KEY=… POSTRIFF_STORAGE_PROBE=1 \\
    python scripts/postriff_storage_probe.py --create-bucket --max-bytes 100000000
  … python scripts/postriff_storage_probe.py --probe [--skip-oversize]

`--create-bucket` creates the private `postriff-video` bucket (production step: needs James's permission).
`--probe` uploads one tiny object under a fresh random workspace prefix and checks: signed PUT, re-PUT refused,
HEAD, Range 206 on the object and on a signed read URL, oversize refused, cleanup. It prints JSON only; the key is
never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted_storage import SupabaseStorage, storage_opener  # noqa: E402

MIMES = ["video/mp4", "video/quicktime"]
SAMPLE = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isommp41" + b"\x00\x00\x00\x10free" + b"probe-data"


def refusal(argv, env):
    """Why this run must not proceed, or None."""
    if env.get("CI") or env.get("GITHUB_ACTIONS"):
        return "The storage probe never runs in CI."
    if env.get("POSTRIFF_STORAGE_PROBE") != "1":
        return "Set POSTRIFF_STORAGE_PROBE=1 to confirm this manual probe."
    if not env.get("POSTRIFF_SUPABASE_URL") or not env.get("POSTRIFF_SUPABASE_SECRET_KEY"):
        return "POSTRIFF_SUPABASE_URL and POSTRIFF_SUPABASE_SECRET_KEY are required."
    if not (argv.create_bucket or argv.probe):
        return "Choose --create-bucket or --probe."
    return None


def _put(storage, url, body, mime):
    try:
        # The oversize probe sends the full Free-plan cap; a consumer uplink can take over 20 seconds.
        with storage._open("PUT", url, {"Content-Type": mime}, body, timeout=120) as response:
            return response.status
    except HTTPError as error:
        error.close()
        return error.code


def _range(storage, url, headers):
    try:
        with storage._open("GET", url, {**headers, "Range": "bytes=4-7"}, None) as response:
            return response.status, response.read(4)
    except HTTPError as error:
        error.close()
        return error.code, b""


def create_bucket(storage, max_bytes):
    existing = storage.bucket_info()
    if existing:
        return {"created": False, "bucket": existing}
    body = json.dumps({"id": storage.video_bucket, "name": storage.video_bucket, "public": False,
                       "file_size_limit": max_bytes, "allowed_mime_types": MIMES}).encode()
    status, _, _ = storage.send("POST", f"{storage.project_url}/storage/v1/bucket", storage._headers("application/json"), body)
    return {"created": status in (200, 201), "status": status, "bucket": storage.bucket_info()}


def probe(storage, skip_oversize=False):
    workspace = str(uuid.uuid4())
    name = f"{uuid.uuid4().hex}.mp4"
    checks = {}
    bucket = storage.bucket_info()
    checks["bucket"] = bool(bucket) and not bucket["public"] and sorted(bucket["allowedMimeTypes"]) == MIMES and bool(bucket["fileSizeLimit"])
    try:
        upload = storage.signed_upload_url(workspace, "video", name)
        checks["signed_put"] = _put(storage, upload, SAMPLE, "video/mp4") in (200, 201)
        checks["re_put_refused"] = _put(storage, upload, SAMPLE, "video/mp4") not in (200, 201)
        info = storage.object_info(workspace, "video", name)
        checks["head"] = info["bytes"] == len(SAMPLE) and bool(info["etag"])
        checks["range_object"] = storage.read_range(workspace, "video", name, 4, 4) == {"data": b"ftyp", "ranged": True}
        signed = storage.signed_url(workspace, "video", name, 60)
        status, data = _range(storage, signed, {})
        checks["range_signed_url"] = status == 206 and data == b"ftyp"
        if skip_oversize or not bucket:
            checks["oversize_refused"] = None
        else:
            big_name = f"{uuid.uuid4().hex}.mp4"
            status = _put(storage, storage.signed_upload_url(workspace, "video", big_name), b"\x00" * (int(bucket["fileSizeLimit"]) + 1), "video/mp4")
            checks["oversize_refused"] = status not in (200, 201)
            if not checks["oversize_refused"]:
                storage.delete(workspace, "video", big_name)
    except (AlphaError, URLError, OSError) as error:
        checks["error"] = type(error).__name__ + ": " + str(error)
    finally:
        try:
            storage.delete(workspace, "video", name)
            checks["cleanup"] = storage.list_prefix(f"{workspace}/video") == []
        except AlphaError as error:
            checks["cleanup"] = False
            checks["cleanup_error"] = str(error)
    checks["ok"] = all(v is not False for k, v in checks.items() if k not in ("error", "cleanup_error")) and "error" not in checks
    return checks


def main(args=None, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--create-bucket", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=100_000_000)
    parser.add_argument("--skip-oversize", action="store_true")
    argv = parser.parse_args(args)
    env = os.environ if env is None else env
    reason = refusal(argv, env)
    if reason:
        print(json.dumps({"ok": False, "refused": reason}))
        return 2
    if not 1 <= argv.max_bytes <= 100_000_000:
        print(json.dumps({"ok": False, "refused": "--max-bytes must be between 1 and 100000000 (Phase 1 cap)."}))
        return 2
    storage = SupabaseStorage(env["POSTRIFF_SUPABASE_URL"], env["POSTRIFF_SUPABASE_SECRET_KEY"], opener=storage_opener())
    out = {}
    if argv.create_bucket:
        out["createBucket"] = create_bucket(storage, argv.max_bytes)
    if argv.probe:
        out["probe"] = probe(storage, argv.skip_oversize)
    out["ok"] = all(part.get("ok", part.get("created", True) or part.get("bucket")) for part in out.values() if isinstance(part, dict))
    print(json.dumps(out, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
