"""Credit-mode photo reads on disposable PostgreSQL (chat-context SPEC §8.2; PLAN S21): a read needs a quote for exactly
that asset, the quote is used once, a limit under the ceiling is refused (402), and a note Rafii already has costs
nothing and needs no quote. All funding is synthetic; the vision provider is a local fake transport.
"""
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import media_notes as mn  # noqa: E402
from postriff_phase2.agent_runtime_v2.config import RuntimeConfig  # noqa: E402
from postriff_phase2.credit_meter import POLICY_VERSION  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from consumer_fixtures import approve_budgets  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
PHOTO = "0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f10"
OTHER = "9ab1c2d3e4f5061728394a5b6c7d8e9f"
FINDINGS = {"description": "A grand piano on a lit stage.", "visibleText": [], "composition": ["centered"], "issues": [], "aspect": "4:5", "cta": "", "brandFit": [], "confidence": "high"}
clock = [time.time()]
passed = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: "notes-credits-session"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


def refused(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return error
    raise AssertionError("accepted")


class Transport:
    calls = 0

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls += 1
        return {"status": 200, "body": {"output_text": json.dumps(FINDINGS), "usage": {"input_tokens": 1500, "output_tokens": 350}}}


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (800, 600), (40, 90, 160)).save(out, "JPEG")
    return out.getvalue()


with connection() as db:
    db.execute((Path(__file__).resolve().parents[2] / "migrations/postriff/020_credit_quotes.sql").read_text())
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], credits_enabled=True)
snap = service.bootstrap("one", "studio")
wid = snap["workspaceId"]
with connection() as db:
    cur = db.cursor()
    service.ledger.ensure_entitlement(cur, wid, None)
    ent = {"writingBatches": 10, "mediaCredits": 1, "members": 1, "connectedAccounts": 3, "storageMb": 200, "creditPolicy": POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('notes-credits','studio',998,'Synthetic credits',0,'active',%s::jsonb)", (json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='notes-credits' WHERE workspace_id=%s", (wid,))
    service.ledger.credits.grant(cur, wid, ONE, "notes-funding", 100000, None)
approve_budgets(connection, wid)

transport = Transport()
reader = mn.MediaReader(RuntimeConfig.from_environment({"OPENAI_API_KEY": "sk-test-key-0123456789"}), transport, enabled=True)
notes = mn.MediaNotes(service.ideas, reader, fetch_images=lambda workspace_id, token, asset: [(jpeg(), "image/jpeg")], clock=lambda: clock[0])
service.ideas.media_notes, service.ideas.notes_enabled = notes, True


def shape(state):
    state.setdefault("phase2", {}).setdefault("assets", [])
    state["phase2"]["assets"] += [{"id": PHOTO, "mime": "image/jpeg", "hash": "h-photo", "processing": "decoded", "deleted": False},
                                  {"id": OTHER, "mime": "image/jpeg", "hash": "h-other", "processing": "decoded", "deleted": False}]
    state["mediaEgress"] = {"cloud": True, "decidedBy": ONE, "decidedAt": clock[0], "processors": [reader.processor()], "scope": ["photo", "video_frames", "photo_edit"]}


with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    shape(state)
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))

credits = service.ideas.credit_requests
revision = lambda: service.get(wid, "one")["revision"]  # noqa: E731
body = {"operation": "media-notes", "request": {"assetId": PHOTO}}

# 1. The estimate names the vision model and the state revision; nothing is read without a quote.
estimate = credits.estimate(wid, "one", body)
check("estimate: photo, one frame, not cached, priced", estimate["kind"] == "photo" and estimate["frames"] == 1 and estimate["cached"] is False and estimate["ceilingMilliCredits"] > 0
      and estimate["stateRevision"] == revision() and estimate["model"] == reader.estimate("photo")["model"], estimate)
refused(lambda: notes.read(wid, "one", {"assetId": PHOTO, "idempotencyKey": "no-quote"}), 402)
check("no quote: 402 and no reader call", transport.calls == 0, transport.calls)

# 2. A limit under the ceiling is refused.
refused(lambda: credits.issue(wid, "one", {**body, "expectedRevision": revision(), "maxMilliCredits": estimate["ceilingMilliCredits"] - 1}), 402)
passed.append("a limit under the ceiling is refused (402)")

# 3. A quote for another asset doesn't authorize this one.
other = credits.issue(wid, "one", {"operation": "media-notes", "request": {"assetId": OTHER}, "expectedRevision": revision(), "maxMilliCredits": estimate["ceilingMilliCredits"]})
refused(lambda: notes.read(wid, "one", {"assetId": PHOTO, "idempotencyKey": "wrong-quote", "creditQuoteId": other["quoteId"]}), 409)
check("a quote for another asset: 409 and no reader call", transport.calls == 0, transport.calls)

# 4. The matching quote reads once; the same quote can't pay for a second read.
quote = credits.issue(wid, "one", {**body, "expectedRevision": revision(), "maxMilliCredits": estimate["ceilingMilliCredits"]})
result = notes.read(wid, "one", {"assetId": PHOTO, "idempotencyKey": "with-quote", "creditQuoteId": quote["quoteId"]})
check("quoted read: ready, one reader call, usage in credits", result["status"] == "ready" and transport.calls == 1 and result["usage"]["milliCredits"] > 0, result)
with connection() as db:
    held = service.ledger.credits.view(db.cursor(), wid)["heldMilliCredits"]
check("quoted read: settled, nothing left held", held == 0, held)
# Single use: OTHER is read with its own quote; after its bytes change (a new hash, so no cached note), the same quote
# can't pay for the second read.
other_estimate = credits.estimate(wid, "one", {"operation": "media-notes", "request": {"assetId": OTHER}})
other_quote = credits.issue(wid, "one", {"operation": "media-notes", "request": {"assetId": OTHER}, "expectedRevision": revision(), "maxMilliCredits": other_estimate["ceilingMilliCredits"]})
check("other asset: read with its own quote", notes.read(wid, "one", {"assetId": OTHER, "idempotencyKey": "other-1", "creditQuoteId": other_quote["quoteId"]})["status"] == "ready" and transport.calls == 2)
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    next(a for a in state["phase2"]["assets"] if a["id"] == OTHER)["hash"] = "h-other-2"
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))
refused(lambda: notes.read(wid, "one", {"assetId": OTHER, "idempotencyKey": "other-2", "creditQuoteId": other_quote["quoteId"]}), 409)
check("a used quote can't pay again", transport.calls == 2, transport.calls)

# 5. A cached note: the estimate says so and costs nothing, no quote is issued or needed, and no reader call happens.
cached = credits.estimate(wid, "one", body)
check("cached: estimate is zero and marked cached", cached["cached"] is True and cached["ceilingMilliCredits"] == 0, cached)
refused(lambda: credits.issue(wid, "one", {**body, "expectedRevision": revision(), "maxMilliCredits": estimate["ceilingMilliCredits"]}), 409)
again = notes.read(wid, "one", {"assetId": PHOTO, "idempotencyKey": "cached"})
check("cached: read without a quote, from the cache", again["status"] == "ready" and again["cached"] is True and transport.calls == 2, again)

# 6. Writing turns keep their own operation; a notes quote can't pay for a draft.
refused(lambda: credits.estimate(wid, "one", {"operation": "media-notes", "request": {"assetId": PHOTO, "text": "extra"}}), 400)
passed.append("a notes request carries the asset id only (400 otherwise)")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": passed}, indent=2))
