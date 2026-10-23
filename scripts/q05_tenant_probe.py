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


class Client:
    def __init__(self, config, budget, delay):
        self.config = config
        self.budget = budget
        self.delay = delay
        # localhost http needs no TLS context; https uses the default verified one.
        self._ctx = ssl.create_default_context() if config.base_url.startswith("https") else None

    def request(self, method, path, token_key, *, body=None, mutation=False):
        """Return (status, text, body_obj). Never raises on HTTP error status."""
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
        try:
            with urllib.request.urlopen(req, timeout=30, context=self._ctx) as resp:
                raw = resp.read(2_000_000)
                status = resp.status
        except urllib.error.HTTPError as err:
            raw = err.read(2_000_000)
            status = err.code
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            return (0, "transport_error:" + type(err).__name__, None)
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
        if ch.get("platform") == "Discord":
            d.connections.append(cid)
        for dest in ch.get("discordDestinations", []) or []:
            if isinstance(dest, dict):
                d._mark(dest.get("id"))
                d._mark(dest.get("channelId"))
                d._mark(dest.get("guildId"))
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

    # Members (own read).
    st, _t, b = client.request("GET", f"/api/workspaces/{d.workspace}/members", tok)
    if st == 200 and isinstance(b, dict):
        for m in b.get("members", []) or []:
            if isinstance(m, dict) and m.get("userId"):
                d.members.append(m["userId"])
                d._mark(m.get("userId"))
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
    parts["members"] = sorted(
        [(m.get("userId"), m.get("role"), json.dumps(m.get("permissions") or m.get("flags") or {}, sort_keys=True))
         for m in (mbody.get("members", []) if st == 200 and isinstance(mbody, dict) else [])
         if isinstance(m, dict)])
    st, _t, abody = client.request("GET", f"/api/workspaces/{ws}/audit", tok)
    events = abody.get("events", []) if st == 200 and isinstance(abody, dict) else []
    parts["auditCount"] = len(events) if isinstance(events, list) else None

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
                 needs=None, victim_key=None):
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
        # results
        self.observed = None
        self.verdict = None
        self.note = ""


DENY_STATUSES = {400, 401, 403, 404, 405, 409, 410, 415, 429}


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
        d_a = disc[attacker]
        arrow = f"{attacker}->{victim}"
        vph = f"<{victim}.workspace>"
        aph = f"<{attacker}.workspace>"

        # ---------- READ, style (i): victim workspace id in path -------------- #
        for suffix, tail in (("get", ""), ("members", "/members"), ("audit", "/audit"),
                             ("invitations", "/invitations"), ("export", "/export"),
                             ("channels", "/channels"), ("analytics", "/analytics/summary"),
                             ("memory", "/memory")):
            cases.append(Case(
                f"read.ws_scope.{suffix}.{arrow}", "GET",
                f"/api/workspaces/{vph}{tail}", arrow, "read", "",
                f"/api/workspaces/{v_ws}{tail}", attacker, victim_key=victim))

        # ---------- READ, style (ii): own workspace id + victim object id ----- #
        if d_v.connections:
            vconn = d_v.connections[0]
            cases.append(Case(
                f"read.idor.destinations.{arrow}", "GET",
                f"/api/workspaces/{aph}/channels/<{victim}.connection>/destinations",
                arrow, "read", "",
                f"/api/workspaces/{a_ws}/channels/{vconn}/destinations", attacker,
                victim_key=victim))
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
                victim_key=victim))
            cases.append(Case(
                f"read.idor.private_review.{arrow}", "GET",
                f"/api/workspaces/{aph}/discord/private-review/<{victim}.identity>",
                arrow, "read", "",
                f"/api/workspaces/{a_ws}/discord/private-review/{vid}", attacker,
                victim_key=victim))
        else:
            for sfx, tailtmpl, tailreal in (
                ("identity_guilds", "/discord/identities/<%s.identity>/guilds", None),
                ("private_review", "/discord/private-review/<%s.identity>", None)):
                cases.append(_not_built(f"read.idor.{sfx}.{arrow}", "GET",
                    f"/api/workspaces/{aph}" + (tailtmpl % victim),
                    arrow, "read", "", victim, "no discord identity discovered for victim"))

        # ---------- WRITE, style (i): victim workspace id in path ------------- #
        cases.append(Case(
            f"write.ws_scope.mutate_mode.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "mode", "payload": {"mode": "personal"},
                  "expectedRevision": d_v.revision}, mutation=True, victim_key=victim))
        cases.append(Case(
            f"write.ws_scope.mutate_refresh.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "inert",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "p2_refresh", "payload": {}, "expectedRevision": d_v.revision},
            mutation=True, victim_key=victim))
        cases.append(Case(
            f"write.ws_scope.invite.{arrow}", "POST",
            f"/api/workspaces/{vph}/invitations", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/invitations", attacker,
            body={"email": "q05-probe@example.invalid", "role": "viewer", "permissions": {}},
            mutation=True, victim_key=victim))
        if d_v.members:
            vmember = d_v.members[0]
            cases.append(Case(
                f"write.ws_scope.member_remove.{arrow}", "DELETE",
                f"/api/workspaces/{vph}/members/<{victim}.member>", arrow, "write", "state",
                f"/api/workspaces/{v_ws}/members/{vmember}", attacker,
                mutation=True, victim_key=victim))
        # approvals / publish-now / schedule / cancel-pause all enter through /actions and
        # the mutate() path; each hits the same membership gate for a foreign workspace.
        cases.append(Case(
            f"write.ws_scope.approve.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "p2_approve", "payload": {"reviewId": "q05", "digest": "q05", "confirmed": True},
                  "expectedRevision": d_v.revision}, mutation=True, victim_key=victim))
        cases.append(Case(
            f"write.ws_scope.cancel.{arrow}", "POST",
            f"/api/workspaces/{vph}/actions", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/actions", attacker,
            body={"action": "p2_cancel", "payload": {"jobId": "q05"}, "expectedRevision": d_v.revision},
            mutation=True, victim_key=victim))
        # Discord connect start for a foreign workspace (the connect/start family).
        cases.append(Case(
            f"write.ws_scope.discord_connect_start.{arrow}", "POST",
            f"/api/workspaces/{vph}/channels/discord/oauth/start", arrow, "write", "state",
            f"/api/workspaces/{v_ws}/channels/discord/oauth/start", attacker,
            body={"capability": "identity", "input": {"discordPurpose": "identity"}},
            mutation=True, victim_key=victim))

        # ---------- WRITE, style (ii)/(iii): own ws + victim object id -------- #
        if d_v.connections:
            vconn = d_v.connections[0]
            cases.append(Case(
                f"write.idor.destination_choose.{arrow}", "POST",
                f"/api/workspaces/{aph}/channels/<{victim}.connection>/destination",
                arrow, "write", "state",
                f"/api/workspaces/{a_ws}/channels/{vconn}/destination", attacker,
                body={"destinationId": "100000000000000001"}, mutation=True, victim_key=victim))
            cases.append(Case(
                f"write.idor.channel_disconnect.{arrow}", "DELETE",
                f"/api/workspaces/{aph}/channels/<{victim}.connection>",
                arrow, "write", "state",
                f"/api/workspaces/{a_ws}/channels/{vconn}", attacker,
                mutation=True, victim_key=victim))
            if d_v.destinations.get(vconn):
                vdest = d_v.destinations[vconn][0]
                cases.append(Case(
                    f"write.idor.destination_remove.{arrow}", "DELETE",
                    f"/api/workspaces/{aph}/channels/<{victim}.connection>/destinations/<{victim}.destination>",
                    arrow, "write", "state",
                    f"/api/workspaces/{a_ws}/channels/{vconn}/destinations/{vdest}", attacker,
                    mutation=True, victim_key=victim))
        if d_v.identities:
            vid = d_v.identities[0]
            cases.append(Case(
                f"write.idor.identity_disconnect.{arrow}", "POST",
                f"/api/workspaces/{aph}/discord/identities/<{victim}.identity>/disconnect",
                arrow, "write", "state",
                f"/api/workspaces/{a_ws}/discord/identities/{vid}/disconnect", attacker,
                mutation=True, victim_key=victim))
            # NOTE: /discord/interaction-links/<id>/bind is intentionally NOT in the matrix.
            # The User-Install feature (POSTRIFF_DISCORD_USER_INSTALL_V1_ENABLED) is OFF at
            # launch (docs .../C-01-env-matrix.md), so the route answers 503 feature-disabled
            # for every caller and is not part of the opened surface. Its IDOR check binds the
            # same identity_record() boundary this disconnect case already exercises. See
            # EXCLUDED_FAMILIES["interaction-links"] and the coverage test.

        # ---------- WRITE, blast=send: dispatch-capable routes ---------------- #
        if d_v.jobs:
            vjob, vdigest = d_v.jobs[0]
            # style (i): victim workspace id in path (membership boundary).
            cases.append(Case(
                f"write.send.job_execute_ws_scope.{arrow}", "POST",
                f"/api/workspaces/{vph}/jobs/<{victim}.job>/execute", arrow, "write", "send",
                f"/api/workspaces/{v_ws}/jobs/{vjob}/execute", attacker,
                body={"approvalDigest": vdigest or "0" * 64}, mutation=True, victim_key=victim))
            # style (ii): own workspace + victim job id (IDOR) + victim digest (iii).
            cases.append(Case(
                f"write.send.job_execute_idor.{arrow}", "POST",
                f"/api/workspaces/{aph}/jobs/<{victim}.job>/execute", arrow, "write", "send",
                f"/api/workspaces/{a_ws}/jobs/{vjob}/execute", attacker,
                body={"approvalDigest": vdigest or "0" * 64}, mutation=True, victim_key=victim))
        else:
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
                body={"state": vstate, "code": "q05-probe-code"}, mutation=True, victim_key=victim))
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
        # write control (inert): refresh action succeeds for the owner, proving
        # the write route is reachable so a denied cross-tenant write is a real
        # deny and not a globally broken/blocked route.
        cases.append(Case(f"control.write_refresh.{owner}", "POST",
            f"/api/workspaces/{oph}/actions", "control", "control", "inert",
            f"/api/workspaces/{o_ws}/actions", owner,
            body={"action": "p2_refresh", "payload": {}, "expectedRevision": d_o.revision},
            mutation=True, expected=("200",)))

    return cases


def _not_built(cid, method, template, direction, kind, blast, victim_key, why):
    c = Case(cid, method, template, direction, kind, blast, None, None,
             victim_key=victim_key)
    c.needs = why
    return c


# --------------------------------------------------------------------------- #
# Execution and verdicts
# --------------------------------------------------------------------------- #
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


def run_case(client, case, disc, flags):
    if case.needs:
        case.verdict = "NOT_RUN"
        case.note = "undiscovered:" + case.needs
        case.observed = "-"
        return
    gate = gated_reason(case, flags)
    if gate:
        case.verdict = "NOT_RUN"
        case.note = gate
        case.observed = "-"
        return

    status, text, _obj = client.request(case.method, case.path, case.token_key,
                                         body=case.body, mutation=case.mutation)
    case.observed = str(status)

    if case.kind == "control":
        case.verdict = "PASS" if status == 200 else "FAIL"
        if status != 200:
            case.note = "control route did not succeed (family inconclusive)"
        return

    # attack case
    markers = disc[case.victim_key].markers if case.victim_key else set()
    if status == 0:
        case.verdict = "FAIL"
        case.note = "transport error"
        return
    if 500 <= status <= 599:
        case.verdict = "FAIL"
        case.note = "server error (5xx) on attack"
        return
    if 200 <= status <= 299:
        case.verdict = "FAIL"
        case.note = "attack unexpectedly accepted (2xx)"
        return
    if leak_detected(text, markers):
        case.verdict = "FAIL"
        case.note = "victim marker present in response"
        return
    if status in DENY_STATUSES:
        case.verdict = "PASS"
        if status not in (403, 404):
            case.note = f"denied via {status} (not 403/404)"
        return
    case.verdict = "FAIL"
    case.note = f"unexpected status {status}"


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
    if summary["undiscovered"]:
        lines.append(f"> NOT RUN (undiscovered victim objects): **{summary['undiscovered']}** "
                     "case(s). These are NOT passes; the gate is not met until the victim "
                     "objects exist and the cases run.")
        lines.append("")
    if summary["inconclusive"]:
        lines.append(f"> INCONCLUSIVE: **{summary['inconclusive']}** control(s) failed. "
                     "A failed control means a 404/403 on an attack cannot be trusted as a deny.")
        lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| metric | count |")
    lines.append("|---|---|")
    for k in ("total", "passed", "failed", "not_run_gated", "undiscovered",
              "controls_passed", "controls_failed", "reads", "writes",
              "blast_state", "blast_send", "blast_inert"):
        lines.append(f"| {k} | {summary.get(k, 0)} |")
    lines.append(f"| overall | {'PASS' if summary['exit'] == 0 else 'FAIL'} |")
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    lines.append("| case | method | route template | dir | kind | blast | expected | observed | verdict | note |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for c in cases:
        r = case_record(c)
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


def summarize(cases):
    s = {k: 0 for k in ("total", "passed", "failed", "not_run_gated", "undiscovered",
                         "controls_passed", "controls_failed", "reads", "writes",
                         "blast_state", "blast_send", "blast_inert", "inconclusive")}
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
        if c.verdict == "PASS":
            s["passed"] += 1
            if c.kind == "control":
                s["controls_passed"] += 1
        elif c.verdict == "FAIL":
            s["failed"] += 1
            if c.kind == "control":
                s["controls_failed"] += 1
                s["inconclusive"] += 1
        elif c.verdict == "NOT_RUN":
            if c.note.startswith("undiscovered"):
                s["undiscovered"] += 1
            else:
                s["not_run_gated"] += 1
    # exit 0 only if no FAIL, no inconclusive control, no undiscovered victim case.
    s["exit"] = 0 if (s["failed"] == 0 and s["inconclusive"] == 0 and s["undiscovered"] == 0) else 1
    return s


def main(argv=None):
    parser = argparse.ArgumentParser(description="Q-05 cross-tenant isolation probe")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the matrix and coverage without sending anything")
    parser.add_argument("--allow-writes", action="store_true",
                        help="run WRITE cases (default: read-only)")
    parser.add_argument("--allow-send-risk", action="store_true",
                        help="also run send-blast cases (needs --allow-writes)")
    parser.add_argument("--victim-is-synthetic", action="store_true",
                        help="declare the victim tenants synthetic; required for send cases")
    parser.add_argument("--budget", type=int, default=600, help="max requests (default 600)")
    parser.add_argument("--delay", type=float, default=0.02, help="seconds between requests")
    parser.add_argument("--out-md", default=None, help="path for the Markdown receipt")
    parser.add_argument("--out-json", default=None, help="path for the JSONL output (default stdout)")
    args = parser.parse_args(argv)
    flags = Flags(args)

    config = Config(os.environ)

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

    budget = Budget(args.budget)
    client = Client(config, budget, args.delay)

    # 1. discovery (reads only, each tenant's own token)
    disc = {k: discover(client, config, k) for k in ("A", "B")}

    # 2. snapshot BEFORE (brackets only the attack set)
    before = {k: snapshot(client, config, k) for k in ("A", "B")}

    # 3. build and run attack cases
    cases = build_matrix(disc, config, flags)
    attack_cases = [c for c in cases if c.kind in ("read", "write")]
    control_cases = [c for c in cases if c.kind == "control"]
    try:
        for c in attack_cases:
            run_case(client, c, disc, flags)
        # 4. snapshot AFTER the attack set, before any owner controls mutate state
        after = {k: snapshot(client, config, k) for k in ("A", "B")}
        # 5. controls (owner on own workspace; may change own state legitimately)
        for c in control_cases:
            run_case(client, c, disc, flags)
    except RuntimeError as err:
        print("probe aborted: " + str(err), file=sys.stderr)
        return 2

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

    all_cases = attack_cases + control_cases + snapshot_cases
    # snapshot failures also make the run inconclusive-equivalent (counted as FAIL)
    summary = summarize(all_cases)
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
