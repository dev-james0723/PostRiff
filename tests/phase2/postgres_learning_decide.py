"""Learned preferences on the hosted repository (preference-learning design, decisions A1 and D):
deciding one is an owner-only command, remembering one leaves the scheduled job and the pending review
valid, the worker still claims the job, VOICE.md shows the item, and a workspace saved by an older build
migrates on its next command.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with migrations 004+).
"""
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha import learning
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
PROPOSAL = "0f3b2c1d5e6a4b7c8d9e0f1a2b3c4d5e"
clock = [time.time()]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "fixture-one":
        raise AlphaError("Verified session required", 401)
    return ONE


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
    else:
        raise AssertionError("expected a refusal")


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s", (wid,))
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
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


def variant(platform):
    return next(v for v in snapshot["state"]["variants"] if v["platform"] == platform)


def channel(platform):
    return {"id": uuid.uuid4().hex, "platform": platform, "account": f"Verified {platform} account", "accountType": "member", "language": "English",
            "scopes": ["w_member_social"], "verifiedAt": clock[0], "expiresAt": clock[0] + 86400, "capabilityVersion": 1, "providerAccountId": f"urn:test:{platform}"}


act("mode", {"mode": "personal"})
act("context", {"purpose": "Make community learning accessible", "audience": "Curious beginners", "subject": "Community workshops", "speaker": "My voice", "layers": []})
act("source", {"kind": "sample"})
source = snapshot["state"]["sources"][-1]
act("approve_source", {"sourceId": source["id"], "factIds": [fact["id"] for fact in source["facts"]]})
act("source_done", {})
act("profile_propose", {"writing": "A small step can be a useful beginning.", "tone": "warm"})
act("profile_decide", {"decision": "approve"})
act("runtime", {"selected": "deterministic-preview"})
for platform in ("LinkedIn", "Threads"):
    act("generate", {"platform": platform, "language": "English"})
    v = variant(platform)
    act("p2_variant_review", {"variantId": v["id"], "variantRevision": v["revision"], "confirmed": True, "excludedUnknowns": v["unknowns"]})
linkedin, threads = channel("LinkedIn"), channel("Threads")
for c in (linkedin, threads):
    command(lambda state, actor, c=c: service.commands.upsert_verified_channel(state, actor, c))
local = datetime.fromtimestamp(clock[0] + 60, timezone.utc).replace(tzinfo=None).isoformat()
act("p2_review", {"channelId": linkedin["id"], "variantId": variant("LinkedIn")["id"], "localTime": local, "timeZone": "UTC", "acknowledgedWarnings": variant("LinkedIn")["warnings"]})
review = snapshot["state"]["phase2"]["reviews"][-1]
act("p2_approve", {"reviewId": review["id"], "digest": review["digest"], "confirmed": True})
job = snapshot["state"]["phase2"]["jobs"][0]
assert job["state"] == "scheduled" and job["manifest"]["styleRevision"] == 0 and job["manifest"]["voiceRevision"] == 1
act("p2_review", {"channelId": threads["id"], "variantId": variant("Threads")["id"], "localTime": local, "timeZone": "UTC", "acknowledgedWarnings": variant("Threads")["warnings"]})
pending = snapshot["state"]["phase2"]["reviews"][-1]
assert pending["status"] == "needs_review"
checks.append("one scheduled job and one pending review on the hosted repository")


def seed(state, actor):
    proposal = {"id": PROPOSAL, "type": "writing_preference", "ruleKey": "opening.style", "polarity": "do", "scope": {"platform": "LinkedIn", "language": "English"},
                "statement": "Use shorter openings.", "params": {"shortOpenings": True}, "source": "chat"}
    assert learning.propose(state, proposal, clock[0])["status"] == "proposed"
    return state


command(seed)
with connection() as db:
    db.execute("update public.pr_memberships set role='editor', can_publish=true where user_id=%s", (ONE,))
denied(lambda: act("preference", {"preferenceId": PROPOSAL, "decision": "remember"}), 403)
with connection() as db:
    db.execute("update public.pr_memberships set role='owner' where user_id=%s", (ONE,))
checks.append("deciding a learned preference is refused for an editor (decision D)")

state = act("preference", {"preferenceId": PROPOSAL, "decision": "remember"})
assert state["speaker"]["activeRevision"] == 1 and state["learning"]["revision"] == 1
assert state["phase2"]["jobs"][0]["state"] == "scheduled"
assert next(r for r in state["phase2"]["reviews"] if r["id"] == pending["id"])["status"] == "needs_review"
assert not any(v["needsReview"] for v in state["variants"])
assert next(p for p in state["preferences"] if p["id"] == PROPOSAL)["status"] == "remembered"
files = service.ideas.memory_files(wid, "fixture-one")["files"]
voice = next(f["body"] for f in files if f["name"] == "VOICE.md")
assert "## Learned from how you edit (style rev 1)" in voice and "- [LinkedIn · English] Use shorter openings. — you said so" in voice
checks.append("remembering a preference moves the style revision only; the scheduled job and pending review stay valid; VOICE.md shows it")


class Social:
    def submit(self, manifest):
        return {"state": "provider_accepted", "confirmed": "Disposable adapter accepted", "reference": "disposable-1"}

    def reconcile(self, manifest, job):
        return {"state": "verified", "confirmed": "Disposable lookup matched", "verification": "disposable_lookup", "reference": "disposable-1"}


worker = PostgresWorker(connection, social=Social(), clock=lambda: clock[0], worker_id="disposable-worker")
clock[0] += 61
assert worker.step()
job = service.get(wid, "fixture-one")["state"]["phase2"]["jobs"][0]
assert job["state"] != "held" and len(job["attempts"]) == 1, job["state"]
checks.append("the worker claims and submits the job after the preference was remembered")

snapshot = service.get(wid, "fixture-one")
act("preview_update", {"variantId": variant("LinkedIn")["id"]})
proposed = variant("LinkedIn")["proposedUpdate"]
assert proposed["text"].startswith("A small start.") and proposed["styleRevision"] == 1
checks.append("the next LinkedIn draft reads the preference and records the style revision")

with connection() as db:
    stored = db.execute("select state from public.pr_workspaces where id=%s", (wid,)).fetchone()[0]
    stored.pop("learning")
    stored["preferences"].append({"id": "hidden-1", "variantId": variant("Threads")["id"], "platform": "Threads", "language": "English", "key": "shortOpenings", "value": True, "label": "Use shorter openings?", "status": "proposed", "createdAt": "2026-09-10T00:00:00+00:00"})
    db.execute("update public.pr_workspaces set state=%s::jsonb where id=%s", (json.dumps(stored), wid))
snapshot = service.get(wid, "fixture-one")
state = act("p2_refresh", {})
assert next(p for p in state["preferences"] if p["id"] == "hidden-1")["status"] == "expired"
assert state["learning"]["migratedAt"] and state["learning"]["revision"] == 0 and learning.active_items(state) == []
assert state["speaker"]["activeRevision"] == 1
checks.append("a workspace saved without learning state migrates on its next command: hidden proposals expire, nothing else moves")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
