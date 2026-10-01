"""Relationship follow-ups through the real service on disposable PostgreSQL (PRD R-REL-01/02).

AC13 thread → assigned reversible follow-up; wrong-tenant thread refs and non-member assignment fail. AC29 revision and
idempotency conflicts and pagination bounds. AC36 tenant isolation and membership revoked mid-flow. Plus: DST-correct
due times, due detection with the reminder identity, dismissal until the due revision changes, snooze/close reversible
and audited, notifications through the existing outbox/planner (reply audience only), Attention with the prior
exchange, and no relationship text in product events, audit, history or notification payloads.

Synthetic only: no provider, model or email traffic. Results are rows of the integrated results slice (migration 080),
read through its real ``results.service.get_declared``."""
import json
import os
import subprocess
import sys
import time
import types
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import flags, runtime
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.relationships import http as rel_http
from postriff_phase2.relationships import jobs
from postriff_phase2.relationships import service as rel

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
MIGRATION = Path(__file__).resolve().parents[2] / "migrations/postriff/081_relationships.sql"
OWNER, EDITOR, VIEWER, OUTSIDER = (str(uuid.uuid4()) for _ in range(4))
NY = ZoneInfo("America/New_York")
offset = [0.0]   # the service clock runs with real time; tests move it forward by an offset


def now():
    return time.time() + offset[0]


checks = []


def connection():
    return psycopg.connect(DSN)


def verify(token):
    if token not in (OWNER, EDITOR, VIEWER, OUTSIDER):
        raise AlphaError("Session required.", 401)
    return token


verify.auth_time = lambda *_: time.time()
verify.session_id = lambda token, _principal: "relationships-session-" + token


def sql(query, *args):
    with connection() as db:
        cur = db.execute(query, args)
        return cur.fetchall() if cur.description else []


def refused(fn, status, code=None):
    try:
        fn()
    except AlphaError as error:
        assert error.status == status, (error.status, error.code, str(error))
        assert code is None or error.code == code, (error.code, str(error))
        return error
    raise AssertionError(f"expected a {status} refusal")


def sunday(year, month, nth):
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7, weeks=nth - 1)


def next_local(month, nth, hour, minute):
    """The next US DST change day (first Sunday of November / second Sunday of March) after now, as a local string."""
    for year in (datetime.now(NY).year, datetime.now(NY).year + 1):
        day = sunday(year, month, nth)
        if datetime(day.year, day.month, day.day, 12, tzinfo=NY).timestamp() > now():
            return f"{day.isoformat()}T{hour:02d}:{minute:02d}"
    raise AssertionError("no DST change found")


flags.attach({rel.FLAG: "1", "RAFII_NOTIFICATIONS_V2_ENABLED": "1"})
hosted = HostedWorkspaceService(connection, verify, clock=now)
runtime.ensure(hosted)   # notifications (outbox + planner) and the coworker (Attention), as the hosted app attaches them
service = rel_http.ensure(hosted)
with connection() as db:
    db.cursor().executemany("INSERT INTO auth.users VALUES(%s)", [(user,) for user in (OWNER, EDITOR, VIEWER, OUTSIDER)])
W = hosted.bootstrap(OWNER, "assist")["workspaceId"]
hosted.bootstrap(EDITOR, "assist")
hosted.bootstrap(VIEWER, "assist")
X = hosted.bootstrap(OUTSIDER, "assist")["workspaceId"]
sql("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections) "
    "VALUES(%s,%s,'editor','active',false,false,false,false),(%s,%s,'viewer','active',false,false,false,false)", W, EDITOR, W, VIEWER)
sql("UPDATE public.pr_profiles SET display_name='Editor Ed' WHERE user_id=%s", EDITOR)


def thread(workspace, comment, body, provider="threads", connection_id="threads-account", author="mei"):
    return sql("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text,permalink) "
               "VALUES(%s,%s,%s,'100',%s,%s,%s,%s) RETURNING id::text", workspace, connection_id, provider, comment, author, body,
               f"https://www.threads.net/@{author}/post/{comment}")[0][0]


T1 = thread(W, "201", "How much is a private lesson?")
T2 = thread(W, "202", "Do you teach on weekends?", provider="instagram", connection_id="ig-account", author="lee")
TX = thread(X, "301", "Outsider's own comment")
sql("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'threads-account','reply','Direct'),(%s,'ig-account','reply','Direct')", W, W)

# --- AC13: a permitted thread becomes an assigned follow-up; replays and conflicting keys -----------------------------------
create = {"idempotencyKey": "rel-create-" + uuid.uuid4().hex[:12], "threadId": T1, "interest": "Private lessons", "nextAction": "Send the autumn schedule"}
created = service.create(W, OWNER, create)
r1 = created["relationship"]
assert created["replayed"] is False and r1["state"] == "new" and r1["displayName"] == "@mei", r1
assert r1["owner"] == {"userId": OWNER, "displayName": r1["owner"]["displayName"], "active": True}
assert r1["threadIds"] == [T1] and [t["threadId"] for t in r1["threads"]] == [T1]
assert r1["contact"] == {"provider": "threads", "accountId": "threads-account", "ref": "mei"}
assert {h["kind"] for h in r1["history"]} == {"created", "thread_linked"}
assert r1["threads"][0]["replyRoute"] == {"kind": "direct", "provider": "threads", "approval": "exact"}
replay = service.create(W, OWNER, create)
assert replay["replayed"] is True and replay["relationship"]["id"] == r1["id"]
refused(lambda: service.create(W, OWNER, {**create, "interest": "Something else"}), 409, "idempotency_conflict")
assert sql("SELECT count(*) FROM public.pr_relationships WHERE workspace_id=%s", W)[0][0] == 1
checks.append("AC13 thread → follow-up assigned to its creator, linked, provider-scoped contact; replay once; conflicting key 409")

refused(lambda: service.create(W, OWNER, {"idempotencyKey": "rel-foreign-thread", "threadId": TX}), 404, "thread_unavailable")
refused(lambda: service.create(W, OWNER, {"idempotencyKey": "rel-unknown-thread", "threadId": str(uuid.uuid4())}), 404, "thread_unavailable")
refused(lambda: service.link_thread(W, OWNER, r1["id"], {"threadId": TX, "expectedRevision": r1["revision"]}), 404, "thread_unavailable")
refused(lambda: service.detail(W, OUTSIDER, r1["id"]), 403)
refused(lambda: service.detail(X, OUTSIDER, r1["id"]), 404, "relationship_not_found")
refused(lambda: service.transition(X, OUTSIDER, r1["id"], {"to": "closed", "expectedRevision": r1["revision"]}), 404, "relationship_not_found")
assert service.list(X, OUTSIDER, {"state": "all"})["relationships"] == []
assert service.list(W, OWNER, {"thread": TX})["relationships"] == []
checks.append("AC13/AC36 wrong-tenant and unknown threads answer the same 404; other workspaces never see or change the record")

refused(lambda: service.assign(W, OWNER, r1["id"], {"ownerId": OUTSIDER, "expectedRevision": r1["revision"]}), 400, "owner_not_member")
refused(lambda: service.assign(W, OWNER, r1["id"], {"ownerId": str(uuid.uuid4()), "expectedRevision": r1["revision"]}), 400, "owner_not_member")
refused(lambda: service.create(W, OWNER, {"idempotencyKey": "rel-bad-owner", "displayName": "X", "ownerId": OUTSIDER}), 400, "owner_not_member")
assigned = service.assign(W, OWNER, r1["id"], {"ownerId": EDITOR, "expectedRevision": r1["revision"]})["relationship"]
assert assigned["owner"] == {"userId": EDITOR, "displayName": "Editor Ed", "active": True} and assigned["revision"] == r1["revision"] + 1
refused(lambda: service.update(W, VIEWER, r1["id"], {"nextAction": "x", "expectedRevision": assigned["revision"]}), 403)
assert service.detail(W, VIEWER, r1["id"])["relationship"]["owner"]["userId"] == EDITOR
checks.append("AC13 non-member assignment refused (400), member assignment recorded; viewers read but cannot edit")

# --- AC29: revision and idempotency conflicts ------------------------------------------------------------------------------
refused(lambda: service.update(W, EDITOR, r1["id"], {"nextAction": "Stale", "expectedRevision": assigned["revision"] - 1}), 409, "revision_conflict")
refused(lambda: service.update(W, EDITOR, r1["id"], {"nextAction": "No revision"}), 400, "revision_required")
change = {"nextAction": "Call after the recital", "expectedRevision": assigned["revision"], "idempotencyKey": "rel-update-0001"}
first = service.update(W, EDITOR, r1["id"], change)
again = service.update(W, EDITOR, r1["id"], change)
assert first["changed"] and again["replayed"] and again["relationship"]["revision"] == first["relationship"]["revision"]
refused(lambda: service.update(W, EDITOR, r1["id"], {**change, "nextAction": "Different"}), 409, "idempotency_conflict")
same = service.update(W, EDITOR, r1["id"], {"nextAction": "Call after the recital", "expectedRevision": first["relationship"]["revision"]})
assert same["changed"] is False and same["relationship"]["revision"] == first["relationship"]["revision"]
checks.append("AC29 stale revision 409, missing revision 400, exact retry replays, reused key with new content 409, no-op keeps the revision")

# --- due, snooze, close: reversible and audited ----------------------------------------------------------------------------


def due_now():
    with connection() as db:
        return {item["id"]: item for item in rel.due_followups(db.cursor(), W, now())}


revision = first["relationship"]["revision"]
due_set = service.update(W, EDITOR, r1["id"], {"due": {"at": now() - 7200, "timeZone": "America/New_York"}, "expectedRevision": revision})["relationship"]
assert due_set["due"]["revision"] == 1 and due_set["followUp"]["status"] == "due" and r1["id"] in due_now()
snoozed = service.snooze(W, EDITOR, r1["id"], {"until": now() + 3600, "expectedRevision": due_set["revision"]})["relationship"]
assert snoozed["followUp"]["status"] == "snoozed" and r1["id"] not in due_now()
unsnoozed = service.unsnooze(W, EDITOR, r1["id"], {"expectedRevision": snoozed["revision"]})["relationship"]
assert unsnoozed["followUp"]["status"] == "due" and r1["id"] in due_now()
closed = service.transition(W, EDITOR, r1["id"], {"to": "closed", "expectedRevision": unsnoozed["revision"]})["relationship"]
assert (closed["state"], closed["previousState"], closed["followUp"]["status"]) == ("closed", "new", "inactive") and r1["id"] not in due_now()
refused(lambda: service.snooze(W, EDITOR, r1["id"], {"until": now() + 60, "expectedRevision": closed["revision"]}), 409, "relationship_closed")
reopened = service.reopen(W, EDITOR, r1["id"], {"expectedRevision": closed["revision"]})["relationship"]
assert (reopened["state"], reopened["previousState"]) == ("new", None) and r1["id"] in due_now()
waiting = service.transition(W, EDITOR, r1["id"], {"to": "waiting", "expectedRevision": reopened["revision"]})["relationship"]
history = {kind for (kind,) in sql("SELECT kind FROM public.pr_relationship_events WHERE relationship_id=%s", r1["id"])}
audits = {kind for (kind,) in sql("SELECT kind FROM public.pr_audit_events WHERE workspace_id=%s AND subject=%s", W, r1["id"])}
for kind in ("created", "thread_linked", "assigned", "updated", "due_changed", "snoozed", "unsnoozed", "closed", "reopened", "state"):
    assert kind in history and f"relationship.{kind}" in audits, kind
outcomes = {(p["state"], p["previous"]) for (p,) in sql("SELECT properties FROM public.pr_product_events WHERE workspace_id=%s AND event='relationship.followup_outcome'", W)}
assert {("closed", "new"), ("new", "closed"), ("waiting", "new")} <= outcomes, outcomes
checks.append("snooze/unsnooze and close/reopen reversible, each in history + audit; outcomes as content-free product events")

# --- won needs a declared result (results slice stand-in) ------------------------------------------------------------------
refused(lambda: service.transition(W, EDITOR, r1["id"], {"to": "won", "wonResultId": str(uuid.uuid4()), "expectedRevision": waiting["revision"]}), 400, "result_required")
# The real results slice (migration 080 + results.service.get_declared) is integrated: declare results as rows of it.


def declared(workspace):
    return sql("INSERT INTO public.pr_result_events(workspace_id,provenance,result_type,provider_event_id,occurred_at,payload_digest,declared_by) "
               "VALUES(%s,'user_declared','lead',%s,now(),%s,(SELECT user_id FROM public.pr_memberships WHERE workspace_id=%s AND role='owner' LIMIT 1)) RETURNING id::text",
               workspace, "decl_" + uuid.uuid4().hex, "a" * 64, workspace)[0][0]


refused(lambda: service.transition(W, EDITOR, r1["id"], {"to": "won", "wonResultId": str(uuid.uuid4()), "expectedRevision": waiting["revision"]}), 400, "result_required")
mine = declared(W)
theirs = declared(X)
refused(lambda: service.transition(W, EDITOR, r1["id"], {"to": "won", "wonResultId": theirs, "expectedRevision": waiting["revision"]}), 400, "result_required")
refused(lambda: service.transition(W, EDITOR, r1["id"], {"to": "won", "expectedRevision": waiting["revision"]}), 400, "result_required")
won = service.transition(W, EDITOR, r1["id"], {"to": "won", "wonResultId": mine, "expectedRevision": waiting["revision"]})["relationship"]
assert (won["state"], won["won"], won["previousState"], won["followUp"]["status"]) == ("won", {"resultId": mine, "provenance": "user_declared"}, "waiting", "inactive")
undone = service.reopen(W, EDITOR, r1["id"], {"expectedRevision": won["revision"]})["relationship"]
assert (undone["state"], undone["won"]) == ("waiting", None)
won_meta = sql("SELECT meta FROM public.pr_relationship_events WHERE relationship_id=%s AND to_state='won'", r1["id"])[0][0]
assert won_meta["resultId"] == mine and won_meta["provenance"] == "user_declared"
checks.append("won refused without a declared same-workspace result; keeps the result id and provenance; reopen undoes it")

# --- DST-correct due times -------------------------------------------------------------------------------------------------
repeated = next_local(11, 1, 1, 30)
manual = service.create(W, OWNER, {"idempotencyKey": "rel-manual-0001", "displayName": "Studio parent (WhatsApp)",
                                   "contact": {"provider": "whatsapp", "ref": "parent-ref-77"},
                                   "due": {"local": repeated, "timeZone": "America/New_York", "fold": 1}})["relationship"]
first_occurrence = datetime.fromisoformat(repeated).replace(tzinfo=NY, fold=0).timestamp()
assert manual["due"]["at"] == first_occurrence + 3600 and manual["due"]["local"] == repeated[:16] and manual["due"]["fold"] == 1
assert manual["due"]["offset"] == "-0500" and manual["replyRoute"] == {"kind": "assisted", "provider": "whatsapp", "href": None, "reason": "no_thread"}
refused(lambda: service.update(W, OWNER, manual["id"], {"due": {"local": repeated, "timeZone": "America/New_York"}, "expectedRevision": manual["revision"]}), 400, "due_time_ambiguous")
refused(lambda: service.update(W, OWNER, manual["id"], {"due": {"local": next_local(3, 2, 2, 30), "timeZone": "America/New_York"},
                                                         "expectedRevision": manual["revision"]}), 400, "due_time_nonexistent")
checks.append("DST: a repeated local time stores the chosen occurrence (fold 1 = EST), a nonexistent one is refused, both read back exactly")

# --- reminders: detection, notifications, dismissal, cosmetic edits ---------------------------------------------------------


def follow_up_events():
    return sql("SELECT dedupe_key,payload FROM public.pr_notification_events WHERE workspace_id=%s AND event_type='relationship.follow_up_due' ORDER BY created_at,id", W)


offset[0] = manual["due"]["at"] + 60 - time.time()   # just after the repeated hour's second 01:30
due = due_now()
assert set(due) == {r1["id"], manual["id"]}
assert due[manual["id"]]["dedupeKey"] == f"relationship.follow_up_due:{manual['id']}:1:{int(manual['due']['at'])}" and due[manual["id"]]["threadId"] is None
assert due[r1["id"]]["threadId"] == T1
tick = jobs.tick(hosted, time.monotonic() + 15)
assert tick == {"status": "ok", "scanned": 2, "emitted": 2}, tick
assert jobs.tick(hosted, time.monotonic() + 15) == {"status": "ok", "scanned": 0, "emitted": 0}
events = follow_up_events()
assert {key for key, _ in events} == {item["dedupeKey"] for item in due.values()}
assert all(set(payload) == {"reason", "href"} and payload["href"].startswith("/app/inbox?filter=follow_ups&relationship=") for _, payload in events)   # no English title: the digest localizes
stored_links = {payload["href"] for _, payload in events}   # as stored by the outbox (after its phone-number redaction)
assert stored_links == {f"/app/inbox?filter=follow_ups&relationship={rel.link_id(rid)}" + (f"&thread={rel.link_id(item['threadId'])}" if item["threadId"] else "")
                        for rid, item in due.items()}, stored_links
recipients = {user for (user,) in sql("SELECT DISTINCT d.user_id::text FROM public.pr_notification_deliveries d JOIN public.pr_notification_events e ON e.id=d.event_id "
                                      "WHERE e.event_type='relationship.follow_up_due' AND e.workspace_id=%s", W)}
assert recipients == {OWNER}, recipients   # audience 'reply': the editor and viewer without reply rights get nothing
cosmetic = service.update(W, OWNER, manual["id"], {"nextAction": "Ask about the trial lesson", "displayName": "Studio parent", "expectedRevision": manual["revision"]})["relationship"]
assert due_now()[manual["id"]]["dedupeKey"] == due[manual["id"]]["dedupeKey"]
assert jobs.tick(hosted, time.monotonic() + 15)["emitted"] == 0 and len(follow_up_events()) == 2
with connection() as db:
    state = db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (W,)).fetchone()[0]
    scan = hosted.notifications.scan(db.cursor(), W, state)
assert len(follow_up_events()) == 2, scan   # the detector path agrees with the job on the reminder identity
checks.append("due follow-ups emitted once per reminder through the outbox (reply audience only); cosmetic edits and the detector rescan never re-alert")

dismissed = service.dismiss_followup(W, OWNER, manual["id"], {"expectedRevision": cosmetic["revision"]})["relationship"]
assert dismissed["followUp"]["status"] == "dismissed" and manual["id"] not in due_now()
restored = service.restore_followup(W, OWNER, manual["id"], {"expectedRevision": dismissed["revision"]})["relationship"]
assert restored["followUp"]["status"] == "due" and manual["id"] in due_now()
dismissed = service.dismiss_followup(W, OWNER, manual["id"], {"expectedRevision": restored["revision"]})["relationship"]
refused(lambda: service.dismiss_followup(W, OWNER, manual["id"], {"expectedRevision": dismissed["revision"]}), 409, "followup_not_due")
assert jobs.tick(hosted, time.monotonic() + 15)["emitted"] == 0
moved = service.update(W, OWNER, manual["id"], {"due": {"at": now() - 30, "timeZone": "Asia/Hong_Kong"}, "expectedRevision": dismissed["revision"]})["relationship"]
assert moved["due"]["revision"] == 2 and moved["followUp"]["status"] == "due" and manual["id"] in due_now()
assert jobs.tick(hosted, time.monotonic() + 15)["emitted"] == 1 and len(follow_up_events()) == 3
checks.append("dismiss as irrelevant suppresses until the due revision changes; undo restores it; a new due time alerts once")

snooze_again = service.snooze(W, EDITOR, r1["id"], {"until": now() + 3600, "expectedRevision": undone["revision"]})["relationship"]
assert r1["id"] not in due_now() and jobs.tick(hosted, time.monotonic() + 15)["emitted"] == 0
offset[0] += 2 * 3600
assert due_now()[r1["id"]]["dedupeKey"].endswith(f":{int(snooze_again['snoozedUntil'])}")
assert jobs.tick(hosted, time.monotonic() + 15)["emitted"] == 1 and len(follow_up_events()) == 4
checks.append("the end of a snooze is a new reminder (one alert); a snoozed follow-up stays quiet")

# --- Attention: prior exchange, reason, one action; reply audience only ------------------------------------------------------
attention = hosted.coworker.attention(W, OWNER)
item = next(i for i in attention["items"] if i["type"] == "relationship.follow_up_due" and i["evidence"]["entityId"] == r1["id"])
assert item["urgent"] is False and item["priority"] == 65 and item["title"] == "Follow up with @mei"
assert item["href"] == f"/app/inbox?filter=follow_ups&relationship=u{r1['id'].replace('-', '')}&thread=u{T1.replace('-', '')}"
context = item["context"]
assert context["exchange"][0] == {"direction": "inbound", "author": "mei", "provider": "threads", "excerpt": "How much is a private lesson?",
                                  "at": context["exchange"][0]["at"]}
assert context["replyRoute"]["kind"] == "direct" and context["revision"] == snooze_again["revision"] and context["due"]["timeZone"] == "America/New_York"
assert not [i for i in hosted.coworker.attention(W, EDITOR)["items"] if i["type"] == "relationship.follow_up_due"]
checks.append("Attention: never urgent, between engagement and learning, prior exchange + reason + Inbox action, hidden from members who can't reply")

# --- links, notes, suggestions, AC15 assisted channel --------------------------------------------------------------------------
current = service.detail(W, OWNER, r1["id"])["relationship"]
linked = service.link_thread(W, OWNER, r1["id"], {"threadId": T2, "expectedRevision": current["revision"]})["relationship"]
instagram = next(t for t in linked["threads"] if t["threadId"] == T2)
assert instagram["replyRoute"]["kind"] == "assisted" and instagram["replyRoute"]["reason"] == "unsupported_provider"   # AC15
unlinked = service.unlink_thread(W, OWNER, r1["id"], T2, {"expectedRevision": linked["revision"]})["relationship"]
assert unlinked["threadIds"] == [T1]
refused(lambda: service.unlink_thread(W, OWNER, r1["id"], T2, {"expectedRevision": unlinked["revision"]}), 404, "thread_unavailable")
noted = service.add_note(W, OWNER, r1["id"], {"text": "Prefers Saturday mornings.\nAsked twice.", "expectedRevision": unlinked["revision"]})["relationship"]
assert noted["notes"][0]["text"] == "Prefers Saturday mornings.\nAsked twice." and noted["noteCount"] == 1
removed = service.remove_note(W, OWNER, r1["id"], noted["notes"][0]["id"], {"expectedRevision": noted["revision"]})["relationship"]
assert removed["notes"] == []
revision = removed["revision"]
for index in range(rel.MAX_NOTES):
    revision = service.add_note(W, OWNER, r1["id"], {"text": f"n{index}", "expectedRevision": revision})["relationship"]["revision"]
refused(lambda: service.add_note(W, OWNER, r1["id"], {"text": "one too many", "expectedRevision": revision}), 409, "notes_full")
refused(lambda: service.add_note(W, OWNER, r1["id"], {"text": "x" * 501, "expectedRevision": revision}), 400)
detail = service.detail(W, OWNER, r1["id"])["relationship"]
assert detail["suggestion"]["state"] == "follow_up_due" and detail["suggestion"]["reason"] == "due_passed"
quiet = service.dismiss_suggestion(W, OWNER, r1["id"], {"key": detail["suggestion"]["key"], "expectedRevision": detail["revision"]})["relationship"]
assert quiet["suggestion"] is None and quiet["state"] == "waiting"   # never applied by itself
refused(lambda: service.dismiss_suggestion(W, OWNER, r1["id"], {"key": "stale", "expectedRevision": quiet["revision"]}), 409, "suggestion_changed")
checks.append("AC15 a Direct-level Instagram link is still assisted; link/unlink, bounded notes; suggestions never apply themselves and can be dismissed")

# --- AC29 pagination (default 25, max 50, deterministic due-first order) ---------------------------------------------------------
for index in range(30):
    due_field = {"due": {"at": now() + (index % 7) * 3600, "timeZone": "UTC"}} if index % 3 else {}
    service.create(W, OWNER, {"idempotencyKey": f"rel-page-{index:04d}", "displayName": f"Lead {index}", **due_field})
page = service.list(W, VIEWER)
assert len(page["relationships"]) == 25 and page["nextCursor"]
rest = service.list(W, VIEWER, {"cursor": page["nextCursor"]})
assert rest["nextCursor"] is None
seen = [r["id"] for r in page["relationships"] + rest["relationships"]]
expected = [rid for (rid,) in sql("SELECT id::text FROM public.pr_relationships WHERE workspace_id=%s AND state NOT IN ('won','closed') "
                                  "ORDER BY due_at ASC NULLS LAST,created_at DESC,id DESC", W)]
assert seen == expected and len(seen) == len(set(seen)) == 32, (len(seen), len(expected))
small = service.list(W, VIEWER, {"limit": "7"})
walked, cursor = [], None
while True:
    chunk = service.list(W, VIEWER, {"limit": "7", **({"cursor": cursor} if cursor else {})})
    walked += [r["id"] for r in chunk["relationships"]]
    cursor = chunk["nextCursor"]
    if not cursor:
        break
assert walked == expected and len(small["relationships"]) == 7
assert len(service.list(W, VIEWER, {"limit": "50"})["relationships"]) == 32
for bad in ({"limit": "51"}, {"limit": "0"}, {"cursor": "not-a-cursor"}, {"state": "bought"}, {"due": "soon"}):
    refused(lambda: service.list(W, VIEWER, bad), 400)
counts = service.list(W, VIEWER, {"due": "due_now"})
assert counts["counts"]["dueNow"] == len(counts["relationships"]) == len(due_now())
checks.append("AC29 pagination: 25 default, 50 max, cursor walks match the deterministic SQL order with no gaps or repeats; bad filters 400")

# --- AC36 membership revoked mid-flow ---------------------------------------------------------------------------------------------
editor_view = service.detail(W, EDITOR, r1["id"])["relationship"]
sql("UPDATE public.pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", W, EDITOR)
refused(lambda: service.update(W, EDITOR, r1["id"], {"nextAction": "after revocation", "expectedRevision": editor_view["revision"]}), 403)
refused(lambda: service.list(W, EDITOR), 403)
owner_view = service.detail(W, OWNER, r1["id"])["relationship"]
assert owner_view["owner"] == {"userId": EDITOR, "displayName": "", "active": False}
refused(lambda: service.assign(W, OWNER, r1["id"], {"ownerId": EDITOR, "expectedRevision": owner_view["revision"]}), 400, "owner_not_member")
service.assign(W, OWNER, r1["id"], {"ownerId": None, "expectedRevision": owner_view["revision"]})
checks.append("AC36 a member revoked mid-flow is refused at the next request, shown as a former owner and cannot be re-assigned")

# --- no relationship text outside the relationship record ---------------------------------------------------------------------------
private = ["Private lessons", "Send the autumn schedule", "Call after the recital", "Studio parent", "parent-ref-77", "Prefers Saturday",
           "How much is a private lesson", "@mei", "Ask about the trial lesson", "Lead 1"]
blobs = (sql("SELECT properties::text FROM public.pr_product_events WHERE workspace_id=%s", W)
         + sql("SELECT subject||' '||meta::text FROM public.pr_audit_events WHERE workspace_id=%s", W)
         + sql("SELECT meta::text FROM public.pr_relationship_events WHERE workspace_id=%s", W)
         + sql("SELECT payload::text FROM public.pr_notification_events WHERE workspace_id=%s", W))
assert blobs and not [(text, blob) for (blob,) in blobs for text in private if text in blob]
checks.append("no names, notes, interests, next actions, contact refs or comment text in product events, audit, history or notification payloads")

# --- flag off: no new work, nothing alerts ----------------------------------------------------------------------------------------
flags.attach({"RAFII_NOTIFICATIONS_V2_ENABLED": "1"})
refused(lambda: service.list(W, OWNER), 404, "feature_disabled")
assert jobs.tick(hosted, time.monotonic() + 5) == {"status": "disabled"}
assert not [i for i in hosted.coworker.attention(W, OWNER)["items"] if i["type"] == "relationship.follow_up_due"]
assert sql("SELECT count(*) FROM public.pr_relationships WHERE workspace_id=%s", W)[0][0] == 32   # records are kept
checks.append("flag off: routes 404 feature_disabled, no reminders or Attention items, records kept")

print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL; synthetic threads; integrated results slice; no provider/model/email traffic", "checks": checks}))
