"""Milestone B on disposable PostgreSQL: quick-start → events → apply, tenancy, policy re-check.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with migrations 004+005).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.source_policy import facts_digest

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
FOUR = "00000000-0000-0000-0000-000000000005"  # distinct from isolation.py's second owner
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in ("one", "four"):
        raise AlphaError("Verified session required.", 401)
    return ONE if token == "one" else FOUR


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]
checks = []


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError("accepted")


with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s)", (FOUR,))
    wid_a = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid_a,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
snap_a = service.bootstrap("one", "studio")
snap_b = service.bootstrap("four", "assist")
wid_b = snap_b["workspaceId"]
ideas = service.ideas

# 1. Source-first activation: own thought → two candidate variants, no channel, no model request.
quick = ideas.quick_start(wid_a, "one", snap_a["revision"], {"text": "The community garden hosts a free seed-swap on Saturday.\nVisitors can bring seeds or simply come to learn.", "ownContent": True, "confirmUse": True, "destinations": [{"platform": "LinkedIn", "language": "English"}, {"platform": "Instagram", "language": "繁體中文"}]})
assert quick["status"] == "completed" and quick["sourcePolicy"] == "public_quote"
kinds = [e["type"] for e in quick["events"]]
assert kinds[0] == "run.started" and kinds[-1] == "run.completed" and "artifact.created" in kinds
assert all(k in ("run.started", "progress.updated", "source.added", "artifact.created", "message.delta", "message.completed", "warning.created", "run.completed") for k in kinds)
assert quick["usage"]["modelRequests"] == 0
checks.append("quick-start produces a completed run with two candidates and only safe events; zero model requests")

# 2. Cursor replay is deterministic and dedup-safe; Last-Event-ID semantics.
first = ideas.events(wid_a, "one", quick["runId"], 0)
later = ideas.events(wid_a, "one", quick["runId"], first["events"][2]["seq"])
assert later["events"][0]["seq"] == first["events"][3]["seq"] and later["cursor"] == first["cursor"]
assert [e["id"] for e in first["events"]] == [f"{quick['runId']}:{i}" for i in range(1, len(first["events"]) + 1)]
checks.append("event cursors replay exactly once with stable IDs")

# 3. Idempotent turn: same key returns the existing run, no duplicate events.
conv = quick["conversationId"]
again = ideas.turn(wid_a, "one", conv, {"text": "same", "idempotencyKey": "k-dup", "destinations": [{"platform": "LinkedIn", "language": "English"}]})
twice = ideas.turn(wid_a, "one", conv, {"text": "same", "idempotencyKey": "k-dup", "destinations": [{"platform": "LinkedIn", "language": "English"}]})
assert again["runId"] == twice["runId"] and len(again["events"]) == len(twice["events"])
checks.append("duplicate idempotency key returns the same run without re-running")

# 4. Cross-tenant: workspace B cannot see A's conversation/run; foreign ids inside own workspace 404.
denied(lambda: ideas.events(wid_a, "four", quick["runId"], 0), 403)
denied(lambda: ideas.messages(wid_a, "four", conv, 0), 403)
denied(lambda: ideas.events(wid_b, "four", quick["runId"], 0), 404)
denied(lambda: ideas.turn(wid_b, "four", conv, {"text": "x"}), 404)
denied(lambda: ideas.apply(wid_b, "four", snap_b["revision"], quick["runId"], quick["artifactHash"]), 404)
checks.append("conversations, runs, and events are tenant-bound; foreign identifiers are unavailable")

# 5. Apply requires exact artifact hash and unchanged policy epoch; stale after policy change.
denied(lambda: ideas.apply(wid_a, "one", quick["revision"], quick["runId"], "0" * 64), 409)
state = service.get(wid_a, "one")
src = state["state"]["sources"][-1]
service.mutate(wid_a, "one", state["revision"], "source_policy", {"sourceId": src["id"], "policy": "internal_reference", "egressConsent": [], "confirmed": True})
state = service.get(wid_a, "one")
denied(lambda: ideas.apply(wid_a, "one", state["revision"], quick["runId"], quick["artifactHash"]), 409)
service.mutate(wid_a, "one", state["revision"], "source_policy", {"sourceId": src["id"], "policy": "public_quote", "egressConsent": [], "confirmed": True})
state = service.get(wid_a, "one")
# The epoch is state-derived: restoring the identical policy makes the candidate current again.
applied = ideas.apply(wid_a, "one", state["revision"], quick["runId"], quick["artifactHash"])
assert applied["status"] == "applied" and applied["variants"] == 2
state = service.get(wid_a, "one")
assert len(state["state"]["variants"]) == 2 and all(v["needsReview"] for v in state["state"]["variants"])
assert state["state"]["variants"][0]["provenance"]["runId"] == quick["runId"]
assert ideas.apply(wid_a, "one", state["revision"], quick["runId"], quick["artifactHash"])["status"] == "applied"
checks.append("apply is exact-hash and policy-epoch bound; a stale candidate is preserved not applied; a current one applies as reviewable variants; re-apply is idempotent")

# 6. Internal-only source never enters a draft projection; prohibited blocks generation entirely.
service.mutate(wid_a, "one", state["revision"], "source_policy", {"sourceId": src["id"], "policy": "internal_reference", "egressConsent": [], "confirmed": True})
run = ideas.turn(wid_a, "one", conv, {"text": "", "sourceIds": [src["id"]], "destinations": [{"platform": "LinkedIn", "language": "English"}]})
assert not any(e["type"] == "source.added" for e in run["events"])
# FINAL-03: the warning names the reason code in `reason` and says it in words in `message`.
assert any(e["type"] == "warning.created" and e.get("reason") == "internal_reference_excluded_from_public_draft" and "internal references stay out of public drafts" in e.get("message", "") for e in run["events"])
assert not any(src["facts"][0]["text"] in json.dumps(e) for e in run["events"])
checks.append("internal_reference source is excluded from the public draft projection and its text never appears in events")

# 7. Pasted third-party text defaults to rewrite_approval and is candidate-only until use is approved.
state = service.get(wid_a, "one")
pasted = ideas.quick_start(wid_a, "one", state["revision"], {"text": "Third-party paragraph one.\nThird-party paragraph two.", "ownContent": False, "confirmUse": True})
assert pasted["sourcePolicy"] == "rewrite_approval"
state = service.get(wid_a, "one")
psrc = next(s for s in state["state"]["sources"] if s["id"] == pasted["sourceId"])
assert not any(f["approved"] for f in psrc["facts"])  # facts are not auto-approved for third-party text
checks.append("third-party pasted text is rewrite_approval and requires fact approval; nothing is auto-approved")

# 8. Browser role cannot read another tenant's runs/events directly.
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (FOUR,))
    assert db.execute("SELECT count(*) FROM public.pr_agent_events WHERE workspace_id=%s", (wid_a,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM public.pr_conversations WHERE workspace_id=%s", (wid_a,)).fetchone()[0] == 0
checks.append("RLS hides other tenants' conversations and events from direct reads")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
