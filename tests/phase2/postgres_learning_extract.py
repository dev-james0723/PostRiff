"""Phase C1 on the hosted repository: the cron's extraction turns three edits that add a closing call to action
on three channels into one language-level proposal, only owners' edits count until team edits are allowed,
automatic proposals are capped at one a day, events are marked seen, the state is never touched, and
deciding the proposal follows the same path as a chat one.

Run through scripts/postriff_disposable_postgres.py (rls.sql loads migrations 004+, including 010).
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha import learning
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
clock = [time.time()]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "fixture-one":
        raise AlphaError("Verified session required", 401)
    return ONE


def count(sql, *params):
    with connection() as db:
        return db.execute(sql, params).fetchone()[0]


with connection() as db:
    wid = str(db.execute("select workspace_id from public.pr_memberships where user_id=%s", (ONE,)).fetchone()[0])
    db.execute("update public.pr_workspaces set state='{}'::jsonb where id=%s", (wid,))
    db.execute("update public.pr_memberships set status='active', role='owner' where user_id=%s", (ONE,))
    for table in ("pr_memory_versions", "pr_memory_proposals", "pr_learning_events"):
        db.execute(f"delete from public.{table} where workspace_id=%s", (wid,))
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
snapshot = service.bootstrap("fixture-one", "studio")


def act(action, payload):
    global snapshot
    snapshot = service.mutate(wid, "fixture-one", snapshot["revision"], action, payload)
    return snapshot["state"]


def variant(platform):
    return next(v for v in snapshot["state"]["variants"] if v["platform"] == platform)


act("mode", {"mode": "personal"})
act("context", {"purpose": "Make community learning accessible", "audience": "Curious beginners", "subject": "Community workshops", "speaker": "My voice", "layers": []})
act("source", {"kind": "sample"})
source = snapshot["state"]["sources"][-1]
act("approve_source", {"sourceId": source["id"], "factIds": [fact["id"] for fact in source["facts"]]})
act("source_done", {})
act("profile_propose", {"writing": "A small step can be a useful beginning.", "tone": "warm"})
act("profile_decide", {"decision": "approve"})
act("runtime", {"selected": "deterministic-preview"})
for platform in ("LinkedIn", "Threads", "Instagram"):
    act("generate", {"platform": platform, "language": "English"})
    v = variant(platform)
    act("variant_edit", {"variantId": v["id"], "variantRevision": v["revision"], "text": v["text"] + "\n\nDrop a comment below if this helped."})
revision_before = service.get(wid, "fixture-one")["revision"]
assert count("select count(*) from public.pr_learning_events where workspace_id=%s and consumed_by is null", wid) == 3

# 1. Three events are not due yet; a day later they are, and the edits become one language-level proposal.
assert service.learning.sweep()["extraction"]["workspaces"] == 0
clock[0] += 86400 + 1
result = service.learning.sweep()["extraction"]
assert result["workspaces"] == 1 and result["proposed"] == 1, result
pending = service.learning.proposals(service.repository, wid, "fixture-one")["pending"]
assert len(pending) == 1
p = pending[0]
assert (p["ruleKey"], p["polarity"], p["statement"], p["scope"], p["source"], p["op"]) == ("closing.cta", "do", "End with a call to action.", {"platform": None, "language": "en", "contentTypeId": None}, "deterministic", "add"), p
assert len(p["evidence"]) == 3 and "3 of your drafts" in p["why"]
assert count("select count(*) from public.pr_learning_events where workspace_id=%s and consumed_by is null", wid) == 0
assert service.get(wid, "fixture-one")["revision"] == revision_before, "extraction never touches the workspace row"
checks.append("three closing-CTA edits across three channels become one language-level proposal; events marked seen; no state write")

# 2. One automatic proposal a day: a second qualifying pattern waits for tomorrow. (An extra short paragraph in the
#    middle: the fixture drafts already carry "• " bullets, so the bullet lines themselves are not a clean signal.)
for platform in ("LinkedIn", "Threads", "Instagram"):
    snapshot = service.get(wid, "fixture-one")
    v = variant(platform)
    paragraphs = v["text"].split("\n\n")
    paragraphs.insert(1, "- one thing\n- another thing")
    act("variant_edit", {"variantId": v["id"], "variantRevision": v["revision"], "text": "\n\n".join(paragraphs)})
clock[0] += 3600
result = service.learning.sweep()["extraction"]
assert result["proposed"] == 0 and len(service.learning.proposals(service.repository, wid, "fixture-one")["pending"]) == 1, result
clock[0] += 86400
result = service.learning.sweep()["extraction"]
assert result["proposed"] == 1, result
statements = sorted(q["statement"] for q in service.learning.proposals(service.repository, wid, "fixture-one")["pending"])
assert statements == ["End with a call to action.", "Keep paragraphs short."], statements
checks.append("automatic proposals are capped at one a day")

# 3. An editor's edits do not count until the owner allows team edits.
with connection() as db:
    db.execute("delete from public.pr_memory_proposals where workspace_id=%s", (wid,))
    db.execute("update public.pr_learning_events set actor=%s, consumed_by=null where workspace_id=%s", (TWO, wid))
clock[0] += 86400
assert service.learning.sweep()["extraction"]["proposed"] == 0
assert count("select count(*) from public.pr_learning_events where workspace_id=%s and consumed_by is null", wid) == 0, "seen, but not counted"
with connection() as db:
    db.execute("update public.pr_learning_events set consumed_by=null where workspace_id=%s", (wid,))
snapshot = service.get(wid, "fixture-one")
act("learning_settings", {"teamEdits": True})
clock[0] += 86400
assert service.learning.sweep()["extraction"]["proposed"] == 1
checks.append("an editor's edits count only when the owner allows team edits")

# 4. Deciding an extracted proposal follows the chat path: version, style revision, VOICE.md with the evidence summary.
snapshot = service.get(wid, "fixture-one")
p = service.learning.proposals(service.repository, wid, "fixture-one")["pending"][0]
decided = service.learning.decide(service.repository, wid, "fixture-one", snapshot["revision"], p["id"], "remember")
# The strongest pattern here collected two observations per draft (the CTA paragraph also shortened the average paragraph).
assert decided["item"]["evidenceState"] == "observed_in_approved_example" and re.fullmatch(r"from [36] edits", decided["item"]["evidenceSummary"]), decided["item"]
state = service.get(wid, "fixture-one")["state"]
assert state["learning"]["revision"] == 1 and learning.active_items(state)[0]["id"] == p["id"]
checks.append("an extracted proposal is remembered like a chat one, with its evidence summary")


# 5. A model extractor's observations go through the same consolidation; its proposal says so, and it runs only when allowed.
class FakeExtractor:
    def __init__(self, local):
        self.local, self.runs = local, 0

    def observe(self, state, events, now):
        self.runs += 1
        scope = {"platform": "LinkedIn", "language": "English", "contentTypeId": None}
        key = learning.scope_key("writing_preference", "other", "do", scope)
        # Strong enough to outrank the deterministic candidates still waiting for a daily slot.
        return [{"ruleKey": "other", "polarity": "do", "scope": scope, "scopeKey": key, "weight": 2.0, "at": now, "eventId": e["id"], "variantId": f"v-{n}", "value": None, "source": "model", "statement": "Lead with the concrete thing that happened."} for n, e in enumerate(events[:3])]


snapshot = service.get(wid, "fixture-one")
v = variant("LinkedIn")
act("variant_edit", {"variantId": v["id"], "variantRevision": v["revision"], "text": v["text"] + " Again."})
clock[0] += 86400 + 1
cloud = FakeExtractor(local=False)
service.learning.extractor = cloud
result = service.learning.sweep()["extraction"]
assert cloud.runs == 0 and result["modelRuns"] == 0, "a cloud extractor waits for both consents"
with connection() as db:
    db.execute("update public.pr_learning_events set consumed_by=null where workspace_id=%s", (wid,))
snapshot = service.get(wid, "fixture-one")
act("learning_settings", {"cloudExtraction": True})
act("memory_egress", {"cloud": True, "confirmed": True})
clock[0] += 86400 + 1
result = service.learning.sweep()["extraction"]
assert cloud.runs == 1 and result["modelRuns"] == 1 and result["proposed"] == 1, result
# The earlier sweep spent that day's slot on a leftover deterministic candidate; the model's proposal is the newer pending row.
pending = service.learning.proposals(service.repository, wid, "fixture-one")["pending"]
p = next(q for q in pending if q["source"] == "model")
assert (p["ruleKey"], p["statement"], p["scopeLabel"]) == ("other", "Lead with the concrete thing that happened.", "LinkedIn · English"), p
checks.append("a model extractor runs only with both consents and its candidates clear the same bar")

# 5b. A cloud call is money: reserved in the usage ledger before the call (no writing batch consumed), settled after,
# and refused entirely when the workspace stop-line would be crossed; the person's own CLI books nothing.
with connection() as db:
    rows = db.execute("select kind, estimated_usd_micro, actual_usd_micro, charge_batch from public.pr_usage_ledger where workspace_id=%s and provider='learning' order by at, kind", (wid,)).fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [("reserve", 10000, None, False), ("settle", 10000, 10000, False)], rows
    assert db.execute("select spent_usd_micro from public.pr_budgets where scope=%s", (f"workspace:{wid}",)).fetchone()[0] == 10000
    db.execute("update public.pr_budgets set stop_usd_micro=0 where scope=%s", (f"workspace:{wid}",))
    db.execute("update public.pr_learning_events set consumed_by=null where workspace_id=%s", (wid,))
clock[0] += 86400 + 1
result = service.learning.sweep()["extraction"]
assert cloud.runs == 1 and result.get("modelBlocked") == 1 and result["modelRuns"] == 0, result
with connection() as db:
    assert db.execute("select count(*) from public.pr_usage_ledger where workspace_id=%s and provider='learning'", (wid,)).fetchone()[0] == 2, "a refused reservation books nothing"
    db.execute("update public.pr_budgets set stop_usd_micro=%s where scope=%s", (50_000_000, f"workspace:{wid}"))
    db.execute("update public.pr_learning_events set consumed_by=null where workspace_id=%s", (wid,))
local = FakeExtractor(local=True)
service.learning.extractor = local
clock[0] += 86400 + 1
result = service.learning.sweep()["extraction"]
assert local.runs == 1 and result["modelRuns"] == 1, result
with connection() as db:
    assert db.execute("select count(*) from public.pr_usage_ledger where workspace_id=%s and provider='learning'", (wid,)).fetchone()[0] == 2, "the person's own CLI books nothing"
service.learning.extractor = None
checks.append("a cloud model call is reserved and settled in the usage ledger, refused past the stop-line, and free on the person's own CLI")

# 6. Performance: the newest available value per job feeds a like-for-like note (never a proposal by itself).
from postriff_phase2 import learning_extract as extract  # noqa: E402
from postriff_phase2.learning_service import latest_metrics_by_job  # noqa: E402
with connection() as db:
    for n in range(6):
        for observed, value in ((clock[0] - 7200, 5.0), (clock[0] - 60, 10.0 if n < 3 else 20.0)):
            db.execute("insert into public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at) values(%s,'c','threads',%s,%s,'saved','2026-09',%s,'count','available',to_timestamp(%s))",
                       (wid, f"post-{n}", f"job-{n}", value, observed))
        db.execute("insert into public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at) values(%s,'c','threads',%s,%s,'views','2026-09',NULL,'count','unavailable',to_timestamp(%s))",
                   (wid, f"post-{n}", f"job-{n}", clock[0]))
    metrics = latest_metrics_by_job(db.cursor(), wid)
assert metrics["job-0"] == {"saved": 10.0} and metrics["job-5"] == {"saved": 20.0}, metrics
approvals = [{"kind": "draft.approved", "at": clock[0], "subject": {"variantId": f"v{n}", "jobId": f"job-{n}"}, "scope": {"platform": "Threads", "language": "English"}, "features": {"editDistance": 0.1, "approved": {"hashtags": 2 if n < 3 else 0}}} for n in range(6)]
note = extract.performance_note({"ruleKey": "hashtags.use", "polarity": "avoid", "scope": {"platform": "Threads", "language": "English", "contentTypeId": None}}, approvals, metrics)
assert note["direction"] == "supports" and note["withoutFeature"]["mean"] == 20.0, note
checks.append("the newest available metric per job feeds a like-for-like performance note")
print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))

