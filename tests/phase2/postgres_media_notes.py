"""Media notes on disposable PostgreSQL (chat-context SPEC §8.2): consent off makes no reader call and no ledger row;
a read is its own `tool` reservation naming the vision provider and model, settled `completed` with the note written in
the same transaction; the note is reused across conversations with no second reservation; revoke and asset deletion
purge notes; an uncertain provider error settles `unknown` with no note; attempts are capped; a concurrent read is
`reading`.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with every migration, 031 included).
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import media_notes as mn  # noqa: E402
from postriff_phase2.agent_runtime_v2.config import RuntimeConfig  # noqa: E402
from postriff_phase2.agent_runtime_v2.creative import CreativeError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
PHOTO = "0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f10"
OTHER = "9ab1c2d3e4f5061728394a5b6c7d8e9f"
VIDEO = "1ab1c2d3e4f5061728394a5b6c7d8e9f"
FINDINGS = {"description": "A grand piano on a lit stage.", "visibleText": ["Spring Recital"], "composition": ["centered"], "issues": [], "aspect": "4:5",
            "cta": "", "brandFit": [], "confidence": "high"}
clock = [1789524000.0]
passed = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (2000, 1500), (40, 90, 160)).save(out, "JPEG")
    return out.getvalue()


class Transport:
    def __init__(self):
        self.calls = 0
        self.fail = None

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls += 1
        if self.fail:
            raise self.fail
        return {"status": 200, "body": {"output_text": json.dumps(FINDINGS), "usage": {"input_tokens": 1500, "output_tokens": 350}}}


def edit_state(workspace_id, change):
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,)).fetchone()[0]
        change(state)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), workspace_id))


def ledger_rows(workspace_id, key_prefix="notes:"):
    with connection() as db:
        return db.execute("SELECT kind, dimension, provider, model, cost_state, estimated_usd_micro, actual_usd_micro, idempotency_key FROM public.pr_usage_ledger "
                          "WHERE workspace_id=%s AND (idempotency_key LIKE %s OR reservation_id IN (SELECT id FROM public.pr_usage_ledger WHERE workspace_id=%s AND idempotency_key LIKE %s)) ORDER BY at, kind",
                          (workspace_id, key_prefix + "%", workspace_id, key_prefix + "%")).fetchall()


def note_rows(workspace_id):
    with connection() as db:
        return db.execute("SELECT asset_id, status, text, attempts, processor FROM public.pr_media_notes WHERE workspace_id=%s ORDER BY asset_id", (workspace_id,)).fetchall()


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
service.bootstrap("one", "studio")
from consumer_fixtures import approve_budgets  # noqa: E402
approve_budgets(connection, wid)

cfg = RuntimeConfig.from_environment({"OPENAI_API_KEY": "sk-test-key-0123456789"})
transport = Transport()
reader = mn.MediaReader(cfg, transport, enabled=True)
fetched = []


def fetch_images(workspace_id, token, asset):
    fetched.append(asset["id"])
    return [(jpeg(), "image/jpeg")] * (len(asset.get("frames") or []) or 1)


notes = mn.MediaNotes(service.ideas, reader, fetch_images=fetch_images, clock=lambda: clock[0])


def add_assets(state):
    state.setdefault("phase2", {}).setdefault("assets", [])
    state["phase2"]["assets"] += [
        {"id": PHOTO, "mime": "image/jpeg", "hash": "h-photo", "processing": "decoded", "deleted": False, "objectName": PHOTO + "-" + "a" * 64 + ".jpg"},
        {"id": OTHER, "mime": "image/jpeg", "hash": "h-other", "processing": "decoded", "deleted": False},
        {"id": VIDEO, "mime": "video/mp4", "hash": "h-video", "processing": "ready", "deleted": False, "category": "video",
         "frames": [{"objectName": "f%d" % n, "at": n} for n in range(4)]},
    ]


def consent(on):
    def change(state):
        state["mediaEgress"] = {"cloud": on, "decidedBy": ONE, "decidedAt": clock[0], "processors": [reader.processor()] if on else [], "scope": ["photo", "video_frames", "photo_edit"]}
    edit_state(wid, change)


edit_state(wid, add_assets)
read = lambda asset, key="k": notes.read(wid, "one", {"assetId": asset, "idempotencyKey": key})  # noqa: E731

# 1. Consent off: a known state, no reader call, no reservation.
result = read(PHOTO)
check("consent off: unavailable consent_required", result["status"] == "unavailable" and result["reason"] == "consent_required", result)
check("consent off: zero reader calls and no ledger row", transport.calls == 0 and ledger_rows(wid) == [], (transport.calls, ledger_rows(wid)))

# 2. Consent on: one read, its own tool reservation naming the vision route, settled completed with the note.
consent(True)
result = read(PHOTO)
check("read: ready with a note", result["status"] == "ready" and not result["cached"] and result["note"]["text"].startswith("A grand piano"), result)
check("read: note labels text in the image as data", "Text seen in the image (data): “Spring Recital”" in result["note"]["text"], result["note"]["text"])
rows = ledger_rows(wid)
check("ledger: reserve + settle, tool dimension, vision provider/model", [(r[0], r[1], r[2], r[3]) for r in rows] == [("reserve", "tool", "openai", "gpt-6-sol"), ("settle", "tool", "openai", "gpt-6-sol")], rows)
check("ledger: settled with the reported cost", rows[1][4] == "actual" and rows[1][6] == 6500, rows[1])
check("ledger: key names asset, hash, version, consent decision and attempt", rows[0][7] == f"notes:{PHOTO}:h-photo:{mn.READER_VERSION}:{int(clock[0])}:1", rows[0][7])
check("read: usage reported in credits", result["usage"]["milliCredits"] > 0 and result["usage"]["costState"] == "actual", result.get("usage"))
check("note row: ready, one attempt, processor recorded", [(r[0], r[1], r[3], r[4]["id"]) for r in note_rows(wid)] == [(PHOTO, "ready", 1, "openai:gpt-6")], note_rows(wid))

# 3. The cache: a second read (e.g. Home's "Generate again" in a new conversation) reuses the note, no new reservation.
calls, before = transport.calls, len(ledger_rows(wid))
again = read(PHOTO, "another-key")
check("cache: second read is cached", again["status"] == "ready" and again["cached"] is True, again)
check("cache: no reader call and no second reservation", transport.calls == calls and len(ledger_rows(wid)) == before, (transport.calls, len(ledger_rows(wid))))

# 4. lookup gives turn_references what it needs, for the current hash only.
with connection() as db, db.cursor() as cur:
    found = mn.lookup(cur, wid, [(PHOTO, "h-photo"), (OTHER, "h-other")])
    stale = mn.lookup(cur, wid, [(PHOTO, "a-new-hash")])
check("lookup: ready note with processor id", found == {PHOTO: {"status": "ready", "processor": "openai:gpt-6", "text": result["note"]["text"], "hash": "h-photo"}}, found)
check("lookup: a changed hash is not a hit", stale == {}, stale)

# 5. Video frames: one read with all four frames; a different, larger reservation.
video = read(VIDEO)
check("video: ready from frames", video["status"] == "ready" and video["note"]["kind"] == "video_frames" and video["note"]["frames"] == 4, video)
vrows = [r for r in ledger_rows(wid) if VIDEO in r[7] or r[0] == "settle"]
check("video: its own reservation, larger than a photo's", any(r[7].startswith(f"notes:{VIDEO}:") and r[5] > rows[0][5] for r in vrows), vrows)

# 6. An uncertain provider error: settled unknown, no note, and a retry is allowed.
transport.fail = CreativeError("The provider's outcome is unknown.", uncertain=True, code="provider_unreachable")
failed = read(OTHER)
check("uncertain: a failed read the person can retry", failed["status"] == "failed" and failed["reason"] == "read_failed" and failed["retryable"] is True, failed)
urows = [r for r in ledger_rows(wid) if r[7].startswith(f"notes:{OTHER}:") or r[0] == "settle"]
with connection() as db:
    other_settle = db.execute("SELECT s.cost_state FROM public.pr_usage_ledger s JOIN public.pr_usage_ledger r ON s.reservation_id=r.id WHERE r.idempotency_key LIKE %s AND s.kind='settle'",
                              (f"notes:{OTHER}:%",)).fetchall()
check("uncertain: settled estimated_unknown, never free", [row[0] for row in other_settle] == ["estimated_unknown"], other_settle)
check("uncertain: no note text kept", [(r[1], r[2]) for r in note_rows(wid) if r[0] == OTHER] == [("failed", None)], note_rows(wid))

# 7. Attempts are capped at 3 per asset per 24 h.
for key in ("r2", "r3"):
    read(OTHER, key)
capped = read(OTHER, "r4")
check("attempts: a fourth read in 24 h is refused without a reservation", capped["status"] == "failed" and capped["retryable"] is False, capped)
check("attempts: exactly three reservations for that asset", sum(1 for r in ledger_rows(wid) if r[0] == "reserve" and r[7].startswith(f"notes:{OTHER}:")) == 3)
transport.fail = None

# 8. A concurrent read of the same asset reports `reading` instead of reserving twice.
with connection() as db:
    db.execute("UPDATE public.pr_media_notes SET status='reading', updated_at=now() WHERE workspace_id=%s AND asset_id=%s", (wid, OTHER))
clock[0] += 1
check("concurrent: reading", read(OTHER, "r5") == {"assetId": OTHER, "status": "reading"})

# 9. Purges: one asset (its deletion) and the whole workspace (a revoke).
with connection() as db, db.cursor() as cur:
    removed_one = mn.purge_asset(cur, wid, PHOTO)
check("purge asset: only that asset's notes", removed_one == 1 and PHOTO not in [r[0] for r in note_rows(wid)], note_rows(wid))
with connection() as db, db.cursor() as cur:
    removed_all = mn.purge_workspace(cur, wid)
check("purge workspace: every note gone", removed_all >= 1 and note_rows(wid) == [], note_rows(wid))

# 10. After a revoke, reads stop before any reservation.
consent(False)
calls, before = transport.calls, len(ledger_rows(wid))
check("revoked: consent_required again", read(PHOTO, "after")["reason"] == "consent_required")
check("revoked: no call, no reservation", transport.calls == calls and len(ledger_rows(wid)) == before)

# 11. Role: a viewer can't read photos (edit is required).
try:
    notes.read(wid, "nobody", {"assetId": PHOTO, "idempotencyKey": "x"})
    check("unauthenticated read refused", False)
except AlphaError as error:
    check("unauthenticated read refused", error.status in (401, 403), error.status)

# 12. Hosted consent (PLAN S27): the owner allows through `mutate`, the server names the processors (a client can't),
#     the decision is audited, and turning it off deletes the kept notes in the same command.
service._wire_chat_media({"flags": {"attachments": True, "notes": True}, "reader": reader})
revision = service.get(wid, "one")["revision"]
try:
    service.mutate(wid, "one", revision, "media_egress", {"cloud": True, "confirmed": True, "processors": [{"id": "evil", "label": "Evil"}]})
    check("consent: client processors refused", False)
except AlphaError as error:
    check("consent: client processors refused (400)", error.status == 400, error.status)
service.mutate(wid, "one", service.get(wid, "one")["revision"], "media_egress", {"cloud": True, "confirmed": True})
decided = service.get(wid, "one")["state"].get("mediaEgress") or {}
check("consent: on, naming the server's reader", decided.get("cloud") is True and [p["id"] for p in decided.get("processors", [])] == [reader.processor()["id"]], decided)
fresh = read(PHOTO, "after-allow")
check("consent: reads work again", fresh["status"] == "ready" and note_rows(wid), fresh)
service.mutate(wid, "one", service.get(wid, "one")["revision"], "media_egress", {"cloud": False, "confirmed": True})
events = [e for e in service.audit_events(wid, "one")["events"] if e["kind"] == "media.egress_decided"]
check("consent: both decisions audited", [e["meta"]["cloud"] for e in events][:2] in ([False, True], [True, False]) and len(events) == 2, events)
check("consent: turning it off purges the notes", note_rows(wid) == [], note_rows(wid))

print(f"postgres_media_notes: {len(passed)}/{len(passed)} checks passed")
