"""Connection Health Center (connection_health.py): truthful per-platform readiness, flag-off golden, no false ready.

Fixtures are real records, not hand-written state strings: every channel row is the record
`HostedPhase2Commands.upsert_verified_channel` saves, every capability matrix comes from `OAuthService._capabilities`
for a mounted adapter from `providers.registry_from_environment`, and every view goes through `channels.customer_view`
(with the YouTube vault overlay) and `OAuthService.connection_readiness`, exactly as `OAuthService.channels` builds them.
"""
import copy
import io
import json
import unittest
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2 import connection_health as health
from postriff_phase2 import providers
from postriff_phase2.channels import assisted_matrix, customer_view, with_youtube_credential_status
from postriff_phase2.oauth import CredentialVault, OAuthService

NOW = 1_800_000_000.0
KEY = CredentialVault.generate_key()
ON = {health.FLAG: "1", health.WORKSPACES: "ws-a"}


def environment(**extra):
    values = {"POSTRIFF_PUBLIC_BASE_URL": "https://app.example", "POSTRIFF_TELEGRAM_BOT_TOKEN": "123456:synthetic-telegram-token",
              "POSTRIFF_TELEGRAM_WEBHOOK_SECRET": "s" * 40, "POSTRIFF_DISCORD_BOT_TOKEN": "synthetic-discord-token",
              "POSTRIFF_OAUTH_REDDIT_CONTACT": "ops@example.com", "POSTRIFF_YOUTUBE_CREATOR_ENABLED": "1"}
    for pid in providers.ADAPTERS:
        prefix = f"POSTRIFF_OAUTH_{pid.upper()}_"
        values.update({prefix + "CLIENT_ID": "synthetic-id-" + pid, prefix + "CLIENT_SECRET": "synthetic-secret-" + pid,
                       prefix + "ENABLED": "true", prefix + "VERIFIED": "true"})
    values.update(extra)
    return values


class World:
    """One deployment: mounted adapters and their catalogue, as `OAuthService.channels` sees them."""

    def __init__(self, **extra):
        self.registry = providers.registry_from_environment(environment(**extra))
        self.oauth = OAuthService(None, None, CredentialVault(KEY), self.registry, "https://app.example", clock=lambda: NOW)
        self.catalog = self.oauth.provider_catalog()
        self.by_platform = {p["platform"]: p for p in self.catalog}

    def adapter(self, pid):
        return self.registry[pid]

    def view(self, pid, capability, granted, *, account="acct-1", expires=None, record=None, credential=None, matrix=None):
        """The Channels row for a completed OAuth grant (oauth._complete → upsert_verified_channel → channels)."""
        adapter = self.adapter(pid)
        requested = adapter.capability_scopes(capability)
        if pid == "youtube":
            from postriff_phase2.youtube.model import has_scopes
            missing = sorted(scope for scope in requested if not has_scopes(granted, (scope,)))
        else:
            missing = sorted(set(requested) - set(granted))
        built = OAuthService._capabilities(adapter, capability, list(granted), missing, NOW, "synthetic-access") if matrix is None else matrix
        channel = {"id": OAuthService._connection_id(pid, account), "platform": adapter.platform, "account": account,
                   "accountType": "professional", "scopes": sorted(granted), "verifiedAt": NOW,
                   "expiresAt": NOW + 30 * 86400 if expires is None else expires, "capabilityVersion": adapter.capability_version,
                   "providerAccountId": account}
        if pid == "youtube":
            channel.update(refreshBindingRequired=False, authorizationLane="standard", youtubeIdentityIngestedAt=NOW)
        channel.update({"configured": True, "identityVerified": True,
                        "capabilityVerified": not missing and built["publish"]["level"] == "Direct", "revoked": False,
                        "qualification": "server_verified", "evidenceSource": "live_provider", "scenario": None})
        channel.update(record or {})
        if pid == "youtube":
            channel = with_youtube_credential_status(channel, credential)
        view = {**customer_view(channel, built, NOW), "pictureDigest": None}
        view["socialReadiness"] = OAuthService.connection_readiness(view, self.by_platform[adapter.platform])
        return view

    def health(self, views, *, facts=..., collection=None, history_enabled=False, can_manage=True, youtube_policy=None,
               autonomy=None, publishing_live=True):
        payload = {"channels": views, "providers": self.catalog}
        facts = {v["id"]: {} for v in views} if facts is ... else facts   # None = the facts could not be read
        return health.build(payload, adapters=dict(self.registry), facts=facts, collection=collection or {},
                            history_enabled=history_enabled, can_manage=can_manage, youtube_policy=youtube_policy,
                            autonomy=autonomy or {"source": "todays_behaviour", "mode": "off", "href": None}, now=NOW,
                            publishing_live=publishing_live)

    def account(self, view, **kwargs):
        result = self.health([view], **kwargs)
        accounts = [a for p in result["platforms"] for a in p["accounts"]]
        assert len(accounts) == 1, accounts
        return accounts[0]


def all_scopes(adapter):
    return sorted({scope for scopes in adapter.SCOPES.values() for scope in scopes})


class FlagTests(unittest.TestCase):
    def test_off_unless_flag_and_listed(self):
        self.assertFalse(health.workspace_enabled("ws-a", {}))
        self.assertFalse(health.workspace_enabled("ws-a", {health.FLAG: "1"}))            # empty list = no workspace
        self.assertFalse(health.workspace_enabled("ws-a", {health.FLAG: "0", health.WORKSPACES: "*"}))
        self.assertFalse(health.workspace_enabled("ws-b", ON))
        self.assertTrue(health.workspace_enabled("WS-A", ON))
        self.assertTrue(health.workspace_enabled("anything", {health.FLAG: "true", health.WORKSPACES: "*"}))

    def test_channels_response_is_unchanged_when_off(self):
        payload = {"channels": [{"id": "c"}], "providers": []}
        before = copy.deepcopy(payload)
        for env in ({}, {health.FLAG: "1"}, {health.FLAG: "1", health.WORKSPACES: "ws-b"}):
            self.assertIs(health.annotate_channels(payload, "ws-a", env), payload)
        self.assertEqual(payload, before)
        added = health.annotate_channels(payload, "ws-a", ON)
        self.assertEqual(added["connectionHealth"], {"available": True, "href": "/app/channels/health"})
        self.assertEqual(payload, before)   # never mutated


class Fake:
    """The smallest hosted service the router needs, with a recorded Channels reading."""

    def __init__(self, env):
        self.connection_health_env = env
        self.reads = []
        world = World()
        self.payload = {"channels": [world.view("linkedin", "publish", all_scopes(world.adapter("linkedin")))], "providers": world.catalog}
        outer = self

        class OAuth:
            providers = world.registry
            clock = staticmethod(lambda: NOW)

            def channels(self, workspace_id, token):
                outer.reads.append(workspace_id)
                if workspace_id != "ws-a":
                    raise AlphaError("Workspace unavailable.", 403)
                return copy.deepcopy(outer.payload)

        self.oauth = OAuth()


def call(service, path):
    from postriff_phase2.hosted_app import HostedApplication
    captured = {}
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "wsgi.input": io.BytesIO(b""), "wsgi.url_scheme": "https",
               "HTTP_HOST": "app.example", "HTTP_AUTHORIZATION": "Bearer synthetic-session-" + "x" * 30}
    body = b"".join(HostedApplication(service, SimpleNamespace())(environ, lambda status, headers: captured.update(status=status)))
    return captured["status"], body


class RouteGoldenTests(unittest.TestCase):
    def test_flag_off_route_answers_exactly_like_an_unknown_route(self):
        for env in ({}, {health.FLAG: "0", health.WORKSPACES: "*"}):
            service = Fake(env)
            unknown = call(service, "/api/workspaces/ws-a/no-such-route")
            self.assertTrue(unknown[0].startswith("404"))
            self.assertEqual(call(service, "/api/workspaces/ws-a/connection-health"), unknown)
            self.assertEqual(service.reads, [])   # nothing was read for the disabled route

    def test_flag_off_channels_bytes_are_unchanged(self):
        service = Fake({})
        status, body = call(service, "/api/workspaces/ws-a/channels")
        self.assertTrue(status.startswith("200"))
        self.assertEqual(body, json.dumps(service.payload, ensure_ascii=False).encode())
        status, body = call(Fake({health.FLAG: "1", health.WORKSPACES: "ws-b"}), "/api/workspaces/ws-a/channels")
        self.assertNotIn(b"connectionHealth", body)

    def test_unlisted_workspace_gets_the_unknown_route_answer_after_membership(self):
        env = {health.FLAG: "1", health.WORKSPACES: "ws-z"}
        service = Fake(env)
        self.assertEqual(call(service, "/api/workspaces/ws-a/connection-health"), call(Fake({}), "/api/workspaces/ws-a/no-such-route"))
        self.assertEqual(service.reads, ["ws-a"])     # membership was checked first
        status, body = call(Fake(ON), "/api/workspaces/ws-other/connection-health")
        self.assertTrue(status.startswith("403"), body)   # not a member: the same answer as every foreign workspace

    def test_api_tokens_never_read_health(self):
        from postriff_phase2.api_tokens import route_scope
        self.assertIsNone(route_scope("GET", ["api", "workspaces", "ws-a", "connection-health"]))
        with self.assertRaises(AlphaError) as raised:
            health.ConnectionHealth(Fake(ON), ON).read("ws-a", "prt_" + "x" * 40)
        self.assertEqual(raised.exception.status, 403)


class StateMappingTests(unittest.TestCase):
    """Every provider × the connection states its real records can reach."""

    def setUp(self):
        self.world = World()

    def test_every_mountable_provider_through_every_state(self):
        world = self.world
        seen = set()
        for pid, adapter in sorted(world.registry.items()):
            provider = world.by_platform[adapter.platform]
            if not provider.get("connectReady"):
                continue
            with self.subTest(provider=pid):
                full = all_scopes(adapter)
                identity = adapter.capability_scopes("identity")
                cases = {
                    # An identity grant can still carry read scopes (Instagram's basic scope reads your posts).
                    "identity_only": (world.view(pid, "identity", identity), ("connected", "limited", "authorized")),
                    "no_scopes": (world.view(pid, "publish", [], record={"scopes": []}), ("connected",)),
                    "expired": (world.view(pid, "publish", full, expires=NOW - 60, credential={"refreshSupported": False, "refreshBindingRequired": False, "accessTokenExpiresAt": NOW - 60, "revoked": False}), ("expired",)),
                    "revoked": (world.view(pid, "publish", full, record={"revoked": True}), ("expired",)),
                    "disconnected": (world.view(pid, "publish", full, record={"configured": False}), ("not_connected",)),
                }
                if pid == "youtube":
                    cases["identity_only"] = (world.view(pid, "identity", identity, credential={"refreshSupported": True, "refreshBindingRequired": False, "accessTokenExpiresAt": NOW + 3000, "revoked": False}), ("connected", "limited", "authorized"))
                for name, (view, expected) in cases.items():
                    account = world.account(view)
                    seen.add(account["state"])
                    self.assertTrue(set(account["reasons"]) <= set(health.REASONS), account["reasons"])
                    self.assertIn(account["state"], expected, (pid, name, account))
                    self.assertNoFalseReady(account)
                    self.assertIn(account["state"], health.STATES)
                    for line in account["lines"].values():
                        self.assertIn(line["status"], health.LINE_STATUSES)
                    if account["state"] in ("expired", "not_connected"):
                        self.assertFalse(any(line["status"] in health.USABLE for line in account["lines"].values()), (pid, name))
                granted = world.account(world.view(pid, "publish", full))
                seen.add(granted["state"])
                # Platforms that offer nothing beyond the account (no approved publishing yet) stay "connected".
                self.assertIn(granted["state"], ("ready", "limited", "authorized", "connected"))
                if granted["state"] == "connected":
                    self.assertEqual(granted["reasons"][0], "account_only")
                    self.assertFalse(any(offered for key, offered in provider["capabilities"].items() if key != "identity"))
                self.assertNoFalseReady(granted)
        self.assertTrue({"connected", "expired", "not_connected", "limited"} <= seen, seen)

    def assertNoFalseReady(self, account):
        if account["state"] == "ready":
            self.assertEqual(account["lines"]["publishing"]["status"], "available")
            self.assertIn(account["lines"]["analytics"]["status"], ("available", "on_request"))
            self.assertNotIn(account["access"]["status"], ("expired", "revoked", "reconnect_required"))

    def test_platforms_that_cannot_be_connected_here_are_unsupported_not_ready(self):
        result = self.world.health([])
        states = {p["platform"]: p["state"] for p in result["platforms"]}
        for provider in self.world.catalog:
            expected = "not_connected" if provider.get("connectReady") and not provider.get("executionPaused") else "unsupported"
            self.assertEqual(states[provider["platform"]], expected, provider["platform"])
        self.assertEqual(states["Weibo"], "unsupported")      # endpoint contract not verified
        self.assertEqual(states["Bluesky"], "unsupported")    # not configured on this deployment

    def test_an_account_on_an_unmounted_platform_is_blocked(self):
        view = {**customer_view({"id": "b1", "platform": "Bluesky", "account": "@me", "configured": True, "identityVerified": True,
                                  "capabilityVerified": True, "scopes": ["atproto"], "expiresAt": NOW + 86400, "revoked": False},
                                 assisted_matrix(), NOW), "pictureDigest": None}
        account = self.world.account(view)
        self.assertEqual(account["state"], "blocked")
        self.assertEqual(account["reasons"][0], "platform_unavailable")
        self.assertFalse(account["reconnect"]["available"])
        self.assertTrue(all(line["status"] in ("unavailable", "not_offered") for line in account["lines"].values()))

    def test_operator_pause_blocks_even_a_fully_granted_account(self):
        world = World(POSTRIFF_OAUTH_THREADS_REVIEWED="true", POSTRIFF_OAUTH_THREADS_DISABLED="true")
        view = world.view("threads", "publish", all_scopes(world.adapter("threads")))
        self.assertEqual(view["capabilities"]["publish"]["level"], "Direct")   # the stored row still says Direct
        account = world.account(view, collection={"threads": True})
        self.assertEqual(account["state"], "blocked")
        self.assertEqual(account["reasons"][0], "operator_paused")
        self.assertEqual(account["lines"]["publishing"]["status"], "unavailable")


class NoFalseReadyTests(unittest.TestCase):
    def test_unknown_scope_requirements_never_claim_a_grant(self):
        adapter = SimpleNamespace(capability_scopes=lambda _cap: (_ for _ in ()).throw(RuntimeError("unavailable")))
        view = {"platform": "Threads", "scopes": ["threads_basic", "threads_content_publish"],
                "capabilities": {"publish": {"level": "Direct"}}}
        provider = {"capabilities": {"publish": True}}
        self.assertIsNone(health.required_scopes(adapter, None, "publish"))
        self.assertFalse(health._granted(view, provider, adapter, None, "publish"))
        self.assertNotEqual(health.publishing_line(view, provider, adapter, None)["status"], "available")

    def test_connection_alone_is_never_ready(self):
        world = World(POSTRIFF_OAUTH_LINKEDIN_REVIEWED="true")
        linkedin = world.account(world.view("linkedin", "publish", all_scopes(world.adapter("linkedin"))))
        self.assertEqual(linkedin["lines"]["publishing"]["status"], "available")
        self.assertEqual(linkedin["lines"]["analytics"]["status"], "not_offered")   # LinkedIn has no analytics scope
        self.assertEqual(linkedin["state"], "limited")

    def test_expired_access_with_direct_rows_is_expired_on_every_line(self):
        world = World(POSTRIFF_OAUTH_THREADS_REVIEWED="true")
        view = world.view("threads", "publish", all_scopes(world.adapter("threads")), expires=NOW - 1)
        self.assertEqual(view["capabilities"]["publish"]["level"], "Direct")
        self.assertEqual(view["connectionState"], "token_expired")
        account = world.account(view, collection={"threads": True})
        self.assertEqual((account["state"], account["reasons"][0]), ("expired", "access_expired"))
        self.assertEqual({line["status"] for line in account["lines"].values()} - {"not_offered"}, {"unavailable"})
        self.assertTrue(account["attention"])

    def test_revoked_youtube_grant_is_revoked_not_ready(self):
        world = World(POSTRIFF_OAUTH_YOUTUBE_REVIEWED="true")
        view = world.view("youtube", "publish", all_scopes(world.adapter("youtube")),
                          credential={"refreshSupported": False, "refreshBindingRequired": False, "accessTokenExpiresAt": NOW + 3000, "revoked": True})
        account = world.account(view)
        self.assertEqual((account["state"], account["reasons"][0]), ("expired", "access_revoked"))

    def test_youtube_refreshable_grant_is_not_expired_and_binding_needs_one_reconnect(self):
        world = World()
        scopes = all_scopes(world.adapter("youtube"))
        renewing = world.account(world.view("youtube", "publish", scopes, expires=NOW - 10,
                                            credential={"refreshSupported": True, "refreshBindingRequired": False, "accessTokenExpiresAt": NOW - 10, "revoked": False}))
        self.assertNotEqual(renewing["state"], "expired")
        self.assertTrue(renewing["access"]["renewsAutomatically"])
        self.assertIsNone(renewing["access"]["expiresAt"])        # an access-token deadline is not a grant expiry
        self.assertEqual(renewing["lines"]["publishing"]["status"], "private_only")
        self.assertEqual(renewing["lines"]["analytics"]["status"], "on_request")
        self.assertEqual(renewing["state"], "limited")            # private uploads only: never ready
        binding = world.account(world.view("youtube", "publish", scopes,
                                           credential={"refreshSupported": False, "refreshBindingRequired": True, "accessTokenExpiresAt": NOW + 3000, "revoked": False}))
        self.assertEqual((binding["state"], binding["reasons"][0]), ("expired", "reconnect_required"))

    def test_youtube_policy_review_and_unpublished_policy(self):
        world = World()
        view = world.view("youtube", "publish", all_scopes(world.adapter("youtube")),
                          credential={"refreshSupported": True, "refreshBindingRequired": False, "accessTokenExpiresAt": NOW + 3000, "revoked": False})
        review = world.account(view, youtube_policy={"ready": True, "requiredForConnection": True, "accepted": False})
        self.assertIn("youtube_policy_review", review["reasons"])
        self.assertNotEqual(review["state"], "ready")
        self.assertTrue(review["attention"])
        blocked = world.account(view, youtube_policy={"ready": False, "requiredForConnection": True, "accepted": False})
        self.assertEqual((blocked["state"], blocked["reasons"][0]), ("blocked", "youtube_policy_unavailable"))
        quiet = world.account(view, youtube_policy={"ready": True, "requiredForConnection": False, "accepted": False})
        self.assertNotIn("youtube_policy_review", quiet["reasons"])

    def test_instagram_analytics_wait_for_meta_and_for_collection(self):
        world = World()
        view = world.view("instagram", "analytics", all_scopes(world.adapter("instagram")))
        self.assertEqual(view["capabilities"]["analytics"]["level"], "Direct")   # account-scoped Standard Access grant
        waiting = world.account(view)
        self.assertEqual(waiting["lines"]["analytics"]["status"], "awaiting_review")   # Meta approval not recorded
        self.assertNotEqual(waiting["state"], "ready")
        approved = World(POSTRIFF_OAUTH_INSTAGRAM_ANALYTICS_APPROVED="true")
        view = approved.view("instagram", "analytics", all_scopes(approved.adapter("instagram")))
        self.assertEqual(approved.account(view)["lines"]["analytics"]["status"], "not_collected")
        self.assertEqual(approved.account(view, collection={"instagram": True})["lines"]["analytics"]["status"], "available")

    def test_instagram_without_the_insights_scope_is_not_granted_whatever_the_row_says(self):
        world = World()
        granted = [s for s in all_scopes(world.adapter("instagram")) if s != "instagram_business_manage_insights"]
        full = world.view("instagram", "analytics", all_scopes(world.adapter("instagram")))
        view = world.view("instagram", "publish", granted, matrix=copy.deepcopy(full["capabilities"]))   # stale Direct row
        account = world.account(view, collection={"instagram": True})
        self.assertEqual(account["lines"]["analytics"], {"status": "not_granted", "grant": "analytics"})
        missing = {m["capability"]: m["scopes"] for m in account["missingPermissions"]}
        self.assertEqual(missing, {"analytics": ["instagram_business_manage_insights"]})
        self.assertEqual(account["reconnect"]["grants"], ["analytics"])

    def test_ready_needs_working_publishing_and_collected_analytics(self):
        world = World(POSTRIFF_OAUTH_THREADS_REVIEWED="true", POSTRIFF_OAUTH_THREADS_ANALYTICS_APPROVED="true")
        view = world.view("threads", "publish", all_scopes(world.adapter("threads")))
        limited = world.account(view)
        self.assertEqual(limited["lines"]["analytics"]["status"], "not_collected")
        self.assertEqual(limited["state"], "limited")
        ready = world.account(view, collection={"threads": True}, facts={view["id"]: {"analyticsAt": NOW - 60, "latestDataAt": NOW - 60}})
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["freshness"]["band"], "recent")
        failed = world.account(view, collection={"threads": True},
                               facts={view["id"]: {"analyticsAt": NOW - 9 * 86400, "latestDataAt": NOW - 9 * 86400, "problemAt": NOW - 3600}})
        self.assertEqual(failed["sync"]["status"], "failed")
        self.assertEqual(failed["freshness"]["band"], "older")
        self.assertNotEqual(failed["state"], "ready")
        self.assertIn("sync_failed", failed["reasons"])
        syncing = world.account(view, collection={"threads": True}, facts={view["id"]: {"importRunning": True}})
        self.assertEqual(syncing["state"], "syncing")
        unknown = world.health([view], collection={"threads": True}, facts=None)["platforms"][0]["accounts"][0]
        self.assertEqual(unknown["sync"]["status"], "unknown")      # unread facts are unknown, never "never"
        self.assertEqual(unknown["freshness"]["band"], "unknown")

    def test_unreviewed_publishing_is_assisted_with_the_review_named(self):
        world = World()
        view = world.view("linkedin", "publish", all_scopes(world.adapter("linkedin")))
        account = world.account(view)
        # The grant is there; LinkedIn has not approved Rafii's posting, so Rafii prepares and you post.
        self.assertEqual(account["lines"]["publishing"], {"status": "assisted", "detail": "awaiting_review"})
        self.assertEqual(account["state"], "limited")

    def test_a_grant_with_nothing_usable_yet_is_authorized(self):
        from postriff_phase2.youtube.model import READ, UPLOAD
        world = World(POSTRIFF_YOUTUBE_CREATOR_ENABLED="0")     # creator features are off on this deployment
        account = world.account(world.view("youtube", "publish", [READ, UPLOAD],
                                           credential={"refreshSupported": True, "refreshBindingRequired": False, "accessTokenExpiresAt": NOW + 3000, "revoked": False}))
        self.assertEqual(account["state"], "authorized")
        self.assertFalse(any(line["status"] in health.USABLE for line in account["lines"].values()))
        self.assertEqual(account["lines"]["publishing"]["status"], "awaiting_review")

    def test_a_grant_is_not_a_publisher_without_live_transport_or_with_a_demo_record(self):
        world = World(POSTRIFF_OAUTH_THREADS_REVIEWED="true", POSTRIFF_OAUTH_THREADS_ANALYTICS_APPROVED="true")
        view = world.view("threads", "publish", all_scopes(world.adapter("threads")))
        off = world.account(view, collection={"threads": True}, publishing_live=False)
        self.assertEqual(off["lines"]["publishing"], {"status": "not_enabled"})
        self.assertIn("publishing_off", off["reasons"])
        self.assertNotEqual(off["state"], "ready")
        demo = world.account({**view, "evidenceSource": "synthetic"}, collection={"threads": True})
        self.assertEqual(demo["lines"]["publishing"], {"status": "not_enabled"})
        self.assertIn("demo_account", demo["reasons"])
        self.assertNotEqual(demo["state"], "ready")

    def test_expiring_soon_is_called_out(self):
        world = World(POSTRIFF_OAUTH_LINKEDIN_REVIEWED="true")
        account = world.account(world.view("linkedin", "publish", all_scopes(world.adapter("linkedin")), expires=NOW + 2 * 86400))
        self.assertEqual(account["access"]["status"], "expiring")
        self.assertIn("access_expiring", account["reasons"])
        self.assertTrue(account["attention"])

    def test_customer_disconnects_are_not_listed(self):
        world = World()
        view = world.view("threads", "publish", all_scopes(world.adapter("threads")), record={"revoked": True})
        for row in view["capabilities"].values():
            row["evidence"] = health.DISCONNECTED_EVIDENCE
        result = world.health([view])
        self.assertEqual([a for p in result["platforms"] for a in p["accounts"]], [])

    def test_reconnect_targets_only_the_existing_oauth_flow_and_respects_roles(self):
        world = World()
        view = world.view("threads", "identity", world.adapter("threads").capability_scopes("identity"))
        owner = world.account(view)
        self.assertEqual(owner["reconnect"]["providerId"], "threads")
        self.assertEqual(owner["reconnect"]["channelId"], view["id"])
        self.assertEqual(set(owner["reconnect"]), {"available", "providerId", "channelId", "account", "grants"})
        viewer = world.account(view, can_manage=False)
        self.assertEqual(viewer["reconnect"], {"available": False, "reason": "manage_required"})
        self.assertFalse(world.health([view], can_manage=False)["canManage"])


class AutonomyTests(unittest.TestCase):
    def test_todays_behaviour_until_lane_b1_is_on(self):
        self.assertEqual(health.autonomy_summary(None, "ws-a", "u", None, {}, NOW, {}), {"source": "todays_behaviour", "mode": "off", "href": None})

    def test_permissions_mode_reuses_live_runtime_config(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        config = SimpleNamespace(permissions_for=Mock(return_value="enforce"))
        service = SimpleNamespace(agent_permissions_config=config)
        self.assertEqual(health.permissions_mode("ws-a", {}, service), "enforce")
        config.permissions_for.assert_called_once_with("ws-a")
        service = SimpleNamespace(agent_runtime=SimpleNamespace(cfg=config))
        self.assertEqual(health.permissions_mode("ws-a", {}, service), "enforce")

    def test_lane_b1_payload_is_reduced_to_allowlisted_values(self):
        payload = {"available": True, "state": {"preset": "recommended", "needsChoice": False, "source": "<script>"},
                   "categories": [{"id": "manage_connected_services", "mode": "ask", "effective": {"state": "asks", "reasons": [{"message": "x"}]}},
                                  {"id": "unknown_category", "mode": "assist", "effective": {"state": "on"}},
                                  {"id": "create_edit", "mode": "everything", "effective": {"state": "always"}}]}
        summary = health.summarize_permissions(payload, "shadow")
        self.assertEqual(summary, {"source": "agent_permissions", "mode": "shadow", "preset": "recommended", "needsChoice": False,
                                   "categories": [{"id": "manage_connected_services", "mode": "ask", "effective": "asks"},
                                                  {"id": "create_edit", "mode": None, "effective": "unavailable"}],
                                   "href": "/app/account/agent"})
        self.assertEqual(health.summarize_permissions(None, "enforce")["source"], "unavailable")   # unread is never "off"


class IsolationTests(unittest.TestCase):
    """Every fact query is bound to this workspace and its own connection ids (PG proof: postgres_connection_health.py)."""

    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))

        def fetchall(self):
            return []

    def test_every_fact_query_filters_by_workspace_and_connection(self):
        cur = self.Cursor()
        facts = health.sync_facts(cur, "ws-a", ["c2", "c1", "c1", None])
        self.assertEqual(facts, {"c1": {}, "c2": {}})
        reads = [(sql, params) for sql, params in cur.calls if not sql.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK"))]
        self.assertEqual(len(reads), 3)
        for sql, params in reads:
            self.assertIn("workspace_id=%s AND connection_id=ANY(%s)", sql)
            self.assertEqual(params, ("ws-a", ["c1", "c2"]))

    def test_a_failed_fact_read_is_unknown_not_empty(self):
        class Broken(self.Cursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                if "pr_metric_reads" in sql:
                    raise RuntimeError("relation does not exist")
        self.assertIsNone(health.sync_facts(Broken(), "ws-a", ["c1"]))


if __name__ == "__main__":
    unittest.main()
