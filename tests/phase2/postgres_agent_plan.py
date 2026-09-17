"""Agent chat step ①/④ on disposable PostgreSQL: a chat message that names channels and times
yields destinations, a candidate plan on the artifact and message, ordered safe events, and
no side effect on jobs or reviews (design §4.4).

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with migrations 004+005).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
# 1789524000 = 2026-09-16T02:00Z = 10:00 Asia/Hong_Kong, so “今日 4 點” is still ahead and “聽日” is the 17th.
clock = [1789524000.0]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]

with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
snap = service.bootstrap("one", "studio")
ideas = service.ideas
before = snap["state"]["phase2"]

# 1. Quick start with named channels and times. Facebook is named but unsupported by the fixture.
text = "AI 點樣幫我練琴。今日晏晝 4 點 post 去 Instagram、今日下晝 5 點 post 去 LinkedIn、聽日晏晝 3 點半 post 去 Facebook。"
quick = ideas.quick_start(wid, "one", snap["revision"], {"text": text, "ownContent": True, "confirmUse": True, "timeZone": "Asia/Hong_Kong", "destinations": [{"platform": "Threads", "language": "English"}]})
assert quick["status"] == "completed"
plan = quick["artifact"]["plan"]
assert plan["kind"] == "schedule" and plan["timeZone"] == "Asia/Hong_Kong" and plan["intent"] == "schedule"
assert [(d["platform"], d["language"], d["localTime"]) for d in plan["destinations"]] == [
    ("Instagram", "zh-Hant", "2026-09-16T16:00"), ("LinkedIn", "zh-Hant", "2026-09-16T17:00")], plan["destinations"]
assert plan["unsupported"] == ["Facebook"]
# Named channels replaced the composer selection (Threads) and each got its own variant.
assert sorted(v["platform"] for v in quick["artifact"]["variants"]) == ["Instagram", "LinkedIn"]

# 2. Event stream keeps its shape and carries the proposal plus the unsupported-channel note.
kinds = [e["type"] for e in quick["events"]]
assert kinds[0] == "run.started" and kinds[-1] == "run.completed", kinds
assert kinds.index("action.proposed") < kinds.index("artifact.created")
proposed = next(e for e in quick["events"] if e["type"] == "action.proposed")
assert proposed["action"] == "schedule_plan" and proposed["destinations"] == 2 and proposed["timeZone"] == "Asia/Hong_Kong"
assert any(e["type"] == "warning.created" and e["message"].startswith("Facebook is not available") for e in quick["events"])

# 3. The assistant message persists the plan so the conversation can re-render it later.
thread = ideas.messages(wid, "one", quick["conversationId"])
assistant = [m for m in thread["messages"] if m["role"] == "assistant"][-1]
assert assistant["body"]["plan"] == plan and assistant["body"]["intent"] == "schedule"
assert assistant["body"]["destinations"] == [{"platform": "Instagram", "language": "zh-Hant"}, {"platform": "LinkedIn", "language": "zh-Hant"}]

# 4. A follow-up turn without channels keeps the composer's selection and yields no plan.
follow = ideas.turn(wid, "one", quick["conversationId"], {"text": "Shorter please.", "destinations": [{"platform": "Threads", "language": "English"}], "timeZone": "Asia/Hong_Kong"})
assert follow["status"] == "completed" and "plan" not in follow["artifact"]
assert [v["platform"] for v in follow["artifact"]["variants"]] == ["Threads"]
assert not any(e["type"] == "action.proposed" for e in follow["events"])

# 5. A bad zone degrades to UTC instead of failing the turn; an unattached time applies to every destination.
later = ideas.turn(wid, "one", quick["conversationId"], {"text": "Post this at 16:00 today.", "destinations": [{"platform": "LinkedIn", "language": "English"}, {"platform": "Threads", "language": "English"}], "timeZone": "Mars/Olympus"})
assert later["artifact"]["plan"]["timeZone"] == "UTC"
assert [d["localTime"] for d in later["artifact"]["plan"]["destinations"]] == ["2026-09-16T16:00", "2026-09-16T16:00"]

# 6. Proposing a plan never touches the execution ledger: no reviews, no jobs, nothing published.
with connection() as db:
    stored = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
after = stored["phase2"]
assert after["reviews"] == before["reviews"] and after["jobs"] == before["jobs"]

# 7. A published variant is a record: a later candidate for the same platform/language becomes a
#    new draft, never an "update" to what went out. An unscheduled draft is still refreshed in place.
import json  # noqa: E402
applied = ideas.apply(wid, "one", service.get(wid, "one")["revision"], quick["runId"], quick["artifactHash"])
assert applied["status"] == "applied"
first = service.get(wid, "one")["state"]["variants"]
linkedin = next(v for v in first if v["platform"] == "LinkedIn")
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    state["phase2"]["jobs"].append({"id": "job-published", "manifest": {"variantId": linkedin["id"], "platform": "LinkedIn"}, "state": "verified", "events": [], "attempts": [], "cancelRequested": False})
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
follow = ideas.turn(wid, "one", quick["conversationId"], {"text": "A second LinkedIn idea, and a fresh Instagram one.", "language": "繁體中文", "destinations": [{"platform": "LinkedIn", "language": "繁體中文"}, {"platform": "Instagram", "language": "繁體中文"}], "timeZone": "Asia/Hong_Kong"})
ideas.apply(wid, "one", service.get(wid, "one")["revision"], follow["runId"], follow["artifactHash"])
variants = service.get(wid, "one")["state"]["variants"]
linkedin_after = [v for v in variants if v["platform"] == "LinkedIn"]
assert len(linkedin_after) == 2 and not next(v for v in linkedin_after if v["id"] == linkedin["id"]).get("proposedUpdate"), "published LinkedIn variant must not receive an update"
assert next(v for v in linkedin_after if v["id"] != linkedin["id"])["provenance"]["runId"] == follow["runId"]
instagram_after = [v for v in variants if v["platform"] == "Instagram"]
shape = [(v["platform"], v["language"], bool(v.get("proposedUpdate")), (v.get("provenance") or {}).get("runId") == follow["runId"]) for v in variants]
assert len(instagram_after) == 1 and (instagram_after[0].get("proposedUpdate") or {}).get("runId") == follow["runId"], ("an unscheduled draft is refreshed in place", shape, follow["artifact"]["variants"] and [(v["platform"], v["language"]) for v in follow["artifact"]["variants"]])
print("postgres_agent_plan: 7/7 checks passed")
