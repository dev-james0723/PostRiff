"""Agent chat → Automations on the hosted repository: a request for recurring drafts, typed on Home or in a
conversation, becomes an automation through the Automations builder's checks, with Rafii's reply and card as the
conversation. Nothing is drafted, stored as a source or published. An owner's request with a free writer is turned
on; a request from someone who is not an owner waits. With a model allowed to read the request, its reading decides
("twice a week" is an automation, "just a draft" is drafted) and its cost is reserved before and settled after; a
failed reading falls back to the deterministic one.

Run through scripts/postriff_disposable_postgres.py (PYTHONPATH=src:tests).
"""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.learning_model import ModelResponse
from consumer_fixtures import approve_budgets

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TOKEN = "fixture-one"
HK = "Asia/Hong_Kong"
EXAMPLE = "Set up an Automation of drafting me a news article post using my voice and template uploaded here about the topic of AI for Science on every Tuesday"
clock = [time.time()]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != TOKEN:
        raise AlphaError("Verified session required", 401)
    return ONE


def count(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchone()[0]


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s", (wid,))
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
ideas = service.ideas
service.bootstrap(TOKEN, "studio")
approve_budgets(connection, wid)


def state():
    return service.get(wid, TOKEN)["state"]


def command(fn):
    return service.repository.command(wid, TOKEN, service.get(wid, TOKEN)["revision"], fn)


channel = {"id": uuid.uuid4().hex, "platform": "LinkedIn", "account": "Studio page", "accountType": "member", "language": "English", "scopes": ["w_member_social"],
           "verifiedAt": clock[0], "expiresAt": clock[0] + 10**8, "capabilityVersion": 1, "providerAccountId": "urn:test:studio"}
command(lambda s, actor: service.commands.upsert_verified_channel(s, actor, channel))


def add_template(s, actor):
    ideas.commands(s, actor, "source", {"kind": "text", "text": "Template: a headline, three short points, then my view in one line.", "title": "News post template"})
    return s


command(add_template)
template = next(s for s in state()["sources"] if s.get("title") == "News post template")["id"]
DESTINATIONS = [{"platform": "LinkedIn", "language": "en", "channelId": channel["id"]}]


def quick_start(text, **extra):
    body = {"text": text, "confirmUse": True, "ownContent": True, "destinations": DESTINATIONS, "model": "deterministic-preview", "timeZone": HK, "voiceMode": "neutral", **extra}
    return ideas.quick_start(wid, TOKEN, service.get(wid, TOKEN)["revision"], body)


def task_of(view):
    return next(t for t in state()["raffi"]["campaignPlanning"]["recurringTasks"] if t["id"] == view["taskId"])


# 1. Home, deterministic reading (the preview writer never sends the message to a model).
sources_before = len(state()["sources"])
runs_before = count("select count(*) from public.pr_agent_runs where workspace_id=%s", wid)
out = quick_start(EXAMPLE, sourceIds=[template])
assert (out["status"], out["runId"], out["sourceId"]) == ("automation", None, None), out
view = out["automation"]
task = task_of(view)
assert (view["status"], task["status"], task["activatedBy"]) == ("active", "active", ONE), view
assert task["schedule"] == {"weekdays": ["Tuesday"], "localTime": "09:00", "timeZone": HK}, task["schedule"]
assert (task["voiceMode"], task["contextSourceIds"], task["contentType"]["contentTypeId"]) == ("personalized", [template], "pack.creator:article_news_commentary"), task
assert task["destinations"] == DESTINATIONS, task["destinations"]
assert count("select status from public.pr_recurring_tasks where id=%s", task["id"]) == "active"  # the planning tables follow in the same command
assert len(state()["sources"]) == sources_before, "the request is an instruction, not content"
assert count("select count(*) from public.pr_agent_runs where workspace_id=%s", wid) == runs_before, "nothing was drafted"
messages = ideas.messages(wid, TOKEN, out["conversationId"])["messages"]
assert [m["role"] for m in messages] == ["user", "assistant"], messages
assert messages[0]["body"] == {"text": EXAMPLE, "sourceIds": [template], "intent": "automation"}, messages[0]["body"]
assert messages[1]["body"]["automation"]["taskId"] == task["id"] and messages[1]["runId"] is None
assert messages[1]["body"]["text"].startswith("Done. Every Tuesday at 09:00 (Asia/Hong_Kong), I'll prepare a news article post about AI for Science for LinkedIn (Studio page)"), messages[1]["body"]["text"]
assert not state()["phase2"].get("jobs"), "nothing is scheduled or published"

# 2. A follow-up in a conversation is read the same way.
cid = out["conversationId"]
turn = ideas.turn(wid, TOKEN, cid, {"text": "Also every Monday at 8am draft a practice tip about warm-ups", "destinations": DESTINATIONS, "model": "deterministic-preview", "timeZone": HK})
assert turn["status"] == "automation" and turn["automation"]["status"] == "active", turn
tip = task_of(turn["automation"])
assert (tip["schedule"]["weekdays"], tip["schedule"]["localTime"], tip["contentType"]["contentTypeId"], tip["voiceMode"]) == (["Monday"], "08:00", "postriff:teach", "neutral"), tip
assert [m["role"] for m in ideas.messages(wid, TOKEN, cid)["messages"]] == ["user", "assistant", "user", "assistant"]

# 3. Someone who is not an owner: prepared, waiting for an owner.
with connection() as db:
    db.execute("update public.pr_memberships set role='editor' where user_id=%s", (ONE,))
waiting = quick_start("Every Friday draft a post about practice habits")
assert waiting["automation"]["status"] == "draft" and [n["code"] for n in waiting["automation"]["needs"]] == ["owner"], waiting["automation"]
assert "waiting" in waiting["reply"]
with connection() as db:
    db.execute("update public.pr_memberships set role='owner' where user_id=%s", (ONE,))


# 4. A model allowed to read the request decides; its cost is reserved before and settled after.
class Reader:
    local = False
    model = "anthropic/claude-haiku-4.5"

    def __init__(self):
        self.answers, self.prompts = [], []

    def __call__(self, system, user, schema):
        self.prompts.append(json.loads(user.split("\n", 1)[1]))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ModelResponse(answer, 1234)


reader = Reader()
ideas.understanding = reader
reader.answers.append({"action": "automation", "automation": {"weekdays": ["Tuesday", "Friday"], "topic": "AI news", "goal": "A short AI news post with my view.",
                                                              "name": "AI news, twice a week", "contentTypeId": "pack.creator:article_news_commentary", "assumptions": ["Twice a week: Tuesday and Friday."]}})
out = quick_start("Keep my LinkedIn going with AI news twice a week")
assert out["status"] == "automation", out
twice = task_of(out["automation"])
assert (twice["schedule"]["weekdays"], twice["name"]) == (["Tuesday", "Friday"], "AI news, twice a week"), twice
assert "Twice a week: Tuesday and Friday." in out["automation"]["notes"], out["automation"]["notes"]
assert set(reader.prompts[-1]) == {"message", "now", "timeZone", "contentTypes", "formats"}, reader.prompts[-1]  # no sources, memory or accounts
with connection() as db:
    rows = db.execute("select r.id, s.kind, s.actual_usd_micro from public.pr_usage_ledger r join public.pr_usage_ledger s on s.reservation_id=r.id and s.kind<>'reserve' where r.workspace_id=%s and r.provider='understanding' and r.kind='reserve'", (wid,)).fetchall()
assert len(rows) == 1 and rows[0][2] == 1234, rows

# "Just a draft": the model's reading wins over the rules, and the message is drafted now.
reader.answers.append({"action": "draft"})
drafted = quick_start("Every Tuesday I teach a new student; write one post about that today")
assert drafted["status"] != "automation" and drafted["runId"], drafted

# A failed reading never blocks the request: the rules decide and the cost is settled as unknown.
reader.answers.append(RuntimeError("provider down"))
fallback = quick_start("Every Wednesday draft a post about rehearsal tips")
assert fallback["status"] == "automation" and task_of(fallback["automation"])["schedule"]["weekdays"] == ["Wednesday"], fallback
with connection() as db:
    settled = db.execute("select count(*) from public.pr_usage_ledger r where r.workspace_id=%s and r.provider='understanding' and r.kind='reserve' and exists(select 1 from public.pr_usage_ledger s where s.reservation_id=r.id and s.kind<>'reserve')", (wid,)).fetchone()[0]
assert settled == 3, settled
ideas.understanding = None

# A plain request never asks a model and is drafted as before.
plain = quick_start("Write a post about my recital")
assert plain["status"] != "automation" and plain["runId"], plain
# Leave the shared fixture workspace as found for scripts that run after this one.
for leftover in state()["raffi"]["campaignPlanning"]["recurringTasks"]:
    if leftover["status"] != "cancelled":
        service.mutate(wid, TOKEN, service.get(wid, TOKEN)["revision"], "raffi_recurrence_cancel", {"taskId": leftover["id"], "confirmed": True})
print("PASS: Home and conversation requests become automations with the builder's checks and a reply card; nothing drafted, stored or published; "
      "non-owner requests wait; a model reading decides and is metered; a failed reading falls back; plain requests draft as before")
