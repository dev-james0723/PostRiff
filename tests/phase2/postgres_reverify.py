"""OAuthService.reverify_for_worker on disposable PostgreSQL (orchestration §5 step 2).

The publish worker has no session token. Right before committing an approved post it re-verifies the channel on
its own authority so the channel is "Ready for posting" for the next hour. Zero network: fake provider adapters.
"""
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
KIND = "channel.reverified_by_worker"
clock = [time.time()]
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"
verify.auth_time = lambda token, principal: clock[0]


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError("accepted")


class FakeLinkedIn:
    """Introspecting provider double: scopes come back in the provider's order, not PostRiff's sorted order."""
    platform = "LinkedIn"
    capability_version = 3
    production_reviewed = True
    native_schedule = False
    assisted_fallback = True

    def __init__(self):
        self.account = "urn:li:person:abc"
        self.granted = ["w_member_social", "openid"]
        self.identity_error = None
        self.refreshes = 0

    def capability_scopes(self, capability):
        return {"publish": ["w_member_social", "openid"], "identity": ["openid"]}.get(capability, [])

    def explain(self, capability):
        return "PostRiff will post on your behalf only when you approve an exact post."

    def authorize_url(self, redirect, state, challenge, scopes):
        return f"https://provider.example/auth?redirect_uri={redirect}&state={state}&code_challenge={challenge}"

    def exchange(self, code, verifier, redirect):
        return {"accessToken": "ACCESS-" + code, "refreshToken": "REFRESH-1", "expiresIn": 86400, "scopes": ["w_member_social", "openid"]}

    def identity(self, access_token):
        if self.identity_error:
            raise self.identity_error
        return {"providerAccountId": self.account, "handle": "Verified Member", "accountType": "member"}

    def inspect_scopes(self, access_token, account):
        return list(self.granted) if self.granted is not None else None

    def refresh(self, refresh_token):
        assert refresh_token.startswith("REFRESH-")
        self.refreshes += 1
        return {"accessToken": f"ACCESS-refreshed-{self.refreshes}", "refreshToken": f"REFRESH-{self.refreshes + 1}", "expiresIn": 86400}

    def revoke(self, token):
        return True


class FakeInstagram:
    """Read-proof provider double: like Instagram Login, it proves basic read access and never write scopes."""
    platform = "Instagram"
    capability_version = 1
    production_reviewed = True
    native_schedule = False
    assisted_fallback = True

    def capability_scopes(self, capability):
        return {"publish": ["instagram_business_basic", "instagram_business_content_publish"], "identity": ["instagram_business_basic"]}.get(capability, [])

    def explain(self, capability):
        return "PostRiff will post on your behalf only when you approve an exact post."

    def authorize_url(self, redirect, state, challenge, scopes):
        return f"https://provider.example/ig?redirect_uri={redirect}&state={state}&code_challenge={challenge}"

    def exchange(self, code, verifier, redirect):
        return {"accessToken": "IG-" + code, "refreshToken": "IG-" + code, "expiresIn": 30 * 86400, "scopes": ["instagram_business_basic", "instagram_business_content_publish"]}

    def identity(self, access_token):
        return {"providerAccountId": "1784", "handle": "@studio", "accountType": "professional"}

    def verify_read_access(self, access_token, expected_account_id):
        return ["instagram_business_basic"]

    def revoke(self, token):
        return True


def connect(provider_id):
    started = oauth.start(wid, "one", provider_id, "publish")
    state = parse_qs(urlparse(started["authorizeUrl"]).query)["state"][0]
    done = oauth.complete(wid, "one", provider_id, state, "good-code")
    assert done["connected"] and done["missingScopes"] == [], done
    return done["connectionId"]


def stored():
    with connection() as db:
        revision, state = db.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s", (wid,)).fetchone()
    return revision, (json.loads(state) if isinstance(state, str) else state)


def channel_of(state, cid):
    return next(c for c in state["phase2"]["channels"] if c["id"] == cid)


def credential_scopes(cid):
    with connection() as db:
        return db.execute("SELECT scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s", (wid, cid)).fetchone()[0]


def levels(cid):
    with connection() as db:
        return dict(db.execute("SELECT capability,level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s", (wid, cid)).fetchall())


with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))

linkedin, instagram = FakeLinkedIn(), FakeInstagram()
service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], vault=CredentialVault(CredentialVault.generate_key()), providers={"linkedin": linkedin, "instagram": instagram}, public_base_url="https://app.postriff.example")
snapshot = service.bootstrap("one", "studio")
oauth, engine = service.oauth, service.commands.engine
connected_at = clock[0]
cid = connect("linkedin")
_, state = stored()
assert channel_of(state, cid)["scopes"] == ["openid", "w_member_social"]  # complete() stores the grant sorted


# An approved job on this channel, publishing three hours from now (the manifest records the channel's scope list).
snapshot = {"revision": stored()[0]}  # connecting bumped the revision


def act(action, payload):
    global snapshot
    snapshot = service.mutate(wid, "one", snapshot["revision"], action, payload)


act("mode", {"mode": "personal"})
act("context", {"purpose": "Make community learning accessible", "audience": "Curious beginners", "subject": "Community workshops", "speaker": "My voice", "layers": []})
act("source", {"kind": "sample"})
source = snapshot["state"]["sources"][-1]
act("approve_source", {"sourceId": source["id"], "factIds": [fact["id"] for fact in source["facts"]]})
act("source_done", {})
act("profile_propose", {"writing": "A small step can be a useful beginning.", "tone": "warm"})
act("profile_decide", {"decision": "approve"})
act("runtime", {"selected": "deterministic-preview"})
act("generate", {"platform": "LinkedIn", "language": "English"})
variant = snapshot["state"]["variants"][0]
act("p2_variant_review", {"variantId": variant["id"], "variantRevision": variant["revision"], "confirmed": True, "excludedUnknowns": variant["unknowns"]})
publish_at = datetime.fromtimestamp(clock[0] + 3 * 3600, timezone.utc).replace(tzinfo=None, second=0, microsecond=0).isoformat()
act("p2_review", {"channelId": cid, "variantId": variant["id"], "localTime": publish_at, "timeZone": "UTC", "acknowledgedWarnings": variant["warnings"]})
review = snapshot["state"]["phase2"]["reviews"][-1]
act("p2_approve", {"reviewId": review["id"], "digest": review["digest"], "confirmed": True})
_, state = stored()
job = state["phase2"]["jobs"][0]
assert job["state"] != "held" and job["manifest"]["channelId"] == cid and job["manifest"]["capability"]["scopes"] == ["openid", "w_member_social"]
live_job = job["state"]

# 1. Two hours later the channel is stale; the worker re-verifies it without a session and it is ready again.
clock[0] += 2 * 3600
revision, state = stored()
assert engine.channel_state(channel_of(state, cid)) == "Finish setup"
out = oauth.reverify_for_worker(wid, cid)
assert out == {"connectionId": cid, "state": "read_verified", "ready": True}, out
after_revision, state = stored()
channel = channel_of(state, cid)
assert after_revision == revision + 1 and channel["verifiedAt"] == clock[0] and engine.channel_state(channel) == "Ready for posting"
assert abs(channel["expiresAt"] - (connected_at + 86400)) < 1 and linkedin.refreshes == 0  # access still valid: no refresh
checks.append("a stale channel is re-verified on worker authority (no session) and is Ready for posting again")

# 2. The provider reported the same set in another order: the channel list is untouched and the approved job stays live.
assert channel["scopes"] == ["openid", "w_member_social"] and channel["capabilityVerified"] is True
assert set(credential_scopes(cid)) == {"openid", "w_member_social"}
job = state["phase2"]["jobs"][0]
assert job["state"] == live_job and engine.current(state, job["manifest"])
reordered = copy.deepcopy(state)
channel_of(reordered, cid)["scopes"] = list(linkedin.granted)
assert not engine.current(reordered, job["manifest"])  # proves the order rule is load-bearing
checks.append("a scope reorder keeps the stored list, so the approved job is not held (a reordered list would have been)")

# 7. Audit: system actor, content-free.
with connection() as db:
    rows = db.execute("SELECT actor,meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind=%s AND subject=%s ORDER BY at", (wid, KIND, cid)).fetchall()
assert rows == [(None, {"state": "read_verified"})], rows
checks.append("each re-verification writes a content-free audit row with a NULL system actor")

# 5. Provider failures never raise, never extend verifiedAt and never downgrade.
verified_at = channel["verifiedAt"]
clock[0] += 600
for failure in (AlphaError("The provider is temporarily unreachable.", 503), TimeoutError("timed out"), KeyError("providerAccountId")):
    linkedin.identity_error = failure
    assert oauth.reverify_for_worker(wid, cid) == {"connectionId": cid, "state": "verification_unavailable", "ready": False}
linkedin.identity_error = None
linkedin.execution_enabled = False  # operator pause: token_for_worker refuses
assert oauth.reverify_for_worker(wid, cid)["state"] == "verification_unavailable"
linkedin.execution_enabled = True
revision_now, state = stored()
channel = channel_of(state, cid)
assert revision_now == after_revision and channel["verifiedAt"] == verified_at and channel["capabilityVerified"] is True
assert engine.channel_state(channel) == "Ready for posting" and levels(cid)["publish"] == "Direct"
checks.append("provider/network failure and operator pause return verification_unavailable with the channel untouched")

# A person re-authorizing while the worker checks wins: the worker writes nothing.
base_identity = linkedin.identity
rotated, rotated_key = oauth.vault.encrypt("ACCESS-reauthorized")


def raced_identity(access):
    with connection() as db:
        db.execute("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s WHERE workspace_id=%s AND connection_id=%s", (rotated, rotated_key, wid, cid))
    return base_identity(access)


linkedin.identity = raced_identity
assert oauth.reverify_for_worker(wid, cid)["state"] == "verification_unavailable"
linkedin.identity = base_identity
assert stored()[0] == after_revision and channel_of(stored()[1], cid)["verifiedAt"] == verified_at
checks.append("a credential rotated during verification fences the worker write")

# 3. Scope loss: scope_changed, not ready, authority downgraded, job held, credential updated.
linkedin.granted = ["openid"]
out = oauth.reverify_for_worker(wid, cid)
assert out == {"connectionId": cid, "state": "scope_changed", "ready": False}, out
_, state = stored()
channel = channel_of(state, cid)
assert channel["scopes"] == ["openid"] and channel["capabilityVerified"] is False and channel["verifiedAt"] == clock[0]
assert levels(cid)["publish"] == "Unsupported" and levels(cid)["identity"] == "Direct" and credential_scopes(cid) == ["openid"]
assert state["phase2"]["jobs"][0]["state"] == "held"
# The worker never upgrades: restored scopes stay unverified until a person reconnects.
linkedin.granted = ["w_member_social", "openid"]
assert oauth.reverify_for_worker(wid, cid) == {"connectionId": cid, "state": "scope_changed", "ready": False}
assert channel_of(stored()[1], cid)["scopes"] == ["openid", "w_member_social"]  # a changed set is stored sorted
assert oauth.reverify_for_worker(wid, cid) == {"connectionId": cid, "state": "read_verified", "ready": False}
assert channel_of(stored()[1], cid)["capabilityVerified"] is False and levels(cid)["publish"] == "Unsupported"
linkedin.granted = None  # introspection returned nothing: fail closed
assert oauth.reverify_for_worker(wid, cid) == {"connectionId": cid, "state": "scope_missing", "ready": False}
assert channel_of(stored()[1], cid)["scopes"] == [] and credential_scopes(cid) == []
linkedin.granted = ["w_member_social", "openid"]
checks.append("scope loss downgrades (scope_changed / scope_missing), holds the approved job, and the worker never upgrades authority")

# 4. Identity drift: reauthorization_required, channel revoked.
linkedin.account = "urn:li:person:someone-else"
assert oauth.reverify_for_worker(wid, cid) == {"connectionId": cid, "state": "reauthorization_required", "ready": False}
channel = channel_of(stored()[1], cid)
assert channel["revoked"] is True and channel["identityVerified"] is False and engine.channel_state(channel) == "Reconnect"
linkedin.account = "urn:li:person:abc"
checks.append("account drift marks the channel revoked (reauthorization_required)")

# 6. Unknown, foreign and revoked connections raise 404; nothing else raises.
denied(lambda: oauth.reverify_for_worker(wid, "0" * 32), 404)
denied(lambda: oauth.reverify_for_worker("00000000-0000-0000-0000-00000000abcd", cid), 404)
assert oauth.disconnect(wid, "one", cid)["disconnected"]
denied(lambda: oauth.reverify_for_worker(wid, cid), 404)
checks.append("unknown, foreign-workspace and revoked connections raise 404")

# A read-proof provider (Instagram) cannot re-observe write scopes: no trust extension, no downgrade.
clock[0] = time.time()  # OAuth transactions expire on the database clock
ig = connect("instagram")
clock[0] += 2 * 3600
revision, state = stored()
before = channel_of(state, ig)
assert oauth.reverify_for_worker(wid, ig) == {"connectionId": ig, "state": "verification_unavailable", "ready": False}
revision_now, state = stored()
assert revision_now == revision and channel_of(state, ig) == before and levels(ig)["publish"] == "Direct"
with connection() as db:
    reason = db.execute("SELECT meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind=%s AND subject=%s ORDER BY at DESC LIMIT 1", (wid, KIND, ig)).fetchone()[0]
assert reason == {"state": "verification_unavailable", "reason": "grant_not_observable"}, reason  # the read proof ran; not a caught crash
checks.append("a read-only proof (Instagram) neither extends trust nor destroys the stored publish grant")

# A person's Re-verify on the same account: the token's epoch values are floats (extract() is numeric since
# PostgreSQL 14, and Instagram's renewal check subtracts the clock from them), identity and read access are
# confirmed, and the stored grant, its levels and the trust window stay as they were.
assert isinstance(oauth.token_for_worker(wid, ig)["expiresAt"], float)
revision, state = stored()
before = channel_of(state, ig)
out = oauth.verify(wid, "one", ig)
assert out == {"connectionId": ig, "identityVerified": True, "scopes": ["instagram_business_basic", "instagram_business_content_publish"], "state": "read_verified"}, out
after = channel_of(stored()[1], ig)
assert after["scopes"] == before["scopes"] and after["verifiedAt"] == before["verifiedAt"] and after["capabilityVerified"] is before["capabilityVerified"] is True
assert levels(ig)["publish"] == "Direct" and credential_scopes(ig) == ["instagram_business_basic", "instagram_business_content_publish"]
checks.append("a person's Re-verify on a read-proof account (Instagram) confirms it without a TypeError and keeps the stored publish grant")

with connection() as db:
    audited = [row[0]["state"] for row in db.execute("SELECT meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind=%s ORDER BY at", (wid, KIND)).fetchall()]
    actors = {row[0] for row in db.execute("SELECT actor FROM public.pr_audit_events WHERE workspace_id=%s AND kind=%s", (wid, KIND)).fetchall()}
assert actors == {None} and {"read_verified", "verification_unavailable", "scope_changed", "scope_missing", "reauthorization_required"} <= set(audited), audited
assert not any("ACCESS-" in json.dumps(e) or "REFRESH-" in json.dumps(e) for e in service.audit_events(wid, "one")["events"])
checks.append("every outcome is audited without tokens")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
