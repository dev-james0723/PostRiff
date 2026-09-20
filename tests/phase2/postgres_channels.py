"""Milestone C on disposable PostgreSQL: OAuth start→complete with PKCE, encrypted custody,
capability rows, scope drift, replay/expiry/cross-member, refresh, disconnect, tenancy, account pictures.
"""
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from PIL import Image

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
SIX = "00000000-0000-0000-0000-000000000006"
clock = [time.time()]
auth_times = {"one": clock[0], "six": clock[0]}


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token not in ("one", "six"):
        raise AlphaError("Verified session required.", 401)
    return ONE if token == "one" else SIX


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: auth_times[token]
checks = []


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError("accepted")


class FakeProvider:
    """Deterministic provider double: no network. Records what it was asked."""
    platform = "LinkedIn"
    capability_version = 3
    production_reviewed = True
    native_schedule = False
    assisted_fallback = True

    def __init__(self):
        self.exchanges, self.revoked, self.refreshes, self.grant_scopes = [], [], 0, None

    def capability_scopes(self, capability):
        return {"publish": ["w_member_social", "openid"], "identity": ["openid"], "analytics": []}.get(capability, [])

    def explain(self, capability):
        return "PostRiff will post on your behalf only when you approve an exact post."

    def authorize_url(self, redirect, state, challenge, scopes):
        return f"https://provider.example/auth?redirect_uri={redirect}&state={state}&code_challenge={challenge}&scope={'+'.join(scopes)}"

    def exchange(self, code, verifier, redirect):
        self.exchanges.append((code, verifier, redirect))
        assert code == "good-code" and len(verifier) >= 43
        return {"accessToken": "ACCESS-" + code, "refreshToken": "REFRESH-1", "expiresIn": 60, "scopes": self.grant_scopes or ["w_member_social", "openid"]}

    def identity(self, access_token):
        assert access_token.startswith("ACCESS-")
        return {"providerAccountId": "urn:li:person:abc", "handle": "Verified Member", "accountType": "member", "pictureUrl": "https://media.licdn.com/dms/image/member.jpg"}

    def refresh(self, refresh_token):
        self.refreshes += 1
        assert refresh_token == "REFRESH-1"
        return {"accessToken": "ACCESS-refreshed", "refreshToken": "REFRESH-2", "expiresIn": 60}

    def revoke(self, token):
        self.revoked.append(token)
        return True


with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s)", (SIX,))
    wid_a = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid_a,))

key = CredentialVault.generate_key()
provider = FakeProvider()
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], vault=CredentialVault(key), providers={"linkedin": provider}, public_base_url="https://app.postriff.example")
snap_a = service.bootstrap("one", "studio")
snap_b = service.bootstrap("six", "assist")
wid_b = snap_b["workspaceId"]
oauth = service.oauth
picture_png = io.BytesIO()
Image.new("RGB", (400, 300), (40, 90, 160)).save(picture_png, format="PNG")
picture_fetches = []


def fetch_picture(url):
    picture_fetches.append(url)
    return (200, "image/png", picture_png.getvalue()) if picture_fetch_ok[0] else (503, "", b"")


picture_fetch_ok = [True]
oauth.picture_fetch = fetch_picture

# 1. Start binds workspace/member/provider/capability/redirect/expiry; state stored hashed; verifier encrypted.
started = oauth.start(wid_a, "one", "linkedin", "publish")
q = parse_qs(urlparse(started["authorizeUrl"]).query)
state = q["state"][0]
assert q["redirect_uri"][0] == "https://app.postriff.example/api/oauth/linkedin/callback" and q["code_challenge"][0]
with connection() as db:
    row = db.execute("SELECT state_hash,verifier_ciphertext,member_id::text,capability,scopes FROM public.pr_oauth_transactions WHERE workspace_id=%s", (wid_a,)).fetchone()
assert row[0] != state and len(row[0]) == 64 and "code_verifier" not in row[1] and row[2] == ONE and row[3] == "publish" and set(row[4]) == {"w_member_social", "openid"}
denied(lambda: oauth.start(wid_a, "one", "linkedin", "analytics"), 409)   # provider offers no analytics scopes
denied(lambda: oauth.start(wid_a, "one", "tiktok", "publish"), 404)       # unregistered provider
denied(lambda: oauth.start(wid_a, "six", "linkedin", "publish"), 403)     # not a member
checks.append("start binds workspace/member/provider/capability/redirect; state hashed; verifier encrypted; unsupported capability and provider refused")

# 2. Complete by a different member of another workspace is unavailable; wrong workspace 403.
denied(lambda: oauth.complete(wid_b, "six", "linkedin", state, "good-code"), 404)
denied(lambda: oauth.complete(wid_b, "one", "linkedin", state, "good-code"), 403)
checks.append("a state cannot be completed from another workspace or by another member")

# 3. Denied consent consumes the transaction without storing anything.
denied_start = oauth.start(wid_a, "one", "linkedin", "publish")
denied_state = parse_qs(urlparse(denied_start["authorizeUrl"]).query)["state"][0]
assert oauth.complete(wid_a, "one", "linkedin", denied_state, None, error="access_denied") == {"connected": False, "reason": "denied"}
denied(lambda: oauth.complete(wid_a, "one", "linkedin", denied_state, "good-code"), 404)  # consumed
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_encrypted_credentials WHERE workspace_id=%s", (wid_a,)).fetchone()[0] == 0
checks.append("denied consent consumes the transaction and stores no credential")

# 4. Successful complete: PKCE verifier passed to exchange, tokens encrypted, channel + capabilities recorded.
done = oauth.complete(wid_a, "one", "linkedin", state, "good-code")
assert done["connected"] and done["confirmAccount"] and done["missingScopes"] == []
assert done["capabilities"]["identity"]["level"] == "Direct" and done["capabilities"]["publish"]["level"] == "Direct" and done["capabilities"]["schedule"]["level"] == "Assisted" and done["capabilities"]["analytics"]["level"] == "Unsupported"
assert provider.exchanges[0][2] == "https://app.postriff.example/api/oauth/linkedin/callback"
with connection() as db:
    cred = db.execute("SELECT access_ciphertext,refresh_ciphertext,key_id,scopes,refresh_supported FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s", (wid_a, done["connectionId"])).fetchone()
assert "ACCESS-good-code" not in cred[0] and "REFRESH-1" not in (cred[1] or "") and cred[4] is True
assert "ACCESS-good-code" not in json.dumps(service.get(wid_a, "one"))  # never in workspace state
denied(lambda: oauth.complete(wid_a, "one", "linkedin", state, "good-code"), 404)  # single use
listed = oauth.channels(wid_a, "one")["channels"]
assert listed[0]["connectionState"] == "publish_verified" and listed[0]["capabilities"]["publish"]["level"] == "Direct"
checks.append("complete exchanges with PKCE, encrypts tokens at rest, records per-capability levels, single-use state, token absent from state and API")

# 4b. The account's picture is read once from the provider's image host, re-encoded, listed by digest, and
#     readable by members of this workspace only (browser role: select own workspace, never write).
assert picture_fetches == ["https://media.licdn.com/dms/image/member.jpg"]
digest = listed[0]["pictureDigest"]
jpeg, served_digest = oauth.picture(wid_a, "one", done["connectionId"])
assert len(digest) == 64 and served_digest == digest and jpeg.startswith(b"\xff\xd8")
denied(lambda: oauth.picture(wid_a, "six", done["connectionId"]), 403)
denied(lambda: oauth.picture(wid_a, "one", "0" * 32), 404)
for member, visible in ((ONE, 1), (SIX, 0)):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (member,))
        assert db.execute("SELECT count(*) FROM public.pr_channel_pictures").fetchone()[0] == visible
with connection() as db:
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
    try:
        db.execute("DELETE FROM public.pr_channel_pictures")
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()
    else:
        raise AssertionError("browser role could delete pictures")
checks.append("the account picture is fetched from the provider's image host, re-encoded, listed by digest, and member-only readable")

# 5. Scope drift: granted scopes missing publish → Assisted publish, capabilityVerified False.
provider.grant_scopes = ["openid"]
drift_start = oauth.start(wid_a, "one", "linkedin", "publish")
drift_state = parse_qs(urlparse(drift_start["authorizeUrl"]).query)["state"][0]
drifted = oauth.complete(wid_a, "one", "linkedin", drift_state, "good-code")
assert drifted["missingScopes"] == ["w_member_social"] and drifted["capabilities"]["publish"]["level"] == "Assisted"
assert oauth.channels(wid_a, "one")["channels"][0]["connectionState"] == "read_verified"
provider.grant_scopes = None
checks.append("scope drift downgrades publish to Assisted and the connection to read_verified")

# 5b. A picture that cannot be fetched on a later identity read keeps the stored one.
picture_fetch_ok[0] = False
kept = oauth.verify(wid_a, "one", done["connectionId"])
assert kept["identityVerified"] and oauth.channels(wid_a, "one")["channels"][0]["pictureDigest"] == digest and len(picture_fetches) == 3
picture_fetch_ok[0] = True
checks.append("a failed picture refresh keeps the stored picture")

# 6. Worker token path refreshes an expired access token server-side; browser role cannot read credentials.
clock[0] += 120
grant = oauth.token_for_worker(wid_a, done["connectionId"])
assert grant["accessToken"] == "ACCESS-refreshed" and provider.refreshes == 1
# SET ROLE is transactional: fresh connection per denied statement (a rollback would restore superuser).
for statement in ("SELECT * FROM public.pr_encrypted_credentials", "SELECT * FROM public.pr_oauth_transactions", "UPDATE public.pr_channel_capabilities SET level='Direct'"):
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
        try:
            db.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            db.rollback()
        else:
            raise AssertionError(f"browser role was allowed: {statement}")
checks.append("expired access is refreshed only in the server worker path; credentials and transactions are never browser-readable")

# 7. Expired transaction cannot complete.
late = oauth.start(wid_a, "one", "linkedin", "publish")
late_state = parse_qs(urlparse(late["authorizeUrl"]).query)["state"][0]
clock[0] += 601
denied(lambda: oauth.complete(wid_a, "one", "linkedin", late_state, "good-code"), 409)
checks.append("expired transactions are refused")

# 8. Disconnect requires step-up, revokes remotely, wipes ciphertext, holds approvals via invalidation.
auth_times["one"] = clock[0] - 3600
denied(lambda: oauth.disconnect(wid_a, "one", done["connectionId"]), 403)
auth_times["one"] = clock[0]
gone = oauth.disconnect(wid_a, "one", done["connectionId"])
assert gone["disconnected"] and gone["remoteRevoked"] and provider.revoked
with connection() as db:
    wiped = db.execute("SELECT access_ciphertext,revoked_at IS NOT NULL FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s", (wid_a, done["connectionId"])).fetchone()
assert wiped == ("", True)
denied(lambda: oauth.token_for_worker(wid_a, done["connectionId"]), 404)
assert oauth.channels(wid_a, "one")["channels"][0]["connectionState"] == "reauthorization_required"
assert oauth.channels(wid_a, "one")["channels"][0]["pictureDigest"] is None
denied(lambda: oauth.picture(wid_a, "one", done["connectionId"]), 404)
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_channel_pictures WHERE workspace_id=%s", (wid_a,)).fetchone()[0] == 0
checks.append("disconnect needs step-up, revokes remotely, wipes ciphertext and the account picture, and the worker can no longer obtain a token")

# 9. Audit trail present and content-free.
events = service.audit_events(wid_a, "one")["events"]
kinds = {e["kind"] for e in events}
assert {"oauth.started", "oauth.denied", "channel.connected", "channel.disconnected"} <= kinds
assert not any("ACCESS-" in json.dumps(e) or "REFRESH-" in json.dumps(e) for e in events)
checks.append("OAuth lifecycle is audited without tokens")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
