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
checks.append("the same own idea drafted again reuses its source (one source, new conversation, completed run, no re-approval)")

# 2. Pasted third-party text drafted twice stays rewrite_approval and is not auto-approved.
pasted = "Third-party paragraph one.\nThird-party paragraph two."
p1 = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": pasted, "ownContent": False, "confirmUse": True, "destinations": destinations})
p2 = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": pasted, "ownContent": False, "confirmUse": True, "destinations": destinations})
assert p1["sourceId"] == p2["sourceId"] and p2["sourcePolicy"] == "rewrite_approval"
assert not any(f["approved"] for f in sources_with(pasted)[0]["facts"])
checks.append("pasted third-party text drafted again reuses its source and keeps rewrite_approval with nothing auto-approved")

# 3. Different text still creates its own source.
other = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "A different thought entirely.", "ownContent": True, "confirmUse": True, "destinations": destinations})
assert other["sourceId"] not in (first["sourceId"], p1["sourceId"])
checks.append("a different idea still becomes its own source")

# 4. Context Pocket: a chosen usable source is read with the idea; an unknown id is refused before anything is stored.
notes = "Rehearsal notes.\nThe second movement needs a slower start.\nBreathe before the coda."
note = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": notes, "ownContent": True, "confirmUse": True, "destinations": destinations})
pocket = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "A thought that leans on my rehearsal notes.", "ownContent": True, "confirmUse": True, "destinations": destinations, "sourceIds": [note["sourceId"]]})
assert pocket["status"] == "completed"
assert any(e["type"] == "source.added" and e.get("sourceId") == note["sourceId"] for e in pocket["events"]), [e["type"] for e in pocket["events"]]
count = len(service.get(wid, "one")["state"]["sources"])
try:
    ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "Another thought.", "ownContent": True, "confirmUse": True, "destinations": destinations, "sourceIds": ["not-a-source"]})
    raise AssertionError("an unknown source id was accepted")
except AlphaError as error:
    assert error.status == 409, error.status
assert len(service.get(wid, "one")["state"]["sources"]) == count
checks.append("Context Pocket: a chosen usable source is read with the idea; an unknown id is refused (409) before any source is stored")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
