"""Learning events on the hosted repository (preference-learning design Phase A): every command's implied
events land in pr_learning_events inside that command's transaction, the worker records a verified
publication, rows carry ids and numbers but never draft text, a member cannot read another workspace's
rows, the export carries them, the sweep drops expired ones, and switching learning off stops capture.

Run through scripts/postriff_disposable_postgres.py (rls.sql loads migrations 004+, including 010).
"""
import io
import json
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
clock = [time.time()]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "fixture-one":
        raise AlphaError("Verified session required", 401)
    return ONE


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    foreign = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (TWO,)).fetchone()[0])
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s", (wid,))
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
    db.execute("delete from public.pr_learning_events where workspace_id in (%s, %s)", (wid, foreign))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
snapshot = service.bootstrap("fixture-one", "studio")


def act(action, payload):
    global snapshot
    snapshot = service.mutate(wid, "fixture-one", snapshot["revision"], action, payload)
    return snapshot["state"]


def command(fn):
    global snapshot
    saved = service.repository.command(wid, "fixture-one", snapshot["revision"], fn)
    snapshot = service.commands.present(saved["state"], saved["revision"])
    return snapshot["state"]


def events():
    with connection() as db:
        rows = db.execute("select kind, subject, scope, features, actor::text, style_revision from public.pr_learning_events where workspace_id=%s order by seq", (wid,)).fetchall()
    return [{"kind": r[0], "subject": r[1], "scope": r[2], "features": r[3], "actor": r[4], "styleRevision": r[5]} for r in rows]


act("mode", {"mode": "personal"})
act("context", {"purpose": "Make community learning accessible", "audience": "Curious beginners", "subject": "Community workshops", "speaker": "My voice", "layers": []})
act("source", {"kind": "sample"})
source = snapshot["state"]["sources"][-1]
act("approve_source", {"sourceId": source["id"], "factIds": [fact["id"] for fact in source["facts"]]})
act("source_done", {})
act("profile_propose", {"writing": "A small step can be a useful beginning.", "tone": "warm"})
act("profile_decide", {"decision": "approve"})
act("runtime", {"selected": "deterministic-preview"})
act("generate", {"platform": "LinkedIn", "language": "English"})
assert events() == [], "setup commands imply no learning event"
variant = snapshot["state"]["variants"][0]
model_text = variant["text"]
edited = "My own opening.\n\n" + model_text.split("\n\n", 1)[-1]
act("variant_edit", {"variantId": variant["id"], "variantRevision": variant["revision"], "text": edited})
recorded = events()
assert [e["kind"] for e in recorded] == ["draft.edited"], recorded
edit = recorded[0]
assert edit["subject"]["variantId"] == variant["id"] and edit["subject"]["origin"] == "author-edit" and edit["actor"] == ONE
assert edit["scope"]["platform"] == "LinkedIn" and edit["features"]["editDistance"] > 0
assert "My own opening" not in json.dumps(recorded) and model_text[:20] not in json.dumps(recorded)
checks.append("an edit is captured in the command's transaction with features and no text")

variant = snapshot["state"]["variants"][0]
act("p2_variant_review", {"variantId": variant["id"], "variantRevision": variant["revision"], "confirmed": True, "excludedUnknowns": variant["unknowns"]})
channel = {"id": uuid.uuid4().hex, "platform": "LinkedIn", "account": "Verified test member", "accountType": "member", "language": "English", "scopes": ["w_member_social"], "verifiedAt": clock[0], "expiresAt": clock[0] + 86400, "capabilityVersion": 1, "providerAccountId": "urn:li:person:test"}
command(lambda state, actor: service.commands.upsert_verified_channel(state, actor, channel))
local = datetime.fromtimestamp(clock[0] + 60, timezone.utc).replace(tzinfo=None).isoformat()
variant = snapshot["state"]["variants"][0]
act("p2_review", {"channelId": channel["id"], "variantId": variant["id"], "localTime": local, "timeZone": "UTC", "acknowledgedWarnings": variant["warnings"]})
review = snapshot["state"]["phase2"]["reviews"][-1]
act("p2_approve", {"reviewId": review["id"], "digest": review["digest"], "confirmed": True})
recorded = events()
assert [e["kind"] for e in recorded] == ["draft.edited", "draft.approved"], [e["kind"] for e in recorded]
approved = recorded[1]
assert approved["features"]["editCount"] == 1 and approved["features"]["editDistance"] > 0 and approved["subject"]["jobId"] == snapshot["state"]["phase2"]["jobs"][0]["id"]
assert approved["styleRevision"] == 0 and approved["scope"]["language"] == "English"
checks.append("an approval is captured with the edit count and distance against the model's text")


class Social:
    def submit(self, manifest):
        return {"state": "provider_accepted", "confirmed": "Disposable adapter accepted", "reference": "disposable-1"}

    def reconcile(self, manifest, job):
        return {"state": "verified", "confirmed": "Disposable lookup matched", "verification": "disposable_lookup", "reference": "disposable-1"}


worker = PostgresWorker(connection, social=Social(), clock=lambda: clock[0], worker_id="disposable-worker")
clock[0] += 61
assert worker.step()
clock[0] += 46
assert worker.step()
job = service.get(wid, "fixture-one")["state"]["phase2"]["jobs"][0]
assert job["state"] == "verified", job["state"]
recorded = events()
assert [e["kind"] for e in recorded][-1] == "post.published" and recorded[-1]["subject"]["providerReference"] == "disposable-1" and recorded[-1]["actor"] is None
checks.append("the worker records a verified publication")

with connection() as db:
    db.execute("set role authenticated")
    db.execute("select set_config('request.jwt.claim.sub', %s, false)", (ONE,))
    own = db.execute("select count(*) from public.pr_learning_events where workspace_id=%s", (wid,)).fetchone()[0]
    other = db.execute("select count(*) from public.pr_learning_events where workspace_id=%s", (foreign,)).fetchone()[0]
    try:
        db.execute("insert into public.pr_learning_events(workspace_id, kind) values (%s, 'draft.edited')", (wid,))
        raise AssertionError("browser insert accepted")
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()
    db.execute("reset role")
assert own == 3 and other == 0, (own, other)
checks.append("members read their own workspace's events only; the browser role cannot write")

raw = service.export(wid, "fixture-one")
with zipfile.ZipFile(io.BytesIO(raw)) as archive:
    lines = archive.read("learning/events.jsonl").decode().strip().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["kind"] == "draft.edited"
    assert "My own opening" not in archive.read("learning/events.jsonl").decode()
    assert json.loads(archive.read("learning/proposals.json")) == [] and json.loads(archive.read("learning/versions.json")) == []
checks.append("the export carries the learning tables without draft text")

with connection() as db:
    db.execute("insert into public.pr_learning_events(workspace_id, kind, created_at, expires_at) values (%s, 'job.cancelled', to_timestamp(%s), to_timestamp(%s))", (wid, clock[0] - 200 * 86400, clock[0] - 20 * 86400))
swept = service.learning.sweep()
assert swept["eventsDropped"] == 1 and swept["captureFailures"] == 0 and len(events()) == 3, swept
checks.append("the sweep drops events past retention and reports no capture failures")

snapshot = service.get(wid, "fixture-one")
with connection() as db:
    state = db.execute("select state from public.pr_workspaces where id=%s", (wid,)).fetchone()[0]
    state["learning"]["enabled"] = False
    db.execute("update public.pr_workspaces set state=%s::jsonb where id=%s", (json.dumps(state), wid))
snapshot = service.get(wid, "fixture-one")
act("generate", {"platform": "Threads", "language": "English"})
threads = next(v for v in snapshot["state"]["variants"] if v["platform"] == "Threads")
act("variant_edit", {"variantId": threads["id"], "variantRevision": threads["revision"], "text": "Edited while learning is off."})
assert len(events()) == 3
checks.append("with learning switched off nothing is captured")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
