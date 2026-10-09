"""T11 against disposable PostgreSQL: quiet in-app suggestions and descriptive usage (acceptance A054–A058).

Runs twice in cloud CI (LIBRARY_PG_PHASE=no_vector, then vector); nothing here depends on pgvector. Fake private storage;
no provider or network calls (search runs lexical only). Users are fresh synthetic UUIDs inserted into auth.users.
Covers: the 3-per-day noncritical cap through LibraryIntelligence.tick, a critical warning bypassing the cap while
deduplicated, dismiss/snooze/preferences through the action surface, category disable persisting, recipient-only
changes, unused-relevant recommendations from the real search with diversity, missing approved inputs, debounce and
replay dedup, revocation and deletion suppressing suggestions, idempotent usage recording, metrics from
pr_metric_observations with unknown values kept null, no causal wording, no outbound notification rows, and
cross-workspace isolation.
"""
import json
import os
import re
import sys
import uuid
from pathlib import Path

os.environ["RAFII_LIBRARY_SUGGESTIONS_ENABLED"] = "1"
os.environ["RAFII_LIBRARY_RETRIEVAL_ENABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402
from postriff_phase2.hosted_storage import PrivateAssetService  # noqa: E402
from postriff_phase2.library_intelligence import api, suggestions, usage, versions  # noqa: E402

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
PHASE = os.environ.get("LIBRARY_PG_PHASE", "no_vector")
OWNER = "00000000-0000-0000-0000-0000000000e1"
EDITOR = "00000000-0000-0000-0000-0000000000e2"
VIEWER = "00000000-0000-0000-0000-0000000000e3"
OTHER = "00000000-0000-0000-0000-0000000000e4"
DRAFTER = "00000000-0000-0000-0000-0000000000e5"
TOKENS = {"owner": OWNER, "editor": EDITOR, "viewer": VIEWER, "other": OTHER, "drafter": DRAFTER}
OUTBOUND = ("pr_notifications", "pr_notification_events", "pr_notification_deliveries", "pr_phone_schedules", "pr_trend_outbox")
CAUSAL = re.compile(r"\b(caused?|causes|causing|drove|driven by|led to|leads to|resulted in|results in|thanks to|boost(ed|s)?|because of (this|the) "
                    r"(asset|item|image|photo|file)|made (the|this|your) post)\b", re.I)
clock = [1789524000.0]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in TOKENS:
        raise AlphaError("Verified session required.", 401)
    return TOKENS[token]


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def check(name, condition, detail=""):
    assert condition, f"{name}: {detail}"
    checks.append(name)


class Storage:
    file_bucket = "postriff-library"

    def __init__(self):
        self.objects = {}

    def signed_upload_url(self, ws, category, name):
        return f"https://upload.invalid/{ws}/{name}?token=fake"

    def put(self, ws, name, raw, mime):
        import hashlib
        self.objects[(ws, name)] = (raw, mime, hashlib.sha256(raw).hexdigest()[:24])

    def object_info(self, ws, category, name):
        raw, mime, etag = self.objects[(ws, name)]
        return {"bytes": len(raw), "mime": mime, "etag": etag}

    def get_bounded(self, ws, category, name, limit):
        return self.objects[(ws, name)][0]

    def signed_url(self, ws, category, name, expires_in=300):
        return f"https://download.invalid/{ws}/{name}?token=fake"

    def delete(self, ws, category, name):
        self.objects.pop((ws, name), None)

    def list_prefix(self, prefix, bucket=None):
        return []


def upload(ws, token, name, raw, tags=None):
    ticket = service.library.begin(ws, token, {"filename": name, "mime": "text/markdown", "bytes": len(raw)})["upload"]
    storage.put(ws, ticket["assetId"] + ".md", raw, "text/markdown")
    service.library.commit(ws, token, ticket["assetId"])
    if tags:
        service.library.metadata(ws, token, ticket["assetId"], {"tags": tags})
    return ticket["assetId"]


def route(method, ws, rest, token, body=None):
    return service.library_intelligence.route(method, ws, rest, {}, lambda: body or {}, token)


def act(ws, token, payload):
    envelope = {"actionId": "pg-sugg", "uiInstanceId": "pg-ui", "actionType": "suggestion.set_state", "targetRefs": [], "expectedRevision": None,
                "idempotencyKey": "pg-" + uuid.uuid4().hex, "payload": payload}
    return route("POST", ws, ["actions"], token, envelope)[1]


def evaluate(ws, principal, event):
    with connection() as db, db.cursor() as cur:
        return suggestions.evaluate_suggestions(api.context(cur, principal, ws), event)


def rows(sql, args=()):
    with connection() as db:
        return db.execute(sql, args).fetchall()


def scalar(sql, args=()):
    found = rows(sql, args)
    return found[0][0] if found else None


def outbound_counts():
    counts = {}
    for table in OUTBOUND:
        if scalar("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",)):
            counts[table] = scalar(f"SELECT count(*) FROM public.{table}")
    return counts


def set_state(ws, mutate):
    with connection() as db:
        state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (ws,)).fetchone()[0]
        mutate(state)
        db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), ws))


def reset_debounce(ws):
    with connection() as db:
        db.execute("DELETE FROM public.pr_library_metrics WHERE workspace_id=%s AND feature='library.suggestions'", (ws,))


# --- identities -------------------------------------------------------------------------------------------------------------
with connection() as db:
    for table in ("pr_library_suggestions", "pr_library_suggestion_prefs", "pr_library_usage_events"):
        check(f"schema: {table} exists", db.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is not None)
    for user in TOKENS.values():
        db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (user,))
storage = Storage()
service = HostedWorkspaceService(connection, verify, assets=PrivateAssetService(storage), clock=lambda: clock[0])
w1 = service.bootstrap("owner", "studio")["workspaceId"]
w2 = service.bootstrap("other", "studio")["workspaceId"]
w3 = service.bootstrap("drafter", "studio")["workspaceId"]
for token in ("editor", "viewer"):
    service.bootstrap(token, "studio")
with connection() as db:
    for user, role in ((EDITOR, "editor"), (VIEWER, "viewer")):
        db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,%s,'active') "
                   "ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role,status='active'", (w1, user, role))
outbound_before = outbound_counts()

# --- the daily cap through LibraryIntelligence.tick --------------------------------------------------------------------------
failed = [upload(w1, "owner", f"report-{n}.md", f"Quarterly report {n}".encode()) for n in range(5)]
with connection() as db:
    for key in failed:
        db.execute("INSERT INTO public.pr_library_capabilities(workspace_id,asset_key,capability,state,error_code,retryable) "
                   "VALUES(%s,%s,'extract','failed','library_processing_failed',true) ON CONFLICT(workspace_id,asset_key,capability) "
                   "DO UPDATE SET state='failed'", (w1, key))
tick = service.library_intelligence.tick(connection)
check("tick: suggestions pass ran and reported", tick["suggestions"]["status"] == "ok" and tick["suggestions"]["errors"] == 0, tick)
per_recipient = dict(rows("SELECT recipient::text,count(*) FROM public.pr_library_suggestions WHERE workspace_id=%s AND NOT critical GROUP BY recipient", (w1,)))
check("cap: at most three new noncritical suggestions per recipient per day", per_recipient == {OWNER: 3, EDITOR: 3}, per_recipient)
check("cap: viewers are not recipients of work suggestions", VIEWER not in per_recipient)
status, inbox = route("GET", w1, ["suggestions"], "owner")
check("inbox: cap and in-app delivery reported", status == 200 and inbox["cap"] == {"noncriticalPerDay": 3, "shownToday": 3}
      and inbox["delivery"]["channels"] == ["in_app"] and inbox["delivery"]["external"] is False, inbox)
check("inbox: every suggestion has a reason and affected work", len(inbox["suggestions"]) == 3 and
      all(s["reason"] and s["affected"] and s["category"] == "failed_processing" for s in inbox["suggestions"]), inbox["suggestions"])
warning = {"type": "source_integrity", "assetKey": failed[0], "affected": [{"kind": "draft", "key": "draft-x"}]}
first = evaluate(w1, OWNER, warning)
check("critical: bypasses the cap for every editor", sorted(s["recipient"] for s in first) == sorted([OWNER, EDITOR]), first)
check("critical: still deduplicated", evaluate(w1, OWNER, warning) == [])
check("critical: listed first", route("GET", w1, ["suggestions"], "owner")[1]["suggestions"][0]["critical"] is True)

# --- dismiss, snooze, preferences and recipient-only changes --------------------------------------------------------------------
mine = route("GET", w1, ["suggestions"], "owner")[1]["suggestions"]
noncritical = [s for s in mine if not s["critical"]]
dismissed = act(w1, "owner", {"suggestionId": noncritical[0]["id"], "action": "dismiss"})
check("dismiss: applied", dismissed["status"] == "applied" and dismissed["result"]["suggestion"]["state"] == "dismissed", dismissed)
snoozed = act(w1, "owner", {"suggestionId": noncritical[1]["id"], "action": "snooze"})
days = scalar("SELECT extract(epoch from snooze_until-now())/86400 FROM public.pr_library_suggestions WHERE id=%s", (uuid.UUID(hex=noncritical[1]["id"]),))
check("snooze: seven days by default", snoozed["status"] == "applied" and 6.9 < float(days) < 7.1, (snoozed, days))
act(w1, "owner", {"action": "preferences", "category": "failed_processing", "snoozeDays": 3})
act(w1, "owner", {"suggestionId": noncritical[1]["id"], "action": "snooze"})
days = scalar("SELECT extract(epoch from snooze_until-now())/86400 FROM public.pr_library_suggestions WHERE id=%s", (uuid.UUID(hex=noncritical[1]["id"]),))
check("snooze: the editable default is used", 2.9 < float(days) < 3.1, days)
foreign = act(w1, "editor", {"suggestionId": noncritical[2]["id"], "action": "dismiss"})
check("recipient-only: another member cannot change it", foreign["status"] == "denied", foreign)
reset_debounce(w1)
with connection() as db:
    db.execute("UPDATE public.pr_library_suggestions SET created_at=created_at-interval '2 days' WHERE workspace_id=%s", (w1,))
service.library_intelligence.tick(connection)
identities = rows("SELECT dedup_key,count(*) FROM public.pr_library_suggestions WHERE workspace_id=%s AND recipient=%s GROUP BY dedup_key HAVING count(*)>1",
                  (w1, OWNER))
check("dedup: a dismissed identity is never recreated", identities == [] and
      scalar("SELECT state FROM public.pr_library_suggestions WHERE id=%s", (uuid.UUID(hex=noncritical[0]["id"]),)) == "dismissed", identities)
check("cap: deferred suggestions arrive on a later day", scalar("SELECT count(*) FROM public.pr_library_suggestions WHERE workspace_id=%s AND recipient=%s "
                                                                 "AND category='failed_processing'", (w1, OWNER)) == 5)
disabled = act(w1, "owner", {"suggestionId": noncritical[2]["id"], "action": "disable_category"})
check("disable: applied and persisted", disabled["status"] == "applied" and
      scalar("SELECT disabled FROM public.pr_library_suggestion_prefs WHERE workspace_id=%s AND recipient=%s AND category='failed_processing'",
             (w1, OWNER)) is True, disabled)
check("disable: open suggestions of that category are suppressed", scalar(
    "SELECT count(*) FROM public.pr_library_suggestions WHERE workspace_id=%s AND recipient=%s AND category='failed_processing' AND state IN ('new','seen')",
    (w1, OWNER)) == 0)
status, later = route("GET", w1, ["suggestions"], "owner")
check("disable: survives a new session", later["preferences"]["failed_processing"]["disabled"] is True
      and later["preferences"]["permission"]["canDisable"] is False, later["preferences"])
try:
    act(w1, "owner", {"action": "disable_category", "category": "permission"})
    check("disable: safety warnings cannot be turned off", False)
except AlphaError as error:
    check("disable: safety warnings cannot be turned off", error.status == 400, error)
check("isolation: other workspace has its own empty inbox", route("GET", w2, ["suggestions"], "other")[1]["suggestions"] == [])
check("isolation: a foreign suggestion id is unavailable", act(w2, "other", {"suggestionId": noncritical[2]["id"], "action": "dismiss"})["status"] == "denied")

# --- drafts: missing inputs, unused relevant items with diversity, debounce -----------------------------------------------------------
poster = upload(w3, "drafter", "brahms-poster.md", b"Brahms concert poster for the recital", ["concert"])
hall = upload(w3, "drafter", "hall-photo.md", b"Concert hall photo from the balcony", ["concert"])
programme = upload(w3, "drafter", "programme.md", b"Concert programme: Brahms Op.118")
imported = service.library.as_source(w3, "drafter", programme, {"expectedRevision": scalar("SELECT revision FROM public.pr_workspaces WHERE id=%s", (w3,))})
set_state(w3, lambda state: state.setdefault("variants", []).extend([
    {"id": "draft-1", "platform": "instagram", "language": "en", "text": "Brahms concert tonight #concert", "sourceIds": [imported["sourceId"]], "revision": 1},
    {"id": "draft-2", "platform": "threads", "language": "en", "text": "Another Brahms evening #concert", "sourceIds": [], "revision": 1}]))
created = evaluate(w3, DRAFTER, {"type": "draft_changed", "draftId": "draft-1"})
categories = {s["category"] for s in created}
check("draft: missing approved inputs and a relevant unused item", categories == {"missing_input", "unused_relevant"}, created)
first_pick = next(s for s in created if s["category"] == "unused_relevant")
check("draft: the cited source's own item is not recommended", first_pick["candidateRefs"][0]["versionId"] != programme, first_pick)
check("draft: the reason says what matched", first_pick["why"]["method"] == "lexical" and first_pick["why"]["matchedTerms"], first_pick["why"])
check("debounce: a burst is coalesced", evaluate(w3, DRAFTER, {"type": "draft_changed", "draftId": "draft-1"}) == [])
reset_debounce(w3)
check("dedup: a replay after the window creates nothing", evaluate(w3, DRAFTER, {"type": "draft_changed", "draftId": "draft-1"}) == [])
second = evaluate(w3, DRAFTER, {"type": "draft_changed", "draftId": "draft-2"})
second_pick = next(s for s in second if s["category"] == "unused_relevant")
check("diversity: the same top item is not repeated for the next draft", {first_pick["candidateRefs"][0]["versionId"], second_pick["candidateRefs"][0]["versionId"]}
      == {poster, hall}, (first_pick, second_pick))
for s in created + second:
    check(f"wording: no causal claim in {s['category']}", CAUSAL.search(s["reason"]) is None, s["reason"])

# --- usage: idempotent recording, metrics unknown not zero, no causal claims -------------------------------------------------------------
with connection() as db, db.cursor() as cur:
    recorded = usage.record_usage(cur, w3, poster, poster, "post_published", post_id="ig-77", channel="instagram", dedup_key="publish:ig-77:" + poster,
                                  source={"path": "publish"})
    replay = usage.record_usage(cur, w3, poster, poster, "post_published", post_id="ig-77", channel="instagram", dedup_key="publish:ig-77:" + poster,
                                source={"path": "publish"})
    usage.record_usage(cur, w3, poster, poster, "post_scheduled", post_id="th-78", channel="threads", dedup_key="schedule:th-78:" + poster,
                       source={"path": "schedule"})
    foreign_use = usage.record_usage(cur, w3, failed[0], failed[0], "downloaded", dedup_key="download:" + failed[0], source={})
check("usage: recorded once per dedup key", recorded["recorded"] is True and replay["recorded"] is False, (recorded, replay))
check("usage: another workspace's item is never recorded", foreign_use["recorded"] is False, foreign_use)
with connection() as db:
    for metric, value, availability in (("likes", None, "unavailable"), ("views", 0, "available")):
        db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,"
                   "availability,observed_at) VALUES(%s,'conn-1','instagram','ig-77',NULL,%s,'v1',%s,'count',%s,to_timestamp(1789700000))",
                   (w3, metric, value, availability))
status, used = route("GET", w3, ["assets", poster, "usage"], "drafter")
by_post = {u["postId"]: u for u in used["uses"] if u["source"] == "library_event"}
check("usage: real events with channel and version", status == 200 and set(by_post) == {"ig-77", "th-78"}
      and by_post["ig-77"]["version"]["versionId"] == poster and by_post["ig-77"]["channel"] == "instagram", used)
likes, views = by_post["ig-77"]["metrics"]["likes"], by_post["ig-77"]["metrics"]["views"]
check("metrics: unavailable stays null and unknown", likes["value"] is None and likes["display"] == "unknown" and likes["observedAt"] == 1789700000.0, likes)
check("metrics: a recorded zero stays zero", views["value"] == 0 and views["display"] == "0", views)
check("metrics: a post without readings is unknown, never zero", by_post["th-78"]["metrics"] is None and by_post["th-78"]["metricsStatus"] == "unknown",
      by_post["th-78"])
check("usage: correlation is not causation", "not causation" in used["note"] and CAUSAL.search(json.dumps(used, ensure_ascii=False)) is None, used["note"])
status, cited = route("GET", w3, ["assets", programme, "usage"], "drafter")
check("usage: Ideas drafts citing an imported source are traced", any(u["source"] == "ideas_draft" and u["draftId"] == "draft-1" for u in cited["uses"]),
      cited["uses"])
try:
    route("GET", w3, ["assets", failed[0], "usage"], "drafter")
    check("isolation: foreign usage is unavailable", False)
except AlphaError as error:
    check("isolation: foreign usage is unavailable", error.status == 404, error)

# --- revocation and deletion suppress suggestions -------------------------------------------------------------------------------------
hall_suggestions = scalar("SELECT count(*) FROM public.pr_library_suggestions WHERE workspace_id=%s AND candidate_refs::text LIKE %s AND state='new'",
                          (w3, f"%{hall}%"))
check("revocation: there is an open suggestion about the item", hall_suggestions >= 1, hall_suggestions)
status, granted = route("POST", w3, ["grants"], "drafter", {"grantType": "purpose", "purpose": "answer", "scope": {"kind": "asset", "assetId": hall}})
status, revoked = route("DELETE", w3, ["grants", granted["grantId"]], "drafter", {"expectedRevision": granted["grantRevision"]})
check("revocation: suggestions naming the item are suppressed", scalar(
    "SELECT count(*) FROM public.pr_library_suggestions WHERE workspace_id=%s AND candidate_refs::text LIKE %s AND state='new'", (w3, f"%{hall}%")) == 0
      and revoked["propagation"]["suggestionsSuppressed"] >= 1, revoked)
first_id = next(s["id"] for s in created if s["category"] == "missing_input")
service.library.delete(w3, "drafter", poster)
check("deletion: the inbox leaves out suggestions about a deleted item", all(
    poster not in json.dumps(s["candidateRefs"]) for s in route("GET", w3, ["suggestions"], "drafter")[1]["suggestions"]))
reset_debounce(w3)
service.library_intelligence.tick(connection)
check("deletion: the periodic pass suppresses them", scalar(
    "SELECT count(*) FROM public.pr_library_suggestions WHERE workspace_id=%s AND candidate_refs::text LIKE %s AND state IN ('new','seen','snoozed')",
    (w3, f"%{poster}%")) == 0)
check("deletion: unrelated suggestions stay", scalar("SELECT state FROM public.pr_library_suggestions WHERE id=%s", (uuid.UUID(hex=first_id),)) == "new")

# --- no outbound side effects ------------------------------------------------------------------------------------------------------
check("delivery: no notification, phone schedule or outbox rows were written", outbound_counts() == outbound_before, (outbound_counts(), outbound_before))
check("delivery: external opt-in column exists but stays unused", scalar(
    "SELECT count(*) FROM public.pr_library_suggestion_prefs WHERE external_opt_in") == 0)

print(json.dumps({"status": "pass", "phase": PHASE, "execution": "disposable-local-postgres", "checks": checks}, indent=2, ensure_ascii=False))
