"""Video uploads on disposable PostgreSQL (chat-context SPEC §7.3): begin writes a pending row and no workspace state;
pending caps; commit adds one asset and marks the row committed in the same command (idempotent on retry); abort keeps
the row; the sweep waits for expiry + 24 h, retries a failed delete, then removes the row; purge clears the workspace.
Storage is a fake (no network); the SQL, locks and the hosted command are real.

Run through scripts/postriff_disposable_postgres.py (rls.sql with every migration, 031 included).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import video_uploads as vu  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from test_video_uploads import FakeAssets, FakeStorage, jpeg_b64, mp4  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [1789524000.0]
passed = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


VIEWER = "00000000-0000-0000-0000-000000000033"


def verify(token):
    if token not in ("one", "viewer"):
        raise AlphaError("Verified session required.", 401)
    return ONE if token == "one" else VIEWER


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


def rows(workspace_id):
    with connection() as db:
        return db.execute("SELECT replace(id::text, '-', ''), status, delete_attempts FROM public.pr_media_uploads WHERE workspace_id=%s ORDER BY created_at", (workspace_id,)).fetchall()


def age(upload_id, seconds):
    with connection() as db:
        db.execute("UPDATE public.pr_media_uploads SET token_expires_at = now() - make_interval(secs => %s), created_at = now() - make_interval(secs => %s) WHERE id=%s",
                   (seconds, seconds, upload_id))


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.bootstrap("one", "studio")
class Storage(FakeStorage):
    """Adds the `media` category reads the service uses for posters and frames."""
    def get(self, ws, category, name):
        self.calls.append(("get", category, name))
        return b"\xff\xd8poster"


class Assets(FakeAssets):
    def remove(self, ws, asset):
        from postriff_phase2.hosted_storage import PrivateAssetService
        PrivateAssetService.remove(self, ws, asset)   # the real kind-aware removal, over the fake storage


storage = Storage()
service.assets = Assets(storage)
uploads = vu.VideoUploads(service, vu.VideoPolicy(enabled=True), storage=storage, clock=lambda: clock[0])
data = mp4()


def begin():
    return uploads.begin(wid, "one", {"mime": "video/mp4", "bytes": len(data), "duration": 42.0, "width": 1080, "height": 1920})["upload"]


# 1. begin: a pending row, no state change.
revision = service.get(wid, "one")["revision"]
first = begin()
check("begin: pending row", rows(wid) == [(first["assetId"], "pending", 0)], rows(wid))
check("begin: workspace revision unchanged", service.get(wid, "one")["revision"] == revision)
with connection() as db:
    stored = db.execute("SELECT row_to_json(u)::text FROM public.pr_media_uploads u WHERE id=%s", (first["assetId"],)).fetchone()[0]
check("begin: no signed token stored", "token=" not in stored and first["uploadUrl"] not in stored)

# 2. Pending caps per member (3).
second, third = begin(), begin()
try:
    begin()
    check("caps: a fourth pending upload is refused", False)
except AlphaError as error:
    check("caps: a fourth pending upload is refused", error.status == 429 and error.code == "video_pending_caps", (error.status, error.code))

# 3. commit: one asset, the row committed in the same command; a retry is idempotent.
storage.put(f"{first['assetId']}.mp4", data)
result = uploads.commit(wid, "one", first["assetId"], {"frames": [{"at": 4.2, "data": jpeg_b64()}], "locationCleared": True})
state = service.get(wid, "one")["state"]
assets = [a for a in state["phase2"]["assets"] if a["id"] == first["assetId"]]
check("commit: the asset is in the workspace, ready, with a poster", len(assets) == 1 and assets[0]["processing"] == "ready" and assets[0]["poster"], assets)
check("commit: the row is committed", dict((r[0], r[1]) for r in rows(wid))[first["assetId"]] == "committed")
check("commit: server evidence recorded", result["video"]["durationSource"] == "container" and result["video"]["duration"] == 42.0, result["video"])
again = uploads.commit(wid, "one", first["assetId"], {"frames": []})
check("commit: a retry returns the stored record", again["video"]["assetId"] == first["assetId"] and len([a for a in service.get(wid, "one")["state"]["phase2"]["assets"] if a["id"] == first["assetId"]]) == 1)

# 4. abort keeps the row (aborted) and deletes the object.
storage.put(f"{second['assetId']}.mp4", data)
check("abort: aborted", uploads.abort(wid, "one", second["assetId"])["status"] == "aborted")
check("abort: row kept, object deleted", dict((r[0], r[1]) for r in rows(wid))[second["assetId"]] == "aborted" and ("video", f"{second['assetId']}.mp4") in storage.deleted)
try:
    uploads.abort(wid, "one", first["assetId"])
    check("abort: a ready video can't be aborted", False)
except AlphaError as error:
    check("abort: a ready video can't be aborted", error.status == 409, error.status)

# 5. sweep: nothing before expiry + 24 h; then a failed delete is retried; then the row goes.
check("sweep: nothing is due yet", uploads.sweep(connection) == {"removed": 0, "failed": 0})
age(second["assetId"], vu.SWEEP_MARGIN + 60)
age(third["assetId"], vu.SWEEP_MARGIN + 60)
storage.fail_delete = True
first_pass = uploads.sweep(connection)
check("sweep: failed deletes are counted and kept", first_pass == {"removed": 0, "failed": 2} and all(r[1] == "deleting" and r[2] == 1 for r in rows(wid) if r[0] in (second["assetId"], third["assetId"])), (first_pass, rows(wid)))
storage.fail_delete = False
second_pass = uploads.sweep(connection)
check("sweep: the retry removes both rows", second_pass == {"removed": 2, "failed": 0} and [r[0] for r in rows(wid)] == [first["assetId"]], (second_pass, rows(wid)))

# 6. Hosted wiring (PLAN S27).
# A video is served as its poster, labelled image/jpeg; playback is a signed URL for anyone who can read.
poster = next(a for a in service.get(wid, "one")["state"]["phase2"]["assets"] if a["id"] == first["assetId"])["poster"]
raw, mime = service.media(wid, "one", first["assetId"])
check("media: a video serves its poster as image/jpeg", mime == "image/jpeg" and ("get", "media", poster["objectName"]) in storage.calls, mime)
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (VIEWER,))
service.bootstrap("viewer", "studio")   # creates the viewer's profile (and their own workspace)
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", (wid, VIEWER))
check("url: a viewer may play (read)", uploads.url(wid, "viewer", first["assetId"])["mime"] == "video/mp4")
for name, call in (("begin", lambda: uploads.begin(wid, "viewer", {"mime": "video/mp4", "bytes": 10, "duration": 1.0, "width": 1, "height": 1})),
                   ("commit", lambda: uploads.commit(wid, "viewer", first["assetId"], {"frames": []})),
                   ("abort", lambda: uploads.abort(wid, "viewer", third["assetId"]))):
    try:
        call()
        check(f"viewer: {name} is refused", False)
    except AlphaError as error:
        check(f"viewer: {name} is refused (403)", error.status == 403, error.status)

# Commit after someone else changed the workspace (a concurrent photo upload): it reads the current revision itself.
fourth = begin()
storage.put(f"{fourth['assetId']}.mp4", data)
service.repository.command(wid, "one", service.get(wid, "one")["revision"], lambda state, actor: state)   # another writer's revision bump
committed = uploads.commit(wid, "one", fourth["assetId"], {"frames": [{"at": 1.0, "data": jpeg_b64()}], "locationCleared": True})
check("commit: succeeds after a concurrent change", committed["video"]["assetId"] == fourth["assetId"])

# A wrong container is refused and its object deleted.
fifth = begin()
storage.put(f"{fifth['assetId']}.mp4", b"\x00" * 64)
try:
    uploads.commit(wid, "one", fifth["assetId"], {"frames": []})
    check("commit: a wrong brand is refused", False)
except AlphaError as error:
    check("commit: a wrong brand is refused (400) and the object deleted", error.status == 400 and ("video", f"{fifth['assetId']}.mp4") in storage.deleted, (error.status, str(error)))

# Library deletion (p2_media_delete → delete_media) removes the video, its poster and frames, and its notes.
video = next(a for a in service.get(wid, "one")["state"]["phase2"]["assets"] if a["id"] == fourth["assetId"])
with connection() as db:
    db.execute("INSERT INTO public.pr_media_notes(workspace_id, asset_id, asset_hash, reader_version, processor, status, kind, frames, attempts, created_by) "
               "VALUES (%s,%s,%s,'v1','{}'::jsonb,'ready','video_frames',1,1,%s)", (wid, fourth["assetId"], str(video.get("hash") or ""), ONE))
service.delete_media(wid, "one", service.get(wid, "one")["revision"], fourth["assetId"])
names = {name for _category, name in storage.deleted}
with connection() as db:
    left = db.execute("SELECT count(*) FROM public.pr_media_notes WHERE workspace_id=%s AND asset_id=%s", (wid, fourth["assetId"])).fetchone()[0]
check("delete: video, poster and frames removed", f"{fourth['assetId']}.mp4" in names and video["poster"]["objectName"] in names and all(f["objectName"] in names for f in video["frames"]), (names, video.get("frames")))
check("delete: the notes are purged in the same command", left == 0, left)

# 7. purge_workspace: every row and the prefix.
begin()
with connection() as db, db.cursor() as cur:
    uploads.purge_workspace(cur, wid)
check("purge: no upload rows left", rows(wid) == [], rows(wid))

print(f"postgres_video: {len(passed)}/{len(passed)} checks passed")
