"""Chips on a drafting turn on disposable PostgreSQL (chat-context SPEC §5.10, §6; PLAN S22): the writer request's material
fields, reference notes used only when ready and consented, provenance fencing (no laundering of a local-only source
through a draft), retraction reaching a variant saved from a rework, media and content type through apply and
accept_update, `usage.references` on the free preview route, and an estimate that bounds the run it prices.

Run through scripts/postriff_pg_suite.py (loads rls.sql).
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import media_notes as mn  # noqa: E402
from postriff_phase2.agent_runtime import AgentRuntime  # noqa: E402
from postriff_phase2.agent_runtime_v2.config import RuntimeConfig  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
PHOTO = "0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f10"
OTHER = "9ab1c2d3e4f5061728394a5b6c7d8e9f"
LOCAL_ONLY_TEXT = "Our kiln firing schedule moves to Thursdays after the studio's insurance review.\nMembers can book a shelf from Monday."
FINDINGS = {"description": "A grand piano on a lit stage.", "visibleText": ["Spring Recital"], "composition": ["centered"], "issues": [], "aspect": "4:5",
            "cta": "", "brandFit": [], "confidence": "high"}
clock = [1789524000.0]
passed = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    passed.append(name)


class FakePaidCloud(AgentRuntime):
    """A synchronous paid cloud route that records each writer request (stands in for the gateway)."""
    provider = "fake-cloud"
    provider_class = "cloud"
    cost_class = "paid"
    asynchronous = False
    model = "fake-cloud:model"

    def __init__(self):
        self.requests = []

    def list_supported_models(self):
        return [{"id": self.model, "label": "Fake cloud", "qualified": True, "costClass": self.cost_class, "route": "fake-cloud", "detail": "fake"}]

    def list_supported_reasoning(self):
        return [{"id": "quick", "available": True, "detail": "fake"}]

    def supported_platforms(self):
        return ("LinkedIn", "Instagram", "Threads")

    def price_quote(self, request, model=None):
        return len(json.dumps(request, ensure_ascii=False, sort_keys=True, default=str).encode()) / 1_000_000

    def start_conversation(self, workspace_id, actor):
        return {}

    def start_turn(self, request, emit):
        self.requests.append(json.loads(json.dumps(request, default=str)))
        emit({"type": "run.started", "model": self.model, "reasoning": "quick", "contextDigest": "d"})
        artifact = {"variants": [{"platform": d["platform"], "language": d["language"], "text": f"Cloud draft for {d['platform']}", "sourceIds": [], "unknowns": [], "warnings": [], "candidateOnly": False} for d in request["destinations"]]}
        usage = {"provenance": "fake", "modelRequests": 1, "costUsd": 0}
        emit({"type": "run.completed", "usage": usage})
        return {"artifact": artifact, "usage": usage}


class Transport:
    calls = 0

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.calls += 1
        return {"status": 200, "body": {"output_text": json.dumps(FINDINGS), "usage": {"input_tokens": 1500, "output_tokens": 350}}}


def jpeg():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (1200, 900), (40, 90, 160)).save(out, "JPEG")
    return out.getvalue()


def edit_state(change):
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
        change(state)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s", (json.dumps(state), wid))


def act(action, payload):
    return service.mutate(wid, "one", service.get(wid, "one")["revision"], action, payload)


def run_row(run_id):
    with connection() as db:
        usage, artifact = db.execute("SELECT usage, artifact FROM public.pr_agent_runs WHERE id::text=%s", (run_id,)).fetchone()
    return usage or {}, artifact or {}


def apply(run):
    return ideas.apply(wid, "one", service.get(wid, "one")["revision"], run["runId"], run["artifactHash"])


def variants():
    return service.get(wid, "one")["state"]["variants"]


def cloud_turn(text, **extra):
    return ideas.turn(wid, "one", cid, {"text": text, "model": cloud.model, "timeZone": "Asia/Hong_Kong", **extra})


def unused(run_id, kind, item_id):
    report = run_row(run_id)[0].get("references") or {}
    return next((u for u in report.get("unused", []) if u["kind"] == kind and u["id"] == item_id), None)


def used(run_id, kind, item_id):
    report = run_row(run_id)[0].get("references") or {}
    return next((u for u in report.get("used", []) if u["kind"] == kind and u["id"] == item_id), None)


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

cloud = FakePaidCloud()
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0])
ideas = service.ideas
snap = service.bootstrap("one", "studio")
from consumer_fixtures import approve_budgets  # noqa: E402
approve_budgets(connection, wid)

reader = mn.MediaReader(RuntimeConfig.from_environment({"OPENAI_API_KEY": "sk-test-key-0123456789"}), Transport(), enabled=True)
notes = mn.MediaNotes(ideas, reader, fetch_images=lambda workspace_id, token, asset: [(jpeg(), "image/jpeg")], clock=lambda: clock[0])
ideas.media_notes, ideas.notes_enabled = notes, True


def setup(state):
    state.setdefault("phase2", {}).setdefault("assets", [])
    state["phase2"]["assets"] += [
        {"id": PHOTO, "mime": "image/jpeg", "hash": "h-photo", "processing": "decoded", "deleted": False, "objectName": PHOTO + "-" + "a" * 64 + ".jpg"},
        {"id": OTHER, "mime": "image/jpeg", "hash": "h-other", "processing": "decoded", "deleted": False},
    ]
    state["phase2"].setdefault("channels", []).append({"id": "ch-li", "platform": "LinkedIn", "account": "Studio page", "configured": True, "revoked": False,
                                                        "expiresAt": clock[0] + 86400 * 30, "identityVerified": True, "capabilityVerified": True, "verifiedAt": clock[0]})


def consent(on):
    def change(state):
        state["mediaEgress"] = {"cloud": on, "decidedBy": ONE, "decidedAt": clock[0], "processors": [reader.processor()] if on else [], "scope": ["photo", "video_frames", "photo_edit"]}
    edit_state(change)


edit_state(setup)
act("p2_content_install_pack", {"packId": "pack.creator", "version": "1.0.0"})

# 0. A fixture draft written from a pasted source that is not shared with cloud routes.
quick = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": LOCAL_ONLY_TEXT, "ownContent": True, "confirmUse": True, "destinations": [{"platform": "LinkedIn", "language": "en-US"}]})
apply(quick)
ideas.runtimes = [ideas.runtime, cloud]   # added after the quick start, which would otherwise default to the paid route
source_id = quick["sourceId"]
v1 = next(v for v in variants() if v["platform"] == "LinkedIn")
# The fixture writer cites nothing, so the draft's provenance is its run's recorded source bindings (SPEC §6.2).
check("setup: the draft's run was given the pasted source, which has no cloud consent",
      source_id in [b["id"] for b in run_row(quick["runId"])[1].get("sourceBindings", [])] and "cloud" not in next(s for s in service.get(wid, "one")["state"]["sources"] if s["id"] == source_id)["egressConsent"], v1["sourceIds"])
cid = ideas.create_conversation(wid, "one", "chips")["conversationId"]

# 1. `usage.references` on the synchronous free preview route: a post for ideas is reported unused, never silently dropped.
run = ideas.turn(wid, "one", cid, {"text": "Something new about glazing.", "model": ideas.runtime.model, "references": [{"kind": "post", "id": v1["id"], "role": "inspire"}], "destinations": [{"platform": "Threads", "language": "en-US"}]})
report = run_row(run["runId"])[0].get("references")
check("fixture route: usage.references is written", isinstance(report, dict) and set(report) == {"used", "unused", "reminders"}, report)
check("fixture route: the post is reported free_writer with its copy", (unused(run["runId"], "post", v1["id"]) or {}).get("reason") == "free_writer", report)
check("fixture route: the run summary carries the same report", run_row(run["runId"])[1].get("summary", {}).get("references") == report or run_row(run["runId"])[0].get("references") == report)

# 2. Material fields: handed-in text reaches the writer as `material`, fenced; the idea is only what was typed.
cloud_turn("Make it warmer.", material="HANDED-IN BODY about the spring show.", destinations=[{"platform": "LinkedIn", "language": "en-US"}])
sent = cloud.requests[-1]
check("material: the idea is the typed text only", sent["idea"] == "Make it warmer.", sent["idea"])
check("material: the handed-in text is a material section", [m["role"] for m in sent.get("material", [])] == ["handed_in"] and "HANDED-IN BODY" in sent["material"][0]["text"], sent.get("material"))
check("material: no referenceNotes field without reference media", "referenceNotes" not in sent or sent["referenceNotes"] == [], sent.get("referenceNotes"))

# 3. Laundering: the draft's own source isn't shared with cloud routes, so the draft isn't either.
before = len(cloud.requests)
run = cloud_turn("Ideas for Threads.", references=[{"kind": "post", "id": v1["id"], "role": "inspire"}], destinations=[{"platform": "Threads", "language": "en-US"}])
sent = cloud.requests[-1]
check("laundering: the run still wrote (never blocked)", run["status"] == "completed" and len(cloud.requests) == before + 1, run["status"])
check("laundering: the post is unused with the source reason", (unused(run["runId"], "post", v1["id"]) or {}).get("reason") == "post_source_excluded", run_row(run["runId"])[0].get("references"))
check("laundering: neither the draft nor its source text reaches the gateway", v1["text"] not in json.dumps(sent) and "insurance review" not in json.dumps(sent), sent.get("material"))
check("laundering: no derived source ids on the run", not run_row(run["runId"])[1].get("derivedSourceIds"), run_row(run["runId"])[1].get("derivedSourceIds"))

# 4. Once the owner shares the source with cloud routes, a rework of the draft may use it; the saved variant keeps the
#    source as provenance, so retracting it later blocks that variant too.
act("source_policy", {"sourceId": source_id, "policy": "public_quote", "egressConsent": ["cloud"], "confirmed": True})
run = cloud_turn("Rework this for Threads.", references=[{"kind": "post", "id": v1["id"], "role": "rework"}], destinations=[{"platform": "Threads", "language": "en-US"}])
sent = cloud.requests[-1]
usage, artifact = run_row(run["runId"])
check("rework: the post is used as the rework", (used(run["runId"], "post", v1["id"]) or {}).get("as") == "rework", usage.get("references"))
check("rework: the material is the draft, fenced, as the rework section", sent["material"][0]["role"] == "rework" and "kiln" in sent["material"][0]["text"].lower(), sent.get("material"))
check("rework: derivedSourceIds names the draft's source", artifact.get("derivedSourceIds") == [source_id] and artifact.get("reworkOf") == v1["id"], (artifact.get("derivedSourceIds"), artifact.get("reworkOf")))
check("rework: the source went to the writer as a binding", source_id in [s["id"] for s in sent["context"]["sources"]] if "context" in sent else source_id in json.dumps(sent), list(sent))
apply(run)
saved = next(v for v in variants() if v["platform"] == "Threads" and (v.get("provenance") or {}).get("runId") == run["runId"])
check("rework: a new draft for another platform records derivedFrom and the derived source", saved["provenance"].get("derivedFrom") == v1["id"] and source_id in saved["sourceIds"], (saved["provenance"], saved["sourceIds"]))
act("retract_source", {"sourceId": source_id})
saved = next(v for v in variants() if v["id"] == saved["id"])
check("retraction: blocks the variant saved from the rework", saved["blockedByRetraction"] is True, saved.get("blockedByRetraction"))

# 5. Reference notes are used only when the note is ready and consent is current.
photo_ref = [{"assetId": PHOTO, "role": "reference"}]
run = cloud_turn("A post about this photo.", attachments=photo_ref, destinations=[{"platform": "LinkedIn", "language": "en-US"}])
check("notes: no consent → consent_required, nothing sent", (unused(run["runId"], "image", PHOTO) or {}).get("reason") == "consent_required" and not cloud.requests[-1].get("referenceNotes"), run_row(run["runId"])[0].get("references"))
consent(True)
run = cloud_turn("A post about this photo.", attachments=photo_ref, destinations=[{"platform": "LinkedIn", "language": "en-US"}])
check("notes: consent but no note yet → not_read_yet", (unused(run["runId"], "image", PHOTO) or {}).get("reason") == "not_read_yet" and not cloud.requests[-1].get("referenceNotes"), run_row(run["runId"])[0].get("references"))
read = notes.read(wid, "one", {"assetId": PHOTO, "idempotencyKey": "read-1"})
check("notes: the read is ready", read["status"] == "ready", read)
run = cloud_turn("A post about this photo.", attachments=photo_ref, destinations=[{"platform": "LinkedIn", "language": "en-US"}])
sent = cloud.requests[-1]
check("notes: ready + consent → used as notes", (used(run["runId"], "image", PHOTO) or {}).get("as") == "notes", run_row(run["runId"])[0].get("references"))
check("notes: the note reaches the writer as referenceNotes, not in the idea", "grand piano" in json.dumps(sent.get("referenceNotes")).lower() and "piano" not in sent["idea"].lower(), sent.get("referenceNotes"))
consent(False)
run = cloud_turn("A post about this photo.", attachments=photo_ref, destinations=[{"platform": "LinkedIn", "language": "en-US"}])
check("notes: consent withdrawn → the stored note is not used", (unused(run["runId"], "image", PHOTO) or {}).get("reason") == "consent_required" and not cloud.requests[-1].get("referenceNotes"), run_row(run["runId"])[0].get("references"))

# 6. Media and content type survive apply (as a proposed update of the reworked draft) and accept_update.
run = cloud_turn("Tighten this.", references=[{"kind": "post", "id": v1["id"], "role": "rework"}, {"kind": "template", "id": "pack.creator:tutorial_how_to"}],
                 attachments=[{"assetId": OTHER, "role": "post"}], destinations=[{"platform": "LinkedIn", "language": "en-US"}])
usage, artifact = run_row(run["runId"])
check("media: the run records post media and the template's content type", artifact.get("media") == [{"assetId": OTHER, "kind": "image", "role": "post", "slot": "A"}]
      and (artifact.get("contentType") or {}).get("contentTypeId") == "pack.creator:tutorial_how_to", (artifact.get("media"), artifact.get("contentType")))
check("media: usage.media matches the artifact", usage.get("media") == artifact.get("media"), usage.get("media"))
apply(run)
draft = next(v for v in variants() if v["id"] == v1["id"])
proposal = draft.get("proposedUpdate") or {}
check("apply: the reworked draft gets a proposal carrying media and content type", proposal.get("media") == artifact["media"] and proposal.get("contentTypeId") == "pack.creator:tutorial_how_to", proposal)
act("accept_update", {"variantId": v1["id"]})
draft = next(v for v in variants() if v["id"] == v1["id"])
check("accept_update: media and content type are saved on the draft", draft.get("media") == artifact["media"] and draft.get("contentTypeId") == "pack.creator:tutorial_how_to" and draft.get("proposedUpdate") is None,
      (draft.get("media"), draft.get("contentTypeId")))

# 7. The estimate bounds the run: same body (post, account, reference photo), note ready or not.
consent(True)
for label, asset in (("note ready", PHOTO), ("note not read", OTHER)):
    body = {"text": "Ideas from this post and photo.", "model": cloud.model, "timeZone": "Asia/Hong_Kong",
            "references": [{"kind": "post", "id": v1["id"], "role": "inspire"}, {"kind": "account", "id": "ch-li"}], "attachments": [{"assetId": asset, "role": "reference"}]}
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()[0]
    runtime, model_id, estimated = ideas.estimate_request(state, body, "turn", ONE)
    ideas.turn(wid, "one", cid, body)
    check(f"estimate ≥ run ({label})", cloud.price_quote(estimated) >= cloud.price_quote(cloud.requests[-1]), (cloud.price_quote(estimated), cloud.price_quote(cloud.requests[-1])))
    check(f"the run writes for the account chip ({label})", [d.get("channelId") for d in cloud.requests[-1]["destinations"]] == ["ch-li"], cloud.requests[-1]["destinations"])

# --- S25: the turn entry ------------------------------------------------------------------------------------------------


def user_messages(conversation_id):
    with connection() as db:
        return [row[0] for row in db.execute("SELECT body FROM public.pr_messages WHERE conversation_id::text=%s AND role='user' ORDER BY seq", (conversation_id,)).fetchall()]


def presence_rows(conversation_id):
    with connection() as db:
        return db.execute("SELECT ref->>'assetId' FROM public.pr_attachments WHERE conversation_id::text=%s AND kind='asset' ORDER BY created_at", (conversation_id,)).fetchall()


def add_folder(state):
    state["phase2"].setdefault("channelFolders", []).append({"id": "fold-1", "name": "Studio", "symbol": "folder", "pinned": False, "accountIds": ["ch-li"]})


edit_state(add_folder)
consent(True)
# The paid route has used this plan's writing allowance; the rest runs on the synchronous (subscription) path.
cloud.cost_class = "subscription"
cid2 = ideas.create_conversation(wid, "one", "every kind")["conversationId"]
recital = ideas.quick_start(wid, "one", service.get(wid, "one")["revision"], {"text": "Spring recital on 12 April.\nDoors open at 7pm.", "ownContent": True, "confirmUse": True, "model": ideas.runtime.model,
                                                                               "destinations": [{"platform": "Instagram", "language": "en-US"}]})
apply(recital)
other_source = recital["sourceId"]
v2 = next(v for v in variants() if (v.get("provenance") or {}).get("runId") == recital["runId"])   # v1 is blocked since its source was retracted
act("source_policy", {"sourceId": other_source, "policy": "public_quote", "egressConsent": ["cloud"], "confirmed": True})
UNKNOWN_ASSET = "f" * 32
run = ideas.turn(wid, "one", cid2, {
    "text": "Ideas for the recital.", "model": cloud.model, "timeZone": "Asia/Hong_Kong",
    "references": [{"kind": "post", "id": v2["id"], "role": "inspire", "label": "Client label is dropped"}, {"kind": "template", "id": "pack.creator:tutorial_how_to"},
                   {"kind": "source", "id": other_source}, {"kind": "account", "id": "ch-li"}, {"kind": "folder", "id": "fold-1"}, {"kind": "skill", "id": "skill.x"},
                   {"kind": "post", "id": "no-such-post"}],
    "attachments": [{"assetId": OTHER, "role": "post"}, {"assetId": PHOTO, "role": "reference"}, {"assetId": UNKNOWN_ASSET, "role": "post"}]})
usage, artifact = run_row(run["runId"])
report = usage["references"]
kinds = sorted((u["kind"], u["as"]) for u in report["used"])
check("every kind: a completed run", run["status"] == "completed", run["status"])
check("every kind: post, template, source, account, folder and both media roles used", kinds == sorted([("post", "inspire"), ("template", "template"), ("source", "source"), ("account", "destination"),
                                                                                                     ("folder", "destination"), ("image", "post_media"), ("image", "notes")]), kinds)
check("every kind: a reserved kind and unknown ids are reported, never fatal",
      {(u["kind"], u["reason"]) for u in report["unused"]} == {("skill", "not_available_yet"), ("post", "not_in_workspace"), ("image", "not_in_workspace")}, report["unused"])
check("every kind: no client label anywhere in the report", "Client label is dropped" not in json.dumps(report))
check("every kind: the account chip is the destination", [d.get("channelId") for d in cloud.requests[-1]["destinations"]] == ["ch-li"], cloud.requests[-1]["destinations"])
body = user_messages(cid2)[-1]
check("user message: resolved ids and roles only, unknown ids left out",
      body.get("references") == [{"kind": "post", "id": v2["id"], "role": "inspire"}, {"kind": "template", "id": "pack.creator:tutorial_how_to"}, {"kind": "source", "id": other_source},
                                 {"kind": "account", "id": "ch-li"}, {"kind": "folder", "id": "fold-1"}, {"kind": "skill", "id": "skill.x"}]
      and body.get("attachments") == [{"assetId": OTHER, "role": "post", "slot": "A"}, {"assetId": PHOTO, "role": "reference", "slot": "B"}], body)
check("presence rows: one per known asset, none for the unknown id", sorted(r[0] for r in presence_rows(cid2)) == sorted([OTHER, PHOTO]), presence_rows(cid2))
warnings = [e for e in run["events"] if e["type"] == "warning.created" and e.get("reference")]
check("events: one warning with `reference` per unused item", sorted((w["reference"]["kind"], w["reference"]["reason"]) for w in warnings) == sorted({(u["kind"], u["reason"]) for u in report["unused"]})
      and all(" wasn't used. " in w["message"] for w in warnings), warnings)
ideas.turn(wid, "one", cid2, {"text": "Again with the same photo.", "model": cloud.model, "attachments": [{"assetId": PHOTO, "role": "reference"}]})
check("presence rows: the same asset on the same conversation is recorded once", sorted(r[0] for r in presence_rows(cid2)) == sorted([OTHER, PHOTO]), presence_rows(cid2))

# A foreign workspace's ids (a second tenant) are unknown here: reported, no rows, the run completes.
with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", ("00000000-0000-0000-0000-000000000009",))


def verify_two(token):
    return ONE if token == "one" else "00000000-0000-0000-0000-000000000009"


verify_two.session_id = verify.session_id
verify_two.auth_time = verify.auth_time
service_two = HostedWorkspaceService(connection, verify_two, clock=lambda: clock[0])
snap_two = service_two.bootstrap("two", "studio")
wid_two = snap_two["workspaceId"]
foreign = service_two.ideas.quick_start(wid_two, "two", snap_two["revision"], {"text": "A private note in another workspace.", "ownContent": True, "confirmUse": True})
service_two.ideas.apply(wid_two, "two", service_two.get(wid_two, "two")["revision"], foreign["runId"], foreign["artifactHash"])
foreign_variant = service_two.get(wid_two, "two")["state"]["variants"][0]["id"]
cid3 = ideas.create_conversation(wid, "one", "foreign")["conversationId"]
run = cloud_turn("Use their draft.", references=[{"kind": "post", "id": foreign_variant, "role": "rework"}, {"kind": "source", "id": foreign["sourceId"]}], destinations=[{"platform": "LinkedIn", "language": "en-US"}])
report = run_row(run["runId"])[0]["references"]
check("foreign ids: the run completes and both are not_in_workspace", run["status"] == "completed" and {(u["kind"], u["reason"]) for u in report["unused"]} == {("post", "not_in_workspace"), ("source", "not_in_workspace")}, report)
check("foreign ids: nothing of the other workspace reaches the writer", "private note in another workspace" not in json.dumps(cloud.requests[-1]), cloud.requests[-1].get("material"))

# A forged materialRef is dropped with the one non-enumerating reminder; the turn still drafts.
run = cloud_turn("Rework this.", material="Some pasted words.", materialRef={"type": "draft", "id": foreign_variant, "title": "Theirs"}, destinations=[{"platform": "LinkedIn", "language": "en-US"}])
usage, artifact = run_row(run["runId"])
check("forged materialRef: reminder, no reworkOf, still drafted", "This item is unavailable in this workspace." in usage["references"]["reminders"] and not artifact.get("reworkOf") and run["status"] == "completed",
      (usage["references"], artifact.get("reworkOf")))

# Chips with automation wording draft now, with the reminder, and create no automation.
before = len(((service.get(wid, "one")["state"].get("raffi") or {}).get("campaignPlanning") or {}).get("recurringTasks") or [])
run = cloud_turn("Every Monday at 9am, post a tip like this one.", references=[{"kind": "post", "id": v1["id"], "role": "inspire"}], destinations=[{"platform": "LinkedIn", "language": "en-US"}])
usage, artifact = run_row(run["runId"])
after = len(((service.get(wid, "one")["state"].get("raffi") or {}).get("campaignPlanning") or {}).get("recurringTasks") or [])
check("automation wording + chips: a draft run, the routing reminder, no automation", run["status"] == "completed" and artifact.get("variants") and after == before
      and "This message has attachments, so Rafii wrote a draft. To set up a repeating task or change memory, send it without attachments." in usage["references"]["reminders"], (usage["references"]["reminders"], before, after))

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": passed}, indent=2))
