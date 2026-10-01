"""Raw-file intake on disposable PostgreSQL (PRD R-FWR-04; AC11, AC12, AC28, AC29, AC30, AC36, AC38).

Real hosted repository, membership/RLS, credit ledger and workspace commands; storage is an in-memory fake (no
network) and the only transcriber is the labelled synthetic one. A text PDF and a WAV recording each go begin →
commit → leased job → review/correction → canonical source. Around them: unsupported, over-limit, scanned,
encrypted and mismatched files; injected instructions, unsafe links and cancelled intake; leases, attempt caps,
stale recovery and unknown provider outcomes; idempotent replays; cross-tenant ids; a member revoked mid-job;
Free refused before any quote; retention, retraction, account-deletion purges and a failing storage delete.

Run: RAFII_PG_PORT=55887 PYTHONPATH=src:tests <python> scripts/rafii_pg_private.py postgres_source_uploads
"""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg  # noqa: E402
from psycopg import errors  # noqa: E402

from consumer_fixtures import approve_budgets  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.credit_meter import V2_POLICY_VERSION  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.source_uploads import jobs, pdf_text, transcribe  # noqa: E402
from postriff_phase2.source_uploads.service import SourceUploads  # noqa: E402
from source_upload_fixtures import INJECTION, PARAGRAPH, encrypted_pdf_bytes, mp3_bytes, pdf_bytes, wav_bytes  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ROOT = Path(__file__).resolve().parents[2]
USERS = {"intake-owner-token-0000000000": "00000000-0000-4000-8000-000000000101", "intake-editor-token-000000000": "00000000-0000-4000-8000-000000000102",
         "intake-viewer-token-000000000": "00000000-0000-4000-8000-000000000103", "intake-other-token-0000000000": "00000000-0000-4000-8000-000000000104"}
OWNER, EDITOR, VIEWER, OTHER = list(USERS)
MIMES = ["application/pdf", "audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg"]
passed = []
assert pdf_text.available(), "pypdf (requirements.txt) must be installed for this suite"


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in USERS:
        raise AlphaError("Verified session required.", 401)
    return USERS[token]


verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
verify.auth_time = lambda token, principal: time.time()


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


def refused(name, call, status, code=None):
    try:
        call()
    except AlphaError as error:
        assert error.status == status and (code is None or error.code == code), f"{name}: {error.status} {error.code} {error}"
        passed.append(name)
        return error
    raise AssertionError(f"{name}: accepted")


def sql(query, args=None):
    with connection() as db:
        cur = db.execute(query, args)
        return cur.fetchall() if cur.description else None


class Storage:
    """Private storage stand-in: signed URL, HEAD, ranged reads and deletes; failures switch on per test."""
    source_bucket = "rafii-source-uploads"

    def __init__(self):
        self.objects, self.deleted, self.fail_delete, self.down = {}, [], False, False

    def bucket_info(self, bucket=None):
        return {"id": bucket, "public": False, "fileSizeLimit": 30_000_000, "allowedMimeTypes": MIMES}

    def signed_upload_url(self, ws, category, name):
        assert category == "source"
        return f"https://abcd1234.supabase.co/storage/v1/object/upload/sign/rafii-source-uploads/{ws}/source/{name}?token=t"

    def put(self, ws, name, data, mime):
        self.objects[(ws, name)] = (data, mime)

    def object_info(self, ws, category, name):
        if self.down:
            raise AlphaError("Private storage is temporarily unavailable.", 503)
        if (ws, name) not in self.objects:
            raise AlphaError("This private media object is unavailable.", 404)
        data, mime = self.objects[(ws, name)]
        return {"bytes": len(data), "mime": mime, "etag": '"etag-1"'}

    def read_range(self, ws, category, name, start, length):
        if self.down:
            raise AlphaError("Private storage is temporarily unavailable.", 503)
        if (ws, name) not in self.objects:
            raise AlphaError("This private media object is unavailable.", 404)
        return {"data": self.objects[(ws, name)][0][start:start + length], "ranged": True}

    def delete(self, ws, category, name):
        if self.fail_delete:
            raise AlphaError("Private storage could not delete this object.", 502)
        self.deleted.append(name)
        self.objects.pop((ws, name), None)


class Route(transcribe.SyntheticTranscriber):
    """The labelled synthetic transcriber with an optional hook that runs while the 'provider' works."""
    during = None

    def transcribe(self, data, mime, seconds, *, timeout):
        if self.during:
            hook, self.during = self.during, None
            hook()
        return super().transcribe(data, mime, seconds, timeout=timeout)


def resolver(host, port, type=None):
    return [(2, 1, 6, "", ("10.0.0.5" if host.startswith("intranet") else "93.184.216.34", 443))]


# --- setup --------------------------------------------------------------------------------------------------------------
with connection() as db:
    for name in ("020_credit_quotes.sql", "021_credit_purchases.sql", "022_credit_payment_lifecycle.sql", "048_pricing_credit_catalog_v2.sql", "050_free_lifecycle_bootstrap.sql"):
        db.execute((ROOT / "migrations/postriff" / name).read_text())
    for user in USERS.values():
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))
# AC30: 087 is in rls.sql already; applying it again changes nothing and fails nothing.
with connection() as db:
    db.execute((ROOT / "migrations/postriff/087_source_uploads.sql").read_text())
check("AC30 migration 087 reapplies cleanly", True)
rows = sql("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c WHERE c.relkind='r' AND c.relname LIKE 'pr_source_upload%' ORDER BY 1")
check("AC30 every intake table has forced RLS", len(rows) == 5 and all(r[1] and r[2] for r in rows), rows)

service = HostedWorkspaceService(connection, verify, credits_enabled=True)
wid = service.bootstrap(OWNER, "studio")["workspaceId"]
other_wid = service.bootstrap(OTHER, "studio")["workspaceId"]
for token, role in ((EDITOR, "editor"), (VIEWER, "viewer")):
    service.bootstrap(token, "studio")
    sql("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active') ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role,status='active'",
        (wid, USERS[token], role))
with connection() as db:
    cur = db.cursor()
    cur.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,currency,status,entitlements) VALUES('intake-creator','creator',997,'Synthetic intake Creator',0,'USD','active',%s::jsonb) ON CONFLICT DO NOTHING",
                (json.dumps({"writingBatches": 0, "mediaCredits": 0, "members": 3, "connectedAccounts": 3, "storageMb": 200, "creditPolicy": V2_POLICY_VERSION, "monthlyCredits": 3500}),))
    for workspace in (wid, other_wid):
        service.ledger.ensure_entitlement(cur, workspace, None)
    cur.execute("UPDATE pr_entitlements SET plan_terms_id='intake-creator' WHERE workspace_id=%s", (wid,))
    cur.execute("UPDATE pr_entitlements SET plan_terms_id='free-v1' WHERE workspace_id=%s", (other_wid,))
    service.ledger.credits.grant(cur, wid, USERS[OWNER], "intake-funding", 60_000, None, source="local-test-only")
approve_budgets(connection, wid)

storage = Storage()
route = Route(script="Our spring concert is on 12 April at the city hall. Tickets open on Monday for every family in the district.")
intake = SourceUploads(service, values={"RAFII_SOURCE_UPLOADS_ENABLED": "1"}, storage=storage, transcriber=route, resolver=resolver)
service.source_uploads = intake
key = lambda: "k-" + uuid.uuid4().hex[:20]  # noqa: E731


def upload(kind, data, *, name="file", mime=None, token=OWNER, workspace=None, commit=True, actual_mime=None):
    workspace = workspace or wid
    mime = mime or {"pdf": "application/pdf", "audio": "audio/wav"}[kind]
    begun = intake.begin(workspace, token, {"kind": kind, "name": name, "mime": mime, "bytes": len(data), "idempotencyKey": key()})
    up = begun["upload"]
    name_on_store = begun["transfer"]["url"].split("/source/")[1].split("?")[0]
    storage.put(workspace, name_on_store, data, actual_mime or begun["transfer"]["headers"]["Content-Type"])
    if commit:
        return intake.commit(workspace, token, up["id"])
    return up


def results(upload_id):
    return sql("SELECT count(*) FROM public.pr_source_upload_results r JOIN public.pr_source_upload_jobs j ON j.id=r.job_id WHERE j.upload_id=%s", (upload_id,))[0][0]


def state():
    return service.get(wid, OWNER)["state"]


def due_now(upload_id):
    sql("UPDATE public.pr_source_upload_jobs SET due_at=now() WHERE upload_id=%s", (upload_id,))


# --- limits ---------------------------------------------------------------------------------------------------------------
shown = intake.limits_view(wid, OWNER)
check("AC11 limits are shown before upload", shown["limits"]["audio"] == {"maxBytes": 30_000_000, "maxSeconds": 600}
      and shown["limits"]["pdf"] == {"maxBytes": 20_000_000, "maxPages": 100, "maxCharacters": 60_000}, shown["limits"])
check("AC11 audio is offered only through the configured synthetic route, labelled", shown["formats"]["audio"]["supported"] and shown["formats"]["audio"]["synthetic"], shown["formats"])
no_route = SourceUploads(service, values={"RAFII_SOURCE_UPLOADS_ENABLED": "1"}, storage=storage)
plain = no_route.limits_view(wid, OWNER)["formats"]["audio"]
check("AC11 without an approved route audio is unsupported, said plainly", not plain["supported"] and plain["reason"] == "transcription_route_not_enabled", plain)
refused("AC11 audio begin is refused before any upload when no route is enabled",
        lambda: no_route.begin(wid, OWNER, {"kind": "audio", "name": "memo.m4a", "mime": "audio/mp4", "bytes": 1000, "idempotencyKey": key()}), 409, "transcription_route_not_enabled")
off = SourceUploads(service, values={}, storage=storage)
refused("flag off: admission answers feature_disabled", lambda: off.begin(wid, OWNER, {"kind": "pdf", "name": "a.pdf", "mime": "application/pdf", "bytes": 10, "idempotencyKey": key()}), 404, "feature_disabled")

# --- AC11: one text PDF through the genuine adapter to a source -------------------------------------------------------------
pdf = upload("pdf", pdf_bytes([PARAGRAPH, "Rehearsals run from 9:30 to 12:00 every Saturday.\nParents may watch the final rehearsal of each term."]), name="Season brief.pdf")
check("AC11 PDF commit verifies and queues a durable job (bounded by its review window, not yet by file retention)",
      pdf["state"] == "committed" and pdf["job"]["state"] == "queued" and pdf["format"] == "pdf" and pdf["retainUntil"] is None
      and 29 * 86400 < pdf["job"]["reviewExpiresAt"] - time.time() <= 30 * 86400 + 60, pdf)
again = intake.commit(wid, OWNER, pdf["id"])
check("AC29 a repeated commit returns the same job (one row)", again["job"]["id"] == pdf["job"]["id"]
      and sql("SELECT count(*) FROM public.pr_source_upload_jobs WHERE upload_id=%s", (pdf["id"],))[0][0] == 1)
done = intake.process(wid, OWNER, pdf["id"])
check("AC11 the PDF job extracts text and waits for review", done["job"]["state"] == "needs_review" and done["job"]["reason"] == "text_review"
      and done["result"]["characters"] > 300 and done["result"]["pageCount"] == 2, done)
text = intake.text(wid, OWNER, pdf["id"])
check("AC11 the text is shown for review as untrusted data", "Riverside Youth Orchestra" in text["text"] and text["untrusted"] and text["revision"] == 0 and text["editable"], text["revision"])
refused("AC11 nothing becomes a source before a person reviews it", lambda: intake.create_source(wid, OWNER, pdf["id"], {"idempotencyKey": key(), "expectedRevision": 0}), 409, "review_required")
fix_key = key()
corrected = intake.save_text(wid, OWNER, pdf["id"], {"expectedRevision": 0, "idempotencyKey": fix_key, "text": text["text"].replace("twelve concerts", "thirteen concerts")})
check("AC11 a correction is a new revision, marked reviewed", corrected["revision"] == 1 and corrected["reviewedRevision"] == 1 and "thirteen" in corrected["text"])
replay = intake.save_text(wid, OWNER, pdf["id"], {"expectedRevision": 0, "idempotencyKey": fix_key, "text": text["text"].replace("twelve concerts", "thirteen concerts")})
check("AC29 replaying the same correction key returns the same revision", replay["revision"] == 1)
refused("AC29 a correction key reused for other text conflicts", lambda: intake.save_text(wid, OWNER, pdf["id"], {"expectedRevision": 1, "idempotencyKey": fix_key, "text": "Different words entirely here."}), 409, "idempotency_conflict")
refused("AC29 a stale revision conflicts", lambda: intake.save_text(wid, OWNER, pdf["id"], {"expectedRevision": 0, "idempotencyKey": key(), "text": "Another full sentence for the orchestra season."}), 409, "revision_conflict")
with connection() as db:
    try:
        db.execute("UPDATE public.pr_source_upload_results SET text='changed' WHERE job_id=%s", (pdf["job"]["id"],))
        check("immutable extraction results", False)
    except errors.InsufficientPrivilege:
        check("immutable extraction results", True)
revision_before = service.get(wid, OWNER)["revision"]
source_key = key()
made = intake.create_source(wid, OWNER, pdf["id"], {"idempotencyKey": source_key, "expectedRevision": 1, "title": "Season brief"})
made_source = next(s for s in state()["sources"] if s["id"] == made["sourceId"])
check("AC11 the reviewed PDF text became one canonical source with approved statements", made_source["active"] and made_source["origin"]["kind"] == "source_upload"
      and made_source["origin"]["revision"] == 1 and any("thirteen concerts" in f["text"] and f["approved"] for f in made_source["facts"]), made_source["origin"])
check("AC11 the job is completed with its source and the file is kept 30 days", made["upload"]["job"]["state"] == "completed" and made["upload"]["job"]["sourceId"] == made["sourceId"]
      and 29 * 86400 < made["upload"]["retainUntil"] - time.time() <= 30 * 86400 + 60, made["upload"]["retainUntil"])
again = intake.create_source(wid, OWNER, pdf["id"], {"idempotencyKey": source_key, "expectedRevision": 1})
check("AC29 creating the source again returns the same source", again["alreadyCreated"] and again["sourceId"] == made["sourceId"]
      and len([s for s in state()["sources"] if (s.get("origin") or {}).get("uploadId") == pdf["id"]]) == 1)
check("nothing was drafted, scheduled or published", not state().get("variants") and not (state().get("phase2") or {}).get("jobs"))

# --- AC11: one raw audio through quote → reservation → synthetic transcriber → review → source ------------------------------
audio = upload("audio", wav_bytes(65.0), name="Concert memo.wav")
check("AC11 audio commit measures the real duration and waits for a quote", audio["durationSeconds"] == 65.0 and audio["job"]["state"] == "needs_review"
      and audio["job"]["reason"] == "quote_required" and audio["next"] == "accept_quote", audio)
refused("AC11 an untranscribed recording can't become a source", lambda: intake.create_source(wid, OWNER, audio["id"], {"idempotencyKey": key(), "expectedRevision": 0}), 409, "quote_required")
quote = intake.quote(wid, OWNER, audio["id"])
check("R-COM-02 the quote is a bounded credit ceiling, read-only", quote["allowed"] and quote["ceilingMilliCredits"] > 0 and quote["estimateMilliCredits"] <= quote["ceilingMilliCredits"]
      and quote["synthetic"] and not sql("SELECT 1 FROM public.pr_credit_quotes WHERE workspace_id=%s", (wid,)), quote)
refused("R-COM-02 a limit under the ceiling is refused before any I/O", lambda: intake.transcribe(wid, OWNER, audio["id"], {"maxMilliCredits": quote["ceilingMilliCredits"] - 100, "idempotencyKey": key()}), 402, "insufficient_budget")
check("R-COM-02 nothing was reserved or sent", not route.calls and not sql("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (wid,)))
accept_key = key()
accepted = intake.transcribe(wid, OWNER, audio["id"], {"maxMilliCredits": quote["ceilingMilliCredits"], "idempotencyKey": accept_key})
reservations = sql("SELECT id::text, estimated_usd_micro, job_id FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (wid,))
check("R-COM-02 accepting the quote reserves credits before the provider is called", accepted["job"]["state"] == "queued" and accepted["job"]["quoteState"] == "reserved"
      and len(reservations) == 1 and reservations[0][2] == accepted["job"]["id"] and not route.calls, reservations)
replayed = intake.transcribe(wid, OWNER, audio["id"], {"maxMilliCredits": quote["ceilingMilliCredits"], "idempotencyKey": accept_key})
check("AC29 the same acceptance again reserves nothing new", replayed["job"]["quoteState"] == "reserved"
      and len(sql("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (wid,))) == 1)
heard = intake.process(wid, OWNER, audio["id"])
settled = sql("SELECT cost_state, actual_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s AND reservation_id=%s::uuid AND kind<>'reserve'", (wid, reservations[0][0]))
check("AC11 the synthetic transcriber ran once and its cost was settled", len(route.calls) == 1 and heard["job"]["state"] == "needs_review" and heard["job"]["reason"] == "text_review"
      and heard["job"]["quoteState"] == "settled" and settled == [("actual", route.typical_cost_usd_micro(65.0))], (heard["job"], settled))
transcript = intake.text(wid, OWNER, audio["id"])
check("AC11 the transcript is labelled synthetic and shown for correction", transcript["synthetic"] and transcript["text"].startswith("[Synthetic transcript") and transcript["editable"])
spoken = intake.create_source(wid, OWNER, audio["id"], {"idempotencyKey": key(), "expectedRevision": 0, "confirmReviewed": True})
spoken_source = next(s for s in state()["sources"] if s["id"] == spoken["sourceId"])
check("AC11 the reviewed transcript became a source that says it is synthetic", spoken_source["origin"]["synthetic"] and spoken_source["origin"]["transcribedBy"] == "synthetic"
      and spoken_source["origin"]["format"] == "voice_memo" and any("12 April" in f["text"] for f in spoken_source["facts"]), spoken_source["origin"])

# --- AC11: transcript files take the same review path --------------------------------------------------------------------------
srt = "1\n00:00:00,000 --> 00:00:02,500\nWe open registration\n\n2\n00:00:02,600 --> 00:00:05,000\nfor the autumn term on Monday morning.\n\n3\n00:00:09,000 --> 00:00:12,000\nEvery section has a professional coach this year.\n"
captions = intake.add_transcript(wid, OWNER, {"name": "talk.srt", "format": "srt", "text": srt, "idempotencyKey": key()})
caption_text = intake.text(wid, OWNER, captions["id"])
check("AC11 an SRT transcript is ready for review with its cues joined into prose",
      captions["job"]["state"] == "needs_review" and caption_text["text"].startswith("We open registration for the autumn term on Monday morning.\n\nEvery section"), caption_text["text"])

# --- AC11: unsupported, over-limit, scanned and encrypted input is handled truthfully --------------------------------------------
refused("AC11 a PDF over 20 MB is refused before upload with its size", lambda: intake.begin(wid, OWNER, {"kind": "pdf", "name": "big.pdf", "mime": "application/pdf", "bytes": 24_300_000, "idempotencyKey": key()}), 413, "over_limit")
refused("AC11 a recording declared over 10 minutes is refused before upload", lambda: intake.begin(wid, OWNER, {"kind": "audio", "name": "long.wav", "mime": "audio/wav", "bytes": 1000, "durationSeconds": 754, "idempotencyKey": key()}), 413, "over_limit")
long_audio = upload("audio", wav_bytes(601.0), name="long.wav", commit=False)
error = refused("AC11 a recording measured over 10 minutes is refused at commit", lambda: intake.commit(wid, OWNER, long_audio["id"]), 413, "over_limit")
check("AC11 the refusal names the measured length", "10:01" in str(error) and "10:00" in str(error), str(error))
check("AC11 the refused recording is deleted from storage", (wid, f"{uuid.UUID(long_audio['id']).hex}.wav") not in storage.objects
      and intake.status(wid, OWNER, long_audio["id"])["state"] == "rejected")
scanned = upload("pdf", pdf_bytes(["", "", ""], image_only=True), name="scan.pdf")
scanned = intake.process(wid, OWNER, scanned["id"])
check("AC11 a scanned PDF is unsupported with no_text_layer, file deleted", scanned["job"]["state"] == "unsupported" and scanned["job"]["reason"] == "no_text_layer"
      and scanned["objectState"] == "deleted" and results(scanned["id"]) == 0, scanned["job"])
locked = intake.process(wid, OWNER, upload("pdf", encrypted_pdf_bytes(), name="locked.pdf")["id"])
check("AC11 an encrypted PDF is unsupported (no password route)", locked["job"]["state"] == "unsupported" and locked["job"]["reason"] == "encrypted", locked["job"])
line = "The youth orchestra rehearses on Saturday mornings and performs across the city every term with families watching. "
heavy = intake.process(wid, OWNER, upload("pdf", pdf_bytes(["\n".join([line] * 22)] * 26), name="handbook.pdf")["id"])
check("AC11 a PDF over 60,000 characters asks for pages and keeps no text", heavy["job"]["reason"] == "page_selection_required" and heavy["job"]["progress"]["totalChars"] > 60_000
      and heavy["job"]["progress"]["pageCount"] == 26 and results(heavy["id"]) == 0, heavy["job"]["progress"].get("totalChars"))
chosen = intake.select_pages(wid, OWNER, heavy["id"], {"from": 3, "to": 10, "idempotencyKey": key()})
chosen = intake.process(wid, OWNER, heavy["id"])
check("AC11 the chosen pages are extracted within the limit", chosen["job"]["reason"] == "text_review" and chosen["result"]["characters"] < 60_000
      and intake.text(wid, OWNER, heavy["id"])["pages"] == {"from": 3, "to": 10}, chosen["job"])
refused("AC12 malformed MIME is refused at begin", lambda: intake.begin(wid, OWNER, {"kind": "audio", "name": "x", "mime": "text/html", "bytes": 10, "idempotencyKey": key()}), 422, "unsupported_input")
refused("AC11 WebM is refused before upload (duration unmeasurable)", lambda: intake.begin(wid, OWNER, {"kind": "audio", "name": "x.webm", "mime": "audio/webm", "bytes": 10, "idempotencyKey": key()}), 422, "unsupported_input")
liar = upload("audio", wav_bytes(3), name="song.mp3", mime="audio/mpeg", commit=False)
refused("AC12 content that isn't what was declared is refused (mime_mismatch)", lambda: intake.commit(wid, OWNER, liar["id"]), 415, "mime_mismatch")
check("AC12 the mismatched file is deleted", intake.status(wid, OWNER, liar["id"])["state"] == "rejected" and intake.status(wid, OWNER, liar["id"])["objectState"] == "deleted")
html = upload("pdf", b"<html><script>fetch('http://169.254.169.254/')</script></html>", name="page.pdf", commit=False)
refused("AC12 HTML posing as a PDF is refused", lambda: intake.commit(wid, OWNER, html["id"]), 415, "mime_mismatch")
pending = upload("pdf", b"%PDF-1.4", name="x.pdf", commit=False)
storage.objects.pop((wid, f"{uuid.UUID(pending['id']).hex}.pdf"))
refused("a commit before the PUT finished is retryable", lambda: intake.commit(wid, OWNER, pending["id"]), 409, "upload_incomplete")
check("the upload stays pending after an incomplete commit", intake.status(wid, OWNER, pending["id"])["state"] == "pending")

# --- AC12: embedded instructions stay data; unsafe links are refused; cancelled intake can't run or leak ----------------------------
poisoned = intake.process(wid, OWNER, upload("pdf", pdf_bytes([PARAGRAPH + "\n" + INJECTION]), name="poisoned.pdf")["id"])
poisoned_text = intake.text(wid, OWNER, poisoned["id"])
check("AC12 injected instructions are flagged and shown only as text", poisoned_text["injectionFlags"] and "Ignore previous instructions" in poisoned_text["text"], poisoned_text["injectionFlags"])
from postriff_phase2.agent_runtime_v2 import tool_adapter  # noqa: E402
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext  # noqa: E402
from postriff_phase2.source_uploads import agent_tools  # noqa: E402
agent_tools.register()
for modality in ("text", "voice"):
    ctx = RafiiRunContext(service=service, workspace_id=wid, token=OWNER, principal=USERS[OWNER], membership=None, conversation_id="c-intake", trace_id="t-intake", modality=modality)
    before = state()
    seen = tool_adapter.execute(ctx, tool_adapter.REGISTRY["source_upload_status"], {"uploadId": poisoned["id"]})
    check(f"AC12/AC28 ({modality}) the status tool returns the instruction only as untrusted data", seen["ok"] and seen["text"]["kind"] == "EXTERNAL_SOURCE"
          and "Ignore previous instructions" in seen["text"]["data"]["excerpt"] and seen["text"]["data"]["injectionFlags"], seen)
    check(f"AC12 ({modality}) reading it ran exactly one tool and changed nothing", [a["tool"] for a in ctx.ledger.tool_activity] == ["source_upload_status"] and state() == before)
    blocked = tool_adapter.execute(ctx, tool_adapter.REGISTRY["source_from_upload"], {"uploadId": poisoned["id"]})
    check(f"AC28 ({modality}) the agent can't create a source from unreviewed text", not blocked["ok"] and blocked["code"] == "review_required" and blocked["needsUser"], blocked)
    asked = tool_adapter.execute(ctx, tool_adapter.REGISTRY["source_from_upload"], {"uploadId": heavy["id"]})
    check(f"AC28 ({modality}) nor accept a quote or review on the person's behalf", not asked["ok"], asked)
intake.review(wid, OWNER, poisoned["id"], {"expectedRevision": 0})
ctx = RafiiRunContext(service=service, workspace_id=wid, token=OWNER, principal=USERS[OWNER], membership=None, conversation_id="c-intake", trace_id="t-intake-2")
created = tool_adapter.execute(ctx, tool_adapter.REGISTRY["source_from_upload"], {"uploadId": poisoned["id"], "title": "Poisoned brief"})
poisoned_source = next(s for s in state()["sources"] if s["id"] == created["sourceId"])
check("AC12 after review the agent creates the source; the instruction never became a statement", created["ok"] and poisoned_source["origin"]["injectionFlags"]
      and not any("Ignore previous instructions" in f["text"] for f in poisoned_source["facts"]) and any("Riverside" in f["text"] for f in poisoned_source["facts"]), created)
check("AC12 no tool other than the one called ran, nothing was published", [a["tool"] for a in ctx.ledger.tool_activity] == ["source_from_upload"] and not (state().get("phase2") or {}).get("jobs"))
for unsafe in ("http://orchestra.example.org/x", "https://169.254.169.254/latest/meta-data", "https://localhost/admin", "https://intranet.rafii-demo.com/brief", "javascript:alert(1)"):
    refused(f"AC12 unsafe link refused by the SSRF guard: {unsafe[:30]}", lambda unsafe=unsafe: intake.create_source(wid, OWNER, captions["id"], {"idempotencyKey": key(), "expectedRevision": 0, "confirmReviewed": True, "originUrl": unsafe}), 400, "unsafe_url")
linked = intake.create_source(wid, OWNER, captions["id"], {"idempotencyKey": key(), "expectedRevision": 0, "confirmReviewed": True, "originUrl": "https://talks.rafii-demo.com/autumn"})
check("a public https origin link is kept as a reference", next(s for s in state()["sources"] if s["id"] == linked["sourceId"])["origin"]["url"] == "https://talks.rafii-demo.com/autumn")
stopped = upload("pdf", pdf_bytes([PARAGRAPH]), name="stop.pdf")
stopped = intake.cancel(wid, OWNER, stopped["id"])
ran = intake.process(wid, OWNER, stopped["id"])
check("AC12 a cancelled intake never runs", ran["job"]["state"] == "cancelled" and ran["job"]["reason"] == "user_cancelled" and results(stopped["id"]) == 0 and ran["objectState"] == "deleted", ran["job"])
refused("AC12 a cancelled intake has no text to leak", lambda: intake.text(wid, OWNER, stopped["id"]), 409, "not_ready")
refused("AC12 a cancelled intake can't become a source", lambda: intake.create_source(wid, OWNER, stopped["id"], {"idempotencyKey": key(), "expectedRevision": 0, "confirmReviewed": True}), 409)
racing = upload("pdf", pdf_bytes([PARAGRAPH]), name="race.pdf")
claimed = jobs.claim(intake, job_id=racing["job"]["id"])
intake.cancel(wid, OWNER, racing["id"])
check("AC12 a result finished after cancellation is discarded (fenced)", jobs._pdf(intake, claimed, time.monotonic() + 30) == "discarded" and results(racing["id"]) == 0)
midway = upload("audio", wav_bytes(30.0), name="midway.wav")
midway_quote = intake.quote(wid, OWNER, midway["id"])
intake.transcribe(wid, OWNER, midway["id"], {"maxMilliCredits": midway_quote["ceilingMilliCredits"], "idempotencyKey": key()})
route.during = lambda: intake.cancel(wid, OWNER, midway["id"])
calls = len(route.calls)
midway = intake.process(wid, OWNER, midway["id"])
released = sql("SELECT u.cost_state, u.actual_usd_micro FROM public.pr_usage_ledger u WHERE u.workspace_id=%s AND u.job_id=%s AND u.kind<>'reserve'", (wid, midway["job"]["id"]))
check("AC12 cancelled while transcribing: no transcript kept, credits released, provider cost still booked",
      len(route.calls) == calls + 1 and midway["job"]["state"] == "cancelled" and results(midway["id"]) == 0 and midway["job"]["quoteState"] == "released"
      and released == [("released", route.typical_cost_usd_micro(30.0))], (midway["job"], released))

# --- AC38: leases, attempts, recovery, unknown outcomes ---------------------------------------------------------------------------------
flaky = upload("pdf", pdf_bytes([PARAGRAPH]), name="flaky.pdf")
storage.down = True
for attempt in (1, 2):
    outcome = intake.process(wid, OWNER, flaky["id"])
    check(f"AC38 storage trouble returns the job to the queue (attempt {attempt})", outcome["job"]["state"] == "queued" and outcome["job"]["reason"] == "storage_unavailable"
          and outcome["job"]["attempts"] == attempt and outcome["job"]["retryable"], outcome["job"])
    due_now(flaky["id"])
outcome = intake.process(wid, OWNER, flaky["id"])
storage.down = False
check("AC38 the third failed attempt is final, visible, and deletes the file", outcome["job"]["state"] == "failed" and outcome["job"]["attempts"] == 3
      and outcome["job"]["reason"] == "storage_unavailable" and outcome["objectState"] in ("deleting", "deleted"), outcome["job"])
stale = upload("pdf", pdf_bytes([PARAGRAPH]), name="stale.pdf")
jobs.claim(intake, job_id=stale["job"]["id"])
sql("UPDATE public.pr_source_upload_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (stale["job"]["id"],))
recovered = jobs.recover(intake)
check("AC38 an expired lease before any provider I/O goes back to the queue", recovered.get("queued") == 1 and intake.status(wid, OWNER, stale["id"])["job"]["state"] == "queued", recovered)
due_now(stale["id"])
check("AC38 the recovered job then completes", intake.process(wid, OWNER, stale["id"])["job"]["reason"] == "text_review")
lost = upload("audio", wav_bytes(20.0), name="lost.wav")
lost_quote = intake.quote(wid, OWNER, lost["id"])
intake.transcribe(wid, OWNER, lost["id"], {"maxMilliCredits": lost_quote["ceilingMilliCredits"], "idempotencyKey": key()})
lost_claim = jobs.claim(intake, job_id=lost["job"]["id"])
jobs._renew(intake, lost_claim, {"stage": "transcribing"}, dispatch=True)   # the worker sent the audio, then died
sql("UPDATE public.pr_source_upload_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (lost["job"]["id"],))
jobs.recover(intake)
lost = intake.status(wid, OWNER, lost["id"])
unknown = sql("SELECT cost_state FROM public.pr_usage_ledger WHERE workspace_id=%s AND job_id=%s AND kind<>'reserve'", (wid, lost["job"]["id"]))
check("AC38 a lease lost after dispatch is outcome_unknown, cost pending, never retried", lost["job"]["state"] == "failed" and lost["job"]["reason"] == "outcome_unknown"
      and lost["job"]["quoteState"] == "unknown" and unknown == [("estimated_unknown",)] and lost["job"]["attempts"] == 1, (lost["job"], unknown))
route.fail = "unknown"
silent = upload("audio", wav_bytes(10.0), name="silent.wav")
silent_quote = intake.quote(wid, OWNER, silent["id"])
intake.transcribe(wid, OWNER, silent["id"], {"maxMilliCredits": silent_quote["ceilingMilliCredits"], "idempotencyKey": key()})
silent = intake.process(wid, OWNER, silent["id"])
check("AC38 a provider that never answers is outcome_unknown (no blind retry)", silent["job"]["state"] == "failed" and silent["job"]["reason"] == "outcome_unknown" and silent["job"]["quoteState"] == "unknown", silent["job"])
route.fail = "refused"
balked = upload("audio", wav_bytes(10.0), name="balked.wav")
balked_quote = intake.quote(wid, OWNER, balked["id"])
intake.transcribe(wid, OWNER, balked["id"], {"maxMilliCredits": balked_quote["ceilingMilliCredits"], "idempotencyKey": key()})
first = intake.process(wid, OWNER, balked["id"])
check("AC38 a refusal before billable work is retried under the same reservation", first["job"]["state"] == "queued" and first["job"]["quoteState"] == "reserved" and first["job"]["attempts"] == 1, first["job"])
for _ in range(2):
    due_now(balked["id"])
    final = intake.process(wid, OWNER, balked["id"])
check("AC38 after three refusals the job fails and the credits are released", final["job"]["state"] == "failed" and final["job"]["quoteState"] == "released" and final["job"]["attempts"] == 3, final["job"])
route.fail = None
summary = jobs.tick(service, time.monotonic() + 20)
check("cron tick reports counts only and never raises", summary["status"] == "ok" and set(summary) == {"status", "recovered", "jobs", "retention", "purges"}, summary)

# --- AC29/AC36: idempotent begin, cross-tenant ids, viewers, revoked membership, RLS ----------------------------------------------------
begin_key = key()
first_begin = intake.begin(wid, OWNER, {"kind": "pdf", "name": "same.pdf", "mime": "application/pdf", "bytes": 1234, "idempotencyKey": begin_key})
second_begin = intake.begin(wid, OWNER, {"kind": "pdf", "name": "same.pdf", "mime": "application/pdf", "bytes": 1234, "idempotencyKey": begin_key})
check("AC29 a repeated begin returns the same upload", first_begin["upload"]["id"] == second_begin["upload"]["id"])
refused("AC29 a begin key reused for another file conflicts", lambda: intake.begin(wid, OWNER, {"kind": "pdf", "name": "other.pdf", "mime": "application/pdf", "bytes": 99, "idempotencyKey": begin_key}), 409, "idempotency_conflict")
refused("AC36 another workspace can't read this upload by id", lambda: intake.status(other_wid, OTHER, pdf["id"]), 404)
refused("AC36 nor cancel it", lambda: intake.cancel(other_wid, OTHER, pdf["id"]), 404)
refused("AC36 nor read its text", lambda: intake.text(other_wid, OTHER, pdf["id"]), 404)
refused("AC36 a non-member can't use the workspace path", lambda: intake.status(wid, OTHER, pdf["id"]), 403)
with connection() as db:
    try:
        db.execute("INSERT INTO public.pr_source_upload_jobs(id,workspace_id,upload_id,kind,state,idempotency_key,created_by) VALUES(%s,%s,%s,'pdf_text','queued','cross-tenant-1',%s)",
                   (str(uuid.uuid4()), other_wid, pdf["id"], USERS[OTHER]))
        check("AC29 composite FK refuses a job pointing at another workspace's upload", False)
    except errors.ForeignKeyViolation:
        check("AC29 composite FK refuses a job pointing at another workspace's upload", True)
refused("viewers can't upload", lambda: intake.begin(wid, VIEWER, {"kind": "pdf", "name": "v.pdf", "mime": "application/pdf", "bytes": 10, "idempotencyKey": key()}), 403)
check("viewers can read status", intake.status(wid, VIEWER, pdf["id"])["id"] == pdf["id"])
first_page = intake.list(wid, OWNER, None, 2)
second_page = intake.list(wid, OWNER, first_page["nextCursor"], 2)
all_ids = [i["id"] for i in intake.list(wid, OWNER, None, 50)["items"]]
check("AC29 pagination is ordered and never repeats a row", first_page["nextCursor"] and not {i["id"] for i in first_page["items"]} & {i["id"] for i in second_page["items"]}
      and [i["id"] for i in first_page["items"] + second_page["items"]] == all_ids[:4], all_ids[:4])
editor_pdf = upload("pdf", pdf_bytes([PARAGRAPH]), name="editor.pdf", token=EDITOR)
sql("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (wid, USERS[EDITOR]))
jobs.run_one(intake, time.monotonic() + 30, job_id=editor_pdf["job"]["id"])
revoked = intake.status(wid, OWNER, editor_pdf["id"])
check("AC36 a member revoked mid-job: the job stops, nothing is extracted, the file goes", revoked["job"]["state"] == "cancelled" and revoked["job"]["reason"] == "membership_revoked"
      and results(editor_pdf["id"]) == 0 and revoked["objectState"] in ("deleting", "deleted"), revoked["job"])
refused("AC36 the revoked member can no longer read it", lambda: intake.status(wid, EDITOR, editor_pdf["id"]), 403)
total = sql("SELECT count(*) FROM public.pr_source_uploads WHERE workspace_id=%s", (wid,))[0][0]
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (USERS[OWNER],))
    mine = db.execute("SELECT count(*) FROM public.pr_source_uploads").fetchone()[0]
    foreign = db.execute("SELECT count(*) FROM public.pr_source_uploads WHERE workspace_id=%s", (other_wid,)).fetchone()[0]
    check("AC36 RLS: members read only their workspace's uploads", mine == total and foreign == 0, (mine, total, foreign))
    try:
        db.execute("SELECT count(*) FROM public.pr_source_upload_purges")
        check("AC36 RLS: the purge queue is service-only", False)
    except errors.InsufficientPrivilege:
        check("AC36 RLS: the purge queue is service-only", True)
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (USERS[OWNER],))
    try:
        db.execute("INSERT INTO public.pr_source_uploads(id,workspace_id,kind,state,object_state,created_by) VALUES(%s,%s,'pdf','pending','awaiting',%s)", (str(uuid.uuid4()), wid, USERS[OWNER]))
        check("AC36 RLS: browsers can't write intake rows", False)
    except errors.InsufficientPrivilege:
        check("AC36 RLS: browsers can't write intake rows", True)

# --- R-COM-03: Free is refused before any quote or reservation --------------------------------------------------------------------------
free_audio = upload("audio", mp3_bytes(30.0), name="free.mp3", mime="audio/mpeg", token=OTHER, workspace=other_wid)
free_quote = intake.quote(other_wid, OTHER, free_audio["id"])
check("R-COM-03 Free sees the upgrade path instead of a quote", not free_quote["allowed"] and free_quote["reason"] == "upgrade_required" and free_quote["upgradePath"], free_quote)
calls = len(route.calls)
refused("R-COM-03 Free can't accept a transcription", lambda: intake.transcribe(other_wid, OTHER, free_audio["id"], {"maxMilliCredits": 10_000, "idempotencyKey": key()}), 402, "insufficient_budget")
check("R-COM-03 nothing was quoted, reserved or sent for Free", len(route.calls) == calls and not sql("SELECT 1 FROM public.pr_credit_quotes WHERE workspace_id=%s", (other_wid,))
      and not sql("SELECT 1 FROM public.pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (other_wid,)))

# --- R-NFR-02: retention, retraction, deletion propagation, visible retryable purges ------------------------------------------------------
sql("UPDATE public.pr_source_uploads SET retain_until=now()-interval '1 minute' WHERE id=%s", (pdf["id"],))
storage.fail_delete = True
jobs.sweep(intake)
failing = jobs.drain(intake)
purge_row = sql("SELECT attempts, last_error FROM public.pr_source_upload_purges WHERE upload_id=%s", (pdf["id"],))
check("R-NFR-02 a failed storage deletion is visible and kept for retry", failing["failed"] >= 1 and purge_row and purge_row[0][0] == 1 and "could not delete" in purge_row[0][1]
      and intake.status(wid, OWNER, pdf["id"])["objectState"] == "deleting", (failing, purge_row))
storage.fail_delete = False
sql("UPDATE public.pr_source_upload_purges SET not_before=now() WHERE upload_id=%s", (pdf["id"],))
jobs.drain(intake)
gone = intake.status(wid, OWNER, pdf["id"])
check("R-NFR-02 after its 30 days the file and its text are deleted; the source stays", gone["state"] == "deleted" and gone["objectState"] == "deleted" and gone["name"] is None
      and results(pdf["id"]) == 0 and next(s for s in state()["sources"] if s["id"] == made["sourceId"])["active"], gone)
revision = service.get(wid, OWNER)["revision"]
service.repository.mutate(wid, OWNER, revision, "retract_source", {"sourceId": spoken["sourceId"]})
jobs.sweep(intake)
jobs.drain(intake)
retracted = intake.status(wid, OWNER, audio["id"])
check("R-NFR-02 retracting the source deletes its recording and transcript", retracted["state"] == "deleted" and retracted["objectState"] == "deleted" and results(audio["id"]) == 0, retracted)
sql("UPDATE public.pr_source_upload_jobs SET review_expires_at=now()-interval '1 minute' WHERE upload_id=%s", (chosen["id"],))
jobs.sweep(intake)
expired = intake.status(wid, OWNER, chosen["id"])
check("R-NFR-02 text never used is deleted after the review window", expired["job"]["state"] == "cancelled" and expired["job"]["reason"] == "review_expired" and results(chosen["id"]) == 0, expired["job"])
abandoned = upload("pdf", pdf_bytes([PARAGRAPH]), name="abandoned.pdf", commit=False)
sql("UPDATE public.pr_source_uploads SET token_expires_at=now()-interval '2 hours' WHERE id=%s", (abandoned["id"],))
jobs.sweep(intake)
jobs.drain(intake)
check("R-NFR-02 an upload never finished is cancelled and its object deleted", intake.status(wid, OWNER, abandoned["id"])["reason"] == "upload_expired"
      and (wid, f"{uuid.UUID(abandoned['id']).hex}.pdf") not in storage.objects)
sql("UPDATE public.pr_source_uploads SET updated_at=now()-interval '31 days' WHERE id IN (%s,%s)", (stopped["id"], racing["id"]))
sql("UPDATE public.pr_source_upload_jobs SET quote_state='reserved' WHERE upload_id=%s", (racing["id"],))
jobs.sweep(intake)
check("R-NFR-02 a settled tombstone (file name included) is removed after the review window",
      not sql("SELECT 1 FROM public.pr_source_uploads WHERE id=%s", (stopped["id"],)))
check("R-NFR-02 but never while a transcription reservation is still held", sql("SELECT 1 FROM public.pr_source_uploads WHERE id=%s", (racing["id"],)))
sql("UPDATE public.pr_source_upload_jobs SET quote_state='not_required' WHERE upload_id=%s", (racing["id"],))
deleted = intake.delete(wid, OWNER, poisoned["id"])
check("R-NFR-02 deleting an upload removes its text; the source made from it is kept", deleted["deleted"] and deleted["sourceKept"] == created["sourceId"] and results(poisoned["id"]) == 0
      and deleted["upload"]["state"] == "deleted")
other_pdf = upload("pdf", pdf_bytes([PARAGRAPH]), name="other.pdf", token=OTHER, workspace=other_wid)
sql("DELETE FROM public.pr_workspaces WHERE id=%s", (other_wid,))
queued = sql("SELECT reason FROM public.pr_source_upload_purges WHERE upload_id=%s", (other_pdf["id"],))
jobs.drain(intake)
check("R-NFR-02 account deletion (cascade) still deletes the stored files", queued and all(r[0] == "row_deleted" for r in queued)
      and not any(k[0] == other_wid for k in storage.objects) and not sql("SELECT 1 FROM public.pr_source_upload_purges WHERE upload_id=%s AND not_before<=now()", (other_pdf["id"],)), queued)
audit = sql("SELECT kind, meta::text FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'source_upload.%%'", (wid,))
check("audit rows are content-free", audit and not any(PARAGRAPH[:20] in meta or "Riverside" in meta or "Ignore previous" in meta for _, meta in audit), len(audit))

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres; fake storage; synthetic transcriber", "checks": len(passed), "names": passed}, indent=1))
