"""One-click tone and polish edits on disposable PostgreSQL (brand intelligence spec 4.3, 5.3-5.5; TONE-1…4, 6…8).

The real hosted service, a real workspace row and real run, message and product-event rows; the writer is the
zero-network fixture writer the dev harness uses (tests/draft_edit_fixtures.py), so no model is called. Pinned here:
request → candidate → accept → undo round-trips on the workspace row; a stale request is refused before any run; a
replayed request runs once; the base rule; a selection keeps every other character; discard; a draft saved while the
writer worked is never overwritten (409); a draft already in the queue gets a new draft; no change; the HTTP route and
its 404 while the flag is off; `draft_edit.*` events written once each, none of them a learning signal; and nothing
written to `speaker`, `learning` or `brandHub`.

Run: LC_ALL=C PYTHONPATH=src:tests <venv python> scripts/postriff_disposable_postgres.py tests/phase2/postgres_draft_edits.py
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.contracts import digest  # noqa: E402
from postriff_phase2.draft_edits import run_key  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication  # noqa: E402
from draft_edit_fixtures import MARKS, attach  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TOKEN = "dev-session-one-" + "0" * 24
TEXT = "We may reopen on 3 March 🎹, according to the landlord. Tickets are $25 at the door."
clock = [1789524000.0]
passed = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != TOKEN:
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: "session-one-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


def refused(call, status, code=None):
    try:
        call()
    except AlphaError as error:
        return error.status == status and (code is None or error.code == code), (error.status, error.code, str(error))
    return False, "not refused"


def revision():
    return service.get(wid, TOKEN)["revision"]


def act(action, payload):
    return service.mutate(wid, TOKEN, revision(), action, payload)


def draft(variant_id=None):
    return next(v for v in service.get(wid, TOKEN)["state"]["variants"] if v["id"] == (variant_id or vid))


def ask(key, variant_id=None, **body):
    current = draft(variant_id)
    return edits.request(wid, TOKEN, variant_id or vid, {"variantRevision": current["revision"], "mode": "tone", "tone": "warm", "idempotencyKey": key,
                                                         "expectedRevision": revision(), **body})


def rows(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchall()


def events(name=None):
    found = rows("SELECT event, dedupe_key FROM public.pr_product_events WHERE workspace_id=%s AND event LIKE 'draft_edit.%%' ORDER BY id", wid)
    return [row for row in found if name is None or row[0] == name]


def runs():
    return rows("SELECT id::text, status, usage, idempotency_key, conversation_id::text FROM public.pr_agent_runs WHERE workspace_id=%s ORDER BY created_at", wid)


def learning_rows():
    return rows("SELECT count(*) FROM public.pr_learning_events WHERE workspace_id=%s AND kind IN ('draft.edited','draft.update_accepted')", wid)[0][0]


def held(state):
    return {key: digest(state.get(key)) for key in ("speaker", "learning", "brandHub")}


def edit_state(change):
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
        change(state)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
ideas = service.ideas
service.bootstrap(TOKEN, "studio")
from consumer_fixtures import approve_budgets  # noqa: E402
approve_budgets(connection, wid)
check("off by default: no route and no catalogue entry", not hasattr(service, "draft_edits") and "draftEdits" not in ideas.model_catalog())
edits = attach(service)
check("mounted: the route exists and the catalogue offers edits", service.draft_edits is edits and ideas.model_catalog()["draftEdits"]["enabled"] is True)

# A draft written by the template writer, then reworded by its author: revision 2 holds known text.
quick = ideas.quick_start(wid, TOKEN, revision(), {"text": "Studio news: the spring reopening.", "ownContent": True, "confirmUse": True,
                                                   "destinations": [{"platform": "LinkedIn", "language": "en-US"}]})
ideas.apply(wid, TOKEN, revision(), quick["runId"], quick["artifactHash"])
vid = next(v["id"] for v in service.get(wid, TOKEN)["state"]["variants"] if (v.get("provenance") or {}).get("runId") == quick["runId"])
act("variant_edit", {"variantId": vid, "variantRevision": 1, "text": TEXT})
check("setup: the draft is at revision 2 with the author's text", (draft()["revision"], draft()["text"]) == (2, TEXT), draft()["revision"])
baseline = held(service.get(wid, TOKEN)["state"])
learned = learning_rows()
check("setup: the author's own edit is a learning signal (so 'none' below means something)", learned >= 1, learned)

# 1. A stale request is refused before any run, conversation or event exists.
before = len(runs())
ok, detail = refused(lambda: edits.request(wid, TOKEN, vid, {"variantRevision": 1, "mode": "tone", "tone": "warm", "idempotencyKey": "k-stale", "expectedRevision": revision()}),
                     409, "draft_revision_conflict")
check("stale: 409 draft_revision_conflict", ok, detail)
check("stale: no run and no event", len(runs()) == before and events() == [], (len(runs()), events()))

# 2. A tone edit: the candidate waits beside the draft; the draft's own text is untouched.
answer = ask("k-warm")
edit = answer["edit"]
run_id = edit["runId"]
check("candidate: spec 5.4 answer", (edit["status"], edit["outcome"], edit["variantId"], edit["base"], edit["voice"]) ==
      ("candidate", "proposed_update", vid, {"kind": "current", "revision": 2}, {"requested": "neutral", "effective": "neutral"}), edit)
check("candidate: no finding on a meaning-preserving edit", edit["fidelity"]["violations"] == [] and "quantities" in edit["fidelity"]["checked"], edit["fidelity"])
check("candidate: usage reports a duration", isinstance(edit["usage"]["durationMs"], int) and edit["usage"]["durationMs"] >= 0, edit["usage"])
saved = draft()
pending = saved["proposedUpdate"] or {}
check("candidate: draft text and revision untouched", (saved["text"], saved["revision"]) == (TEXT, 2), saved["revision"])
check("candidate: proposedUpdate carries the edit", (pending.get("text"), pending.get("runId"), pending.get("baseVariantRevision"), (pending.get("edit") or {}).get("tone"))
      == (TEXT + " " + MARKS["warm"], run_id, 2, "warm"), pending)
check("candidate: the snapshot in the answer shows it", next(v for v in answer["snapshot"]["state"]["variants"] if v["id"] == vid)["proposedUpdate"]["runId"] == run_id)
row = next(r for r in runs() if r[0] == run_id)
check("run: applied, keyed apart from other writing runs, its own workload", row[1] == "applied" and row[3].startswith("draft-edit:")
      and row[2].get("workload") == "draft_edit" and row[2].get("edit") == {"mode": "tone", "tone": "warm", "depth": "standard", "scope": "draft"}, row[1:4])
conversation = row[4]
title = rows("SELECT title FROM public.pr_conversations WHERE id::text=%s", conversation)[0][0]
messages = rows("SELECT role, body FROM public.pr_messages WHERE conversation_id::text=%s ORDER BY seq", conversation)
check("conversation: one 'Draft edits' conversation holds the run's line, no user message", title == "Draft edits" and [m[0] for m in messages] == ["assistant"]
      and messages[0][1]["text"] == "Prepared a warm version of this draft. The candidate is on the draft for review." and messages[0][1]["edit"]["tone"] == "warm", (title, messages))
check("events: requested and candidate, once each", [e[0] for e in events()] == ["draft_edit.requested", "draft_edit.candidate"], events())

# 3. The same request again (a lost answer) is answered from its run: no second run, no second event.
count = len(runs())
again = ask("k-warm")
check("replay: same run, nothing new", again["edit"]["runId"] == run_id and len(runs()) == count and len(events()) == 2, (again["edit"]["runId"], len(runs()), events()))

# 4. Accept, then undo: each is a new revision; neither is a learning signal; each is measured once.
act("accept_update", {"variantId": vid})
saved = draft()
check("accept: revision 3 is the edited text, recorded as an accepted edit", (saved["revision"], saved["text"], saved["revisions"][-1]["origin"], saved["editBase"], saved["proposedUpdate"])
      == (3, TEXT + " " + MARKS["warm"], "accepted-edit", {"revision": 2, "acceptedRevision": 3}, None), saved["revisions"][-1])
act("variant_restore", {"variantId": vid, "variantRevision": 3, "restoreRevision": 2})
saved = draft()
check("undo: revision 4 brings back the author's text", (saved["revision"], saved["text"], saved["revisions"][-1]["origin"], saved["needsReview"]) == (4, TEXT, "restored", True),
      saved["revisions"][-1])
check("accept and undo: one event each", [e[0] for e in events()][2:] == ["draft_edit.accepted", "draft_edit.restored"], events())
check("accept and undo: no learning signal", learning_rows() == learned, (learning_rows(), learned))

# 5. The base rule: right after an accepted edit, the next tone starts from the wording before it.
first = ask("k-warm-2")["edit"]
act("accept_update", {"variantId": vid})
check("base: an accepted second edit", draft()["revision"] == 5 and draft()["editBase"] == {"revision": 4, "acceptedRevision": 5}, draft().get("editBase"))
direct = ask("k-direct", tone="direct", base="original")["edit"]
check("base: the direct tone is written from revision 4, not from the warm text", direct["base"] == {"kind": "original", "revision": 4}
      and draft()["proposedUpdate"]["text"] == TEXT + " " + MARKS["direct"], (direct["base"], draft()["proposedUpdate"]["text"]))

# 6. Discard drops the candidate and nothing else.
act("discard_update", {"variantId": vid})
saved = draft()
check("discard: no candidate, same revision and text", (saved["proposedUpdate"], saved["revision"], saved["text"]) == (None, 5, TEXT + " " + MARKS["warm"]), saved["revision"])
check("discard: one event", len(events("draft_edit.discarded")) == 1, events())

# 7. A selection: only the passage changes; offsets are code points (an emoji sits before it).
act("variant_restore", {"variantId": vid, "variantRevision": 5, "restoreRevision": 2})
current = draft()
start = current["text"].index("Tickets")
selected = ask("k-polish", mode="polish", tone=None, selection={"start": start, "end": len(current["text"])})["edit"]
expected = current["text"] + " " + MARKS["polish"]
check("selection: the passage alone changed", selected["scope"] == "selection" and selected["selection"] == {"start": start, "end": len(current["text"])}
      and draft()["proposedUpdate"]["text"] == expected and draft()["proposedUpdate"]["text"][:start] == current["text"][:start], (selected, draft()["proposedUpdate"]["text"]))
act("discard_update", {"variantId": vid})

# 8. No change is an answer, and nothing is attached.
same = ask("k-same", tone="custom", instruction="Leave it unchanged, it already reads well.")["edit"]
row = next(r for r in runs() if r[0] == same["runId"])
check("no change: answered, not attached, run left completed", same["status"] == "no_change" and draft()["proposedUpdate"] is None and row[1] == "completed", (same, row[1]))
check("no change: measured", len(events("draft_edit.no_change")) == 1, events())

# 9. A draft saved while the writer worked is never overwritten: the late candidate is refused (409).
real_apply = ideas.apply


def save_first(workspace_id, token, current_revision, run, artifact_hash):
    act("variant_edit", {"variantId": vid, "variantRevision": draft()["revision"], "text": "Saved while the writer was working."})
    return real_apply(workspace_id, token, revision(), run, artifact_hash)


ideas.apply = save_first
ok, detail = refused(lambda: ask("k-race"), 409, "draft_revision_conflict")
ideas.apply = real_apply
check("race: 409 draft_revision_conflict", ok, detail)
check("race: the saved text stays, no candidate", (draft()["text"], draft()["proposedUpdate"]) == ("Saved while the writer was working.", None), draft()["text"])
race_run = next(r[0] for r in runs() if r[3] == run_key(vid, "k-race"))
check("race: measured as a failed edit", [e[1] for e in events("draft_edit.failed")] == [f"draft_edit.failed:{vid}:{race_run}"], events("draft_edit.failed"))
ask("k-race-2")
act("variant_edit", {"variantId": vid, "variantRevision": draft()["revision"], "text": "My own wording again."})
ok, detail = refused(lambda: act("accept_update", {"variantId": vid}), 409)
check("race: accept after a concurrent edit is 409", ok, detail)
check("race: the person's text stays", draft()["text"] == "My own wording again.", draft()["text"])

# 10. A draft already in the queue keeps its text; the edit becomes a new draft.
committed = draft()


def queue(state):
    state["phase2"]["jobs"].append({"id": "job-draft-edit", "state": "scheduled", "cancelRequested": False, "scheduleId": "s-1",
                                    "manifest": {"variantId": vid, "contentRevision": committed["revision"], "platform": "LinkedIn", "channelId": None,
                                                 "payload": {"text": committed["text"], "language": committed["language"]}, "voiceRevision": None, "styleRevision": 0}})


edit_state(queue)
fresh = ask("k-queued")["edit"]
after = draft()
derived = draft(fresh["variantId"])
check("queued: a new draft, the committed one untouched", fresh["outcome"] == "new_draft" and fresh["variantId"] != vid
      and (after["revision"], after["text"], after["proposedUpdate"]) == (committed["revision"], committed["text"], None), (fresh, after["revision"]))
check("queued: the new draft holds the edit and its lineage", derived["text"] == committed["text"] + " " + MARKS["warm"] and derived["provenance"]["derivedFrom"] == vid
      and "edit" not in derived and derived["revisions"][0]["origin"] == "ideas-candidate", derived.get("provenance"))

# 11. The HTTP route, and 404 while the flag is off.
second = next(v for v in service.get(wid, TOKEN)["state"]["variants"] if v["id"] == fresh["variantId"])


def http(body, path=None):
    app = HostedApplication(service, public_auth={})
    raw = json.dumps(body).encode()
    environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path or f"/api/workspaces/{wid}/drafts/{second['id']}/edits", "QUERY_STRING": "", "CONTENT_TYPE": "application/json",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "https", "HTTP_HOST": "rafii.example", "HTTP_ORIGIN": "https://rafii.example",
               "HTTP_AUTHORIZATION": "Bearer " + TOKEN, "HTTP_X_POSTRIFF_REQUEST": "founder-alpha"}
    captured = {}
    result = b"".join(app(environ, lambda status, headers: captured.update(status=status))).decode()
    return captured["status"], json.loads(result)


status, body = http({"variantRevision": second["revision"], "mode": "tone", "tone": "playful", "idempotencyKey": "k-http", "expectedRevision": revision()})
check("http: 200 with the snapshot and the edit", status == "200 OK" and set(body) == {"snapshot", "edit"} and body["edit"]["status"] == "candidate"
      and {"runId", "variantId", "base", "fidelity", "voice", "usage"} <= set(body["edit"]), (status, body.get("edit")))
del service.draft_edits
status, body = http({"variantRevision": second["revision"], "mode": "tone", "tone": "warm", "idempotencyKey": "k-off", "expectedRevision": revision()})
check("http: 404 feature_disabled with the flag off", (status, body.get("code")) == ("404 Not Found", "feature_disabled"), (status, body))
service.draft_edits = edits

# 12. Every event once; nothing written to speaker, learning or brandHub.
duplicates = rows("SELECT event, dedupe_key, count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event LIKE 'draft_edit.%%' GROUP BY 1, 2 HAVING count(*) > 1", wid)
counts = {name: n for name, n in rows("SELECT event, count(*) FROM public.pr_product_events WHERE workspace_id=%s AND event LIKE 'draft_edit.%%' GROUP BY 1", wid)}
check("events: none duplicated", duplicates == [], duplicates)
check("events: one per request and action", counts == {"draft_edit.requested": 9, "draft_edit.candidate": 7, "draft_edit.no_change": 1, "draft_edit.failed": 1,
                                                        "draft_edit.accepted": 2, "draft_edit.restored": 2, "draft_edit.discarded": 2}, counts)
texts = rows("SELECT properties::text FROM public.pr_product_events WHERE workspace_id=%s AND event LIKE 'draft_edit.%%'", wid)
check("events: ids and enums only, never text", not any("reopen" in t[0] or "Tickets" in t[0] for t in texts), texts[:2])
check("state: speaker, learning and brandHub untouched by the edits", held(service.get(wid, TOKEN)["state"]) == baseline)

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": passed}, indent=2))
