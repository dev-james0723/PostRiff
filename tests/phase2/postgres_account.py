"""Profile-page account surface on disposable PostgreSQL: workspace summary, cross-workspace
channels, second-factor enforcement, revoke-others, leaving a workspace.

Run through scripts/postriff_disposable_postgres.py (loads rls.sql with migrations 001-009).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
SIX = "00000000-0000-0000-0000-000000000006"
START = time.time()
clock = [START]


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    who = token.split("-")[0]
    if who not in ("one", "six"):
        raise AlphaError("Verified session required.", 401)
    return ONE if who == "one" else SIX


# "one" and "one-aal2" share a session; "one-<device>" is a fresh session on another device.
verify.session_id = lambda token, principal: f"session-{token.split('-aal2')[0]}-0123456789abcdef"
verify.auth_time = lambda token, principal: START  # sign-in time stays put while the clock advances
verify.aal = lambda token, principal: "aal2" if token.endswith("-aal2") else "aal1"
checks = []


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError("accepted")


with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (SIX,))

EMAILS = {ONE: "one@example.invalid", SIX: "six@example.invalid"}
# The default mailer records instead of sending; the base URL lets alert emails carry a profile link.
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], email_lookup=EMAILS.get, public_base_url="https://app.example")
snap_a = service.bootstrap("one", "studio")
snap_b = service.bootstrap("six", "assist")
wid_a, wid_b = snap_a["workspaceId"], snap_b["workspaceId"]

# 1. The owner's workspace list carries name, plan, owner and role counts.
service.update_profile("one", {"displayName": "  James   Au "})
listed = {w["workspaceId"]: w for w in service.workspaces("one")["workspaces"]}
a = listed[wid_a]
assert a["name"] == snap_a["state"]["workspace"]["name"] and a["plan"] == "trial" and a["trialPlan"] == "studio"
assert a["owner"] == {"userId": ONE, "displayName": "James Au"}
assert a["memberCounts"] == {"owner": 1, "admin": 0, "editor": 0, "approver": 0, "viewer": 0}
checks.append("workspace list carries name, trial plan, owner display name and role counts")

# 2. An invited editor sees the same workspace summary from their side, with their own role.
service.usage(wid_a, "one")  # Materialize this fixture's entitlement before changing its seats.
with connection() as db:
    # This membership fixture needs a second seat; production trial terms remain unchanged.
    db.execute("UPDATE public.pr_entitlements SET members=2 WHERE workspace_id=%s", (wid_a,))
invitation = service.invite(wid_a, "one", "six@example.invalid", "editor", {})
service.accept_invitation("six", invitation["token"])
mine = {w["workspaceId"]: w for w in service.workspaces("six")["workspaces"]}
assert mine[wid_a]["membership"]["role"] == "editor" and mine[wid_a]["memberCounts"]["editor"] == 1 and mine[wid_a]["owner"]["displayName"] == "James Au"
assert mine[wid_b]["membership"]["role"] == "owner" and mine[wid_b]["trialPlan"] == "assist"
checks.append("a member sees each workspace's summary with their own role")

# 3. Channels across workspaces: only configured ones, with manage rights per workspace.
now = clock[0]
channel = {"id": "chan-a", "platform": "Threads", "account": "@studio", "accountType": "profile", "language": "English", "scopes": ["threads_basic"], "verifiedAt": now - 5, "expiresAt": now + 3600, "capabilityVersion": 1, "providerAccountId": "1", "configured": True, "identityVerified": True, "capabilityVerified": True, "revoked": False, "evidenceSource": "live_provider"}
placeholder = {"id": "chan-x", "platform": "X", "account": "", "configured": False}
with connection() as db:
    db.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{phase2,channels}',%s::jsonb) WHERE id=%s", (json.dumps([channel, placeholder]), wid_a))
    db.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject) VALUES(%s,%s,'channel.connected','chan-a')", (wid_a, ONE))
owner_view = service.my_channels("one")["channels"]
editor_view = service.my_channels("six")["channels"]
assert [(c["id"], c["connectionState"], c["canManage"]) for c in owner_view] == [("chan-a", "publish_verified", True)]
assert [(c["workspaceId"], c["canManage"]) for c in editor_view] == [(wid_a, False)]
assert owner_view[0]["workspaceName"] == a["name"]
assert editor_view[0]["connectedBy"]["userId"] == ONE and editor_view[0]["connectedBy"]["displayName"] == "James Au"
checks.append("channels span workspaces, skip placeholders, mark manage rights per membership and name who connected them")

# 4. Second factor: AAL1 cannot enable; AAL2 enables once, /me reflects it, audit is workspace-free.
me = service.me("one")
assert me["mfa"] == {"available": True, "enforced": False, "enforcedAt": None, "aal": "aal1"} and me["displayName"] == "James Au"
denied(lambda: service.enable_mfa("one"), 403)
enabled = service.enable_mfa("one-aal2")
again = service.enable_mfa("one-aal2")
assert enabled["enforced"] and again["enforcedAt"] == enabled["enforcedAt"]
assert service.me("one-aal2")["mfa"]["enforced"] is True
with connection() as db:
    kinds = [row[0] for row in db.execute("SELECT kind FROM public.pr_audit_events WHERE actor=%s AND workspace_id IS NULL ORDER BY at", (ONE,)).fetchall()]
    assert kinds.count("mfa.enabled") == 1
    assert db.execute("SELECT count(*) FROM public.pr_mfa_enforcement WHERE user_id=%s", (ONE,)).fetchone()[0] == 1
denied(lambda: service.disable_mfa("one"), 403)
clock[0] += 700  # the AAL2 session is now stale: step-up refuses it
denied(lambda: service.disable_mfa("one-aal2"), 403)
clock[0] -= 700
assert service.disable_mfa("one-aal2") == {"enforced": False, "enforcedAt": None}
assert service.me("one")["mfa"]["enforced"] is False
checks.append("enforcement is written once from an AAL2 session, read back on /me, removed only by a fresh AAL2 session, and audited")

# 5. Revoke every other session: the current one survives, the others are denied.
service.sessions("one")
with connection() as db:
    db.execute("INSERT INTO public.pr_sessions(user_id,session_id,client_label) VALUES(%s,%s,'Other laptop'),(%s,%s,'Phone')", (ONE, "session-other-1-0123456789", ONE, "session-other-2-0123456789"))
revoked = service.revoke_other_sessions("one")
assert revoked["revoked"] == 2 and revoked["refreshRevoked"] is False
states = {s["sessionId"]: s["revoked"] for s in service.sessions("one")["sessions"]}
assert states["session-one-0123456789abcdef"] is False and states["session-other-1-0123456789"] and states["session-other-2-0123456789"]
checks.append("revoke-others denies every other seen session and keeps the current one")

# 6. Leaving: the editor can leave; the owner is told to transfer ownership first.
denied(lambda: service.leave_workspace(wid_a, "one"), 409)
assert service.leave_workspace(wid_a, "six") == {"workspaceId": wid_a, "status": "left"}
assert wid_a not in {w["workspaceId"] for w in service.workspaces("six")["workspaces"]}
denied(lambda: service.get(wid_a, "six"), 403)
assert {w["workspaceId"]: w for w in service.workspaces("one")["workspaces"]}[wid_a]["memberCounts"]["editor"] == 0
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind='member.left' AND actor=%s", (wid_a, SIX)).fetchone()[0] == 1
checks.append("a member leaves and loses access; the owner cannot leave; the departure is audited")

# 7. Account history: what each person did and what happened to their memberships, newest first.
mine = service.security_events("one")["events"]
kinds = [event["kind"] for event in mine]
for expected in ("session.started", "workspace.created", "mfa.enabled", "mfa.disabled", "session.revoked_others"):
    assert expected in kinds, (expected, kinds)
assert all(mine[i]["at"] >= mine[i + 1]["at"] for i in range(len(mine) - 1))
assert not any(k.startswith("channel.") or k.startswith("invitation.created") for k in kinds)
theirs = service.security_events("six")["events"]
their_kinds = [event["kind"] for event in theirs]
assert their_kinds.index("member.left") < their_kinds.index("invitation.accepted")
left = next(event for event in theirs if event["kind"] == "member.left")
assert left["workspaceName"] == a["name"] and left["workspaceId"] == wid_a
assert not any(event["kind"] == "invitation.created" for event in theirs)
checks.append("the account history lists a person's own security actions and membership changes, newest first, with workspace names, and excludes workspace content activity")

# 8. Invitations addressed to my verified email: listed, declinable, acceptable from the profile.
assert service.my_invitations("six") == {"available": True, "invitations": []}
first = service.invite(wid_a, "one", "SIX@example.invalid", "viewer", {})
waiting = service.my_invitations("six")["invitations"]
assert [(w["invitationId"], w["workspaceId"], w["workspaceName"], w["role"], w["invitedBy"]["displayName"]) for w in waiting] == [(first["invitationId"], wid_a, a["name"], "viewer", "James Au")]
assert service.my_invitations("one")["invitations"] == []  # addressed to six, not to the inviter
denied(lambda: service.accept_my_invitation("one", first["invitationId"]), 404)  # someone else cannot take it
assert service.decline_my_invitation("six", first["invitationId"]) == {"invitationId": first["invitationId"], "state": "declined"}
assert service.my_invitations("six")["invitations"] == []
denied(lambda: service.accept_my_invitation("six", first["invitationId"]), 404)  # declined stays declined
second = service.invite(wid_a, "one", "six@example.invalid", "approver", {"can_publish": True})
joined = service.accept_my_invitation("six", second["invitationId"])
assert joined["workspaceId"] == wid_a and joined["role"] == "approver" and joined["can_publish"] is True
assert service.my_invitations("six")["invitations"] == []
assert {w["workspaceId"]: w["membership"]["role"] for w in service.workspaces("six")["workspaces"]}[wid_a] == "approver"
kinds_six = [event["kind"] for event in service.security_events("six")["events"]]
assert kinds_six[:2] == ["invitation.accepted", "invitation.declined"], kinds_six
checks.append("invitations to my email are listed with workspace and inviter, only I can accept or decline them, and both outcomes reach the account history")

# 9. Preferences follow the person: saved on the profile row, read back on /me, cleared to "device".
assert service.me("one")["preferences"] == {"timeZone": "", "locale": "", "alertNewDevice": False}
saved = service.update_profile("one", {"timeZone": "Asia/Hong_Kong", "locale": "zh-Hant"})
assert saved == {"displayName": "James Au", "preferences": {"timeZone": "Asia/Hong_Kong", "locale": "zh-Hant", "alertNewDevice": False}}
assert service.me("one")["preferences"]["timeZone"] == "Asia/Hong_Kong"
assert service.update_profile("one", {"alertNewDevice": True})["preferences"] == {"timeZone": "Asia/Hong_Kong", "locale": "zh-Hant", "alertNewDevice": True}
denied(lambda: service.update_profile("one", {"timeZone": "Mars/Phobos"}), 400)
assert service.update_profile("one", {"timeZone": ""})["preferences"]["timeZone"] == ""
assert service.me("six")["preferences"]["locale"] == ""  # another person's row is untouched
checks.append("time zone, language and the new-device alert are stored per person, validated, and read back on /me")

# 10. New-device alert: opt-in, one email per session's first sighting, visible in the history.
sent = service.mailer.transport.sent
before = len(sent)
service.update_profile("one", {"alertNewDevice": False})
service.me("one", client_label="Chrome")                   # a session we know: nothing
service.me("one-phone", client_label="Safari on iPhone")   # new device, alert off: nothing
assert len(sent) == before
service.update_profile("one", {"alertNewDevice": True})
service.me("one-tablet", client_label="Safari on iPad")
assert len(sent) == before + 1
mail = sent[-1]
assert mail["to"] == "one@example.invalid" and "sign-in" in mail["subject"].lower() and "Safari on iPad" in mail["text"] and "https://app.example/app/account/profile" in mail["text"]
service.me("one-tablet", client_label="Safari on iPad")    # the same session again: no second email
service.sessions("one-tablet")
assert len(sent) == before + 1
history = [event["kind"] for event in service.security_events("one")["events"]]
assert history.index("session.alerted") < history.index("session.started")
alerted = next(event for event in service.security_events("one")["events"] if event["kind"] == "session.alerted")
assert alerted["meta"] == {"sent": False} and alerted["subject"].startswith("session-one-tablet")
checks.append("a new device records one opt-in notification attempt; NullTransport records sent=false in account history")

# 11. Ownership transfer: only the owner may act, needs an active admin and a fresh sign-in, swaps roles atomically.
service.update_member(wid_a, "one", SIX, "admin", {})
denied(lambda: service.transfer_ownership(wid_a, "six", ONE), 403)  # an admin cannot transfer ownership
denied(lambda: service.transfer_ownership(wid_a, "one", ONE), 409)  # cannot transfer to self
NINE = "00000000-0000-0000-0000-000000000009"
denied(lambda: service.transfer_ownership(wid_a, "one", NINE), 404)  # no such member
clock[0] += 700
denied(lambda: service.transfer_ownership(wid_a, "one", SIX), 403)  # a stale sign-in cannot step up
clock[0] -= 700
transferred = service.transfer_ownership(wid_a, "one", SIX)
assert transferred == {"ownerId": SIX, "previousOwnerId": ONE}
roles = {m["userId"]: (m["role"], m["can_publish"], m["can_manage_connections"]) for m in service.members(wid_a, "six")["members"]}
assert roles[SIX][0] == "owner" and roles[ONE] == ("admin", True, True)
denied(lambda: service.leave_workspace(wid_a, "six"), 409)  # the new owner cannot leave either
denied(lambda: service.transfer_ownership(wid_a, "one", SIX), 403)  # the old owner is now an admin, not the owner
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s AND kind='ownership.transferred' AND actor=%s AND subject=%s", (wid_a, ONE, SIX)).fetchone()[0] == 1
checks.append("ownership transfer is owner-only, needs a fresh sign-in and an active admin, swaps roles atomically, and is audited")

# 12. Members carry a display name now, so the UI need not fall back to a truncated id.
names = {m["userId"]: m["displayName"] for m in service.members(wid_a, "six")["members"]}
assert names[ONE] == "James Au" and names[SIX] == ""
checks.append("the members list reports each person's display name alongside their role")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
