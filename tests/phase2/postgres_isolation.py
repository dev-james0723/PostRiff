"""Two-tenant isolation, roles, step-up, invitations, throttling, audit (Milestone A).

Run through scripts/postriff_disposable_postgres.py after rls.sql. Disposable
loopback PostgreSQL only; no hosted credentials are read.
"""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.contracts import digest

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
# rls.sql tombstones user ...0002 at its end; use a fresh fourth user as the second owner.
TWO = "00000000-0000-0000-0000-000000000004"
THREE = "00000000-0000-0000-0000-000000000003"
TOKENS = {"one": ONE, "two": TWO, "three": THREE}
clock = [time.time()]
auth_times = {"one": clock[0], "two": clock[0], "three": clock[0]}


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: auth_times[token]
checks = []


def denied(call, status=None, message=None):
    try:
        call()
    except AlphaError as error:
        if status is not None and error.status != status:
            raise AssertionError(f"expected {status}, got {error.status}: {error}")
        if message is not None and str(error) != message:
            raise AssertionError(f"unexpected message {error!r}")
        return str(error), error.status
    raise AssertionError("call was accepted")


with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s),(%s)", (THREE, TWO))
    wid_a = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid_a,))

class StubAssets:
    """Lets media() reach the membership boundary; never returns bytes."""
    storage = None


service = HostedWorkspaceService(connection, verify, assets=StubAssets(), clock=lambda: clock[0])
snap_a = service.bootstrap("one", "studio", client="198.51.100.1", client_label="TestClient")
snap_b = service.bootstrap("two", "assist", client="198.51.100.2")
wid_b = snap_b["workspaceId"]
assert snap_a["workspaceId"] == wid_a and wid_b != wid_a
assert snap_a["membership"] == {"role": "owner", "can_publish": True, "can_reply": True, "can_moderate": True, "can_manage_connections": True}
checks.append("bootstrap grants owner every action permission")

# 1. Cross-tenant read/mutate/export/media/members/audit/invitations are indistinguishable from nonexistent.
ghost = str(uuid.uuid4())
foreign_msg = denied(lambda: service.get(wid_b, "one"), 403)
ghost_msg = denied(lambda: service.get(ghost, "one"), 403)
assert foreign_msg == ghost_msg == ("Workspace unavailable.", 403)
for call in (
    lambda: service.mutate(wid_b, "one", snap_b["revision"], "mode", {"mode": "personal"}),
    lambda: service.export(wid_b, "one"),
    lambda: service.members(wid_b, "one"),
    lambda: service.audit_events(wid_b, "one"),
    lambda: service.invitations(wid_b, "one"),
    lambda: service.invite(wid_b, "one", "x@y.co", "editor", {}),
    lambda: service.update_member(wid_b, "one", TWO, "viewer", {}),
    lambda: service.remove_member(wid_b, "one", TWO),
    lambda: service.revoke_invitation(wid_b, "one", str(uuid.uuid4())),
):
    assert denied(call) == foreign_msg
assert denied(lambda: service.media(wid_b, "one", "asset"), 403) == foreign_msg
assert denied(lambda: service.media(ghost, "one", "asset"), 403) == foreign_msg
checks.append("cross-tenant read/mutate/export/members/audit/invitation paths deny with the nonexistent-workspace message")

# 2. Foreign workspace not enumerable through the workspace list.
listed = service.workspaces("one")["workspaces"]
assert [item["workspaceId"] for item in listed] == [wid_a]
checks.append("workspace list contains only own memberships")

# 3. Invitation flow: owner invites, third user accepts, roles enforced, token single-use.
invited = service.invite(wid_a, "one", "Third@Example.com", "editor", {"can_publish": False})
raw = invited["token"]
with connection() as db:
    stored = db.execute("SELECT token_hash,email FROM public.pr_invitations WHERE id::text=%s", (invited["invitationId"],)).fetchone()
assert stored[0] != raw and len(stored[0]) == 64 and stored[1] == "third@example.com"
denied(lambda: service.accept_invitation("three", "not-a-real-token-value-at-all"), 404)
accepted = service.accept_invitation("three", raw, client="198.51.100.3")
assert accepted == {"workspaceId": wid_a, "role": "editor", "can_publish": False, "can_reply": False, "can_moderate": False, "can_manage_connections": False}
denied(lambda: service.accept_invitation("three", raw), 404)  # single use
assert service.get(wid_a, "three")["membership"]["role"] == "editor"
assert [m["userId"] for m in service.members(wid_a, "three")["members"]] == sorted([ONE, THREE], key=lambda u: ("owner" if u == ONE else "editor", u))
checks.append("invitation is hashed at rest, single-use, email-normalized, and grants exactly the invited role")

# 4. Role matrix at the repository: editor edits but cannot approve/manage; approver cannot edit.
rev = service.get(wid_a, "three")["revision"]
service.mutate(wid_a, "three", rev, "mode", {"mode": "personal"})
rev = service.get(wid_a, "three")["revision"]
denied(lambda: service.mutate(wid_a, "three", rev, "p2_approve", {"reviewId": "x", "digest": "y", "confirmed": True}), 403)
denied(lambda: service.invite(wid_a, "three", "a@b.co", "viewer", {}), 403)
denied(lambda: service.mutate(wid_a, "three", rev, "p2_channel_disconnect", {"channelId": "x"}), 403)
service.update_member(wid_a, "one", THREE, "approver", {"can_publish": True})
rev = service.get(wid_a, "three")["revision"]
denied(lambda: service.mutate(wid_a, "three", rev, "mode", {"mode": "business"}), 403)
service.update_member(wid_a, "one", THREE, "viewer", {})
rev = service.get(wid_a, "three")["revision"]
denied(lambda: service.mutate(wid_a, "three", rev, "mode", {"mode": "business"}), 403)
denied(lambda: service.update_member(wid_a, "one", ONE, "viewer", {}), 409)  # cannot change own role
denied(lambda: service.remove_member(wid_a, "one", ONE), 409)  # owner cannot be removed
checks.append("role matrix enforced server-side: editor/approver/viewer boundaries and owner protections")

# 5. Step-up: stale auth blocks sensitive actions; fresh auth allows them.
auth_times["one"] = clock[0] - 3600
denied(lambda: service.invite(wid_a, "one", "late@b.co", "viewer", {}), 403, "Sign in again to confirm this sensitive action.")
denied(lambda: service.remove_member(wid_a, "one", THREE), 403)
denied(lambda: service.revoke_session("one", "session-one-0123456789abcdef"), 403)
auth_times["one"] = clock[0]
service.update_member(wid_a, "one", THREE, "editor", {"can_publish": True})
checks.append("step-up freshness window enforced for invitations, member removal, and session revocation")

# 6. Job claim re-authorizes approve authority: a real approval by the publishing editor,
#    then the flag is revoked before the worker claims → held, no attempt.
from datetime import datetime, timezone
snap = service.get(wid_a, "three")


def act(action, payload):
    global snap
    snap = service.mutate(wid_a, "three", snap["revision"], action, payload)


act("context", {"purpose": "Make community learning accessible", "audience": "Curious beginners", "subject": "Community workshops", "speaker": "My voice", "layers": []})
act("source", {"kind": "sample"})
source = snap["state"]["sources"][-1]
act("approve_source", {"sourceId": source["id"], "factIds": [fact["id"] for fact in source["facts"]]})
act("source_done", {})
act("profile_propose", {"writing": "A small step can be a useful beginning.", "tone": "warm"})
denied(lambda: act("profile_decide", {"decision": "approve"}), 403)  # the voice profile is an owner decision, like learned preferences
snap = service.mutate(wid_a, "one", snap["revision"], "profile_decide", {"decision": "approve"})
act("runtime", {"selected": "deterministic-preview"})
act("generate", {"platform": "LinkedIn", "language": "English"})
variant = snap["state"]["variants"][0]
act("p2_variant_review", {"variantId": variant["id"], "variantRevision": variant["revision"], "confirmed": True, "excludedUnknowns": variant["unknowns"]})
channel = {"id": uuid.uuid4().hex, "platform": "LinkedIn", "account": "Verified test member", "accountType": "member", "language": "English", "scopes": ["w_member_social"], "verifiedAt": clock[0], "expiresAt": clock[0] + 86400, "capabilityVersion": 1, "providerAccountId": "urn:li:person:test"}
saved = service.repository.command(wid_a, "one", snap["revision"], lambda state, actor: service.commands.upsert_verified_channel(state, actor, channel), requirement="manage_connections")
snap = service.commands.present(saved["state"], saved["revision"])
act("p2_review", {"channelId": channel["id"], "variantId": variant["id"], "localTime": datetime.fromtimestamp(clock[0] + 60, timezone.utc).replace(tzinfo=None).isoformat(), "timeZone": "UTC", "acknowledgedWarnings": variant["warnings"]})
review = snap["state"]["phase2"]["reviews"][-1]
act("p2_approve", {"reviewId": review["id"], "digest": review["digest"], "confirmed": True})
job = snap["state"]["phase2"]["jobs"][0]
assert job["approvedBy"] == THREE and job["state"] == "scheduled"
service.update_member(wid_a, "one", THREE, "editor", {"can_publish": False})
worker = PostgresWorker(connection, clock=lambda: clock[0] + 120)
worker.step()
with connection() as db:
    held = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid_a,)).fetchone()[0]["phase2"]["jobs"][0]
assert held["state"] == "held" and not held["attempts"], held["state"]
checks.append("worker holds a job whose approver lost publish authority before claim; no provider attempt")

# 7. Sessions inventory and revocation are per-user; another user's session cannot be revoked.
sessions = service.sessions("one")["sessions"]
assert any(item["current"] and item["client"] == "TestClient" for item in sessions)
denied(lambda: service.revoke_session("two", "session-one-0123456789abcdef"), 404)
gone = service.revoke_session("one", "session-one-0123456789abcdef")
assert gone["revoked"] and gone["current"]
assert service.sessions("one")["sessions"][0]["revoked"] is True
checks.append("session list is self-scoped and revocation of another user's session is not possible")

# 8. Throttle: fixed window blocks after the limit.
with connection() as db:
    db.execute("DELETE FROM public.pr_auth_throttle")
for _ in range(30):
    service.bootstrap("two", "assist", client="198.51.100.9")
denied(lambda: service.bootstrap("two", "assist", client="198.51.100.9"), 429)
checks.append("verify endpoint throttles the 31st attempt from one client within a minute")

# 9. Audit trail is workspace-scoped, append-only, content-free.
events = service.audit_events(wid_a, "one")["events"]
kinds = {event["kind"] for event in events}
assert {"workspace.created", "invitation.created", "invitation.accepted", "member.updated"} <= kinds
assert not any("@" in json.dumps(event) for event in events)
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
    assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s", (wid_b,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s", (wid_a,)).fetchone()[0] > 0
# SET ROLE is transactional: use a fresh connection per denied statement so a rollback
# cannot silently restore the superuser for the next check.
for statement in ("UPDATE public.pr_audit_events SET kind='x'", "DELETE FROM public.pr_audit_events", "SELECT * FROM public.pr_invitations", "SELECT * FROM public.pr_sessions", "SELECT * FROM public.pr_auth_throttle", "INSERT INTO public.pr_audit_events(workspace_id,kind) VALUES(NULL,'forged')"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        try:
            db.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
        else:
            raise AssertionError(f"browser role was allowed: {statement}")
checks.append("audit rows are tenant-read-only and immutable; invitations, sessions, and throttle buckets are never browser-readable")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
