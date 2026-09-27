"""Rafii v9 quick start: drafting the same idea again reuses its source instead of refusing it as a
duplicate, and Context Pocket sources (`sourceIds`) are read with the idea or refused when unusable.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]
checks = []

with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
snap = service.bootstrap("one", "studio")
ideas = service.ideas
destinations = [{"platform": "LinkedIn", "language": "English"}]


def sources_with(text):
    return [s for s in service.get(wid, "one")["state"]["sources"] if s.get("active") and s.get("text") == text]


# 1. Own idea drafted twice: one source, two conversations, both runs complete, no re-approval.
idea = "Slow practice is where the performance is decided."
first = ideas.quick_start(wid, "one", snap["revision"], {"text": idea, "ownContent": True, "confirmUse": True, "destinations": destinations})
assert first["status"] == "completed" and first["sourcePolicy"] == "public_quote"
reviewed = sources_with(idea)[0].get("reviewedAt")
second = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": idea, "ownContent": True, "confirmUse": True, "destinations": destinations})
assert second["status"] == "completed", second["status"]
assert second["sourceId"] == first["sourceId"] and second["conversationId"] != first["conversationId"]
assert len(sources_with(idea)) == 1
assert sources_with(idea)[0].get("reviewedAt") == reviewed
assert sources_with(idea)[0]["title"] == idea
assert sources_with(idea)[0].get("origin") == {"kind": "quick_start"}
checks.append("the same own idea drafted again reuses its run-only source with a meaningful title (one source, new conversation, completed run, no re-approval)")

# 2. Pasted third-party text drafted twice stays rewrite_approval and is not auto-approved.
pasted = "Third-party paragraph one.\nThird-party paragraph two."
p1 = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": pasted, "ownContent": False, "confirmUse": True, "destinations": destinations})
p2 = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": pasted, "ownContent": False, "confirmUse": True, "destinations": destinations})
assert p1["sourceId"] == p2["sourceId"] and p2["sourcePolicy"] == "rewrite_approval"
assert sources_with(pasted)[0]["title"] == "Third-party paragraph one."
assert sources_with(pasted)[0].get("origin") == {"kind": "quick_start"}
assert not any(f["approved"] for f in sources_with(pasted)[0]["facts"])
checks.append("pasted third-party text drafted again reuses its run-only source, uses the first line as its title and keeps rewrite_approval with nothing auto-approved")

# 3. Different/long text still creates its own source; deriving its display title never rejects the prompt.
long_idea = "One thing piano practice taught me about creating: consistency matters more than waiting for inspiration."
other = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": long_idea, "ownContent": True, "confirmUse": True, "destinations": destinations})
assert other["sourceId"] not in (first["sourceId"], p1["sourceId"])
assert sources_with(long_idea)[0]["title"] == long_idea[:80]
checks.append("a different idea still becomes its own source and a long first line gets a bounded title without rejecting the request")

# 4. Context Pocket: an explicitly saved reusable source is read with the idea; an unknown id is refused before anything is stored.
notes = "Rehearsal notes.\nThe second movement needs a slower start.\nBreathe before the coda."
current = service.get(wid, "one")
with_note = service.mutate(wid, "one", current["revision"], "source", {"kind": "text", "text": notes, "title": "Rehearsal notes"})
note = next(source for source in with_note["state"]["sources"] if source.get("text") == notes)
with_policy = service.mutate(wid, "one", with_note["revision"], "source_policy", {"sourceId": note["id"], "policy": "public_quote", "egressConsent": ["local"], "confirmed": True})
note = next(source for source in with_policy["state"]["sources"] if source["id"] == note["id"])
with_approval = service.mutate(wid, "one", with_policy["revision"], "approve_source", {"sourceId": note["id"], "factIds": [fact["id"] for fact in note["facts"]]})
note = next(source for source in with_approval["state"]["sources"] if source["id"] == note["id"])
assert (note.get("origin") or {}).get("kind") != "quick_start"
pocket = ideas.quick_start(wid, "one", with_approval["revision"], {"text": "A thought that leans on my rehearsal notes.", "ownContent": True, "confirmUse": True, "destinations": destinations, "sourceIds": [note["id"]]})
assert pocket["status"] == "completed"
assert any(e["type"] == "source.added" and e.get("sourceId") == note["id"] for e in pocket["events"]), [e["type"] for e in pocket["events"]]
count = len(service.get(wid, "one")["state"]["sources"])
try:
    ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "Another thought.", "ownContent": True, "confirmUse": True, "destinations": destinations, "sourceIds": ["not-a-source"]})
    raise AssertionError("an unknown source id was accepted")
except AlphaError as error:
    assert error.status == 409, error.status
assert len(service.get(wid, "one")["state"]["sources"]) == count
checks.append("Context Pocket: a chosen usable source is read with the idea; an unknown id is refused (409) before any source is stored")

# 5. Chat-context S25: chips on a quick start are forwarded to the turn only when present, and never route elsewhere.
with psycopg.connect(DSN) as db:
    def turn_bodies():
        return [row[0] for row in db.execute("SELECT body FROM public.pr_messages m JOIN public.pr_conversations c ON c.id=m.conversation_id WHERE c.workspace_id=%s AND m.role='user' ORDER BY m.created_at, m.seq", (wid,)).fetchall()]
    before = len(turn_bodies())
    posted = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "Every Monday at 9am post a practice tip.", "ownContent": True, "confirmUse": True, "destinations": destinations,
                                                                                "references": [{"kind": "source", "id": note["id"], "label": "Spoofed client label"}]})
    assert posted["status"] == "completed" and posted.get("runId"), posted
    usage = db.execute("SELECT usage FROM public.pr_agent_runs WHERE id::text=%s", (posted["runId"],)).fetchone()[0]
    # The client's label never reaches the report; the server names the source by its own title.
    assert "Spoofed client label" not in json.dumps(usage["references"]), usage["references"]
    assert [u["id"] for u in usage["references"]["used"]] == [note["id"]], usage.get("references")
    assert "This message has attachments" in " ".join(usage["references"]["reminders"]), usage["references"]["reminders"]
    plain = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "One more thought about scales.", "ownContent": True, "confirmUse": True, "destinations": destinations})
    plain_usage = db.execute("SELECT usage FROM public.pr_agent_runs WHERE id::text=%s", (plain["runId"],)).fetchone()[0]
    # A quick start's turn has no typed text, so it writes no user message of its own.
    assert "references" not in plain_usage and len(turn_bodies()) == before, plain_usage
checks.append("chips on a quick start reach the turn (the report is on the run, labels dropped), automation wording still drafts with the reminder, and a chip-less quick start carries no chip keys")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
