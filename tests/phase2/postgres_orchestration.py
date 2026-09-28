"""Raffi orchestration end to end on disposable PostgreSQL (orchestration acceptance A–F).

Chat request → structured automation → staged run (research → draft → per-platform posts) → review or standing
approval → queued through the Phase 2 review/approve chain → published by the hosted worker, with every step in the
run's history. Zero network: a fake LinkedIn provider connected through the real OAuth flow, fake research backends,
the fixture writer, and a disposable publishing adapter.

  A  one-time post today at 2 PM, review first: drafted now, approved, published at 14:00 (and a second one that is
     never approved expires unpublished)
  B  Wednesday and Friday 4:30 PM quote post for Xiaohongshu, LinkedIn and X, auto-publish: three platform variants,
     the verified quote, LinkedIn published automatically, X and Xiaohongshu kept as drafts with the reason
  C  weekly BBC reflection: research Wednesday, review notice Thursday morning (not before), publish Saturday 6 PM
  D  conditional skip: nothing worth posting → the run is skipped with the reason, no draft; unreachable source →
     source_unavailable; both explained in chat
  E  "Actually move it to Friday at 6": same automation, the waiting post moves, no duplicate run, task or job
  F  disconnected account: no false success, the post is blocked as "account disconnected" and explained
  plus: model reading with strong/light routing hidden from the person, pause for two weeks / resume / delete in chat.

Run through scripts/postriff_disposable_postgres.py (PYTHONPATH=src:tests).
"""
import datetime as dt
import json
import os
import sys
import zoneinfo
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns, research as web_research
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.campaign_worker import CampaignWorker
from postriff_phase2.contracts import digest
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.source_policy import facts_digest, use_approved
from consumer_fixtures import approve_budgets

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TOKEN = "one"
HK = "Asia/Hong_Kong"
ZONE = zoneinfo.ZoneInfo(HK)


def at(day, hour, minute=0):
    """Epoch of a local Hong Kong time in the week of Monday 28 September 2026 (day 0 = Monday)."""
    return dt.datetime(2026, 9, 28, hour, minute, tzinfo=ZONE).timestamp() + day * 86400


import time
clock = [time.time()]   # the OAuth transaction expires by database time, so connect first, then move to the scenario week
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != TOKEN:
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: "session-orchestration-0123456789"
verify.auth_time = lambda token, principal: clock[0]


class FakeLinkedIn:
    platform = "LinkedIn"
    capability_version = 3
    production_reviewed = True
    native_schedule = False
    assisted_fallback = True

    def capability_scopes(self, capability):
        return {"publish": ["w_member_social", "openid"], "identity": ["openid"]}.get(capability, [])

    def explain(self, capability):
        return "PostRiff will post on your behalf only when you approve an exact post."

    def authorize_url(self, redirect, state, challenge, scopes):
        return f"https://provider.example/auth?redirect_uri={redirect}&state={state}&code_challenge={challenge}"

    def exchange(self, code, verifier, redirect):
        return {"accessToken": "ACCESS-" + code, "refreshToken": "REFRESH-1", "expiresIn": 60 * 86400, "scopes": ["w_member_social", "openid"]}

    def identity(self, access_token):
        return {"providerAccountId": "urn:li:person:studio", "handle": "Studio", "accountType": "member"}

    def inspect_scopes(self, access_token, account):
        return ["openid", "w_member_social"]

    def refresh(self, refresh_token):
        return {"accessToken": "ACCESS-refreshed", "refreshToken": "REFRESH-2", "expiresIn": 60 * 86400}

    def revoke(self, token):
        return True


class Social:
    """Disposable publishing adapter: accepts, then confirms by lookup."""
    def __init__(self):
        self.submitted = []

    def submit(self, manifest):
        self.submitted.append(manifest)
        return {"state": "provider_accepted", "confirmed": "Disposable adapter accepted", "reference": f"post-{len(self.submitted)}"}

    def reconcile(self, manifest, job):
        return {"state": "verified", "confirmed": "Disposable lookup matched", "verification": "disposable_lookup", "reference": job.get("providerReference") or "post-x"}


def page(title, host, days_old, words):
    body = "\n\n".join(f"{words} paragraph {i}: the study describes how {words} changes everyday practice, with measured results and careful caveats from the researchers." for i in range(5))
    published = dt.datetime.fromtimestamp(clock[0] - days_old * 86400, dt.timezone.utc).date().isoformat()
    return {"title": title, "url": f"https://{host}/{abs(hash(title)) % 10**6}", "published": published, "snippet": f"{title}. {words}", "text": f"Title: {title}\n\n{body}"}


class Backends:
    """Fake search/read: `pages` is what the web holds right now; `down` makes every search fail."""
    def __init__(self):
        self.pages, self.down, self.queries = [], False, []

    def search(self, query, limit=6):
        self.queries.append(query)
        if self.down:
            raise OSError("search unreachable")
        return [{k: p[k] for k in ("title", "url", "published", "snippet")} for p in self.pages][:limit]

    def read(self, url):
        found = next((p for p in self.pages if p["url"] == url), None)
        if found is None:
            raise OSError("not found")
        return {"title": found["title"], "text": found["text"]}


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s", (wid,))
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
provider = FakeLinkedIn()
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], vault=CredentialVault(CredentialVault.generate_key()), providers={"linkedin": provider}, public_base_url="https://app.postriff.example")
service.publishing_live = True
backends = Backends()
os.environ["POSTRIFF_RESEARCH"] = "1"      # research is on, but only through the fake backends below (no network)
service.automation_research = backends
service.ideas.researcher = None
class Writer(FixtureAgentRuntime):
    """The fixture writer; with `clean` it answers like a model whose every claim is backed by the given sources
    (no unknowns, no preview banner), which is what an automatic post needs."""
    clean = False

    def start_turn(self, request, emit):
        result = super().start_turn(request, emit)
        if self.clean:
            for variant in result["artifact"]["variants"]:
                variant["unknowns"] = []
                variant["warnings"] = [w for w in variant["warnings"] if "Deterministic writing preview" not in w]
        return result


runtime = Writer()
service.ideas.runtime, service.ideas.runtimes = runtime, [runtime]
service.bootstrap(TOKEN, "studio")
approve_budgets(connection, wid)
ideas = service.ideas
social = Social()
publisher_worker = PostgresWorker(connection, social=social, clock=lambda: clock[0], worker_id="orchestration-worker")
workers = CampaignWorker(service)
started = service.oauth.start(wid, TOKEN, "linkedin", "publish")
oauth_state = parse_qs(urlparse(started["authorizeUrl"]).query)["state"][0]
connected = service.oauth.complete(wid, TOKEN, "linkedin", oauth_state, "good-code")
CHANNEL = connected["connectionId"]
clock[0] = at(0, 10)
DESTINATIONS = [{"platform": "LinkedIn", "language": "en", "channelId": CHANNEL}]
conversation = ideas.create_conversation(wid, TOKEN, "Automations")["conversationId"]


def state():
    return service.get(wid, TOKEN)["state"]


def act(action, payload):
    return service.mutate(wid, TOKEN, service.get(wid, TOKEN)["revision"], action, payload)["state"]


def say(text, cid=None, **extra):
    body = {"text": text, "destinations": DESTINATIONS, "model": runtime.model, "timeZone": HK, "voiceMode": "neutral", **extra}
    return ideas.turn(wid, TOKEN, cid or conversation, body)


def root():
    return state()["raffi"]["campaignPlanning"]


def task(task_id):
    return next(t for t in root()["recurringTasks"] if t["id"] == task_id)


def runs(task_id):
    return [o for o in root()["occurrences"] if o["taskId"] == task_id]


def cron(until=None, step=60):
    """Advance the clock to `until` minute by minute where something is due, running the cron's workers."""
    results = []
    while True:
        publisher_worker.tick()             # the cron route runs the publishing worker first, then automations
        results.append(workers.tick_many())
        if until is None or clock[0] >= until:
            return results
        clock[0] = min(until, clock[0] + step)


def jump(to):
    """Move the clock and run the cron until nothing is left to do at that minute (a long gap leaves missed runs)."""
    clock[0] = to
    for _ in range(12):
        result = cron()[-1]
        if result == {"idle": True}:
            return result
    return result


def decide(occurrence, item, decision, **extra):
    s = state()
    variant = next(v for v in s["variants"] if v["id"] == item["variantId"])
    uses = [{"sourceId": sid, "factsDigest": facts_digest(src)} for sid in variant["sourceIds"]
            for src in [next(x for x in s["sources"] if x["id"] == sid)] if src.get("sourcePolicy") == "rewrite_approval" and not use_approved(src)]
    return act("raffi_run_decide", {"occurrenceId": occurrence["id"], "itemKey": item["key"], "decision": decision, "confirmed": True, "variantRevision": variant["revision"],
                                    "excludedUnknowns": variant["unknowns"], "acknowledgedWarnings": variant.get("warnings") or [], "sourceUse": uses, **extra})


def jobs_for(occurrence_id):
    return [j for j in state()["phase2"]["jobs"] if (j.get("automation") or {}).get("occurrenceId") == occurrence_id]


def denied(call, status=None, code=None):
    try:
        call()
    except AlphaError as error:
        assert status is None or error.status == status, (error.status, str(error))
        assert code is None or getattr(error, "code", None) == code, (getattr(error, "code", None), str(error))
        return str(error)
    raise AssertionError("accepted")


# ---------------------------------------------------------------------------------------------------------------
# A. One-time: "Post an update about my music studio today at 2 PM" — review first.
out = say("Post an update about my music studio today at 2 PM")
card = out["automation"]
assert out["status"] == "automation" and card["pending"]["question"] == "policy", card
assert card["quickReplies"] == ["Publish automatically", "Send them to me for approval first", "Just prepare drafts"], card["quickReplies"]
assert card["schedule"]["kind"] == "once" and card["schedule"]["date"] == "2026-09-28" and card["schedule"]["localTime"] == "14:00", card["schedule"]
assert task(card["taskId"])["status"] == "draft", "nothing runs until the publishing decision is made"
assert "publish these automatically, or send them to you for approval first" in out["reply"], out["reply"]
answer = say("Send them to me for approval first")
card_a = answer["automation"]
assert card_a["taskId"] == card["taskId"] and card_a["status"] == "active" and card_a["policy"] == "review", card_a
assert len([t for t in root()["recurringTasks"] if t.get("intent", "").startswith("Post an update about my music studio")]) == 1, "answering never duplicates"
a = task(card_a["taskId"])
assert a["authorityVersion"] == 3 and a["workflow"]["stages"]["generate"] == {"asap": True} and a["workflow"]["stages"]["publish"] == {"at": "anchor"}, a["workflow"]
assert "Nothing publishes without your approval" in answer["reply"] and "{" not in answer["reply"], answer["reply"]
checks.append("A: a one-time request becomes a staged automation; the only question asked is the publishing policy, answered in the same conversation")
cron()
run_a = runs(a["id"])[0]
assert run_a["lifecycle"] == "drafted" and run_a["state"] == "completed", run_a
item_a = run_a["items"][0]
assert item_a["state"] == "ready_for_review" and item_a["publishAt"] == at(0, 14), item_a
assert not jobs_for(run_a["id"]), "review-required: no job before approval"
assert run_a["notices"].get("reviewSentAt"), "the review notice goes out once drafted (review at generation)"
jump(at(0, 13, 40))
assert not jobs_for(run_a["id"]) and runs(a["id"])[0]["items"][0]["state"] == "ready_for_review", "silence never approves"
decide(run_a, item_a, "approve")
item_a = runs(a["id"])[0]["items"][0]
assert item_a["state"] == "approved" and item_a["approvedVia"] == "human" and item_a["decision"]["by"] == ONE, item_a
cron()
item_a = runs(a["id"])[0]["items"][0]
[job_a] = jobs_for(run_a["id"])
assert item_a["state"] == "scheduled" and item_a["jobId"] == job_a["id"] and job_a["approvedBy"] == ONE and job_a["manifest"]["actor"] == ONE, (item_a, job_a["approvedBy"])
assert job_a["manifest"]["timing"]["local"] == "2026-09-28T14:00" and job_a["automation"]["approvedVia"] == "human", job_a["manifest"]["timing"]
jump(at(0, 14, 1))
jump(at(0, 14, 2))
item_a = runs(a["id"])[0]["items"][0]
assert item_a["state"] == "published", item_a
assert len(social.submitted) == 1
checks.append("A: drafted now, waits for approval (silence never approves), approved, queued through review/approve as the approver, published at 14:00")
why = say("Why did Rafii post this?")
assert why["explain"]["about"] == "why_posted" and any("after you approved it" in line for line in why["explain"]["lines"]), why["explain"]
checks.append("A: “why did Rafii post this?” is answered from the run history")


# A (not approved). A second one-time post that nobody approves never publishes.
say("Post a reminder about the Saturday masterclass tomorrow at 10 AM")
held = say("Send them to me for approval first")["automation"]
cron()
[run_held] = runs(held["taskId"])
assert run_held["items"][0]["state"] == "ready_for_review" and run_held["items"][0]["publishAt"] == at(1, 10), run_held["items"][0]
jump(at(1, 10, 1))
run_held = runs(held["taskId"])[0]
assert run_held["items"][0]["state"] == "approval_expired" and not jobs_for(run_held["id"]), run_held["items"][0]
assert len(social.submitted) == 1, "nothing else was submitted"
denied(lambda: decide(run_held, run_held["items"][0], "approve"), 409)
checks.append("A: a review-required post that is never approved expires at its time, unpublished, and can no longer be approved")
explained = say("Why wasn't the masterclass post published?")
assert any("approval expired" in line.lower() and "not published" in line for line in explained["explain"]["lines"]), explained["explain"]["lines"]
checks.append("A: “why wasn't it published?” names the missing approval")

# ---------------------------------------------------------------------------------------------------------------
# B. Recurring, several days, three platforms, a verified quote, auto-publish.
clock[0] = at(0, 11)
quote = "“The important thing is not to stop questioning. Curiosity has its own reason for existence.” — Albert Einstein"
backends.pages = [
    {**page("Einstein on curiosity", "quotes.example.org", 1, "curiosity"), "text": "Title: Einstein on curiosity\n\n" + "\n\n".join([quote] + [f"Curiosity note {i}: scientists on why questions matter to learning and discovery in daily practice." for i in range(4)])},
    {**page("Great scientists on questions", "physics.example.edu", 2, "questions"), "text": "Title: Great scientists on questions\n\n" + "\n\n".join([quote] + [f"Physics note {i}: the history of questions that changed how science is practised and taught." for i in range(4)])},
]
act("research_egress", {"web": True, "confirmed": True})   # the owner lets PostRiff look things up on the web
b_text = "Every Wednesday and Friday at 4:30 PM, create a motivational quote post using a quote from a famous scientist and publish it to Xiaohongshu, LinkedIn, and X."
b_first = say(b_text)
assert b_first["automation"]["pending"]["question"] == "policy", b_first["automation"]
b = say("Publish automatically")["automation"]
bt = task(b["taskId"])
assert bt["schedule"] == {"weekdays": ["Wednesday", "Friday"], "localTime": "16:30", "timeZone": HK}, bt["schedule"]
assert [d["platform"] for d in bt["destinations"]] == ["Xiaohongshu", "LinkedIn", "X"], bt["destinations"]
assert bt["workflow"]["policy"] == "auto" and bt["publishAuthority"]["grantedBy"] == ONE and bt["publishAuthority"]["sourceUse"] is True, bt.get("publishAuthority")
assert bt["workflow"]["research"]["quote"], bt["workflow"]["research"]
platforms = {p["platform"]: p for p in b["platforms"]}
assert platforms["LinkedIn"]["canPublish"] and not platforms["X"]["canPublish"] and not platforms["Xiaohongshu"]["canPublish"], platforms
b_reply = say  # keep flake-free
# X has a hosted publisher now; with no X adapter mounted in this environment the reason is "not available yet".
assert "Publishing to X isn't available yet" in b["platforms"][2]["reason"] if b["platforms"][2]["platform"] == "X" else True
skills = [step["skill"] for step in b["skills"]]
assert skills[:1] == ["schedule_trigger"] and "quote_verification" in skills and "platform_adaptation" in skills and "auto_publish_check" in skills and "approval_gate" not in skills, skills
checks.append("B: Wednesday+Friday 16:30 for Xiaohongshu, LinkedIn and X; auto-publish granted by the owner in chat; the card says X and Xiaohongshu can't publish; skills composed from the request")
runtime.clean = True
jump(at(2, 16, 30))
cron()
[run_b] = runs(bt["id"])
items_b = {i["platform"]: i for i in run_b["items"]}
assert run_b["lifecycle"] == "drafted" and run_b["research"]["quote"]["verified"] is True, run_b["research"]
assert items_b["X"]["publishAt"] is None and items_b["X"]["state"] == "ready_for_review" and "X" in items_b["X"]["reason"], items_b["X"]
assert items_b["Xiaohongshu"]["publishAt"] is None and items_b["Xiaohongshu"]["state"] == "ready_for_review", items_b["Xiaohongshu"]
variants = {v["id"]: v for v in state()["variants"]}
assert len({variants[i["variantId"]]["text"] for i in run_b["items"]}) == 3, "a version per platform"
assert len(variants[items_b["X"]["variantId"]]["text"]) <= 280, variants[items_b["X"]["variantId"]]["text"]
assert items_b["LinkedIn"]["approvedVia"] == "owner_preauthorization" and items_b["LinkedIn"]["state"] in ("approved", "scheduled"), items_b["LinkedIn"]
cron()
jump(at(2, 16, 34))
jump(at(2, 16, 35))
items_b = {i["platform"]: i for i in runs(bt["id"])[0]["items"]}
[job_b] = jobs_for(run_b["id"])
assert items_b["LinkedIn"]["state"] == "published" and job_b["approvedBy"] == ONE and job_b["automation"]["approvedVia"] == "owner_preauthorization", (items_b["LinkedIn"], job_b["state"])
assert job_b["manifest"]["platform"] == "LinkedIn" and len(social.submitted) == 2
assert not any(j["manifest"]["platform"] in ("X", "Xiaohongshu") for j in state()["phase2"]["jobs"]), "no false publishing"
checks.append("B: three platform versions (X within 280), a quote verified on two sites, LinkedIn published automatically under the owner's standing authority; X and Xiaohongshu stay drafts with the reason")
assert task(bt["id"])["nextOccurrence"]["anchorAt"] == at(4, 16, 30), task(bt["id"])["nextOccurrence"]
checks.append("B: the next run is Friday 16:30")
runtime.clean = False

# ---------------------------------------------------------------------------------------------------------------
# C + E. Weekly BBC reflection: research Wednesday, review Thursday morning, publish Saturday 6 PM; then moved.
clock[0] = at(2, 17)
backends.pages = [page("How music shapes memory, researchers find", "www.bbc.co.uk", 1, "music memory"),
                  page("Markets fall", "www.cnn.com", 0, "markets"), page("Old news on music", "www.bbc.co.uk", 30, "music memory")]
c_text = "Every Thursday, find a notable BBC News article about music, turn it into a personal reflection in my voice, have it ready for me Friday morning, and publish it Sunday at 6 PM."
c = say(c_text)["automation"]
ct = task(c["taskId"])
assert ct["workflow"]["policy"] == "review" and ct["workflow"]["stages"]["review"] == {"weekday": "Friday", "localTime": "09:00"} and ct["workflow"]["stages"]["publish"] == {"weekday": "Sunday", "localTime": "18:00"}, ct["workflow"]["stages"]
assert ct["workflow"]["research"]["domains"] == ["bbc.co.uk", "bbc.com"] and ct["voiceMode"] == "personalized", ct["workflow"]["research"]
assert c["status"] == "active" and not c.get("pending"), c
checks.append("C: generation (Thursday), review (Friday morning) and publication (Sunday 18:00) are separate stages; BBC only; in the person's voice; no question needed")
jump(at(3, 9))
[run_c] = runs(ct["id"])
assert run_c["research"]["chosen"]["host"].endswith("bbc.co.uk") and run_c["stages"]["publishAt"] == at(6, 18) and run_c["stages"]["reviewAt"] == at(4, 9), (run_c["research"], run_c["stages"])
assert all(c_["host"].endswith("bbc.co.uk") for c_ in run_c["research"]["candidates"]), run_c["research"]["candidates"]
item_c = run_c["items"][0]
assert item_c["state"] == "ready_for_review" and not run_c["notices"].get("reviewSentAt"), "the review notice waits for Friday morning"
jump(at(4, 9, 1))
run_c = runs(ct["id"])[0]
assert run_c["notices"].get("reviewSentAt"), run_c["notices"]
checks.append("C: the chosen article is from bbc.co.uk and recent; the review request goes out Friday morning, not when drafted")
tasks_before, runs_before = len(root()["recurringTasks"]), len(root()["occurrences"])
moved = say("Actually move it to Saturday at 6", cid=None)
assert moved["automation"]["taskId"] == ct["id"], moved["automation"]
ct = task(ct["id"])
assert ct["workflow"]["stages"]["publish"] == {"weekday": "Saturday", "localTime": "18:00"} and ct["status"] == "active", (ct["workflow"]["stages"], ct["status"])
run_c = runs(ct["id"])[0]
assert run_c["items"][0]["publishAt"] == at(5, 18) and run_c["items"][0]["state"] == "ready_for_review", run_c["items"][0]
assert len(root()["recurringTasks"]) == tasks_before and len(root()["occurrences"]) == runs_before, "no duplicate automation or run"
assert ct["nextOccurrence"]["anchorAt"] == at(10, 9), ct["nextOccurrence"]
assert "Saturday" in moved["reply"], moved["reply"]
checks.append("E: “Actually move it to Saturday at 6” moves the same automation's publish time and the waiting post with it; no duplicate task, run or post")
decide(run_c, run_c["items"][0], "approve")
jump(at(5, 17, 31))
jump(at(5, 18, 1))
jump(at(5, 18, 2))
run_c = runs(ct["id"])[0]
assert run_c["items"][0]["state"] == "published" and len(jobs_for(run_c["id"])) == 1, run_c["items"][0]
assert jobs_for(run_c["id"])[0]["manifest"]["timing"]["local"] == "2026-10-03T18:00"
source = next(x for x in state()["sources"] if x["id"] == run_c["research"]["sourceId"])
assert source["origin"]["kind"] == "automation_research" and source["origin"]["host"].endswith("bbc.co.uk") and use_approved(source), source["origin"]
where = say("Where did this article come from?")
assert any("bbc.co.uk" in line and "How music shapes memory" in line for line in where["explain"]["lines"]), where["explain"]["lines"]
checks.append("C: approved and published Saturday 18:00 exactly once; the source carries its provenance and “where did this article come from?” is answered")

# ---------------------------------------------------------------------------------------------------------------
# D. Conditional skip and unreachable source.
clock[0] = at(5, 20)
backends.pages = [page("Celebrity gossip roundup", "www.nature.com", 1, "gossip")]
d = say("Every Monday at 9am, find a recent Nature article about sleep research and summarize it for LinkedIn for my approval. Skip the week if there's nothing worth posting.")["automation"]
assert d["pending"]["question"] == "review_time" and "The day before at 17:00" in d["quickReplies"], d
d = say("The day before at 17:00")["automation"]
dt_ = task(d["taskId"])
assert dt_["status"] == "active" and dt_["workflow"]["stages"]["generate"] == {"dayOffset": -1, "localTime": "17:00"}, dt_["workflow"]["stages"]
checks.append("D: approval without a review time → Rafii asks when the drafts should be ready; the quick reply sets drafting the day before at 17:00")
assert dt_["workflow"]["research"]["onNothing"] == "skip" and dt_["workflow"]["research"]["domains"] == ["nature.com"], dt_["workflow"]["research"]
agent_runs = lambda: psycopg.connect(DSN).execute("select count(*) from public.pr_agent_runs where workspace_id=%s", (wid,)).fetchone()[0]
before = agent_runs()
jump(at(6, 17))
[run_d] = runs(dt_["id"])
assert run_d["lifecycle"] == "skipped" and run_d["state"] == "cancelled" and not run_d.get("items"), run_d
assert agent_runs() == before, "no filler draft"
assert "sleep" in run_d["research"]["reason"] or "cleared the bar" in run_d["research"]["reason"], run_d["research"]["reason"]
backends.down = True
jump(at(13, 17))
run_d2 = sorted(runs(dt_["id"]), key=lambda o: o["scheduledFor"])[-1]
assert run_d2["lifecycle"] == "source_unavailable" and run_d2["state"] == "failed", run_d2
backends.down = False
why_not = say("Why wasn't this week's sleep research post published?")
assert why_not["explain"]["about"] == "not_published" and any("Source unavailable" in line or "could not be reached" in line or "couldn't" in line for line in why_not["explain"]["lines"]), why_not["explain"]["lines"]
checks.append("D: nothing worth posting → the week is skipped with the reason and no draft; an unreachable source → source unavailable; both explained")

# ---------------------------------------------------------------------------------------------------------------
# F. Disconnected account: no false success.
clock[0] = at(14, 10)
f = say("Every Tuesday at 3 PM, post a studio tip about scales on LinkedIn and publish automatically.")["automation"]
ft = task(f["taskId"])
assert ft["workflow"]["policy"] == "auto" and ft["status"] == "active", ft["workflow"]
service.oauth.disconnect(wid, TOKEN, CHANNEL)
runtime.clean = True
assert ft["workflow"]["stages"]["generate"] == {"minutesOffset": -60}, ft["workflow"]["stages"]
jump(at(15, 14, 1))
[run_f] = runs(ft["id"])
item_f = run_f["items"][0]
assert item_f["state"] == "platform_disconnected" and not jobs_for(run_f["id"]), item_f
assert "disconnect" in item_f["reason"].lower() or "reconnect" in item_f["reason"].lower(), item_f["reason"]
jump(at(15, 15, 1))
item_f = runs(ft["id"])[0]["items"][0]
assert item_f["state"] == "failed" and "disconnected" in item_f["reason"] and not jobs_for(run_f["id"]), item_f
assert len(social.submitted) == 3, "nothing was submitted for the disconnected account"
f_why = say("Why wasn't the scales post published?")
assert any("disconnected" in line.lower() for line in f_why["explain"]["lines"]), f_why["explain"]["lines"]
card_after = say("Every Friday at 5pm post a practice recap on LinkedIn, publish automatically", destinations=[{"platform": "LinkedIn", "language": "en"}])["automation"]
assert card_after["platforms"][0]["canPublish"] is False and "connect" in card_after["platforms"][0]["reason"].lower(), card_after["platforms"]
checks.append("F: with LinkedIn disconnected the post is blocked as “account disconnected”, never submitted, explained; new automations say it can't publish until reconnected")
runtime.clean = False

# ---------------------------------------------------------------------------------------------------------------
# Conversational control: pause for two weeks, resume, delete by name.
paused = say("Pause the motivational quote automation for two weeks")
bt = task(b["taskId"])
assert bt["status"] == "paused" and abs(bt["pausedUntil"] - (clock[0] + 14 * 86400)) < 1, (bt["status"], bt.get("pausedUntil"))
assert "paused it until" in paused["reply"], paused["reply"]
resumed = say("Resume the motivational quote automation")
assert task(b["taskId"])["status"] == "active", resumed["reply"]
gone = say("Delete the motivational quote automation")
bt = task(b["taskId"])
assert bt["status"] == "cancelled" and bt.get("deletedAt") and runs(bt["id"]), "deleted, history kept"
checks.append("pause for two weeks, resume and delete by name work in chat; a deleted automation keeps its run history")


# ---------------------------------------------------------------------------------------------------------------
# G. An unanticipated request read by the model: several stages, a source limit and a condition go to the strong
# model; the reading builds the workflow; which model read it is recorded but never shown.
from postriff_phase2.learning_model import ModelResponse


class Reader:
    local = False
    model = "anthropic/claude-sonnet-5"

    def __init__(self):
        self.answers, self.prompts = [], []

    def __call__(self, system, user, schema):
        self.prompts.append(json.loads(user.split("\n", 1)[1]))
        return ModelResponse(self.answers.pop(0), 2500)


reader = Reader()
ideas.understanding = reader
clock[0] = at(15, 16)
g_text = ("On the 5th and 20th of each month, pick a recent Gramophone review of a piano album, write my honest take for LinkedIn in my voice, "
          "have it ready the evening before, and publish at 9 AM if I approve.")
reader.answers.append({"action": "automation", "automation": {
    "name": "Gramophone piano take", "topic": "piano album reviews", "goal": "My honest take on a recent Gramophone piano album review.",
    "schedule": {"kind": "monthly", "monthDays": [5, 20], "localTime": "09:00"}, "timeRole": "publish",
    "stages": {"generate": None, "review": {"dayOffset": -1, "localTime": "19:00"}, "publish": None}, "policy": "review",
    "platforms": ["LinkedIn"], "research": {"query": "Gramophone review piano album", "about": "piano album", "domains": ["gramophone.co.uk"], "publications": "Gramophone",
                                            "urls": [], "recencyDays": 14, "onNothing": "skip", "quote": None},
    "content": {"task": "reflection", "instructions": "my honest take"}, "platformNotes": {}, "voice": True, "contentTypeId": None, "formatId": None, "assumptions": []}})
g = say(g_text, destinations=[{"platform": "LinkedIn", "language": "en"}])
gt = task(g["automation"]["taskId"])
assert gt["schedule"] == {"kind": "monthly", "monthDays": [5, 20], "localTime": "09:00", "timeZone": HK}, gt["schedule"]
assert gt["workflow"]["stages"]["generate"] == {"dayOffset": -1, "localTime": "19:00"} and gt["workflow"]["stages"]["review"] == {"at": "generate"}, gt["workflow"]["stages"]
assert gt["workflow"]["research"]["domains"] == ["gramophone.co.uk"] and gt["workflow"]["policy"] == "review" and gt["status"] == "active", gt["workflow"]
last = ideas.messages(wid, TOKEN, conversation)["messages"][-1]
assert last["body"]["understanding"] == "strong", last["body"].get("understanding")
for hidden in ("sonnet", "haiku", "claude", "anthropic", "model"):
    assert hidden not in g["reply"].lower(), g["reply"]
assert "gramophone.co.uk" in json.dumps(reader.prompts[-1]) or "Gramophone" in reader.prompts[-1]["message"]
assert all("channelId" not in json.dumps(item) for item in reader.prompts[-1].get("automations", [])), "no account ids reach the model"
checks.append("G: an unanticipated monthly, sourced, conditional request is read by the strong model into a staged workflow; the model choice is recorded, never shown")
reader.answers.append({"action": "edit", "edit": {"target": {"name": "Gramophone piano take"}, "changes": [{"op": "add_platform", "platform": "Threads"}]}})
added = say("Also share the Gramophone one on Threads", destinations=[{"platform": "LinkedIn", "language": "en"}])
assert [d["platform"] for d in task(gt["id"])["destinations"]] == ["LinkedIn", "Threads"] and task(gt["id"])["id"] == gt["id"], task(gt["id"])["destinations"]
assert ideas.messages(wid, TOKEN, conversation)["messages"][-1]["body"]["understanding"] == "strong"
checks.append("G: a model-read edit adds a platform to the same automation")
ideas.understanding = None

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
