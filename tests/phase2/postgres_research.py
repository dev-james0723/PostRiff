"""Web research before drafting, on disposable PostgreSQL (agent chat design §11, Phase 5 slice 1):
a topic with no facts triggers research, pages become approved third-party sources with provenance,
the run cites them and warns to verify; first-person ideas, own content and disabled turns skip it;
the same page is never stored twice; a pasted link is read directly.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with migrations 004+005).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import content_types
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [1789524000.0]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]

PAGE = {"title": "Introducing v6 - Suno AI", "url": "https://suno.com/blog/introducing-v6", "host": "suno.com", "published": "2026-09-09",
        "facts": ["Suno introduced v6, a new generation of music models developed with industry partners including Warner Music Group, BMG and Believe.",
                  "v6 comes in three models: v6 for Pro and Premier subscribers, v6-wild for exploration, and v6-mini, a faster version available to everyone."], "fetchedAt": "2026-09-16T10:00:00Z"}
REVIEW = {"title": "Suno v6 review", "url": "https://www.example-news.com/suno-v6-review", "host": "example-news.com", "published": "2026-09-10",
          "facts": ["A hands-on review found v6-wild the most varied of the three models and v6-mini the fastest.", "The review noted that previous models are being retired as v6 rolls out."], "fetchedAt": "2026-09-16T10:00:01Z"}


class FakeResearcher:
    def __init__(self):
        self.calls = []

    def run(self, text, intent="draft"):
        self.calls.append(text)
        if "https://" in text:
            url = next(w for w in text.split() if w.startswith("https://")).rstrip(".")
            return {"query": "", "pages": [{**PAGE, "url": url, "title": "Pasted page", "facts": ["Pasted page paragraph one, distinct from the searched pages so it is stored as its own source.", "Pasted page paragraph two about the same model."]}], "searched": [url], "warnings": [], "elapsed": 0.1}
        return {"query": "the most advanced model of Suno AI", "pages": [PAGE, REVIEW], "searched": [PAGE["url"], REVIEW["url"]], "warnings": ["Could not read x.com (TimeoutError)."], "elapsed": 1.2}


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
fake = FakeResearcher()
service.ideas.researcher = fake
ideas = service.ideas
service.bootstrap("one", "studio")
cid = ideas.create_conversation(wid, "one", "research")["conversationId"]

# 1. A topic with no facts is researched first; pages become approved sources with provenance; the run cites and warns.
run = ideas.turn(wid, "one", cid, {"text": "write a post about the most advanced model of Suno AI", "timeZone": "Asia/Hong_Kong"})
assert run["status"] == "completed", run["status"]
assert fake.calls == ["write a post about the most advanced model of Suno AI"]
state = service.get(wid, "one")["state"]
researched = [s for s in state["sources"] if s.get("origin", {}).get("kind") == "web_research"]
assert [s["origin"]["host"] for s in researched] == ["suno.com", "example-news.com"], [s.get("origin") for s in state["sources"]]
assert all(f["approved"] for s in researched for f in s["facts"]) and all(len(s["facts"]) == 2 for s in researched)
assert all(s["sourcePolicy"] == "rewrite_approval" and "cloud" in s["egressConsent"] for s in researched), "third-party web pages: use needs approval, but they may travel to any route"
assert researched[0]["title"] == "Introducing v6 - Suno AI — suno.com" and researched[0]["origin"]["query"] == "the most advanced model of Suno AI"
kinds = [e["type"] for e in run["events"]]
assert kinds.count("source.added") == 2 and any(e["type"] == "progress.updated" and e.get("stage") == "researched" for e in run["events"]), kinds
assert any(e["type"] == "warning.created" and "Could not read x.com" in e["message"] for e in run["events"])
assert all(any("web research" in w for w in v["warnings"]) for v in run["artifact"]["variants"]), run["artifact"]["variants"][0]["warnings"]
assistant = [m for m in ideas.messages(wid, "one", cid)["messages"] if m["role"] == "assistant"][-1]
assert assistant["body"]["research"]["pages"][0]["url"] == PAGE["url"] and len(assistant["body"]["research"]["sourceIds"]) == 2
assert "2 found on the web" in assistant["body"]["text"], assistant["body"]["text"]
assert len(run["events"][0]) and json.loads(json.dumps(run["usage"]))  # usage is JSON-serialisable

# 2. The same pages are not stored twice; the existing sources are reused for the new run.
again = ideas.turn(wid, "one", cid, {"text": "write a post about the most advanced model of Suno AI", "timeZone": "Asia/Hong_Kong"})
assert len(fake.calls) == 2 and again["status"] == "completed"
state = service.get(wid, "one")["state"]
assert len([s for s in state["sources"] if s.get("origin", {}).get("kind") == "web_research"]) == 2, "no duplicate sources"

# 3. A first-person idea is written from the person's own words; nothing is looked up.
calls_before = len(fake.calls)
own = ideas.turn(wid, "one", cid, {"text": "I keep noticing how much slower I play when I record myself.", "timeZone": "Asia/Hong_Kong", "sourceIds": []})
assert own["status"] == "completed" and len(fake.calls) == calls_before

# 4. Research can be switched off for a turn.
off = ideas.turn(wid, "one", cid, {"text": "write about climate change", "timeZone": "Asia/Hong_Kong", "research": False, "sourceIds": []})
assert off["status"] == "completed" and len(fake.calls) == calls_before

# 5. A pasted link is read directly and its page is the source, even when other facts exist.
linked = ideas.turn(wid, "one", cid, {"text": "Thoughts on https://suno.com/blog/introducing-v6 please", "timeZone": "Asia/Hong_Kong", "sourceIds": []})
assert linked["status"] == "completed" and fake.calls[-1].startswith("Thoughts on https://")
assert any(s["title"].startswith("Pasted page") for s in service.get(wid, "one")["state"]["sources"])

# 6. A quick start with the person's own text has approved facts already, so nothing is looked up.
calls_before = len(fake.calls)
quick = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "Practice was rough today; my left hand kept rushing the coda.", "ownContent": True, "confirmUse": True, "timeZone": "Asia/Hong_Kong"})
assert quick["status"] == "completed" and len(fake.calls) == calls_before

# 6b. The Home composer path: a topic typed as "my own writing" still gets researched (the idea text is not a fact).
calls_before = len(fake.calls)
home = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "write a post about the most advanced model of Suno AI", "ownContent": True, "confirmUse": True, "timeZone": "Asia/Hong_Kong"})
assert home["status"] == "completed" and len(fake.calls) == calls_before + 1, (home["status"], len(fake.calls), calls_before)
assert any(e["type"] == "progress.updated" and e.get("stage") == "researched" for e in home["events"])

# 7. A type that promises the person's own tested method is not satisfied by general web steps.
with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state = jsonb_set(state, '{contentSystem,selection}', '{\"contentTypeId\": \"postriff:teach\", \"contentTypeVersion\": \"1.0.0\", \"formatId\": null, \"pillarIds\": [], \"changedAt\": null}'::jsonb, true) WHERE id=%s", (wid,))
state = service.get(wid, "one")["state"]
if "tested_steps" in content_types.selected_rule_ids(state):
    calls_before = len(fake.calls)
    try:
        ideas.turn(wid, "one", cid, {"text": "write a post about how to use Suno v6", "timeZone": "Asia/Hong_Kong", "sourceIds": []})
    except AlphaError:
        pass
    assert len(fake.calls) == calls_before, "a how-to keeps its own-method promise: no web steps"
    print("postgres_research: 7/7 checks passed")
else:
    print("postgres_research: 6/6 checks passed (tested_steps type unavailable here; check 7 skipped)")
