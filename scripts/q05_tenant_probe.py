#!/usr/bin/env python3
"""Q-05 cross-tenant isolation probe for the Rafii (PostRiff) Discord launch.

Gate G4 (RELEASE-DEFINITION-v2.md): with two accounts A and B, in BOTH directions,
every READ and every WRITE aimed at the other tenant must be denied AND have no
side effects. This probe is the repeatable evidence for that gate. It talks to the
hosted API over HTTP using each tenant's own bearer token; it never reads the
database directly and never needs provider secrets.

Standard library only. No third-party imports.

Configuration is through environment variables only:
  Q05_BASE_URL          base origin of the API, e.g. https://rafii.io or http://127.0.0.1:8000
  Q05_TOKEN_A           bearer token for tenant A's owner
  Q05_TOKEN_B           bearer token for tenant B's owner
  Q05_WORKSPACE_A       workspace id owned by A
  Q05_WORKSPACE_B       workspace id owned by B
  Q05_EXTRA_HEADER_NAME optional deployment-protection bypass header name (never printed)
  Q05_EXTRA_HEADER_VALUE optional value for that header (never printed)
  Q05_VICTIM_A_OAUTH_STATE optional: an OAuth `state` value belonging to A (for the
  Q05_VICTIM_B_OAUTH_STATE state-binding case). When absent that case is NOT RUN.

Object ids (connections, destinations, identities, posts, jobs, reviews, members)
are DISCOVERED by calling the app's own list/read endpoints with each tenant's OWN
token, so the hosted run needs few inputs. A case whose victim object cannot be
discovered is reported NOT RUN (never PASS).

Output: one JSON line per case on stdout, plus a Markdown receipt. Both contain
only: case id, method, route TEMPLATE (ids replaced by placeholders), direction,
kind, blast label, expected, observed status, verdict. No bodies, no tokens, no
full ids, no victim data.

Exit code 0 only if every case that ran passed and no family is inconclusive and
no case that should have run was skipped for lack of a discovered victim object.
Intentionally gated-off writes (no --allow-writes) do not by themselves fail the
run, but the receipt says loudly that writes were not covered.
"""
import argparse
import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class Config:
    def __init__(self, env):
        self.base_url = (env.get("Q05_BASE_URL") or "").rstrip("/")
        self.token = {"A": env.get("Q05_TOKEN_A"), "B": env.get("Q05_TOKEN_B")}
        self.workspace = {"A": env.get("Q05_WORKSPACE_A"), "B": env.get("Q05_WORKSPACE_B")}
        self.extra_header_name = env.get("Q05_EXTRA_HEADER_NAME")
        self.extra_header_value = env.get("Q05_EXTRA_HEADER_VALUE")
        # Optional injected victim OAuth state values (the only object that has no
        # read/list endpoint to discover it). Keyed by the tenant that OWNS it.
        self.victim_oauth_state = {"A": env.get("Q05_VICTIM_A_OAUTH_STATE"),
                                   "B": env.get("Q05_VICTIM_B_OAUTH_STATE")}
        # Optional OTHER members of each workspace, for the intra-workspace sender-name cases
        # (Q05_TOKEN_A_VIEWER, ..._EDITOR, ..._CONNMGR = editor with connection-management,
        # ..._ADMIN = admin who did not authorize the connection, ..._REMOVED = a removed member).
        # Absent => those cases are NOT RUN (undiscovered), never PASS.
        for key in ("A", "B"):
            for role in ROLE_KEYS:
                self.token[f"{key}.{role}"] = env.get(f"Q05_TOKEN_{key}_{role.upper()}")
        # Local harness only: mark the attack phase so the harness can bracket it exactly.
        self.phase_markers = env.get("Q05_PHASE_MARKERS") == "1"

    def missing(self):
        names = []
        if not self.base_url:
            names.append("Q05_BASE_URL")
        for key in ("A", "B"):
            if not self.token[key]:
                names.append("Q05_TOKEN_" + key)
            if not self.workspace[key]:
                names.append("Q05_WORKSPACE_" + key)
        return names

    def origin(self):
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"


OTHER = {"A": "B", "B": "A"}
ROLE_KEYS = ("viewer", "editor", "connmgr", "admin", "removed")

# Workspace-scoped route families (the first path segment after /api/workspaces/<id>/)
# that the probe LIVE-attacks. Everything else must be in EXCLUDED_FAMILIES with a reason.
COVERED_FAMILIES = {
    "get": "GET /api/workspaces/<id> (workspace state, incl. jobs/receipts) — ws_scope read",
    "members": "members read + cross-tenant member remove",
    "invitations": "invitations read + cross-tenant invite create",
    "audit": "audit read",
    "export": "export read",
    "analytics": "analytics read",
    "memory": "memory read",
    "channels": "channel list; destinations list/choose/remove IDOR; discord connect start; disconnect IDOR",
    "discord": "discord identity guilds / private-review (read) and identity disconnect (write) IDOR",
    "jobs": "job execute (publish-now) ws-scope + IDOR, blast=send",
    "actions": "mutate actions: mode/p2_refresh/p2_approve/p2_cancel (approve/schedule/cancel/pause)",
}

# Route families that take a workspace id or an object id but are deliberately NOT live-
# attacked, each with a written reason. The coverage unit test fails if any hosted
# workspace-scoped family is neither in COVERED_FAMILIES nor here.
EXCLUDED_FAMILIES = {
    # --- generic workspace routes: all funnel through the SAME membership gate ---------- #
    # PostgresWorkspaceRepository.transaction()/get()/command()/mutate() resolve the member
    # row (w.id=%s AND m.user_id=%s AND status='active') and raise the uniform
    # "Workspace unavailable." 403 BEFORE any object lookup. The ws_scope cases prove that
    # gate; these families add no object-id binding of their own.
    "account": "generic ws route; shared repository membership gate (ws_scope cases prove it)",
    "data-requests": "generic ws route; shared repository membership gate",
    "drafts": "generic ws route (drafts/export); shared repository membership gate",
    "leave": "generic ws route; shared repository membership gate",
    "profile-export": "generic ws route; shared repository membership gate",
    "skills": "generic ws route (skill preview); shared repository membership gate",
    "subscription": "generic ws route (usage view); shared repository membership gate",
    "support": "generic ws route; shared repository membership gate",
    "time-savings": "generic ws route; shared repository membership gate",
    "transfer-ownership": "generic ws route; shared repository membership gate + owner check",
    "usage": "generic ws route; shared repository membership gate",
    "youtube-policy": "generic ws route (policy status/accept); shared repository membership gate",
    "billing": "generic ws route; owner-only + shared repository membership gate",
    "growth": "generic ws route; every handler calls repository.transaction(workspace, token)",
    # --- object-id families on at launch but not yet LIVE-covered (recommended future) -- #
    # Each resolves its object id ONLY inside repository.transaction(workspace, token), so
    # membership is enforced before the object is read; there is no cross-workspace object
    # fetch on these paths (verified by reading the handlers). Listed in PLAN.md as
    # recommended additional live IDOR cases for defence in depth.
    "channels-other-providers": "non-Discord provider connections share channels/<id> + _member_grant boundary already attacked via Discord",
    "ideas": "object ids (conversation/run) resolved inside repository.transaction; recommended future live case",
    "connectors": "productivity connectors; object ids resolved inside repository.transaction; recommended future live case",
    "site-agent": "run ids resolved inside repository.transaction; recommended future live case",
    "audience": "thread/reply ids resolved inside repository.transaction; recommended future live case",
    "library": "asset ids resolved inside repository.transaction; recommended future live case",
    "media": "asset ids resolved inside repository.transaction; recommended future live case",
    "youtube": "connection/action ids resolved inside repository.transaction; needs a connected YouTube channel in both tenants",
    # --- feature flags OFF in the launch build (docs .../C-01-env-matrix.md) ------------- #
    "connection-health": "RAFII_CONNECTION_HEALTH flag off at launch; 404 for everyone",
    "phone": "phone-mode flags off at launch; routes 404 for everyone",
    "agent": "agent runtime flags off at launch; routes 404 for everyone",
    "coworker": "coworker RESOURCES flags off at launch; routes 404 for everyone",
    "notifications": "coworker resource; flags off at launch; shared repository membership gate",
    "notification-preferences": "coworker resource; flags off at launch; shared repository membership gate",
    "push-subscriptions": "coworker resource; flags off at launch; shared repository membership gate",
    "discord-engagement": "Discord engagement feature off at launch; replies gated by ready(provider)",
    "interaction-links": "User-Install feature off at launch; same identity_record() boundary as identities/disconnect",
    # --- not workspace-scoped (matched by the extractor but out of scope) --------------- #
    "tokens": "API-token admin keyed to the caller; create requires manage; not a cross-workspace object fetch",
    "callback": "not a workspace route: /api/oauth/<provider>/callback, public redirect only",
    "invoke": "not a workspace route: /api/tools/<id>/invoke, no workspace or victim object",
}

# Non-workspace routes that nonetheless take a bearer or an id, excluded with reason.
OTHER_EXCLUSIONS = {
    "/api/me*": "the caller's own profile/channels/invitations/security-events; no workspace path id",
    "/api/auth/sessions/<id>": "the caller's own session id, bound to the verified principal",
    "/api/invitations/accept": "single-use hashed invitation token; not a workspace path id",
    "/api/oauth/<provider>/callback": "public provider callback; redirect only",
    "/api/discord/interactions": "signed Ed25519 interaction; one-use id; no bearer/workspace authority",
    "/api/youtube/notifications/<id>": "WebSub callback authenticated by its own hub signature",
}


# --------------------------------------------------------------------------- #
# HTTP client (stdlib only)
# --------------------------------------------------------------------------- #
class Budget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0

    def take(self):
        self.used += 1
        if self.used > self.limit:
            raise RuntimeError(f"request budget of {self.limit} exhausted")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: return None so the 3xx is the observed status and the
    Authorization header is never resent to the Location (possibly another origin)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, config, budget, delay):
        self.config = config
        self.budget = budget
        self.delay = delay
        # localhost http needs no TLS context; https uses the default verified one.
        self._ctx = ssl.create_default_context() if config.base_url.startswith("https") else None
        handlers = [_NoRedirect()]
        if self._ctx is not None:
            handlers.append(urllib.request.HTTPSHandler(context=self._ctx))
        self._opener = urllib.request.build_opener(*handlers)
        # (provider calls, provider writes) the LOCAL harness attributes to the last request, from its
        # X-Q05-Provider-Calls / -Writes headers; None when unobservable (every hosted run).
        self.last_provider = None
        self.last_elapsed = None     # seconds the last request took (twin timing comparison)

    def marker(self, name):
        """Local harness only: tell it where the attack phase starts/ends (a GET it answers itself)."""
        self.budget.take()
        req = urllib.request.Request(self.config.base_url + "/api/health", method="GET",
                                     headers={"X-Q05-Phase": name, "Accept": "application/json"})
        try:
            with self._opener.open(req, timeout=30) as resp:
                resp.read(1000)
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

    def request(self, method, path, token_key, *, body=None, mutation=False):
        """Return (status, text, body_obj). Never raises on HTTP error status, and never
        follows a redirect (a 3xx is returned as-is, so Authorization cannot leak to another
        origin and a redirect scores as INCONCLUSIVE, never a deny)."""
        self.budget.take()
        if self.delay:
            time.sleep(self.delay)
        url = self.config.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        token = self.config.token[token_key]
        if token:
            headers["Authorization"] = "Bearer " + token
        if mutation:
            # The hosted application guard for browser-origin mutations.
            headers["X-Postriff-Request"] = "founder-alpha"
            headers["Origin"] = self.config.origin()
            headers["Content-Type"] = "application/json"
            data = json.dumps(body if body is not None else {}).encode()
        if self.config.extra_header_name and self.config.extra_header_value:
            headers[self.config.extra_header_name] = self.config.extra_header_value
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        self.last_provider = None
        started = time.monotonic()
        try:
            with self._opener.open(req, timeout=30) as resp:
                raw = resp.read(2_000_000)
                status = resp.status
                rhead = resp.headers
        except urllib.error.HTTPError as err:
            raw = err.read(2_000_000)
            status = err.code
            rhead = err.headers
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            return (0, "transport_error:" + type(err).__name__, None)
        finally:
            self.last_elapsed = time.monotonic() - started
        try:
            calls, writes = rhead.get("X-Q05-Provider-Calls"), rhead.get("X-Q05-Provider-Writes")
            if calls is not None and writes is not None:
                self.last_provider = (int(calls), int(writes))
        except (TypeError, ValueError, AttributeError):
            self.last_provider = None
        text = raw.decode("utf-8", "replace")
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        return (status, text, obj)


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
class Discovery:
    """Everything learned about one tenant through its OWN token. The `markers`
    set holds victim-identifying strings used only for in-memory leak detection;
    they are never written to output."""

    def __init__(self, key, workspace):
        self.key = key
        self.workspace = workspace
        self.ok = False
        self.revision = None
        self.connections = []        # discord installation/webhook connection ids
        self.all_channel_ids = []    # every channel/connection id (any provider)
        self.identities = []         # discord identity link ids
        self.destinations = {}       # connection_id -> [stableId,...]
        self.jobs = []               # (job_id, approvalDigest-or-None)
        self.reviews = []
        self.variants = []
        self.members = []            # member user ids
        # The caller's OWN member entry ("you": true) when its role is owner, else None. The only safe
        # target for member_remove: the owner-differential DELETE of the owner is refused (409).
        self.owner_member = None
        # Customer sender names (RC2): connections by kind, the owner's own profile per connection
        # (fingerprint/name/kind, from its own GET), and whether this build serves the route at all
        # (True / False = route absent on this build / None = no Discord connection to ask about).
        self.webhooks = []
        self.installations = []
        self.sender = {}
        self.sender_feature = None
        self.sender_contract = None   # 1 = the integration-tip (v1) answers, 2 = docs/sender-name/UI-API-CONTRACT.md v2
        self.markers = set()

    def _mark(self, value):
        if isinstance(value, str) and len(value) >= 8:
            self.markers.add(value)


def discover(client, config, key):
    d = Discovery(key, config.workspace[key])
    tok = key
    status, _text, body = client.request("GET", f"/api/workspaces/{d.workspace}", tok)
    if status != 200 or not isinstance(body, dict):
        return d  # ok stays False; controls will catch an unusable tenant
    d.ok = True
    d.revision = body.get("revision")
    state = body.get("state") or {}
    phase2 = state.get("phase2") or {}
    for ch in phase2.get("channels", []) or []:
        if not isinstance(ch, dict):
            continue
        cid = ch.get("id")
        d.all_channel_ids.append(cid)
        d._mark(cid)
        d._mark(ch.get("account"))
        d._mark(ch.get("providerAccountId"))
        d._mark(ch.get("discordSenderName"))
        if ch.get("platform") == "Discord" and not ch.get("revoked"):
            d.connections.append(cid)
            if ch.get("discordConnectionKind") == "webhook":
                d.webhooks.append(cid)
            elif ch.get("discordConnectionKind") == "installation":
                d.installations.append(cid)
        for dest in ch.get("discordDestinations", []) or []:
            if isinstance(dest, dict):
                d._mark(dest.get("id"))
                d._mark(dest.get("channelId"))
                d._mark(dest.get("guildId"))
    # installations first, so the pre-existing connection cases keep targeting a bot installation
    d.connections = d.installations + [c for c in d.connections if c not in d.installations]
    for link in phase2.get("discordIdentityLinks", []) or []:
        if isinstance(link, dict) and link.get("id"):
            d.identities.append(link["id"])
            d._mark(link.get("id"))
            d._mark(link.get("userId"))
            d._mark(link.get("account"))
    for job in phase2.get("jobs", []) or []:
        if isinstance(job, dict) and job.get("id"):
            d.jobs.append((job["id"], job.get("approvalDigest")))
            d._mark(job.get("id"))
    for rv in phase2.get("reviews", []) or []:
        if isinstance(rv, dict) and rv.get("id"):
            d.reviews.append(rv["id"])
            d._mark(rv.get("id"))
    for v in state.get("variants", []) or []:
        if isinstance(v, dict) and v.get("id"):
            d.variants.append(v["id"])
            d._mark(v.get("id"))

    # Destinations per discord connection, via the tenant's own authorized read.
    for cid in d.connections:
        st, _t, b = client.request("GET", f"/api/workspaces/{d.workspace}/channels/{cid}/destinations", tok)
        if st == 200 and isinstance(b, dict):
            for dest in b.get("destinations", []) or []:
                if isinstance(dest, dict):
                    stable = dest.get("stableId") or dest.get("authorizedId") or dest.get("id")
                    if stable:
                        d.destinations.setdefault(cid, []).append(stable)
                        d._mark(stable)

    # Customer sender names: the owner's OWN profile of its first webhook and first installation. NOTE
    # this GET is not read-only on the RC2 line (it re-verifies the connection and records that), which
    # is why it runs here, before the attack-phase snapshot, and why owner differentials for these
    # routes run as controls after the attack phase.
    for cid in d.webhooks[:1] + d.installations[:1]:
        st, text, b = client.request("GET", f"/api/workspaces/{d.workspace}/channels/{cid}/{SENDER_ROUTE}", tok)
        err = error_body(b, text)
        if st == 200 and isinstance(b, dict) and isinstance(b.get("fingerprint"), str):
            d.sender_feature = True
            contract = b.get("contractVersion") if isinstance(b.get("contractVersion"), int) else 1
            feature = b.get("feature") if isinstance(b.get("feature"), dict) else {}
            d.sender[cid] = {"kind": b.get("senderKind"), "fingerprint": b["fingerprint"], "name": b.get("name"),
                             "contract": contract,
                             # v2 server-side switch, as this request saw it (v1 has none: always on)
                             "namesOn": feature.get("senderNames", True) is not False}
            d.sender_contract = max(d.sender_contract or 1, contract)
            d._mark(b.get("name"))
            d._mark(b.get("guildId"))
        elif st == 404 and err not in SENDER_404_BODIES:
            d.sender_feature = False if d.sender_feature is None else d.sender_feature   # route not served
        else:
            d.sender_feature = True   # the route answers (e.g. reconnect needed); its control will fail loudly
    if d.sender:
        # the v1 sender GET re-verifies and saves (revision bump): re-read the revision the owner controls use
        st, _t, b = client.request("GET", f"/api/workspaces/{d.workspace}", tok)
        if st == 200 and isinstance(b, dict):
            d.revision = b.get("revision")

    # Members (own read). Never treat members[0] as the owner: the app lists members ORDER BY role (text),
    # so admin/approver/editor sort BEFORE owner. Only the caller's own entry ("you") with role owner is
    # used as the member_remove target, so the owner-differential DELETE can only hit "the owner cannot be
    # removed" (409) and never removes a real member.
    st, _t, b = client.request("GET", f"/api/workspaces/{d.workspace}/members", tok)
    if st == 200 and isinstance(b, dict):
        for m in b.get("members", []) or []:
            if isinstance(m, dict) and m.get("userId"):
                d.members.append(m["userId"])
                d._mark(m.get("userId"))
                if (m.get("you") is True and m.get("role") == "owner"
                        and m.get("status", "active") == "active"):
                    d.owner_member = m["userId"]
    return d


# --------------------------------------------------------------------------- #
# Snapshot (API-level, per tenant, through its own reads)
# --------------------------------------------------------------------------- #
def snapshot(client, config, key):
    """A stable projection of a tenant's own state, for before/after comparison.
    Returns (digest, detail) where detail names only generic field groups."""
    tok = key
    ws = config.workspace[key]
    parts = {}
    status, _t, body = client.request("GET", f"/api/workspaces/{ws}", tok)
    if status != 200 or not isinstance(body, dict):
        return (None, {"reachable": False, "status": status})
    state = body.get("state") or {}
    phase2 = state.get("phase2") or {}
    parts["revision"] = body.get("revision")
    parts["channels"] = sorted(
        [(c.get("id"), c.get("discordAuthorizationGeneration"), bool(c.get("revoked")),
          c.get("displayState"), len(c.get("discordDestinations", []) or []))
         for c in phase2.get("channels", []) or [] if isinstance(c, dict)])
    parts["identities"] = sorted(
        [(x.get("id"), x.get("status"), x.get("authorizationGeneration"))
         for x in phase2.get("discordIdentityLinks", []) or [] if isinstance(x, dict)])
    parts["jobs"] = sorted(
        [(j.get("id"), j.get("state"), bool(j.get("cancelRequested")))
         for j in phase2.get("jobs", []) or [] if isinstance(j, dict)])
    parts["reviews"] = sorted(
        [r.get("id") for r in phase2.get("reviews", []) or [] if isinstance(r, dict)])
    parts["variants"] = len(state.get("variants", []) or [])

    st, _t, mbody = client.request("GET", f"/api/workspaces/{ws}/members", tok)
    # status is included: a member REMOVED during the attack phase stays listed as "revoked", so a
    # projection without status would miss exactly that side effect.
    parts["members"] = sorted(
        [(m.get("userId"), m.get("role"), m.get("status"),
          json.dumps(m.get("permissions") or m.get("flags") or {}, sort_keys=True))
         for m in (mbody.get("members", []) if st == 200 and isinstance(mbody, dict) else [])
         if isinstance(m, dict)])
    st, _t, abody = client.request("GET", f"/api/workspaces/{ws}/audit", tok)
    events = abody.get("events", []) if st == 200 and isinstance(abody, dict) else []
    # The server returns at most ~200 audit rows, so the count alone can miss a silent write that
    # adds one and ages one out. Also hash the newest rows' ids and timestamps.
    parts["auditCount"] = len(events) if isinstance(events, list) else None
    if isinstance(events, list):
        ids = sorted((str(e.get("id", "")), str(e.get("at", e.get("createdAt", e.get("timestamp", "")))))
                     for e in events if isinstance(e, dict))
        parts["auditDigest"] = hashlib.sha256(json.dumps(ids, sort_keys=True).encode()).hexdigest()
    else:
        parts["auditDigest"] = None

    canon = json.dumps(parts, sort_keys=True, default=str)
    digest = hashlib.sha256(canon.encode()).hexdigest()
    # Keep the raw parts in memory for a generic "what changed" diff; the detail
    # exposed to output names only the group, never values.
    return (digest, {"reachable": True, "parts": parts})


def snapshot_diff_groups(before_detail, after_detail):
    """Names of field groups that differ, with no values. Safe to print."""
    if not before_detail.get("reachable") or not after_detail.get("reachable"):
        return ["unreachable"]
    bp, ap = before_detail.get("parts", {}), after_detail.get("parts", {})
    changed = []
    for group in sorted(set(bp) | set(ap)):
        if bp.get(group) != ap.get(group):
            changed.append(group)
    return changed


# --------------------------------------------------------------------------- #
# Case model
# --------------------------------------------------------------------------- #
class Case:
    def __init__(self, cid, method, template, direction, kind, blast, path,
                 token_key, *, body=None, mutation=False, expected=("403", "404"),
                 needs=None, victim_key=None, scope=None, differential=False,
                 owner_token_key=None, twin_path=None, expect_status=None, expect_body=None,
                 expect_prefix=None, deferred=None, expect_pairs=None, role_profile=None, late=False):
        self.cid = cid
        self.method = method
        self.template = template
        self.direction = direction          # "A->B", "B->A", or "control"
        self.kind = kind                      # "read", "write", "control"
        self.blast = blast                    # "inert", "state", "send", or "" for reads/controls
        self.path = path
        self.token_key = token_key
        self.body = body
        self.mutation = mutation
        self.expected = list(expected)
        self.needs = needs                    # None, or ("why it could not be built")
        self.victim_key = victim_key          # which tenant owns the data being attacked
        # how the denial is scored: "ws_scope" (403 + the gate body) or "idor" (404/409 + an
        # object-binding body). None for controls.
        self.scope = scope
        # ws_scope differential: the legitimate owner of the attacked workspace sends the
        # identical request and must get PAST the gate (any answer that is not the gate 403).
        self.differential = differential
        self.owner_token_key = owner_token_key
        # existence oracle: the same request aimed at an id that has never existed must get the SAME
        # answer (status, error, code); a different answer tells an attacker the victim object exists.
        self.twin_path = twin_path
        # "role"/"validation" scopes, and non-2xx controls: the exact expected answer.
        self.expect_status = expect_status
        self.expect_body = expect_body
        self.expect_prefix = expect_prefix
        # "role" scope: the accepted (status, error body) answers of another member of the same workspace,
        # or, for a GET a member may make, the profile it must get ("readonly": a 200 offering no edit and
        # answered without Discord; "manager": a read-only profile OR an editable one, never a write).
        self.expect_pairs = expect_pairs
        self.role_profile = role_profile
        # run after the attack phase (a same-workspace read the contract allows may read Discord)
        self.late = late
        # a ws_scope differential that cannot run inline (the owner's request has its own write side
        # effects on this line): it is the named control, run after the attack phase; if that control
        # does not PASS, this case is downgraded to INCONCLUSIVE.
        self.deferred = deferred
        # results
        self.observed = None
        self.owner_observed = None
        self.twin_observed = None
        self.timing = None
        self.verdict = None
        self.note = ""


# Exact deny bodies, read from the RC source (hosted.py / store.py / oauth.py / discord/oauth.py).
# Compared in memory against a response's "error" field; never printed.
GATE_DENY_BODY = "Workspace unavailable."   # the uniform tenant membership gate (403)
IDOR_DENY_BODIES = frozenset({
    "Connection unavailable.",                                     # oauth._member_grant / _disconnect
    "This item is not available in your workspace.",               # store.find (jobs)
    "This Discord identity is unavailable to this workspace member.",  # discord identity_record
    "Connection request unavailable.",                             # discord OAuth state binding
    "This Discord connection is unavailable.",                     # discord sender_names custody (RC2)
})

# Customer Discord sender names (RC2): GET/POST /api/workspaces/{ws}/channels/{conn}/discord-sender-name.
# Bodies read from the RC2 source (discord/sender_names.py, permissions.py); compared in memory only.
SENDER_ROUTE = "discord-sender-name"
SENDER_404_BODIES = frozenset({"This Discord connection is unavailable.",
                               "This Discord identity is unavailable to this workspace member."})
PERMISSION_DENY_BODY = "This action needs the 'manage_connections' permission in this workspace."
AUTHORIZER_DENY_BODY = "Only this webhook’s authorizing member can change its sender name."
SENDER_STALE_BODY = "Discord sender settings changed. Reload and review the name again."
NAME_RULE_PREFIX = "Choose a name of 1–"
# A well-formed POST body whose fingerprint can never be current: the owner's identical request gets past
# every authorization check and stops at the fingerprint compare (409), so it can never rename anything.
STALE_SENDER_BODY = {"name": "Q05 probe name", "fingerprint": "0" * 64, "confirmed": True,
                     "sharedServerConfirmed": True}
# Never-existing ids for the existence-oracle twins (same shape as real ones).
NONEXISTENT_WORKSPACE = "00000000-0000-4000-8000-000000000e05"
NONEXISTENT_CONNECTION = {"webhook": "discord-webhook-00000000-0000-5000-8000-000000000e05",
                          "bot": "discord-installation-00000000-0000-5000-8000-000000000e05"}
# Statuses that are neither a clean deny nor a clear accept: a run that sees one on an attack
# cannot conclude isolation holds, so it is INCONCLUSIVE (a failure of the run), never a PASS.
INCONCLUSIVE_STATUSES = {400, 401, 405, 410, 415, 429}


def error_body(obj, text):
    """The app's error message from a parsed JSON body, or None for a non-JSON/HTML response.
    Returned for in-memory comparison only; callers must never print it."""
    if isinstance(obj, dict) and isinstance(obj.get("error"), str):
        return obj["error"]
    return None


def jwt_sub(token):
    """The `sub` claim from a JWT access token, locally (base64, no network), or None. Never printed."""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        payload = json.loads(base64.urlsafe_b64decode(seg.encode()))
        sub = payload.get("sub")
        return sub if isinstance(sub, str) and sub else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Case matrix
# --------------------------------------------------------------------------- #
def build_matrix(disc, config, flags):
    """Return a list[Case] for both directions plus controls. `disc` maps 'A'/'B'
    to Discovery."""
    cases = []

    # ---- attack cases, for each direction ---------------------------------- #
    for attacker in ("A", "B"):
        victim = OTHER[attacker]
        a_ws = config.workspace[attacker]
        v_ws = config.workspace[victim]
        d_v = disc[victim]
        arrow = f"{attacker}->{victim}"
        vph = f"<{victim}.workspace>"
        aph = f"<{attacker}.workspace>"
        # Deliberately-stale revision: no workspace revision is ever negative, so expectedRevision -1
        # always loses the revision compare-and-swap (409) AFTER the membership gate — the attacker
        # hits the gate (403) first, and the owner-differential request gets a harmless 409, never a
        # mutation.
        STALE = -1

        # ---------- READ, style (i): victim workspace id in path (differential) ---------- #
        for suffix, tail in (("get", ""), ("members", "/members"), ("audit", "/audit"),
                             ("invitations", "/invitations"), ("export", "/export"),
                             ("channels", "/channels"), ("analytics", "/analytics/summary"),
                             ("memory", "/memory")):
            cases.append(Case(
                f"read.ws_scope.{suffix}.{arrow}", "GET",
                f"/api/workspaces/{vph}{tail}", arrow, "read", "",
                f"/api/workspaces/{v_ws}{tail}", attacker, victim_key=victim,
                scope="ws_scope", differential=True, owner_token_key=victim))

        # ---------- READ, style (ii): own workspace id + victim object id (IDOR) ---------- #
        if d_v.connections:
            vconn = d_v.connections[0]
            cases.append(Case(
                f"read.idor.destinations.{arrow}", "GET",
                f"/api/workspaces/{aph}/channels/<{victim}.connection>/destinations",
                arrow, "read", "",
                f"/api/workspaces/{a_ws}/channels/{vconn}/destinations", attacker,
                victim_key=victim, scope="idor"))
        else:
            cases.append(_not_built(f"read.idor.destinations.{arrow}", "GET",
                f"/api/workspaces/{aph}/channels/<{victim}.connection>/destinations",
                arrow, "read", "", victim, "no discord connection discovered for victim"))

        if d_v.identities:
            vid = d_v.identities[0]
            cases.append(Case(
                f"read.idor.identity_guilds.{arrow}", "GET",
                f"/api/workspaces/{aph}/discord/identities/<{victim}.identity>/guilds",
                arrow, "read", "",
                f"/api/workspaces/{a_ws}/discord/identities/{vid}/guilds", attacker,
                victim_key=victim, scope="idor"))
            cases.append(Case(
                f"read.idor.private_review.{arrow}", "GET",
                f"/api/workspaces/{aph}/discord/private-review/<{victim}.identity>",
                arrow, "read", "",
                f"/api/workspaces/{a_ws}/discord/private-review/{vid}", attacker,
                victim_key=victim, scope="idor"))
        else:
            for sfx, tailtmpl in (("identity_guilds", "/discord/identities/<%s.identity>/guilds"),
                                  ("private_review", "/discord/private-review/<%s.identity>")):
                cases.append(_not_built(f"read.idor.{sfx}.{arrow}", "GET",
                    f"/api/workspaces/{aph}" + (tailtmpl % victim),
                    arrow, "read", "", victim, "no discord identity discovered for victim"))

        # ---------- WRITE, style (i): victim workspace id in path ------------- #
        # Differential writes: the owner's identical request gets a harmless 409 (stale revision)
        # or 409 (owner-cannot-be-removed), i.e. PAST the gate, while the attacker gets the gate 403.
        cases.append(Case(
            f"write.ws_scope.mutate_mode.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "mode", "payload": {"mode": "personal"}, "expectedRevision": STALE},
            mutation=True, victim_key=victim, scope="ws_scope", differential=True, owner_token_key=victim))
        cases.append(Case(
            f"write.ws_scope.mutate_refresh.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "inert",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "p2_refresh", "payload": {}, "expectedRevision": STALE},
            mutation=True, victim_key=victim, scope="ws_scope", differential=True, owner_token_key=victim))
        cases.append(Case(
            f"write.ws_scope.approve.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "p2_approve", "payload": {"reviewId": "q05", "digest": "q05", "confirmed": True},
                  "expectedRevision": STALE}, mutation=True, victim_key=victim,
            scope="ws_scope", differential=True, owner_token_key=victim))
        cases.append(Case(
            f"write.ws_scope.cancel.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "p2_cancel", "payload": {"jobId": "q05"}, "expectedRevision": STALE},
            mutation=True, victim_key=victim, scope="ws_scope", differential=True, owner_token_key=victim))
        if d_v.owner_member:
            # ONLY the victim owner's own entry: its owner-differential DELETE removes "self" -> 409
            # "The owner cannot be removed." Any other member would really be removed by the owner.
            vmember = d_v.owner_member
            cases.append(Case(
                f"write.ws_scope.member_remove.{arrow}", "DELETE",
                f"/api/workspaces/{vph}/members/<{victim}.owner>", arrow, "write", "state",
                f"/api/workspaces/{v_ws}/members/{vmember}", attacker,
                mutation=True, victim_key=victim, scope="ws_scope", differential=True, owner_token_key=victim))
        else:
            cases.append(_not_built(f"write.ws_scope.member_remove.{arrow}", "DELETE",
                f"/api/workspaces/{vph}/members/<{victim}.owner>", arrow, "write", "state",
                victim, "victim's own owner entry not found in its member list (never target another member)"))
        # invite and connect-start are strict-attacker (no owner differential: a legitimate owner
        # request would mutate / send an e-mail). Gate removal still turns them FAIL (2xx or past-gate).
        cases.append(Case(
            f"write.ws_scope.invite.{arrow}", "POST",
            f"/api/workspaces/{vph}/invitations", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/invitations", attacker,
            body={"email": "q05-probe@example.invalid", "role": "viewer", "permissions": {}},
            mutation=True, victim_key=victim, scope="ws_scope"))
        cases.append(Case(
            f"write.ws_scope.discord_connect_start.{arrow}", "POST",
            f"/api/workspaces/{vph}/channels/discord/oauth/start", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/channels/discord/oauth/start", attacker,
            body={"capability": "identity", "input": {"discordPurpose": "identity"}},
            mutation=True, victim_key=victim, scope="ws_scope"))

        # ---------- WRITE, style (ii)/(iii): own ws + victim object id (IDOR) -------- #
        if d_v.connections:
            vconn = d_v.connections[0]
            cases.append(Case(
                f"write.idor.destination_choose.{arrow}", "POST",
                f"/api/workspaces/{aph}/channels/<{victim}.connection>/destination",
                arrow, "write", "state",
                f"/api/workspaces/{a_ws}/channels/{vconn}/destination", attacker,
                body={"destinationId": "100000000000000001"}, mutation=True, victim_key=victim, scope="idor"))
            cases.append(Case(
                f"write.idor.channel_disconnect.{arrow}", "DELETE",
                f"/api/workspaces/{aph}/channels/<{victim}.connection>",
                arrow, "write", "state",
                f"/api/workspaces/{a_ws}/channels/{vconn}", attacker,
                mutation=True, victim_key=victim, scope="idor"))
            if d_v.destinations.get(vconn):
                vdest = d_v.destinations[vconn][0]
                cases.append(Case(
                    f"write.idor.destination_remove.{arrow}", "DELETE",
                    f"/api/workspaces/{aph}/channels/<{victim}.connection>/destinations/<{victim}.destination>",
                    arrow, "write", "state",
                    f"/api/workspaces/{a_ws}/channels/{vconn}/destinations/{vdest}", attacker,
                    mutation=True, victim_key=victim, scope="idor"))
            else:
                cases.append(_not_built(f"write.idor.destination_remove.{arrow}", "DELETE",
                    f"/api/workspaces/{aph}/channels/<{victim}.connection>/destinations/<{victim}.destination>",
                    arrow, "write", "state", victim, "no victim destination discovered"))
        else:
            for sfx in ("destination_choose", "channel_disconnect", "destination_remove"):
                cases.append(_not_built(f"write.idor.{sfx}.{arrow}",
                    "POST" if sfx == "destination_choose" else "DELETE",
                    f"/api/workspaces/{aph}/channels/<{victim}.connection>/...",
                    arrow, "write", "state", victim, "no discord connection discovered for victim"))
        if d_v.identities:
            vid = d_v.identities[0]
            cases.append(Case(
                f"write.idor.identity_disconnect.{arrow}", "POST",
                f"/api/workspaces/{aph}/discord/identities/<{victim}.identity>/disconnect",
                arrow, "write", "state",
                f"/api/workspaces/{a_ws}/discord/identities/{vid}/disconnect", attacker,
                mutation=True, victim_key=victim, scope="idor"))
            # /discord/interaction-links/<id>/bind is intentionally excluded (User-Install feature
            # OFF at launch; same identity_record() boundary as identities/disconnect; see
            # EXCLUDED_FAMILIES["interaction-links"]).
        else:
            cases.append(_not_built(f"write.idor.identity_disconnect.{arrow}", "POST",
                f"/api/workspaces/{aph}/discord/identities/<{victim}.identity>/disconnect",
                arrow, "write", "state", victim, "no discord identity discovered for victim"))

        # ---------- WRITE, blast=send: dispatch-capable routes ---------------- #
        if d_v.jobs:
            vjob, vdigest = d_v.jobs[0]
            cases.append(Case(
                f"write.send.job_execute_ws_scope.{arrow}", "POST",
                f"/api/workspaces/{vph}/jobs/<{victim}.job>/execute", arrow, "write", "send",
                f"/api/workspaces/{v_ws}/jobs/{vjob}/execute", attacker,
                body={"approvalDigest": vdigest or "0" * 64}, mutation=True, victim_key=victim, scope="ws_scope"))
            cases.append(Case(
                f"write.send.job_execute_idor.{arrow}", "POST",
                f"/api/workspaces/{aph}/jobs/<{victim}.job>/execute", arrow, "write", "send",
                f"/api/workspaces/{a_ws}/jobs/{vjob}/execute", attacker,
                body={"approvalDigest": vdigest or "0" * 64}, mutation=True, victim_key=victim, scope="idor"))
        else:
            cases.append(_not_built(f"write.send.job_execute_ws_scope.{arrow}", "POST",
                f"/api/workspaces/{vph}/jobs/<{victim}.job>/execute", arrow, "write", "send",
                victim, "no job discovered for victim"))
            cases.append(_not_built(f"write.send.job_execute_idor.{arrow}", "POST",
                f"/api/workspaces/{aph}/jobs/<{victim}.job>/execute", arrow, "write", "send",
                victim, "no job discovered for victim"))

        # ---------- WRITE, style (iii): OAuth state binding ------------------- #
        vstate = config.victim_oauth_state[victim]
        if vstate:
            cases.append(Case(
                f"write.state_binding.oauth_complete.{arrow}", "POST",
                f"/api/workspaces/{aph}/channels/discord/oauth/complete",
                arrow, "write", "state",
                f"/api/workspaces/{a_ws}/channels/discord/oauth/complete", attacker,
                body={"state": vstate, "code": "q05-probe-code"}, mutation=True, victim_key=victim, scope="idor"))
        else:
            cases.append(_not_built(f"write.state_binding.oauth_complete.{arrow}", "POST",
                f"/api/workspaces/{aph}/channels/discord/oauth/complete",
                arrow, "write", "state", victim,
                "no victim OAuth state provided (Q05_VICTIM_%s_OAUTH_STATE)" % victim))

    # ---- positive controls: the owner succeeds through the same route ------- #
    for owner in ("A", "B"):
        o_ws = config.workspace[owner]
        d_o = disc[owner]
        oph = f"<{owner}.workspace>"
        cases.append(Case(f"control.ws_get.{owner}", "GET",
            f"/api/workspaces/{oph}", "control", "control", "",
            f"/api/workspaces/{o_ws}", owner, expected=("200",)))
        cases.append(Case(f"control.members.{owner}", "GET",
            f"/api/workspaces/{oph}/members", "control", "control", "",
            f"/api/workspaces/{o_ws}/members", owner, expected=("200",)))
        cases.append(Case(f"control.audit.{owner}", "GET",
            f"/api/workspaces/{oph}/audit", "control", "control", "",
            f"/api/workspaces/{o_ws}/audit", owner, expected=("200",)))
        cases.append(Case(f"control.channels.{owner}", "GET",
            f"/api/workspaces/{oph}/channels", "control", "control", "",
            f"/api/workspaces/{o_ws}/channels", owner, expected=("200",)))
        if d_o.connections:
            oconn = d_o.connections[0]
            cases.append(Case(f"control.destinations.{owner}", "GET",
                f"/api/workspaces/{oph}/channels/<{owner}.connection>/destinations",
                "control", "control", "",
                f"/api/workspaces/{o_ws}/channels/{oconn}/destinations", owner, expected=("200",)))
        else:
            cases.append(_not_built(f"control.destinations.{owner}", "GET",
                f"/api/workspaces/{oph}/channels/<{owner}.connection>/destinations",
                "control", "control", "", owner, "owner has no discord connection to control"))
        if d_o.identities:
            oid = d_o.identities[0]
            cases.append(Case(f"control.identity_guilds.{owner}", "GET",
                f"/api/workspaces/{oph}/discord/identities/<{owner}.identity>/guilds",
                "control", "control", "",
                f"/api/workspaces/{o_ws}/discord/identities/{oid}/guilds", owner, expected=("200",)))
        else:
            # Fresh accounts (and every account on a build without Discord v2) have no identity: emit the
            # NOT RUN placeholder so the fixed expected-case list is complete. It counts as undiscovered:
            # tolerated by --smoke, a failure in gate mode.
            cases.append(_not_built(f"control.identity_guilds.{owner}", "GET",
                f"/api/workspaces/{oph}/discord/identities/<{owner}.identity>/guilds",
                "control", "control", "", owner, "owner has no discord identity to control"))
        # write control (inert): refresh action succeeds for the owner, proving
        # the write route is reachable so a denied cross-tenant write is a real
        # deny and not a globally broken/blocked route.
        cases.append(Case(f"control.write_refresh.{owner}", "POST",
            f"/api/workspaces/{oph}/actions", "control", "control", "inert",
            f"/api/workspaces/{o_ws}/actions", owner,
            body={"action": "p2_refresh", "payload": {}, "expectedRevision": d_o.revision},
            mutation=True, expected=("200",)))

    cases.extend(build_channel_cases(disc, config))
    cases.extend(build_sender_cases(disc, config))
    return cases


def _not_built(cid, method, template, direction, kind, blast, victim_key, why):
    c = Case(cid, method, template, direction, kind, blast, None, None,
             victim_key=victim_key)
    c.needs = why
    return c


def _not_applicable(cid, method, template, direction, kind, blast, victim_key, why):
    """NOT RUN because the build does not serve the route at all (no hole can exist in a route that is
    not there). Reported loudly, does not fail the probe's exit; a hosted GATE run still fails on any
    NOT RUN case, and gate runs are pinned to the reviewed build."""
    c = _not_built(cid, method, template, direction, kind, blast, victim_key, why)
    c.not_applicable = True
    return c


# --------------------------------------------------------------------------- #
# Customer Discord sender names (RC2)
# --------------------------------------------------------------------------- #
def _sender_post(fingerprint, name="Q05 probe name"):
    return {"name": name, "fingerprint": fingerprint, "confirmed": True, "sharedServerConfirmed": True}


UNAVAILABLE_BODY = "This Discord sender name cannot be changed right now."   # v2 discord_sender_name_unavailable
IDENTITY_DENY_BODY = "This Discord identity is unavailable to this workspace member."
# which roles are probed against which connection kinds (the permission and gate checks precede the
# kind-specific custody, so viewer/editor/removed are probed on the webhook only)
ROLE_KINDS = {"viewer": ("webhook",), "editor": ("webhook",), "connmgr": ("webhook", "bot"),
              "admin": ("webhook", "bot"), "removed": ("webhook",)}
# Contract v2 throttles sender-name POSTs to 6 per 10 minutes per connection and 15 per workspace, counting
# every POST that gets past the gate, the role check and the connection lookup. The owner's webhook needs 5
# (stale control, one invalid name, save / stale replay / restore), so a non-authorizing manager's POST is
# probed with the admin only (the connection manager's would be the same answer).
ROLE_POST_SKIP = {("connmgr", "bot"), ("connmgr", "webhook")}


def role_expect(role, kind, method, contract):
    """What another member of the SAME workspace must get, per sender-name contract version.
    Returns (accepted (status, error body) pairs, twin?, profile). profile is None for a refusal, else the
    200 a GET must answer: "readonly" (editable false with not_authorizing_member, answered without any
    Discord read) or "manager" (readonly, or an editable profile of exactly that connection; never a write).
    A "manager" GET runs after the attack phase, since the contract lets it read Discord."""
    if role in ("viewer", "editor"):
        # A member without connection-management: refused before any object is read (the contract says to
        # branch on the code, permission_denied; the earlier draft named the gate body, also accepted). The
        # never-existing-connection twin must get the same answer.
        return {(403, PERMISSION_DENY_BODY), (403, GATE_DENY_BODY)}, True, None
    if role == "removed":
        return {(403, GATE_DENY_BODY)}, True, None                    # no longer a member: the tenant gate
    # connmgr / admin: hold connection-management, but did not authorize this connection
    if contract >= 2:
        if kind == "webhook":
            # Contract head: a webhook name is a Rafii setting that any member with connection-management may
            # edit (only a bot nickname, a shared Discord object, is authorizer-only); an authorizer-only build
            # is stricter and also accepted. The probe's never-current fingerprint is refused either way.
            if method == "GET":
                return set(), False, "manager"
            return {(403, UNAVAILABLE_BODY), (409, SENDER_STALE_BODY)}, False, None
        if method == "GET":
            return set(), False, "readonly"
        return {(403, UNAVAILABLE_BODY)}, False, None
    if kind == "webhook":
        return {(403, AUTHORIZER_DENY_BODY)}, False, None
    return {(404, IDENTITY_DENY_BODY)}, False, None


MALFORMED_CONNECTIONS = (("short", "x"), ("dots", ".."), ("quote", "discord-webhook-%27%20OR%201%3D1--"),
                         ("long", "A" * 300))
# One: every owner POST counts against the per-connection throttle (see ROLE_POST_SKIP). A reserved word
# (Discord's own name) is the impersonation rule that matters for a sender name.
BAD_NAMES = (("reserved", "Discord official"),)


def _sender_clear(fingerprint):
    """The contract's "clear" body (webhook only): remove the saved name."""
    return {"reset": True, "fingerprint": fingerprint, "confirmed": True}


CHANNEL_ROUTES = (
    # (case id stem, method, path tail, kind, blast, scope, owner control that is the deferred differential)
    ("channel_verify", "POST", "verify", "write", "state", "ws_scope", "control.channel_verify"),
    ("channel_verify", "POST", "verify", "write", "state", "idor", None),
    ("creator_info", "GET", "creator-info", "read", "", "ws_scope", None),
    ("picture", "GET", "picture", "read", "", "ws_scope", None),
    ("history_preview", "POST", "posts", "write", "inert", "ws_scope", None),
    ("refresh_authorization", "POST", "refresh-authorization", "write", "state", "ws_scope", None),
)


def build_channel_cases(disc, config):
    """Per-connection channel routes: verify (through the victim's workspace: the gate, with the victim owner's
    own verify as the deferred differential; through the attacker's workspace: the credential lookup), and
    creator-info, picture, history preview and refresh-authorization as workspace-scope denies. Every case
    is compared with a never-existing id (workspace for the gate, connection for the lookup)."""
    cases = []

    def route(ws, conn, tail):
        return f"/api/workspaces/{ws}/channels/{conn}/{tail}"

    for attacker in ("A", "B"):
        victim = OTHER[attacker]
        a_ws, v_ws, d_v = config.workspace[attacker], config.workspace[victim], disc[victim]
        arrow = f"{attacker}->{victim}"
        vconn = (d_v.installations or d_v.connections or [None])[0]
        for stem, method, tail, ck, blast, scope, control in CHANNEL_ROUTES:
            cid = f"{ck}.{scope}.{stem}.{arrow}"
            ws_ph = f"<{victim}.workspace>" if scope == "ws_scope" else f"<{attacker}.workspace>"
            tmpl = f"/api/workspaces/{ws_ph}/channels/<{victim}.connection>/{tail}"
            if not vconn:
                cases.append(_not_built(cid, method, tmpl, arrow, ck, blast, victim,
                                        "no discord connection discovered for victim"))
                continue
            twin = (route(NONEXISTENT_WORKSPACE, vconn, tail) if scope == "ws_scope"
                    else route(a_ws, NONEXISTENT_CONNECTION["bot"], tail))
            cases.append(Case(cid, method, tmpl, arrow, ck, blast,
                              route(v_ws if scope == "ws_scope" else a_ws, vconn, tail), attacker,
                              body={} if method == "POST" else None, mutation=(method == "POST"),
                              victim_key=victim, scope=scope, twin_path=twin,
                              deferred=f"{control}.{victim}" if control else None))
    for owner in ("A", "B"):
        d_o, o_ws = disc[owner], config.workspace[owner]
        oconn = (d_o.installations or d_o.connections or [None])[0]
        cid, tmpl = f"control.channel_verify.{owner}", f"/api/workspaces/<{owner}.workspace>/channels/<{owner}.connection>/verify"
        if not oconn:
            cases.append(_not_built(cid, "POST", tmpl, "control", "control", "", owner,
                                    "owner has no discord connection to verify"))
        else:
            # the owner's own verify reads Discord (about five requests) and records the result: a control,
            # run after the attack phase
            cases.append(Case(cid, "POST", tmpl, "control", "control", "", route(o_ws, oconn, "verify"), owner,
                              body={}, mutation=True, expected=("200",)))
    return cases


PREREQUISITE_NOTE = "build prerequisite: sender-name switch or webhook route is off"


def _sender_prerequisite(disc, absent):
    """One named case for the build the sender-name cases need: the master switch and the webhook route ON and an
    incoming-webhook connection in each account. Without it a gate run fails with this one message instead of
    a row of anonymous NOT RUN cases."""
    c = Case("prerequisite.sender_names", "-", "(sender-name switch, webhook route, one webhook per account)",
             "control", "control", "", None, None, expected=("on",), scope="prerequisite")
    if all(absent.values()):
        return _not_applicable(c.cid, c.method, c.template, "control", "control", "", None,
                               "sender-name route not served by this build")
    lacking = [k for k in ("A", "B") if absent[k] or (disc[k].sender_feature and (
        not disc[k].webhooks or any(p.get("namesOn") is False for p in disc[k].sender.values())))]
    if not lacking and any(disc[k].sender_feature is None for k in ("A", "B")):
        # no Discord connection at all in an account: nothing to read the settings from (fresh accounts)
        return _not_built(c.cid, c.method, c.template, "control", "control", "", None,
                          "no discord connection discovered to read the sender-name settings from")
    c.prereq_ok = not lacking
    c.prereq_note = PREREQUISITE_NOTE + (f" (or account(s) {', '.join(lacking)} have no incoming-webhook connection)"
                                         if lacking else "")
    return c


def build_sender_cases(disc, config):
    """Sender-name cases. Attacks (cross-tenant, mixed ids, other members of the same workspace,
    malformed ids) run in the attack phase and never reach the provider; the owner controls — which on
    this line re-verify and record (writes) — run after the attack phase and double as the deferred
    differentials of the workspace-scope attacks."""
    cases = []
    absent = {k: disc[k].sender_feature is False for k in ("A", "B")}
    na_why = "sender-name route not served by this build"
    cases.append(_sender_prerequisite(disc, absent))

    def route(ws, conn):
        return f"/api/workspaces/{ws}/channels/{conn}/{SENDER_ROUTE}"

    # ---- cross-tenant: victim workspace (gate) and own workspace + victim connection (IDOR) ------- #
    for attacker in ("A", "B"):
        victim = OTHER[attacker]
        a_ws, v_ws = config.workspace[attacker], config.workspace[victim]
        d_a, d_v = disc[attacker], disc[victim]
        arrow = f"{attacker}->{victim}"
        vph, aph = f"<{victim}.workspace>", f"<{attacker}.workspace>"
        for kind, vlist in (("webhook", d_v.webhooks), ("bot", d_v.installations)):
            vconn = vlist[0] if vlist else None
            prof = d_v.sender.get(vconn) if vconn else None
            t_ws = f"/api/workspaces/{vph}/channels/<{victim}.{kind}>/{SENDER_ROUTE}"
            t_idor = f"/api/workspaces/{aph}/channels/<{victim}.{kind}>/{SENDER_ROUTE}"
            specs = (
                # id, method, template, kind, blast, scope, workspace in path, body, deferred owner differential
                (f"read.sender.ws_scope.{kind}.{arrow}", "GET", t_ws, "read", "", "ws_scope", v_ws, None,
                 f"control.sender.get.{kind}.{victim}"),
                (f"write.sender.ws_scope.{kind}.{arrow}", "POST", t_ws, "write", "state", "ws_scope", v_ws,
                 STALE_SENDER_BODY, f"control.sender.post_stale.{kind}.{victim}"),
                (f"read.sender.idor.{kind}.{arrow}", "GET", t_idor, "read", "", "idor", a_ws, None, None),
                (f"write.sender.idor.{kind}.{arrow}", "POST", t_idor, "write", "state", "idor", a_ws,
                 STALE_SENDER_BODY, None),
                # the victim's REAL current fingerprint, replayed. The fingerprint also binds the member who
                # read it, so without the gate this replay would still fail at the fingerprint compare (409);
                # the case proves the GATE stops it first (403). No owner differential: the owner's identical
                # request would succeed and rename.
                (f"write.sender.replay_ws_scope.{kind}.{arrow}", "POST", t_ws, "write", "state", "ws_scope",
                 v_ws, "victim-fingerprint", None),
            ) + ((
                # CLEAR the victim's saved webhook name with its real fingerprint, through the victim's workspace
                # (the gate) and through the attacker's own workspace (the connection lookup); both refused before
                # any throttle is counted, and the IDOR one against a never-existing-connection twin
                (f"write.sender.ws_scope_clear.{kind}.{arrow}", "POST", t_ws, "write", "state", "ws_scope",
                 v_ws, "victim-clear", None),
                (f"write.sender.idor_clear.{kind}.{arrow}", "POST", t_idor, "write", "state", "idor",
                 a_ws, "victim-clear", None),
            ) if kind == "webhook" else ())
            for cid, method, tmpl, ck, blast, scope, ws_path, body, deferred in specs:
                if absent[victim]:
                    cases.append(_not_applicable(cid, method, tmpl, arrow, ck, blast, victim, na_why))
                    continue
                real_fp = body in ("victim-fingerprint", "victim-clear")
                if not vconn or (real_fp and not prof):
                    cases.append(_not_built(cid, method, tmpl, arrow, ck, blast, victim,
                                            f"no victim {kind} connection"
                                            + (" sender profile" if real_fp else "") + " discovered"))
                    continue
                if body == "victim-fingerprint":
                    body = _sender_post(prof["fingerprint"])
                elif body == "victim-clear":
                    body = _sender_clear(prof["fingerprint"])
                # existence twins: every gate case; the IDOR GET and the IDOR clear (the connection lookup
                # precedes the throttle, so neither spends a POST of the attacker's own budget)
                twin = (route(NONEXISTENT_WORKSPACE, vconn) if scope == "ws_scope"
                        else route(a_ws, NONEXISTENT_CONNECTION[kind]) if method == "GET" or "clear" in cid
                        else None)
                cases.append(Case(cid, method, tmpl, arrow, ck, blast, route(ws_path, vconn), attacker,
                                  body=body, mutation=(method == "POST"), victim_key=victim, scope=scope,
                                  twin_path=twin, deferred=deferred))
        # mixed: the attacker's OWN webhook id under the victim's workspace id -> the gate. For the GET the
        # victim owner's identical request stops at "connection unavailable" before any re-verification, so
        # that differential runs inline; the POST uses the deferred owner control (one fewer throttled POST).
        own = d_a.webhooks[0] if d_a.webhooks else None
        for method, ck, blast in (("GET", "read", ""), ("POST", "write", "state")):
            cid = f"{ck}.sender.mixed.{arrow}"
            tmpl = f"/api/workspaces/{vph}/channels/<{attacker}.webhook>/{SENDER_ROUTE}"
            if absent[attacker] or absent[victim]:
                cases.append(_not_applicable(cid, method, tmpl, arrow, ck, blast, victim, na_why))
            elif not own:
                cases.append(_not_built(cid, method, tmpl, arrow, ck, blast, victim,
                                        "no attacker webhook connection discovered"))
            else:
                inline = method == "GET"
                cases.append(Case(cid, method, tmpl, arrow, ck, blast, route(v_ws, own), attacker,
                                  body=STALE_SENDER_BODY if method == "POST" else None, mutation=(method == "POST"),
                                  victim_key=victim, scope="ws_scope", differential=inline,
                                  owner_token_key=victim if inline else None,
                                  twin_path=route(NONEXISTENT_WORKSPACE, own),
                                  deferred=None if inline else f"control.sender.post_stale.webhook.{victim}"))
        # malformed ids from the attacker's own workspace: a clean 4xx, never 2xx/5xx, never the provider
        for label, conn in MALFORMED_CONNECTIONS + (("ws", None),):
            for method, ck, blast in (("GET", "read", ""),):
                cid = f"{ck}.sender.malformed.{label}.{attacker}"
                tmpl = (f"/api/workspaces/<malformed>/channels/<{victim}.webhook>/{SENDER_ROUTE}" if conn is None
                        else f"/api/workspaces/{aph}/channels/<malformed:{label}>/{SENDER_ROUTE}")
                if absent[attacker]:
                    cases.append(_not_applicable(cid, method, tmpl, attacker, ck, blast, victim, na_why))
                    continue
                if conn is None and not d_v.webhooks:
                    cases.append(_not_built(cid, method, tmpl, attacker, ck, blast, victim,
                                            "no victim webhook connection discovered"))
                    continue
                path = route("not-a-workspace-id", d_v.webhooks[0]) if conn is None else route(a_ws, conn)
                cases.append(Case(cid, method, tmpl, attacker, ck, blast, path, attacker,
                                  body=STALE_SENDER_BODY if method == "POST" else None, mutation=(method == "POST"),
                                  victim_key=victim, scope="malformed"))

    # ---- other members of the SAME workspace: viewer/editor vs connection managers vs removed ------ #
    contract = max([d.sender_contract for d in disc.values() if d.sender_contract] or [1])
    for owner in ("A", "B"):
        d_o, o_ws, oph = disc[owner], config.workspace[owner], f"<{owner}.workspace>"
        for role in ROLE_KEYS:
            tok_key = f"{owner}.{role}"
            for kind in ROLE_KINDS[role]:
                olist = d_o.webhooks if kind == "webhook" else d_o.installations
                oconn = olist[0] if olist else None
                for method, ck, blast in (("GET", "read", ""), ("POST", "write", "state")):
                    if method == "POST" and (role, kind) in ROLE_POST_SKIP:
                        continue
                    pairs, twin, profile = role_expect(role, kind, method, contract)
                    cid = f"{ck}.sender.role.{role}.{kind}.{owner}"
                    tmpl = f"/api/workspaces/{oph}/channels/<{owner}.{kind}>/{SENDER_ROUTE}"
                    direction = f"{owner}:{role}"
                    if absent[owner]:
                        cases.append(_not_applicable(cid, method, tmpl, direction, ck, blast, None, na_why))
                    elif not config.token.get(tok_key):
                        # The hosted run signs in the two owners only, so same-workspace roles run in the local
                        # harness (exact SHA). Reported NOT RUN (local-only); scope "role" lets the hosted gate
                        # tell these apart from an undiscovered victim object, which always fails a gate run.
                        c = _not_built(cid, method, tmpl, direction, ck, blast, None,
                                       f"role principal not provided (Q05_TOKEN_{owner}_{role.upper()}); "
                                       "the local harness runs this case")
                        c.local_only, c.scope = True, "role"
                        cases.append(c)
                    elif not oconn:
                        cases.append(_not_built(cid, method, tmpl, direction, ck, blast, None,
                                                f"no {kind} connection discovered"))
                    else:
                        cases.append(Case(
                            cid, method, tmpl, direction, ck, blast, route(o_ws, oconn), tok_key,
                            body=STALE_SENDER_BODY if method == "POST" else None,
                            mutation=(method == "POST"), scope="role", expect_pairs=pairs, role_profile=profile,
                            late=profile == "manager",
                            twin_path=route(o_ws, NONEXISTENT_CONNECTION[kind]) if twin else None,
                            deferred=f"control.sender.{'get' if method == 'GET' else 'post_stale'}.{kind}.{owner}"))

    # ---- owner controls (run after the attack phase) --------------------------------------------- #
    for owner in ("A", "B"):
        d_o, o_ws, oph = disc[owner], config.workspace[owner], f"<{owner}.workspace>"
        for kind, olist in (("webhook", d_o.webhooks), ("bot", d_o.installations)):
            oconn = olist[0] if olist else None
            prof = d_o.sender.get(oconn) if oconn else None
            names_off = bool(prof) and not prof.get("namesOn", True)
            tmpl = f"/api/workspaces/{oph}/channels/<{owner}.{kind}>/{SENDER_ROUTE}"
            # post_stale: the owner's identical-shape POST gets past every authorization check and is refused
            # harmlessly — the stale fingerprint (both versions) or, on v2, a switched-off capability.
            specs = [(f"control.sender.get.{kind}.{owner}", "GET", None, None, None, False),
                     (f"control.sender.post_stale.{kind}.{owner}", "POST", STALE_SENDER_BODY, 409,
                      {SENDER_STALE_BODY, UNAVAILABLE_BODY}, False)]
            if kind == "webhook":
                # an invalid name with the owner's CURRENT fingerprint (v2 checks the fingerprint's state half
                # before the name rules): must be refused 400, nothing renamed, no provider write
                specs += [(f"control.sender.reject_name.{label}.{owner}", "POST",
                           _sender_post(prof["fingerprint"], name=bad) if prof else None, 400, None, True)
                          for label, bad in BAD_NAMES]
            for cid, method, body, st, bd, needs_names in specs:
                if absent[owner]:
                    cases.append(_not_applicable(cid, method, tmpl, "control", "control", "", owner, na_why))
                elif not oconn or (needs_names and not prof):
                    cases.append(_not_built(cid, method, tmpl, "control", "control", "", owner,
                                            f"owner has no {kind} connection{' sender profile' if needs_names else ''} to control"))
                elif needs_names and names_off:
                    cases.append(_not_applicable(cid, method, tmpl, "control", "control", "", owner,
                                                 "sender names are switched off on this build"))
                else:
                    cases.append(Case(cid, method, tmpl, "control", "control", "", route(o_ws, oconn), owner,
                                      body=body, mutation=(method == "POST"), expected=(str(st or 200),),
                                      expect_status=st, expect_body=bd,
                                      expect_prefix=NAME_RULE_PREFIX if cid.startswith("control.sender.reject_name") else None))
        # replay of an OLD settings fingerprint (a stateful sequence on the owner's own webhook)
        wprof = d_o.sender.get(d_o.webhooks[0]) if d_o.webhooks else None
        for step in ("save", "stale_replay", "restore"):
            cid = f"control.sender.{step}.{owner}"
            tmpl = f"/api/workspaces/{oph}/channels/<{owner}.webhook>/{SENDER_ROUTE}"
            if absent[owner]:
                cases.append(_not_applicable(cid, "POST", tmpl, "control", "control", "state", owner, na_why))
            elif wprof and not wprof.get("namesOn", True):
                cases.append(_not_applicable(cid, "POST", tmpl, "control", "control", "state", owner,
                                             "sender names are switched off on this build"))
            elif not d_o.webhooks:
                cases.append(_not_built(cid, "POST", tmpl, "control", "control", "state", owner,
                                        "owner has no webhook connection to control"))
            else:
                c = Case(cid, "POST", tmpl, "control", "control", "state", route(o_ws, d_o.webhooks[0]), owner,
                         mutation=True, scope="sequence")
                c.sequence_step = step
                cases.append(c)
        # audit leak: after the attacks, the attacker's own audit must hold none of the victim's data
        cid = f"control.sender.audit_leak.{owner}"
        cases.append(Case(cid, "GET", f"/api/workspaces/{oph}/audit", "control", "control", "",
                          f"/api/workspaces/{o_ws}/audit", owner, scope="audit_leak",
                          victim_key=OTHER[owner]))
    return cases


class _FullFlags:
    allow_writes = allow_send_risk = victim_is_synthetic = True
    smoke = False


def _full_discovery(config):
    disc = {}
    for k in ("A", "B"):
        d = Discovery(k, config.workspace.get(k) or f"<{k}.workspace>")
        d.ok, d.revision = True, 1
        d.connections = [f"{k}-conn"]
        d.all_channel_ids = [f"{k}-conn"]
        d.identities = [f"{k}-identity"]
        d.destinations = {f"{k}-conn": [f"{k}-dest"]}
        d.jobs = [(f"{k}-job", "0" * 64)]
        d.members = [f"{k}-member"]
        d.owner_member = f"{k}-member"
        d.installations, d.webhooks = [f"{k}-conn"], [f"{k}-webhook"]
        d.connections = [f"{k}-conn", f"{k}-webhook"]
        d.sender = {c: {"kind": kind, "fingerprint": "f" * 64, "name": "x", "contract": 1, "namesOn": True}
                    for c, kind in ((f"{k}-conn", "bot"), (f"{k}-webhook", "webhook"))}
        d.sender_feature, d.sender_contract = True, 1
        disc[k] = d
    return disc


def _full_matrix(config):
    """The matrix as it is when every victim object is discovered and every role principal is given."""
    saved, saved_tokens = dict(config.victim_oauth_state), dict(config.token)
    config.victim_oauth_state = {"A": "state-a", "B": "state-b"}
    for key in ("A", "B"):
        for role in ROLE_KEYS:
            config.token[f"{key}.{role}"] = config.token.get(f"{key}.{role}") or "role-token"
    try:
        return build_matrix(_full_discovery(config), config, _FullFlags())
    finally:
        config.victim_oauth_state = saved
        config.token = saved_tokens


def expected_case_ids(config):
    """The FIXED full set of case ids the matrix produces when every victim object is discovered.
    Gate mode fails if any of these is missing from an actual run (M4)."""
    return {c.cid for c in _full_matrix(config)}


def case_manifest(config):
    """Every row a complete run reports, as (case id, kind, blast, scope): the full matrix plus the two
    no-side-effect snapshots. docs/q05/case-manifest.tsv is this list (python scripts/q05_tenant_probe.py
    --print-manifest); a test compares the two, and a gate request pins the row count."""
    rows = [(c.cid, c.kind, c.blast, c.scope or "") for c in _full_matrix(config)]
    rows += [(f"snapshot.no_side_effect.{k}", "control", "", "") for k in ("A", "B")]
    return sorted(rows)


# --------------------------------------------------------------------------- #
# Execution and verdicts
# --------------------------------------------------------------------------- #
def apply_deferred(cases):
    """A refusal whose differential is a named owner control (run after the attack phase) counts only once
    that control PASSED; otherwise the refusal is INCONCLUSIVE (the owner may be stopped by the same check)."""
    by_id = {c.cid: c for c in cases}
    for c in cases:
        if c.kind in ("read", "write") and c.deferred and c.verdict == "PASS":
            control = by_id.get(c.deferred)
            if control is None or control.verdict != "PASS":
                c.verdict = "INCONCLUSIVE"
                c.note = f"deferred owner differential {c.deferred} did not pass"


def missing_cases_case(config, cases):
    """A FAIL case listing every expected case id absent from this run, or None when none is."""
    missing_ids = sorted(expected_case_ids(config) - {c.cid for c in cases})
    if not missing_ids:
        return None
    mc = Case("matrix.missing_cases", "-", "(fixed expected list)", "control", "control", "",
              None, None, expected=("complete",))
    mc.verdict, mc.observed = "FAIL", "missing"
    mc.note = f"{len(missing_ids)} expected case id(s) absent from the run: " + ",".join(missing_ids)
    return mc


def gated_reason(case, flags):
    """Return a reason string if this case is intentionally gated off, else None."""
    if case.kind == "write" and not flags.allow_writes:
        return "gated:write (pass --allow-writes)"
    if case.blast == "send":
        if not flags.allow_send_risk:
            return "gated:send (pass --allow-send-risk)"
        if not flags.victim_is_synthetic:
            return "refused:send without --victim-is-synthetic"
    return None


def leak_detected(text, markers):
    if not text:
        return False
    return any(m and m in text for m in markers)


def error_code(obj):
    return obj.get("code") if isinstance(obj, dict) and isinstance(obj.get("code"), str) else None


def run_case(client, case, disc, flags):
    if case.scope == "prerequisite" and not case.needs:
        case.observed = "on" if case.prereq_ok else "off"
        if case.prereq_ok:
            case.verdict = "PASS"
        else:
            case.verdict = "NOT_RUN" if flags.smoke else "FAIL"
            case.note = ("undiscovered:" if flags.smoke else "") + case.prereq_note
        return
    if case.needs:
        case.verdict = "NOT_RUN"
        case.note = ("not-applicable:" if getattr(case, "not_applicable", False)
                     else "local-only:" if getattr(case, "local_only", False) else "undiscovered:") + case.needs
        case.observed = "-"
        return
    gate = gated_reason(case, flags)
    if gate:
        case.verdict = "NOT_RUN"
        case.note = gate
        case.observed = "-"
        return

    status, text, obj = client.request(case.method, case.path, case.token_key,
                                       body=case.body, mutation=case.mutation)
    provider = client.last_provider        # (calls, writes) when the local harness can attribute them
    elapsed = getattr(client, "last_elapsed", None)
    case.observed = str(status)
    err = error_body(obj, text)

    if case.scope == "audit_leak":
        # The attacker's own audit after the attack phase: no data unique to the victim may appear.
        own = disc[OTHER[case.victim_key]].markers if case.victim_key else set()
        unique = (disc[case.victim_key].markers - own) if case.victim_key else set()
        if not 200 <= status <= 299:
            case.verdict, case.note = "FAIL", "own audit unreadable (INCONCLUSIVE)"
        elif leak_detected(text, unique):
            case.verdict, case.note = "FAIL", "victim data present in the attacker's own audit log"
        else:
            case.verdict = "PASS"
        return

    if case.kind == "control":
        if case.expect_status is not None:
            # a control whose healthy answer is a specific refusal (stale fingerprint, invalid name):
            # it proves the owner gets PAST every authorization check and is stopped later, harmlessly
            ok = (status == case.expect_status
                  and (case.expect_body is None or err in _as_set(case.expect_body))
                  and (case.expect_prefix is None or (err or "").startswith(case.expect_prefix)))
            if ok and provider is not None and provider[1] > 0:
                case.verdict, case.note = "FAIL", "a refused owner request wrote to the provider"
            elif ok:
                case.verdict = "PASS"
            else:
                case.verdict = "FAIL"
                case.note = "control did not answer as expected (INCONCLUSIVE)"
            return
        # A control passes ONLY on a 2xx: a success (or object-level answer) proves the owner
        # gets through the route. Anything else makes the family INCONCLUSIVE (a run failure),
        # so a 403/404/step-up on a control can never be mistaken for a healthy deny elsewhere.
        if 200 <= status <= 299:
            case.verdict = "PASS"
        else:
            case.verdict = "FAIL"
            case.note = "control did not succeed (INCONCLUSIVE): the owner must get through this route"
        return

    # what only the victim has: a fact both tenants legitimately see (a Discord server both installed the bot in,
    # that server's shared bot nickname) is not a leak
    markers = (disc[case.victim_key].markers - disc[OTHER[case.victim_key]].markers) if case.victim_key else set()

    def inconclusive(reason):
        case.verdict = "INCONCLUSIVE"
        case.note = reason

    # (a "manager" settings read may legitimately read Discord; its scoring checks the provider itself)
    if provider is not None and provider[0] > 0 and case.role_profile != "manager":
        case.verdict = "FAIL"
        case.note = f"the refused request reached the provider ({provider[0]} request(s), {provider[1]} write(s))"
        return
    _score_attack(client, case, status, text, obj, err, markers, inconclusive)
    if case.verdict == "PASS" and case.twin_path:
        _check_twin(client, case, status, err, error_code(obj), inconclusive, obj=obj, elapsed=elapsed, text=text)


TIMING_PAIRS = 2          # extra alternating (victim id, never-existing id) pairs for a sender-name GET twin
TIMING_MARGIN = 0.025     # seconds: every victim-id answer slower than every twin answer by more than this fails


def _check_twin(client, case, status, err, code, inconclusive, obj=None, elapsed=None, text=None):
    """The same request at an id that never existed must get the same answer: the same status, error and
    code, and (JSON) the same whole body, so no extra field, reason or retry time can tell the two apart.
    For a sender-name GET the timing is compared too: a few alternating pairs, and the case fails only if
    EVERY answer for the victim's id is slower than EVERY never-existing-id answer by more than
    TIMING_MARGIN (dominance, so ordinary jitter cannot fail it)."""
    t_status, t_text, t_obj = client.request(case.method, case.twin_path, case.token_key,
                                             body=case.body, mutation=case.mutation)
    t_times = [getattr(client, "last_elapsed", None)]
    case.twin_observed = str(t_status)
    t_provider = client.last_provider
    if t_status == 0 or 300 <= t_status <= 399 or t_status >= 500 or t_status == 429:
        return inconclusive(f"existence twin answered {t_status}; cannot compare")
    if t_provider is not None and t_provider[0] > 0:
        case.verdict, case.note = "FAIL", "the never-existing-id twin reached the provider"
        return
    if (t_status, error_body(t_obj, t_text), error_code(t_obj)) != (status, err, code) or (
            isinstance(obj, dict) and obj != t_obj) or (obj is None and t_obj is None and text != t_text):
        case.verdict = "FAIL"
        case.note = "existence oracle: the answer for the victim's id differs from a never-existing id"
        return
    if case.method != "GET" or ".sender." not in case.cid or elapsed is None:
        return
    v_times = [elapsed]
    for _ in range(TIMING_PAIRS):
        for path, times, first in ((case.path, v_times, (status, obj)), (case.twin_path, t_times, (t_status, t_obj))):
            r_status, _r_text, r_obj = client.request("GET", path, case.token_key)
            times.append(getattr(client, "last_elapsed", None))
            if (r_status, r_obj) != first:
                case.verdict, case.note = "FAIL", "existence oracle: a repeated answer differs"
                return
    if any(not isinstance(t, float) for t in v_times + t_times):
        return
    case.timing = (min(v_times), max(t_times))
    if min(v_times) > max(t_times) + TIMING_MARGIN:
        case.verdict = "FAIL"
        case.note = "timing oracle: the victim's id is consistently slower than a never-existing id"


def _as_set(value):
    return value if isinstance(value, (set, frozenset)) else {value}


def run_sender_sequence(client, steps, flags):
    """Replay of an OLD settings fingerprint, on the owner's OWN webhook (own data only): save a name (the
    fingerprint read before it is now stale) -> replaying that old fingerprint must be refused with the
    stale-settings answer and change nothing -> restore the original name. Needs --allow-writes."""
    by_step = {c.sequence_step: c for c in steps}
    save, replay, restore = by_step["save"], by_step["stale_replay"], by_step["restore"]
    for c in steps:
        c.observed = "-"
    if not flags.allow_writes:
        for c in steps:
            c.verdict, c.note = "NOT_RUN", "gated:write (pass --allow-writes)"
        return

    def fail_all(from_cases, why):
        for c in from_cases:
            if c.verdict is None:
                c.verdict, c.note = "FAIL", why

    path, tok = save.path, save.token_key
    owner = save.cid.rsplit(".", 1)[1]
    st, _t, prof = client.request("GET", path, tok)
    if st != 200 or not isinstance(prof, dict) or not isinstance(prof.get("fingerprint"), str):
        return fail_all(steps, "could not read the owner's own sender profile (INCONCLUSIVE)")
    old_fp = prof["fingerprint"]
    # The name to restore: the saved override, or None when there is none (contract v2 reports savedName;
    # a first connection starts without one). None is restored with the contract's "clear" (reset), never by
    # saving the webhook's own name as an override.
    original = prof.get("savedName") if "savedName" in prof else (prof.get("name") or None)
    renamed = f"Q05 renamed {owner}"
    st, _t, body = client.request("POST", path, tok, body=_sender_post(old_fp, renamed), mutation=True)
    save.observed = str(st)
    if st != 200 or not isinstance(body, dict) or body.get("name") != renamed:
        return fail_all(steps, "the owner could not save its own sender name (INCONCLUSIVE)")
    save.verdict = "PASS"
    st, text, obj = client.request("POST", path, tok, body=_sender_post(old_fp, "Q05 stale replay"), mutation=True)
    provider = client.last_provider
    replay.observed = str(st)
    st2, _t2, now_prof = client.request("GET", path, tok)
    unchanged = st2 == 200 and isinstance(now_prof, dict) and now_prof.get("name") == renamed
    if st == 409 and error_body(obj, text) == SENDER_STALE_BODY and unchanged:
        if provider is not None and provider[1] > 0:
            replay.verdict, replay.note = "FAIL", "the refused stale replay wrote to the provider"
        else:
            replay.verdict = "PASS"
    else:
        replay.verdict = "FAIL"
        replay.note = ("an old fingerprint was accepted, or the name changed" if st == 200 or not unchanged
                       else f"stale replay answered {st} (expected the stale-settings 409) (INCONCLUSIVE)")
    if not (isinstance(now_prof, dict) and isinstance(now_prof.get("fingerprint"), str)
            and (original is None or (isinstance(original, str) and original))):
        return fail_all([restore], "could not restore the original name (INCONCLUSIVE)")
    body = (_sender_clear(now_prof["fingerprint"]) if original is None
            else _sender_post(now_prof["fingerprint"], original))
    st, _t, obj = client.request("POST", path, tok, body=body, mutation=True)
    restore.observed = str(st)
    restored = obj.get("savedName") if isinstance(obj, dict) and "savedName" in obj else (
        obj.get("name") if isinstance(obj, dict) else None)
    if st == 200 and isinstance(obj, dict) and (restored == original or (original is None and not restored)):
        restore.verdict = "PASS"
    else:
        fail_all([restore], f"restoring the original name answered {st} (INCONCLUSIVE)")


def _score_role_profile(client, case, status, text, obj, markers, inconclusive):
    """Contract v2: a member who holds connection-management but did not authorize the connection may READ
    its sender settings. "readonly" (a bot nickname, authorizer-only): a 200 that offers no edit
    (editable false, not_authorizing_member) and was answered without any Discord read. "manager" (a
    webhook name, which the contract head lets any connection manager edit): that read-only answer, or an
    editable profile of exactly the requested connection that wrote nothing to Discord."""
    provider = client.last_provider
    if status != 200 or not isinstance(obj, dict):
        return inconclusive(f"expected a 200 settings profile, got {status}")
    if leak_detected(text, markers):
        case.verdict, case.note = "FAIL", "victim marker present in response"
        return
    if obj.get("connectionId") != case.path.split("/")[5]:
        case.verdict, case.note = "FAIL", "the settings profile is not the requested connection's"
        return
    codes = [r.get("code") for r in (obj.get("unavailable") or []) if isinstance(r, dict)]
    if obj.get("editable") is False and "not_authorizing_member" in codes:
        if obj.get("observedAt") is not None or (provider is not None and provider[0] > 0):
            case.verdict, case.note = "FAIL", "a non-authorizer's read made a Discord read"
            return
        case.verdict = "PASS"
        if case.role_profile == "manager":
            case.note = "read-only for a non-authorizing manager (stricter than the contract head)"
        return
    if case.role_profile == "manager" and obj.get("editable") is True and not codes:
        if provider is not None and provider[1] > 0:
            case.verdict, case.note = "FAIL", "a settings read wrote to the provider"
            return
        case.verdict, case.note = "PASS", "editable for a connection manager (contract head: webhook names)"
        return
    if case.role_profile == "manager":
        return inconclusive("neither the read-only nor the manager profile (another reason was reported)")
    case.verdict, case.note = "FAIL", "a member who did not authorize the connection was offered an edit"


def _score_attack(client, case, status, text, obj, err, markers, inconclusive):
    if case.scope == "role" and case.role_profile:
        return _score_role_profile(client, case, status, text, obj, markers, inconclusive)
    if case.scope == "malformed":
        # A malformed id must get a clean JSON 4xx: never accepted, never a server error, no leak.
        if status == 0 or 300 <= status <= 399 or status in (401, 429):
            return inconclusive(f"status {status} on a malformed id (cannot conclude)")
        if status >= 500:
            return inconclusive("server error on a malformed id (robustness; cannot conclude)")
        if 200 <= status <= 299:
            case.verdict, case.note = "FAIL", "malformed id accepted (2xx)"
            return
        if leak_detected(text, markers):
            case.verdict, case.note = "FAIL", "victim marker present in response"
            return
        if err is None:
            return inconclusive(f"{status} without a JSON error body")
        case.verdict = "PASS"
        return

    if status == 0:
        return inconclusive("transport error (cannot conclude)")
    if 300 <= status <= 399:
        return inconclusive("redirect not followed (cannot conclude; Authorization not resent)")
    if 500 <= status <= 599:
        return inconclusive("server error 5xx (cannot conclude)")
    if 200 <= status <= 299:
        case.verdict = "FAIL"
        case.note = "attack unexpectedly accepted (2xx)"
        return
    if leak_detected(text, markers):
        case.verdict = "FAIL"
        case.note = "victim marker present in response"
        return

    if case.scope == "ws_scope":
        # A workspace-scope attack passes ONLY on the tenant gate's own 403 body.
        if status == 403 and err == GATE_DENY_BODY:
            if case.differential and case.owner_token_key:
                o_status, _ot, o_obj = client.request(case.method, case.path, case.owner_token_key,
                                                       body=case.body, mutation=case.mutation)
                case.owner_observed = str(o_status)
                o_err = error_body(o_obj, None)
                if o_status == 0 or 500 <= o_status <= 599 or 300 <= o_status <= 399:
                    return inconclusive("owner differential request failed; cannot confirm the gate is tenant-specific")
                if o_status == 403 and o_err == GATE_DENY_BODY:
                    return inconclusive("the owner of the attacked workspace also hit the gate (differential broken)")
                # owner got PAST the gate (object-level/validation answer), attacker got the gate: confirmed
            case.verdict = "PASS"
            return
        if status == 403:
            return inconclusive("403 but not the tenant-gate body (permission/origin?), not the membership gate")
        if status in (404, 409):
            case.verdict = "FAIL"
            case.note = "workspace-scope attack was NOT stopped at the membership gate (reached an object check)"
            return
        return inconclusive(f"status {status} on a workspace-scope attack")

    if case.scope == "idor":
        if status in (404, 409) and err in IDOR_DENY_BODIES:
            case.verdict = "PASS"
            return
        if status in (404, 409):
            return inconclusive("object-level 404/409 but not a known object-binding body")
        if status == 403:
            return inconclusive("403 on an IDOR attack (step-up/permission?); cannot attribute to tenancy")
        return inconclusive(f"status {status} on an IDOR attack")

    if case.scope == "role":
        # Another member of the SAME workspace: must be refused by the exact control the feature names
        # (permission / authorizing member / the gate for a removed member / the stale fingerprint).
        if (status, err) in (case.expect_pairs or ()):
            case.verdict = "PASS"
            return
        return inconclusive(f"refused with {status}, but not by the expected control")

    return inconclusive("case has no deny scope")


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def case_record(case):
    return {
        "case": case.cid,
        "method": case.method,
        "route": case.template,
        "direction": case.direction,
        "kind": case.kind,
        "blast": case.blast,
        "expected": "|".join(case.expected),
        "observed": case.observed,
        "ownerObserved": case.owner_observed,
        "twinObserved": case.twin_observed,
        # [fastest victim-id answer, slowest never-existing-id answer] in ms (sender-name GET twins only)
        "timingMs": [round(t * 1000, 1) for t in case.timing] if case.timing else None,
        "scope": case.scope or "",
        "verdict": case.verdict,
        "note": case.note,
    }


def write_markdown(path, cases, summary, flags, config):
    lines = []
    lines.append("# Q-05 cross-tenant isolation probe receipt")
    lines.append("")
    lines.append(f"- base origin: `{config.origin()}`")
    lines.append(f"- generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    lines.append(f"- writes covered: **{'YES' if flags.allow_writes else 'NO (read-only run)'}**")
    lines.append(f"- send-risk cases covered: **{'YES' if (flags.allow_writes and flags.allow_send_risk and flags.victim_is_synthetic) else 'NO'}**")
    lines.append("")
    if not flags.allow_writes:
        lines.append("> WRITE COVERAGE: **NOT RUN.** This run proves reads only. "
                     "Gate G4 requires a run with `--allow-writes` in BOTH directions.")
        lines.append("")
    if flags.smoke:
        lines.append("> SMOKE MODE: undiscovered victim objects are reported NOT RUN below and do "
                     "**not** fail this run. This is a smoke run, not the G4 gate. A FAIL or any "
                     "INCONCLUSIVE case — an attack as well as a control — still fails a smoke run.")
        lines.append("")
    if summary["undiscovered"]:
        lines.append(f"> NOT RUN (undiscovered victim objects): **{summary['undiscovered']}** "
                     "case(s). These are NOT passes; the gate is not met until the victim "
                     "objects exist and the cases run"
                     + (" (allowed in this smoke run)." if flags.smoke else "."))
        lines.append("")
    if summary.get("not_applicable"):
        lines.append(f"> NOT APPLICABLE: **{summary['not_applicable']}** case(s) target a route this build does "
                     "not serve (e.g. customer sender names before RC2). They do not fail this probe run, but a "
                     "hosted GATE run fails on any NOT RUN case, and gate runs are pinned to the reviewed build.")
        lines.append("")
    if summary.get("local_only"):
        lines.append(f"> NOT RUN (local-only): **{summary['local_only']}** same-workspace role case(s) need other "
                     "members of the workspace, which this run did not sign in; the local harness runs them against "
                     "the same SHA. They are not passes and do not fail this run.")
        lines.append("")
    if summary["inconclusive"]:
        lines.append(f"> INCONCLUSIVE: **{summary['inconclusive']}** case(s) could not be classified as a "
                     "clean deny (a failed control, or an attack that returned a redirect, 5xx, 401/429/"
                     "400/405/410/415, or a 4xx without the expected deny body). The run FAILS; these are "
                     "never counted as passes.")
        lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| metric | count |")
    lines.append("|---|---|")
    for k in ("total", "passed", "failed", "inconclusive", "not_run_gated", "undiscovered", "not_applicable",
              "controls_passed", "controls_failed", "reads", "writes",
              "blast_state", "blast_send", "blast_inert", "sender_cases", "sender_passed"):
        lines.append(f"| {k} | {summary.get(k, 0)} |")
    lines.append(f"| overall | {'PASS' if summary['exit'] == 0 else 'FAIL'} |")
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    lines.append("| case | method | route template | dir | kind | blast | expected | observed | verdict | note |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    def cell(value):
        return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")
    for c in cases:
        r = {k: cell(v) for k, v in case_record(c).items()}
        r["expected"] = cell("/".join(c.expected))
        lines.append("| {case} | {method} | `{route}` | {direction} | {kind} | {blast} | "
                     "{expected} | {observed} | {verdict} | {note} |".format(**r))
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
class Flags:
    def __init__(self, args):
        self.allow_writes = args.allow_writes
        self.allow_send_risk = args.allow_send_risk
        self.victim_is_synthetic = args.victim_is_synthetic
        self.smoke = getattr(args, "smoke", False)


def summarize(cases, smoke=False):
    s = {k: 0 for k in ("total", "passed", "failed", "not_run_gated", "undiscovered",
                         "controls_passed", "controls_failed", "reads", "writes",
                         "blast_state", "blast_send", "blast_inert", "inconclusive",
                         "not_applicable", "local_only", "sender_cases", "sender_passed", "unscored")}
    for c in cases:
        s["total"] += 1
        if c.kind == "read":
            s["reads"] += 1
        elif c.kind == "write":
            s["writes"] += 1
        if c.blast == "state":
            s["blast_state"] += 1
        elif c.blast == "send":
            s["blast_send"] += 1
        elif c.blast == "inert":
            s["blast_inert"] += 1
        if ".sender." in c.cid:
            s["sender_cases"] += 1
            if c.verdict == "PASS":
                s["sender_passed"] += 1
        if c.verdict not in ("PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN"):
            s["unscored"] += 1           # a case that ended without a verdict (a swallowed error): the run fails
        if c.verdict == "PASS":
            s["passed"] += 1
            if c.kind == "control":
                s["controls_passed"] += 1
        elif c.verdict == "FAIL":
            s["failed"] += 1
            if c.kind == "control":
                s["controls_failed"] += 1
                s["inconclusive"] += 1
        elif c.verdict == "INCONCLUSIVE":
            s["inconclusive"] += 1
        elif c.verdict == "NOT_RUN":
            if c.note.startswith("undiscovered"):
                s["undiscovered"] += 1
            elif c.note.startswith("not-applicable"):
                s["not_applicable"] += 1   # the build does not serve the route: reported, not a probe failure
            elif c.note.startswith("local-only"):
                s["local_only"] += 1       # same-workspace roles this run could not sign in: reported, not a failure
            else:
                s["not_run_gated"] += 1
    # exit 0 only if no FAIL, nothing INCONCLUSIVE (a control that did not succeed, or an attack
    # whose status could not be classified as a clean deny), and (unless --smoke) no undiscovered
    # victim case. --smoke is for a smoke run against a build that cannot yet hold the Discord
    # objects some cases need: undiscovered cases are still reported loudly as NOT RUN, they just
    # do not fail the exit. A FAIL or anything INCONCLUSIVE always fails, in any mode.
    s["smoke"] = bool(smoke)
    ok = (s["failed"] == 0 and s["inconclusive"] == 0 and s["unscored"] == 0
          and (smoke or s["undiscovered"] == 0))
    s["exit"] = 0 if ok else 1
    return s


def main(argv=None):
    parser = argparse.ArgumentParser(description="Q-05 cross-tenant isolation probe")
    parser.add_argument("--print-manifest", action="store_true",
                        help="print the case manifest (id, kind, blast, scope per line) and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the matrix and coverage without sending anything")
    parser.add_argument("--allow-writes", action="store_true",
                        help="run WRITE cases (default: read-only)")
    parser.add_argument("--allow-send-risk", action="store_true",
                        help="also run send-blast cases (needs --allow-writes)")
    parser.add_argument("--victim-is-synthetic", action="store_true",
                        help="declare the victim tenants synthetic; required for send cases")
    parser.add_argument("--smoke", action="store_true",
                        help="smoke run: undiscovered victim objects are reported NOT RUN but do "
                             "not fail the exit (a FAIL or any INCONCLUSIVE case, attack or control, "
                             "still does)")
    parser.add_argument("--budget", type=int, default=600, help="max requests (default 600)")
    parser.add_argument("--delay", type=float, default=0.02, help="seconds between requests")
    parser.add_argument("--out-md", default=None, help="path for the Markdown receipt")
    parser.add_argument("--out-json", default=None, help="path for the JSONL output (default stdout)")
    args = parser.parse_args(argv)
    flags = Flags(args)

    config = Config(os.environ)

    if args.print_manifest:
        placeholder = Config({"Q05_BASE_URL": "http://127.0.0.1:9", "Q05_TOKEN_A": "a", "Q05_TOKEN_B": "b",
                              "Q05_WORKSPACE_A": "<A.workspace>", "Q05_WORKSPACE_B": "<B.workspace>"})
        print("case\tkind\tblast\tscope")
        for row in case_manifest(placeholder):
            print("\t".join(row))
        return 0

    if args.dry_run:
        # Build the matrix with empty discovery so the shape is visible; objects
        # that would be discovered are shown as NOT RUN placeholders.
        disc = {k: Discovery(k, config.workspace.get(k) or f"<{k}.workspace>") for k in ("A", "B")}
        for k in disc:
            disc[k].revision = 0
        cases = build_matrix(disc, config, flags)
        print("# Q-05 probe dry run: matrix and coverage\n")
        print(f"writes: {'ON' if flags.allow_writes else 'off'}  "
              f"send-risk: {'ON' if flags.allow_send_risk else 'off'}  "
              f"victim-synthetic: {'yes' if flags.victim_is_synthetic else 'no'}\n")
        for c in cases:
            gate = "" if c.needs else (gated_reason(c, flags) or "")
            label = c.needs or gate or "would run"
            print(f"{c.cid:50s} {c.method:6s} {c.kind:7s} {c.blast:5s} {c.template}  [{label}]")
        counts = {}
        for c in cases:
            counts[(c.kind, c.blast)] = counts.get((c.kind, c.blast), 0) + 1
        print("\n# coverage by (kind, blast):")
        for key in sorted(counts):
            print(f"  {key}: {counts[key]}")
        return 0

    missing = config.missing()
    if missing:
        print("missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2

    # A and B must be two DIFFERENT tenants, or every "cross-tenant" result is meaningless.
    if config.workspace["A"] == config.workspace["B"]:
        print("refusing: Q05_WORKSPACE_A and Q05_WORKSPACE_B are the same workspace", file=sys.stderr)
        return 2
    if config.token["A"] == config.token["B"]:
        print("refusing: Q05_TOKEN_A and Q05_TOKEN_B are the same token", file=sys.stderr)
        return 2
    sub_a, sub_b = jwt_sub(config.token["A"]), jwt_sub(config.token["B"])
    if sub_a and sub_b and sub_a == sub_b:
        print("refusing: the two access tokens belong to the same user (identical sub claim)", file=sys.stderr)
        return 2
    config.same_user_checked = bool(sub_a and sub_b)
    if not config.same_user_checked:
        # never silent: opaque tokens (the local harness) carry no subject; the workspace guard still applies
        print("note: the same-user guard could not read a subject from the tokens (opaque tokens); "
              "identical tokens and identical workspaces are still refused", file=sys.stderr)

    budget = Budget(args.budget)
    client = Client(config, budget, args.delay)

    # 1. discovery (reads only, each tenant's own token)
    disc = {k: discover(client, config, k) for k in ("A", "B")}

    # 2. snapshot BEFORE (brackets only the attack set)
    before = {k: snapshot(client, config, k) for k in ("A", "B")}

    # 3. build and run attack cases
    cases = build_matrix(disc, config, flags)
    attack_cases = [c for c in cases if c.kind in ("read", "write") and not c.late]
    # same-workspace reads the contract allows (they may read Discord): after the attack phase, before controls
    late_cases = [c for c in cases if c.kind in ("read", "write") and c.late]
    control_cases = [c for c in cases if c.kind == "control"]
    audit_checks = [c for c in control_cases if c.scope == "audit_leak"]
    sequences = [c for c in control_cases if c.scope == "sequence"]
    plain_controls = [c for c in control_cases if c.scope not in ("audit_leak", "sequence")]
    try:
        if config.phase_markers:
            client.marker("attack-start")
        for c in attack_cases:
            run_case(client, c, disc, flags)
        if config.phase_markers:
            client.marker("attack-end")
        # 4. snapshot AFTER the attack set, before any owner controls mutate state
        after = {k: snapshot(client, config, k) for k in ("A", "B")}
        # 5. controls (owner on own workspace; may change own state legitimately). The audit-leak checks run
        #    first, before any owner control writes audit rows of its own.
        for c in audit_checks + late_cases + plain_controls:
            run_case(client, c, disc, flags)
        for owner in ("A", "B"):
            steps = [c for c in sequences if c.cid.endswith("." + owner)]
            if steps and all(not c.needs for c in steps):
                run_sender_sequence(client, steps, flags)
            else:
                for c in steps:
                    run_case(client, c, disc, flags)
    except RuntimeError as err:
        print("probe aborted: " + str(err), file=sys.stderr)
        return 2

    # 5b. deferred owner differentials: a workspace-scope or same-workspace refusal only counts once the
    #     route's owner control (run above, after the attacks) proved the owner gets past those checks.
    apply_deferred(cases)

    # 6. no-side-effect verdict per tenant (attacks must not change the victim)
    snapshot_cases = []
    for key in ("A", "B"):
        bdig, bdet = before[key]
        adig, adet = after[key]
        groups = snapshot_diff_groups(bdet, adet)
        sc = Case(f"snapshot.no_side_effect.{key}", "SNAPSHOT",
                  f"<{key}.workspace> (revision/counts digest)", "control",
                  "control", "", None, None, expected=("unchanged",))
        if bdig is None or adig is None:
            sc.verdict = "FAIL"
            sc.observed = "unreachable"
            sc.note = "tenant snapshot unreachable"
            snapshot_cases.append(sc)
            continue
        if bdig == adig and not groups:
            sc.verdict = "PASS"
            sc.observed = "unchanged"
        else:
            sc.verdict = "FAIL"
            sc.observed = "changed"
            sc.note = "changed groups: " + ",".join(groups)
        snapshot_cases.append(sc)

    # M4: every expected case id must be present (a forgotten NOT RUN placeholder is a bug).
    extra_cases = [mc for mc in (missing_cases_case(config, cases),) if mc is not None]

    all_cases = attack_cases + late_cases + control_cases + snapshot_cases + extra_cases
    summary = summarize(all_cases, smoke=flags.smoke)
    # fold snapshot FAILs into failed count already done by summarize (kind=control)
    # but snapshot FAIL is counted as controls_failed/inconclusive which is correct.

    # emit JSONL
    out = open(args.out_json, "w", encoding="utf-8") if args.out_json else sys.stdout
    try:
        for c in all_cases:
            out.write(json.dumps(case_record(c), sort_keys=True) + "\n")
        out.write(json.dumps({"summary": summary}, sort_keys=True) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()

    if args.out_md:
        write_markdown(args.out_md, all_cases, summary, flags, config)

    print(f"# Q-05 probe: {summary['passed']} passed, {summary['failed']} failed, "
          f"{summary['undiscovered']} undiscovered, {summary['not_run_gated']} gated-off, "
          f"overall {'PASS' if summary['exit'] == 0 else 'FAIL'}  "
          f"(budget used {budget.used}/{budget.limit})", file=sys.stderr)
    return summary["exit"]


if __name__ == "__main__":
    sys.exit(main())
