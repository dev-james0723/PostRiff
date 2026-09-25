"""Wave 1 hosted connectors (Bluesky, Mastodon, Telegram, Discord, X): adapters, mount rules, OAuth service flows
and publishing, all offline with injected transports. Live provider accounts are a separate deployment gate."""
import base64
import copy
import hashlib
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError
from postriff_phase2 import providers
from postriff_phase2.atproto_oauth import BlueskyProvider, b64u, b64u_decode, generate_jwk, tid
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.outcomes import normalize_result
from postriff_phase2.permissions import Membership, require
from postriff_phase2.social_connectors import DiscordProvider, MastodonProvider, TelegramConnector, XProvider

BASE = "https://app.example"
DID = "did:plc:abcdefghijklmnopqrstuvwx"
BOT = "123456789:" + "A" * 35
SECRET = "webhook-secret-0123456789"


def PUBLIC(host, port, type=None):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def PRIVATE(host, port, type=None):
    return [(2, 1, 6, "", ("10.0.0.5", 443))]


def ok(body=None, status=200, headers=None):
    return {"status": status, "headers": headers or {}, "body": {} if body is None else body}


class Wire:
    def __init__(self, responses=()):
        self.calls, self.responses = [], list(responses)

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "form": form, "body": body, "data": data})
        if not self.responses:
            raise AssertionError(f"unexpected {method} {url}")
        return self.responses.pop(0)


def jwt(token):
    header, payload, signature = token.split(".")
    return json.loads(b64u_decode(header)), json.loads(b64u_decode(payload)), signature


def verify_es256(token, jwk):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    header, payload, signature = token.split(".")
    raw = b64u_decode(signature)
    public = ec.EllipticCurvePublicNumbers(int.from_bytes(b64u_decode(jwk["x"]), "big"), int.from_bytes(b64u_decode(jwk["y"]), "big"), ec.SECP256R1()).public_key()
    public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), f"{header}.{payload}".encode(), ec.ECDSA(hashes.SHA256()))


def client_jwk():
    return generate_jwk(kid="rafii-2026-09")


# --- mount rules ----------------------------------------------------------------------------------------------------
class MountRules(unittest.TestCase):
    def test_nothing_mounts_without_credentials_and_existing_three_are_unchanged(self):
        self.assertEqual(providers.registry_from_environment({"POSTRIFF_PUBLIC_BASE_URL": BASE}), {})
        registry = providers.registry_from_environment({"POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID": "id", "POSTRIFF_OAUTH_LINKEDIN_CLIENT_SECRET": "s"})
        self.assertEqual(set(registry), {"linkedin"})
        self.assertEqual(registry.diagnostics["bluesky"]["configurationState"], "not_configured")

    def test_each_wave1_adapter_mounts_only_with_its_own_complete_configuration(self):
        values = {"POSTRIFF_PUBLIC_BASE_URL": BASE, "POSTRIFF_BLUESKY_CLIENT_JWK": json.dumps(client_jwk()),
                  "POSTRIFF_OAUTH_MASTODON_ENABLED": "true",
                  "POSTRIFF_TELEGRAM_BOT_TOKEN": BOT, "POSTRIFF_TELEGRAM_WEBHOOK_SECRET": SECRET,
                  "POSTRIFF_OAUTH_DISCORD_CLIENT_ID": "1234567", "POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET": "ds", "POSTRIFF_DISCORD_BOT_TOKEN": "bot.token",
                  "POSTRIFF_OAUTH_X_CLIENT_ID": "xid", "POSTRIFF_OAUTH_X_CLIENT_SECRET": "xs", "POSTRIFF_OAUTH_X_REVIEWED": "true",
                  "POSTRIFF_OAUTH_DISCORD_DISABLED": "true"}
        registry = providers.registry_from_environment(values)
        self.assertEqual(set(registry), {"bluesky", "mastodon", "telegram", "discord", "x"})
        self.assertTrue(registry["x"].production_reviewed)
        self.assertFalse(registry["bluesky"].production_reviewed)
        self.assertFalse(registry["discord"].execution_enabled)
        self.assertEqual(registry["bluesky"].client_id, BASE + "/api/oauth/bluesky/client-metadata.json")

    def test_partial_and_invalid_configurations_never_mount_or_echo_values(self):
        cases = {
            "bluesky": {"POSTRIFF_PUBLIC_BASE_URL": BASE, "POSTRIFF_BLUESKY_CLIENT_JWK": '{"kty":"EC"}'},
            "mastodon": {"POSTRIFF_PUBLIC_BASE_URL": BASE, "POSTRIFF_OAUTH_MASTODON_ENABLED": "yes"},
            "telegram": {"POSTRIFF_PUBLIC_BASE_URL": BASE, "POSTRIFF_TELEGRAM_BOT_TOKEN": BOT},
            "discord": {"POSTRIFF_PUBLIC_BASE_URL": BASE, "POSTRIFF_OAUTH_DISCORD_CLIENT_ID": "1", "POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET": "2"},
        }
        for provider_id, values in cases.items():
            with self.subTest(provider=provider_id):
                registry = providers.registry_from_environment(values)
                self.assertNotIn(provider_id, registry)
                diagnostic = registry.diagnostics[provider_id]
                self.assertIn(diagnostic["configurationState"], ("partial_configuration", "invalid_configuration"))
                self.assertNotIn(BOT, json.dumps(diagnostic))
        missing = providers.registry_from_environment(cases["telegram"]).diagnostics["telegram"]["missingVariables"]
        self.assertEqual(missing, ["POSTRIFF_TELEGRAM_WEBHOOK_SECRET"])

    def test_catalog_describes_connect_shape_from_adapter_attributes(self):
        registry = providers.registry_from_environment({"POSTRIFF_PUBLIC_BASE_URL": BASE, "POSTRIFF_OAUTH_MASTODON_ENABLED": "true"})
        service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), registry, BASE)
        catalog = {entry["id"]: entry for entry in service.provider_catalog()}
        self.assertEqual(catalog["mastodon"]["startInput"]["name"], "instance")
        self.assertTrue(catalog["mastodon"]["connectReady"])
        self.assertEqual(catalog["telegram"]["connectKind"], "bot_code")
        self.assertTrue(catalog["discord"]["hasDestinations"])
        self.assertEqual(catalog["instagram"]["accountRequirement"], "Instagram Creator or Business account. No Facebook Page required.")
        self.assertEqual(catalog["linkedin"]["accountRequirement"], "LinkedIn member profile.")
        self.assertIn("POSTRIFF_BLUESKY_CLIENT_JWK", " ".join(catalog["bluesky"]["setupIssues"]))


# --- X ------------------------------------------------------------------------------------------------------------
class XAdapter(unittest.TestCase):
    def test_pkce_basic_auth_scopes_identity_refresh_and_revoke(self):
        wire = Wire([ok({"access_token": "AT", "refresh_token": "RT", "expires_in": 7200, "scope": "tweet.read users.read tweet.write media.write offline.access"}),
                     ok({"data": {"id": "42", "username": "rafii", "profile_image_url": "https://pbs.twimg.com/p.jpg"}}),
                     ok({"access_token": "AT2", "expires_in": 7200, "scope": "tweet.read users.read"}),
                     ok({"revoked": True})])
        x = XProvider("client", "secret", transport=wire)
        query = parse_qs(urlparse(x.authorize_url(BASE + "/api/oauth/x/callback", "STATE", "CHALLENGE", x.capability_scopes("publish"))).query)
        self.assertEqual((query["code_challenge"][0], query["code_challenge_method"][0]), ("CHALLENGE", "S256"))
        self.assertIn("offline.access", query["scope"][0].split())
        grant = x.exchange("CODE", "VERIFIER", BASE + "/api/oauth/x/callback")
        self.assertTrue(wire.calls[0]["headers"]["Authorization"].startswith("Basic "))
        self.assertEqual(wire.calls[0]["form"]["code_verifier"], "VERIFIER")
        self.assertEqual(json.loads(grant["accessToken"])["at"], "AT")
        self.assertEqual(x.inspect_scopes(grant["accessToken"]), sorted(grant["scopes"]))
        identity = x.identity(grant["accessToken"])
        self.assertEqual((identity["providerAccountId"], identity["handle"]), ("42", "@rafii"))
        self.assertEqual(wire.calls[1]["headers"]["Authorization"], "Bearer AT")
        refreshed = x.refresh("RT")
        self.assertEqual(refreshed["refreshToken"], "RT")  # X did not rotate it this time
        self.assertTrue(x.revoke(refreshed["accessToken"]))
        self.assertEqual(wire.calls[3]["form"]["token"], "AT2")


# --- Mastodon -----------------------------------------------------------------------------------------------------
class MastodonAdapter(unittest.TestCase):
    def test_registers_per_connect_then_pkce_exchange_identity_and_scopes(self):
        wire = Wire([ok({"client_id": "cid", "client_secret": "csec"}),
                     ok({"access_token": "MT", "scope": "read:accounts read:statuses write:statuses write:media"}),
                     ok({"id": "1099", "username": "james"}),
                     ok({"name": "Rafii", "scopes": ["read:accounts", "write:statuses"]})])
        mastodon = MastodonProvider(BASE, transport=wire, resolver=PUBLIC)
        begun = mastodon.begin(BASE + "/api/oauth/mastodon/callback", "STATE", "VERIFIER", "CHALLENGE", mastodon.capability_scopes("publish"), "https://Mastodon.Social/")
        self.assertEqual(wire.calls[0]["url"], "https://mastodon.social/api/v1/apps")
        self.assertEqual(wire.calls[0]["form"]["website"], BASE)
        query = parse_qs(urlparse(begun["authorizeUrl"]).query)
        self.assertEqual((query["client_id"][0], query["code_challenge_method"][0]), ("cid", "S256"))
        grant = mastodon.exchange("CODE", json.dumps({"verifier": "VERIFIER", **begun["context"]}), BASE + "/api/oauth/mastodon/callback")
        self.assertEqual(wire.calls[1]["form"]["code_verifier"], "VERIFIER")
        self.assertEqual(json.loads(grant["accessToken"])["instance"], "mastodon.social")
        self.assertEqual(mastodon.identity(grant["accessToken"])["providerAccountId"], "1099@mastodon.social")
        self.assertEqual(mastodon.inspect_scopes(grant["accessToken"]), ["read:accounts", "write:statuses"])

    def test_private_or_malformed_servers_are_refused_before_any_request(self):
        for resolver, instance in ((PUBLIC, "localhost"), (PUBLIC, "10.0.0.5"), (PUBLIC, "box.local"), (PRIVATE, "mastodon.example.org"), (PUBLIC, "not a host")):
            with self.subTest(instance=instance):
                wire = Wire([])
                with self.assertRaises(AlphaError):
                    MastodonProvider(BASE, transport=wire, resolver=resolver).begin(BASE + "/cb", "S", "V", "C", ["read:accounts"], instance)
                self.assertEqual(wire.calls, [])


# --- Discord ------------------------------------------------------------------------------------------------------
class DiscordAdapter(unittest.TestCase):
    def adapter(self, wire):
        return DiscordProvider("1234567", "secret", "bot.token", BASE, transport=wire)

    def test_bot_install_needs_a_server_keeps_no_user_token_and_resolves_through_the_bot(self):
        wire = Wire([ok({"access_token": "UT", "scope": "identify bot", "guild": {"id": "555555", "name": "Rafii HQ"}}),
                     ok({"id": "4242424"}), ok({}), ok({"id": "555555", "name": "Rafii HQ", "icon": "abc123"})])
        discord = self.adapter(wire)
        query = parse_qs(urlparse(discord.authorize_url(BASE + "/api/oauth/discord/callback", "STATE", "C", ["identify", "bot"])).query)
        self.assertEqual((query["scope"][0], query["permissions"][0]), ("identify bot", str(DiscordProvider.PERMISSIONS)))
        grant = discord.exchange("CODE", "V", BASE + "/api/oauth/discord/callback")
        self.assertEqual(json.loads(grant["accessToken"]), {"v": 1, "guild": "555555", "channel": None, "user": "4242424"})
        self.assertEqual((wire.calls[1]["url"].endswith("/users/@me"), wire.calls[1]["headers"]["Authorization"]), (True, "Bearer UT"))
        self.assertIn("/oauth2/token/revoke", wire.calls[2]["url"])  # the person's own token is revoked, not stored
        identity = discord.identity(grant["accessToken"])
        self.assertEqual((identity["providerAccountId"], identity["accountType"]), ("555555", "server"))
        self.assertEqual(wire.calls[3]["headers"]["Authorization"], "Bot bot.token")
        self.assertTrue(wire.calls[3]["headers"]["User-Agent"].startswith("DiscordBot ("))
        with self.assertRaises(AlphaError):
            self.adapter(Wire([ok({"access_token": "UT", "scope": "identify bot"})])).exchange("CODE", "V", BASE + "/cb")

    def test_destinations_need_the_bot_to_send_and_the_connecting_person_to_see(self):
        VIEW, SEND = DiscordProvider.VIEW_CHANNEL, DiscordProvider.SEND_MESSAGES
        guild = {"id": "555555", "owner_id": "1000001", "roles": [{"id": "555555", "permissions": str(VIEW | SEND)}, {"id": "7000001", "permissions": "0"}]}
        hidden = [{"id": "555555", "type": 0, "allow": "0", "deny": str(VIEW)}, {"id": "9000009", "type": 1, "allow": str(VIEW | SEND), "deny": "0"}]
        channels = [{"id": "7777777", "name": "general", "type": 0, "position": 1}, {"id": "8888888", "name": "voice", "type": 2},
                    {"id": "9999999", "name": "news", "type": 5, "position": 0},
                    {"id": "6666666", "name": "staff", "type": 0, "position": 2, "permission_overwrites": hidden + [{"id": "7000001", "type": 0, "allow": str(VIEW), "deny": "0"}]},
                    {"id": "5555556", "name": "readonly", "type": 0, "position": 3, "permission_overwrites": [{"id": "555555", "type": 0, "allow": "0", "deny": str(SEND)}]}]
        token = json.dumps({"v": 1, "guild": "555555", "channel": None, "user": "4242424"})
        outsider = self.adapter(Wire(discord_listing(guild, channels, user_roles=[])))
        self.assertEqual([d["id"] for d in outsider.destinations(token)], ["9999999", "7777777"])  # staff is hidden from this person
        staff = self.adapter(Wire(discord_listing(guild, channels, user_roles=["7000001"])))
        self.assertEqual([d["id"] for d in staff.destinations(token)], ["9999999", "7777777", "6666666"])
        chooser = self.adapter(Wire(discord_listing(guild, channels, user_roles=[])))
        self.assertEqual(json.loads(chooser.with_destination(token, "7777777"))["channel"], "7777777")
        for refused in ("8888888", "5555556", "6666666"):  # voice, bot cannot send, hidden from this person
            with self.subTest(channel=refused), self.assertRaises(AlphaError):
                self.adapter(Wire(discord_listing(guild, channels, user_roles=[]))).with_destination(token, refused)
        left = self.adapter(Wire([ok(guild), ok({"id": "9000009"}), ok({"roles": []}), ok({"message": "Unknown Member"}, 404)]))
        self.assertEqual(left.destinations(token), [])  # the person who connected has left the server


def discord_listing(guild, channels, user_roles):
    """Bot-token answers destinations() reads: the server, the bot user, the bot and the person as members, the channels."""
    return [ok(guild), ok({"id": "9000009"}), ok({"roles": []}), ok({"roles": user_roles}), ok(channels)]


# --- Telegram -----------------------------------------------------------------------------------------------------
class TelegramAdapter(unittest.TestCase):
    def test_code_shape_webhook_setup_observation_and_rights(self):
        wire = Wire([ok({"ok": True, "result": {"url": ""}}), ok({"ok": True, "result": True}),
                     ok({"ok": True, "result": {"id": 999, "username": "RafiiBot"}}),
                     ok({"ok": True, "result": {"status": "administrator", "can_post_messages": True}}),
                     ok({"ok": True, "result": {"id": -100123, "type": "channel", "username": "jamesau"}})])
        telegram = TelegramConnector(BOT, SECRET, BASE, transport=wire)
        code = telegram.new_code()
        self.assertRegex(code, r"^rafii-connect-[A-Z2-7]{16}$")
        instructions = telegram.connect_instructions()
        self.assertEqual(instructions["botUsername"], "@RafiiBot")
        self.assertEqual(wire.calls[1]["body"]["url"], BASE + "/api/telegram/webhook")
        self.assertEqual(wire.calls[1]["body"]["secret_token"], SECRET)
        self.assertNotIn(BOT, json.dumps(instructions))
        update = {"channel_post": {"message_id": 5, "text": f"connect {code}", "chat": {"id": -100123, "type": "channel", "title": "James"}}}
        self.assertEqual(telegram.observe(update)[0], code)
        self.assertIsNone(telegram.observe({"message": update["channel_post"]}))  # a private chat is not a channel post
        grant = telegram.grant_from_context({"chat": {"id": -100123}})
        self.assertEqual(grant["scopes"], ["can_post_messages"])
        self.assertEqual(telegram.identity(grant["accessToken"])["handle"], "@jamesau")


# --- Bluesky ------------------------------------------------------------------------------------------------------
class BlueskyAdapter(unittest.TestCase):
    AUTH = "https://auth.example.com"

    def resolution(self):
        return [ok({"raw": DID}),
                ok({"id": DID, "alsoKnownAs": ["at://alice.example.com"], "service": [{"id": "#atproto_pds", "type": "AtprotoPersonalDataServer", "serviceEndpoint": "https://pds.example.com"}]}),
                ok({"authorization_servers": [self.AUTH]}),
                ok({"issuer": self.AUTH, "pushed_authorization_request_endpoint": self.AUTH + "/oauth/par", "authorization_endpoint": self.AUTH + "/oauth/authorize",
                    "token_endpoint": self.AUTH + "/oauth/token", "scopes_supported": ["atproto", "transition:generic"], "dpop_signing_alg_values_supported": ["ES256"]})]

    def test_par_with_nonce_retry_signed_assertion_and_dpop(self):
        key = client_jwk()
        wire = Wire(self.resolution() + [ok({"error": "use_dpop_nonce"}, 400, {"dpop-nonce": "n1"}), ok({"request_uri": "urn:ietf:params:oauth:request_uri:x"}, 201)])
        bluesky = BlueskyProvider(key, BASE, transport=wire, clock=lambda: 1_790_000_000, resolver=PUBLIC)
        begun = bluesky.begin(BASE + "/api/oauth/bluesky/callback", "STATE", "VERIFIER", "CHALLENGE", ["atproto", "transition:generic"], "@Alice.Example.com")
        self.assertEqual(wire.calls[1]["url"], "https://plc.directory/" + DID)
        par = wire.calls[-1]
        header, payload, _ = jwt(par["headers"]["DPoP"])
        self.assertEqual((header["typ"], header["alg"], payload["htm"], payload["htu"], payload["nonce"]), ("dpop+jwt", "ES256", "POST", self.AUTH + "/oauth/par", "n1"))
        self.assertNotIn("d", header["jwk"])
        verify_es256(par["headers"]["DPoP"], begun["context"]["dpopJwk"])
        assertion = par["form"]["client_assertion"]
        verify_es256(assertion, key)
        _, claims, _ = jwt(assertion)
        self.assertEqual((claims["iss"], claims["aud"]), (bluesky.client_id, self.AUTH))
        self.assertEqual((par["form"]["code_challenge_method"], par["form"]["login_hint"]), ("S256", "alice.example.com"))
        self.assertEqual(parse_qs(urlparse(begun["authorizeUrl"]).query)["request_uri"][0], "urn:ietf:params:oauth:request_uri:x")
        self.assertEqual(begun["context"]["dpopNonce"], "n1")
        self.assertNotIn("d", bluesky.jwks()["keys"][0])  # the private scalar is never published
        self.assertEqual(bluesky.client_metadata()["client_id"], bluesky.client_id)

    def test_exchange_checks_issuer_and_subject_then_dpop_identity_with_nonce(self):
        key = client_jwk()
        wire = Wire(self.resolution() + [ok({"request_uri": "urn:x"}, 201)])
        bluesky = BlueskyProvider(key, BASE, transport=wire, clock=lambda: 1_790_000_000, resolver=PUBLIC)
        context = json.dumps({"verifier": "VERIFIER", **bluesky.begin(BASE + "/cb", "S", "VERIFIER", "C", ["atproto"], "alice.example.com")["context"]})
        with self.assertRaises(AlphaError):
            bluesky.exchange("CODE", context, BASE + "/cb", iss="https://evil.example.com")
        wire.responses = [ok({"access_token": "AT", "refresh_token": "RT", "token_type": "DPoP", "expires_in": 900, "scope": "atproto transition:generic", "sub": "did:plc:zzzzzzzzzzzzzzzzzzzzzzzz"})]
        with self.assertRaises(AlphaError):
            bluesky.exchange("CODE", context, BASE + "/cb", iss=self.AUTH)  # token for another account
        wire.responses = [ok({"access_token": "AT", "refresh_token": "RT", "token_type": "DPoP", "expires_in": 900, "scope": "atproto transition:generic", "sub": DID}),
                          ok({"error": "use_dpop_nonce"}, 401, {"dpop-nonce": "p1"}), ok({"did": DID, "handle": "alice.example.com"})]
        grant = bluesky.exchange("CODE", context, BASE + "/cb", iss=self.AUTH + "/")
        self.assertEqual(grant["scopes"], ["atproto", "transition:generic"])
        self.assertEqual(wire.calls[-1]["form"]["code_verifier"], "VERIFIER")
        identity = bluesky.identity(grant["accessToken"])
        self.assertEqual((identity["providerAccountId"], identity["handle"]), (DID, "@alice.example.com"))
        retried = wire.calls[-1]
        self.assertEqual(retried["headers"]["Authorization"], "DPoP AT")
        _, proof, _ = jwt(retried["headers"]["DPoP"])
        self.assertEqual((proof["nonce"], proof["ath"]), ("p1", b64u(hashlib.sha256(b"AT").digest())))

    def test_well_known_on_a_private_address_falls_back_and_a_private_pds_is_refused(self):
        def resolver(host, port, type=None):
            return PRIVATE(host, port) if host in ("alice.example.com", "pds.example.com") else PUBLIC(host, port)
        wire = Wire([ok({"did": DID}),
                     ok({"id": DID, "alsoKnownAs": ["at://alice.example.com"], "service": [{"id": "#atproto_pds", "type": "AtprotoPersonalDataServer", "serviceEndpoint": "https://pds.example.com"}]})])
        with self.assertRaises(AlphaError):
            BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=resolver).begin(BASE + "/cb", "S", "V", "C", ["atproto"], "alice.example.com")
        self.assertTrue(wire.calls[0]["url"].startswith(BlueskyProvider.RESOLVE_HANDLE))
        self.assertEqual(len(wire.calls), 2)  # nothing was sent to the private server

    def test_tid_is_thirteen_sortable_characters(self):
        self.assertRegex(tid(1_790_000_000_000_000), r"^[2-7a-z]{13}$")
        self.assertLess(tid(1_790_000_000_000_000), tid(1_790_000_000_000_001))


# --- OAuth service flows ------------------------------------------------------------------------------------------
class Database:
    def __init__(self, clock):
        self.clock, self.txns, self.credentials, self.audit = clock, {}, {}, []

    def cursor(self):
        return Cursor(self)


class Cursor:
    def __init__(self, db):
        self.db, self.result, self.rowcount, self.rows = db, None, 0, []

    def execute(self, sql, params=()):
        s, db = " ".join(sql.split()), self.db
        if s.startswith("INSERT INTO public.pr_auth_throttle"):
            self.result = (1,)
        elif s.startswith("INSERT INTO public.pr_oauth_transactions"):
            workspace, member, provider, capability, redirect, scopes, state_hash, ciphertext, key_id, ttl = params
            txn_id = f"txn-{len(db.txns) + 1}"
            db.txns[txn_id] = {"workspace": workspace, "member": member, "provider": provider, "capability": capability, "redirect": redirect, "scopes": scopes,
                               "state_hash": state_hash, "ciphertext": ciphertext, "key_id": key_id, "expires": db.clock() + ttl, "consumed": False}
            self.result = (txn_id,)
        elif s.startswith("SELECT id::text,member_id::text,provider"):
            state_hash, workspace = params
            found = next(((k, t) for k, t in db.txns.items() if t["state_hash"] == state_hash and t["workspace"] == workspace), None)
            self.result = None if not found else (found[0], found[1]["member"], found[1]["provider"], found[1]["capability"], found[1]["redirect"], found[1]["scopes"],
                                                  found[1]["ciphertext"], found[1]["key_id"], found[1]["expires"], found[1]["consumed"])
        elif s.startswith("SELECT id::text,verifier_ciphertext,key_id,extract(epoch from expires_at)::float8,consumed_at IS NOT NULL FROM public.pr_oauth_transactions"):
            found = next(((k, t) for k, t in db.txns.items() if t["state_hash"] == params[0] and t["provider"] == "telegram"), None)
            self.result = None if not found else (found[0], found[1]["ciphertext"], found[1]["key_id"], found[1]["expires"], found[1]["consumed"])
        elif s.startswith("UPDATE public.pr_oauth_transactions SET verifier_ciphertext"):
            db.txns[params[2]].update(ciphertext=params[0], key_id=params[1])
        elif s.startswith("UPDATE public.pr_oauth_transactions SET consumed_at"):
            db.txns[params[0]]["consumed"] = True
        elif s.startswith("INSERT INTO public.pr_encrypted_credentials"):
            workspace, connection, provider, account, access, refresh, key_id, scopes, expires, refresh_supported = params
            db.credentials[connection] = {"workspace": workspace, "provider": provider, "account": account, "access": access, "key_id": key_id, "scopes": scopes, "expires": expires, "revoked": False}
        elif s.startswith("SELECT provider_account_id FROM public.pr_encrypted_credentials"):
            found = db.credentials.get(params[1])
            self.result = (found["account"],) if found and found.get("workspace", "workspace") == params[0] else None
        elif s.startswith("SELECT 1 FROM public.pr_encrypted_credentials"):
            provider, account, workspace, connection = params
            self.result = next(((1,) for key, c in db.credentials.items() if c["provider"] == provider and c["account"] == account and not c["revoked"]
                                and not (c.get("workspace", "workspace") == workspace and key == connection)), None)
        elif s.startswith("SELECT provider,access_ciphertext,key_id,connection_id FROM public.pr_encrypted_credentials"):
            self.rows = [(c["provider"], c["access"], c["key_id"], key) for key, c in db.credentials.items() if c.get("workspace", "workspace") == params[0] and not c["revoked"]]
        elif s.startswith("UPDATE public.pr_encrypted_credentials SET revoked_at=now()"):
            db.credentials[params[1]]["revoked"] = True
        elif s.startswith("UPDATE public.pr_channel_capabilities"):
            self.result = None
        elif s.startswith("SELECT provider,access_ciphertext,key_id FROM public.pr_encrypted_credentials"):
            found = db.credentials.get(params[1])
            self.result = None if not found or found["revoked"] else (found["provider"], found["access"], found["key_id"])
        elif s.startswith("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s,updated_at=now()"):
            ciphertext, key_id, workspace, connection, expected = params
            found = db.credentials.get(connection)
            self.rowcount = 0
            if found and found["access"] == expected:
                found.update(access=ciphertext, key_id=key_id)
                self.rowcount = 1
        elif s.startswith(("INSERT INTO public.pr_channel_capabilities", "SAVEPOINT", "RELEASE", "ROLLBACK TO")) or "pr_channel_pictures" in s:
            self.result = None
        elif s.startswith("INSERT INTO public.pr_audit_events"):
            db.audit.append(params[2])
        else:
            raise AssertionError("unexpected SQL: " + s[:100])

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.rows


class Repository:
    def __init__(self, clock):
        self.db = Database(clock)
        self.state = initial_phase2_state("workspace", "owner", "Owner", "studio", 100)
        self.revision = 1

    @contextmanager
    def transaction(self, token, workspace):
        if token != "session" or workspace != "workspace":
            raise AlphaError("Workspace unavailable.", 403)
        yield self.db.cursor(), (self.revision, self.state, "owner", False, False, False, False), "owner"

    def get(self, workspace, token):
        return {"state": self.state, "revision": self.revision}

    def command(self, workspace, token, revision, command, requirement="edit", after=None, **kwargs):
        require(Membership("owner"), requirement)
        self.state, self.revision = command(copy.deepcopy(self.state), "owner"), self.revision + 1
        return {"state": self.state, "revision": self.revision}

    def assert_fresh(self, token, principal):
        return None

    def mutate(self, workspace, token, revision, action, payload):
        raise AlphaError("Channel unavailable.", 404)

    @contextmanager
    def connection_factory(self):
        @contextmanager
        def cursor():
            yield self.db.cursor()
        yield SimpleNamespace(cursor=cursor)


class ServiceFlows(unittest.TestCase):
    def service(self, adapters):
        self.now = 1_790_000_000.0
        self.repo = Repository(lambda: self.now)
        return OAuthService(self.repo, HostedPhase2Commands(lambda: self.now), CredentialVault(CredentialVault.generate_key()), adapters, BASE, clock=lambda: self.now)

    @patch("postriff_phase2.billing.require_plan_capacity", lambda *a, **k: None)
    def test_mastodon_needs_a_server_then_connects_without_a_false_expiry(self):
        wire = Wire([ok({"client_id": "cid", "client_secret": "csec"}), ok({"access_token": "MT", "scope": "read:accounts"}),
                     ok({"id": "1099", "username": "james"}), ok({"name": "Rafii", "scopes": ["read:accounts"]})])
        service = self.service({"mastodon": MastodonProvider(BASE, transport=wire, resolver=PUBLIC)})
        with self.assertRaises(AlphaError):
            service.start("workspace", "session", "mastodon", "identity", inputs={})
        self.assertEqual(wire.calls, [])
        started = service.start("workspace", "session", "mastodon", "identity", inputs={"instance": "mastodon.social"})
        state = parse_qs(urlparse(started["authorizeUrl"]).query)["state"][0]
        result = service.complete("workspace", "session", "mastodon", state, "CODE")
        self.assertTrue(result["connected"])
        channel = self.repo.state["phase2"]["channels"][-1]
        self.assertEqual((channel["platform"], channel["account"]), ("Mastodon", "@james@mastodon.social"))
        self.assertGreater(channel["expiresAt"], self.now + 86400 * 365)
        stored = self.repo.db.credentials[result["connectionId"]]
        self.assertIsNone(stored["expires"])
        self.assertNotIn("csec", stored["access"])  # encrypted at rest

    @patch("postriff_phase2.billing.require_plan_capacity", lambda *a, **k: None)
    def test_telegram_code_is_claimed_by_the_first_channel_post_then_connects(self):
        wire = Wire([ok({"ok": True, "result": {"url": BASE + "/api/telegram/webhook"}}), ok({"ok": True, "result": {"id": 999, "username": "RafiiBot"}})])
        telegram = TelegramConnector(BOT, SECRET, BASE, transport=wire)
        service = self.service({"telegram": telegram})
        started = service.start("workspace", "session", "telegram", "publish")
        self.assertIsNone(started["authorizeUrl"])
        self.assertEqual(len(wire.calls), 2)  # the webhook already pointed here, so it was not reset
        code = started["code"]
        self.assertEqual(service.complete("workspace", "session", "telegram", code, None), {"connected": False, "reason": "waiting", "pending": True})
        with self.assertRaises(AlphaError):
            service.telegram_webhook("wrong-secret", b"{}")
        post = lambda chat, message: json.dumps({"channel_post": {"message_id": message, "text": code, "chat": {"id": chat, "type": "channel", "title": "James"}}}).encode()
        wire.responses = [ok({"ok": True, "result": True})]
        self.assertEqual(service.telegram_webhook(SECRET, post(-100123, 7)), {"ok": True})
        self.assertEqual(wire.calls[-1]["body"], {"chat_id": -100123, "message_id": 7})  # the code message is deleted
        self.assertEqual(service.telegram_webhook(SECRET, post(-100999, 8)), {"ok": True})  # a later copy elsewhere changes nothing
        wire.responses = [ok({"ok": True, "result": {"status": "administrator", "can_post_messages": True}}),
                          ok({"ok": True, "result": {"id": -100123, "type": "channel", "title": "James"}})]
        result = service.complete("workspace", "session", "telegram", code, None)
        self.assertTrue(result["connected"])
        self.assertEqual(result["missingScopes"], [])
        self.assertEqual(self.repo.state["phase2"]["channels"][-1]["providerAccountId"], "-100123")

    def test_issuer_reaches_adapters_that_require_it_and_callbacks_keep_it(self):
        location = OAuthService.callback_redirect(BASE, "bluesky", {"state": "s", "code": "c", "iss": "https://auth.example.com", "other": "x"})
        query = parse_qs(urlparse(location).query)
        self.assertEqual((query["iss"][0], "other" in query), ("https://auth.example.com", False))

    def test_destination_choice_is_compare_and_swap_on_the_stored_grant(self):
        guild = {"id": "555555", "owner_id": "1", "roles": [{"id": "555555", "permissions": str(DiscordProvider.VIEW_CHANNEL | DiscordProvider.SEND_MESSAGES)}]}
        channels = [{"id": "7777777", "name": "general", "type": 0}]
        discord = DiscordProvider("1234567", "secret", "bot.token", BASE, transport=Wire(discord_listing(guild, channels, []) * 2))
        service = self.service({"discord": discord})
        ciphertext, key_id = service.vault.encrypt(json.dumps({"v": 1, "guild": "555555", "channel": None, "user": "4242424"}))
        self.repo.db.credentials["conn"] = {"workspace": "workspace", "provider": "discord", "account": "555555", "access": ciphertext, "key_id": key_id, "scopes": ["bot"], "expires": None, "revoked": False}
        self.assertEqual(service.destinations("workspace", "session", "conn")["destinations"][0]["id"], "7777777")
        service.choose_destination("workspace", "session", "conn", "7777777")
        stored = self.repo.db.credentials["conn"]
        self.assertEqual(json.loads(service.vault.decrypt(stored["access"], stored["key_id"]))["channel"], "7777777")
        with self.assertRaises(AlphaError):
            service.choose_destination("workspace", "session", "conn", "not-a-channel")


# --- publishing ---------------------------------------------------------------------------------------------------
class Grants:
    def __init__(self, token, scopes):
        self.token, self.scopes = token, scopes

    def token_for_worker(self, workspace_id, connection_id):
        return {"accessToken": self.token, "scopes": self.scopes, "expiresAt": None}


def manifest(platform, account_id, text="Hello from Rafii https://rafii.example/x", account="@james", media=None):
    return {"workspaceId": "w", "channelId": "conn", "platform": platform, "operation": "post", "providerAccountId": account_id, "account": account,
            "payload": {"text": text, "language": "en"}, "media": media or [], "idempotencyKey": "k" * 64}


class Publishing(unittest.TestCase):
    def reviewed(self, adapter):
        adapter.production_reviewed = True
        return adapter

    def test_unreviewed_or_unsupported_media_never_reaches_the_network(self):
        wire = Wire([])
        x = XProvider("c", "s", transport=wire)
        social = HostedSocial(Grants(json.dumps({"v": 1, "at": "AT", "scope": ["tweet.write"]}), ["tweet.write"]), {"x": x})
        self.assertEqual(social.submit(manifest("X", "42"))["state"], "held")
        x.production_reviewed = True
        video = [{"id": "m", "mime": "video/mp4", "alt": ""}]
        self.assertEqual(social.submit(manifest("X", "42", media=video))["state"], "failed")
        self.assertEqual(wire.calls, [])

    def test_bluesky_post_with_link_facet_then_readback(self):
        session = {"v": 1, "at": "AT", "did": DID, "pds": "https://pds.example.com", "iss": "https://auth.example.com", "tokenEndpoint": "x", "jwk": generate_jwk(), "scope": ["atproto", "transition:generic"]}
        wire = Wire([])
        bluesky = self.reviewed(BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=PUBLIC))
        social = HostedSocial(Grants(json.dumps(session), ["atproto", "transition:generic"]), {"bluesky": bluesky})

        def create(method, url, headers=None, form=None, body=None, data=None):
            wire.calls.append({"url": url, "headers": headers, "body": body})
            return ok({"uri": f"at://{DID}/app.bsky.feed.post/{body['rkey']}", "cid": "c"})
        bluesky.transport = create
        result = social.submit(manifest("Bluesky", DID))
        self.assertEqual(result["state"], "provider_accepted")
        record = wire.calls[0]["body"]["record"]
        facet = record["facets"][0]["index"]
        self.assertEqual(record["text"].encode()[facet["byteStart"]:facet["byteEnd"]].decode(), "https://rafii.example/x")
        rkey = result["reference"].rsplit("/", 1)[1]
        bluesky.transport = Wire([ok({"value": {"text": manifest("Bluesky", DID)["payload"]["text"]}})])
        verified = social.reconcile(manifest("Bluesky", DID), {"providerReference": result["reference"]})
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(normalize_result(verified, {"manifest": {"platform": "Bluesky"}})["state"], "verified")
        self.assertTrue(verified["url"].endswith(rkey))

    def test_mastodon_uses_the_idempotency_key_and_reads_back_html(self):
        wire = Wire([ok({"id": "111", "url": "https://mastodon.social/@james/111"}),
                     ok({"id": "111", "account": {"id": "1099"}, "content": "<p>Hello from Rafii <a href=\"https://rafii.example/x\"><span class=\"invisible\">https://</span><span>rafii.example/x</span></a></p>"})])
        mastodon = self.reviewed(MastodonProvider(BASE, transport=wire, resolver=PUBLIC))
        token = json.dumps({"v": 1, "at": "MT", "instance": "mastodon.social", "clientId": "c", "clientSecret": "s", "scope": ["write:statuses"]})
        social = HostedSocial(Grants(token, ["write:statuses", "read:statuses"]), {"mastodon": mastodon})
        result = social.submit(manifest("Mastodon", "1099@mastodon.social"))
        self.assertEqual((result["state"], wire.calls[0]["headers"]["Idempotency-Key"]), ("provider_accepted", "k" * 64))
        verified = social.reconcile(manifest("Mastodon", "1099@mastodon.social"), {"providerReference": result["reference"]})
        self.assertEqual(normalize_result(verified, {"manifest": {"platform": "Mastodon"}})["state"], "verified")

    def test_telegram_receipt_is_verified_only_for_the_exact_text_and_channel(self):
        text = manifest("Telegram", "-100123")["payload"]["text"]
        wire = Wire([ok({"ok": True, "result": {"message_id": 9, "chat": {"id": -100123, "type": "channel", "username": "jamesau"}, "text": text}}),
                     ok({"ok": True, "result": {"message_id": 10, "chat": {"id": -100123, "type": "channel"}, "text": "edited"}})])
        telegram = self.reviewed(TelegramConnector(BOT, SECRET, BASE, transport=wire))
        social = HostedSocial(Grants(json.dumps({"v": 1, "chat": -100123}), ["can_post_messages"]), {"telegram": telegram})
        receipt = social.submit(manifest("Telegram", "-100123"))
        self.assertEqual(normalize_result(receipt, {"manifest": {"platform": "Telegram"}})["state"], "verified")
        self.assertEqual(receipt["url"], "https://t.me/jamesau/9")
        self.assertEqual(social.submit(manifest("Telegram", "-100123"))["state"], "published")

    def test_discord_holds_without_a_channel_and_never_pings_everyone(self):
        wire = Wire([ok({"id": "4444444", "channel_id": "7777777"}),
                     ok({"id": "4444444", "channel_id": "7777777", "content": manifest("Discord", "555555")["payload"]["text"]})])
        discord = self.reviewed(DiscordProvider("1234567", "secret", "bot.token", BASE, transport=wire))
        no_channel = HostedSocial(Grants(json.dumps({"v": 1, "guild": "555555", "channel": None}), ["bot"]), {"discord": discord})
        self.assertEqual(no_channel.submit(manifest("Discord", "555555"))["state"], "held")
        social = HostedSocial(Grants(json.dumps({"v": 1, "guild": "555555", "channel": "7777777"}), ["bot", "identify"]), {"discord": discord})
        result = social.submit(manifest("Discord", "555555"))
        self.assertEqual(wire.calls[0]["body"]["allowed_mentions"], {"parse": []})
        self.assertEqual((wire.calls[0]["body"]["nonce"], wire.calls[0]["body"]["enforce_nonce"]), ("k" * 25, True))  # Discord dedupes a repeat
        verified = social.reconcile(manifest("Discord", "555555"), {"providerReference": result["reference"]})
        self.assertEqual(normalize_result(verified, {"manifest": {"platform": "Discord"}})["state"], "verified")

    def test_x_post_and_readback_bind_the_author(self):
        text = manifest("X", "42")["payload"]["text"]
        wire = Wire([ok({"data": {"id": "1800000000000000001", "text": text}}, 201), ok({"data": {"id": "1800000000000000001", "text": text, "author_id": "99"}}),
                     ok({"data": {"id": "1800000000000000001", "text": text, "author_id": "42"}})])
        x = self.reviewed(XProvider("c", "s", transport=wire))
        social = HostedSocial(Grants(json.dumps({"v": 1, "at": "AT", "scope": ["tweet.write"]}), ["tweet.write"]), {"x": x})
        result = social.submit(manifest("X", "42"))
        self.assertEqual(result["state"], "provider_accepted")
        self.assertEqual(social.reconcile(manifest("X", "42"), {"providerReference": result["reference"]})["state"], "uncertain")  # another author
        verified = social.reconcile(manifest("X", "42"), {"providerReference": result["reference"]})
        self.assertEqual(normalize_result(verified, {"manifest": {"platform": "X"}})["state"], "verified")
        self.assertEqual(verified["url"], "https://x.com/james/status/1800000000000000001")



# --- review fixes -------------------------------------------------------------------------------------------------
class DefiniteRejections(unittest.TestCase):
    """A provider refusal that posted nothing ends failed with the provider's own reason, never uncertain."""
    def x(self, *responses):
        adapter = XProvider("c", "s", transport=Wire(responses))
        adapter.production_reviewed = True
        return HostedSocial(Grants(json.dumps({"v": 1, "at": "AT", "scope": ["tweet.write"]}), ["tweet.write"]), {"x": adapter})

    def test_x_bad_request_duplicate_and_permission(self):
        refused = self.x(ok({"detail": "Your Tweet text is too long."}, 400)).submit(manifest("X", "42"))
        self.assertEqual(refused["state"], "failed")
        self.assertIn("Your Tweet text is too long.", refused["confirmed"])
        duplicate = self.x(ok({"detail": "You are not allowed to create a Tweet with duplicate content.", "status": 403}, 403)).submit(manifest("X", "42"))
        self.assertEqual(duplicate["state"], "failed")
        self.assertTrue(duplicate["confirmed"].startswith("Duplicate content"))
        self.assertNotIn("re-authorization", duplicate["confirmed"])
        self.assertEqual(self.x(ok({"detail": "Forbidden"}, 403)).submit(manifest("X", "42"))["state"], "held")

    def test_telegram_error_codes(self):
        cases = ((400, {"ok": False, "error_code": 400, "description": "Bad Request: message text is empty"}, "failed"),
                 (403, {"ok": False, "error_code": 403, "description": "Forbidden: bot is not a member of the channel chat"}, "failed"),
                 (429, {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 5}}, "scheduled"),
                 (502, {"raw": "Bad Gateway"}, "uncertain"))
        for status, body, state in cases:
            with self.subTest(status=status):
                telegram = TelegramConnector(BOT, SECRET, BASE, transport=Wire([ok(body, status)]))
                telegram.production_reviewed = True
                result = HostedSocial(Grants(json.dumps({"v": 1, "chat": -100123}), ["can_post_messages"]), {"telegram": telegram}).submit(manifest("Telegram", "-100123"))
                self.assertEqual(result["state"], state)
                if state == "failed":
                    self.assertIn(body["description"], result["confirmed"])

    def test_discord_and_bluesky_bad_requests(self):
        discord = DiscordProvider("1234567", "secret", "bot.token", BASE, transport=Wire([ok({"message": "Invalid Form Body", "code": 50035}, 400)]))
        discord.production_reviewed = True
        result = HostedSocial(Grants(json.dumps({"v": 1, "guild": "555555", "channel": "7777777"}), ["bot"]), {"discord": discord}).submit(manifest("Discord", "555555"))
        self.assertEqual((result["state"], "Invalid Form Body" in result["confirmed"]), ("failed", True))
        session = {"v": 1, "at": "AT", "did": DID, "pds": "https://pds.example.com", "iss": "https://auth.example.com", "tokenEndpoint": "x", "jwk": generate_jwk()}
        bluesky = BlueskyProvider(client_jwk(), BASE, transport=Wire([ok({"error": "InvalidRequest", "message": "Record/text must not be longer than 300 graphemes"}, 400),
                                                                     ok({"error": "RecordNotFound"}, 400)]), resolver=PUBLIC)
        bluesky.production_reviewed = True
        result = HostedSocial(Grants(json.dumps(session), ["atproto", "transition:generic"]), {"bluesky": bluesky}).submit(manifest("Bluesky", DID))
        self.assertEqual(result["state"], "failed")
        self.assertIn("300 graphemes", result["confirmed"])


class XWeightedPreflight(unittest.TestCase):
    """Approval measures X length the way X counts, so an over-length post never reaches X."""
    import test_postriff_phase2 as _phase2
    setUp, tearDown = _phase2.Phase2Acceptance.setUp, _phase2.Phase2Acceptance.tearDown
    channel, draft = _phase2.Phase2Acceptance.channel, _phase2.Phase2Acceptance.draft

    def manifest(self, text):
        from datetime import datetime, timezone
        if not hasattr(self, "prepared"):
            self.prepared = (self.draft(), self.channel())
        variant, channel = self.prepared
        state = copy.deepcopy(self.j.state)
        state["variants"][0].update(platform="X", text=text)
        next(c for c in state["phase2"]["channels"] if c["id"] == channel["id"])["platform"] = "X"  # the fixture store cannot add X
        payload = {"channelId": channel["id"], "variantId": variant["id"], "localTime": datetime.fromtimestamp(self.now + 60, timezone.utc).replace(tzinfo=None).isoformat(),
                   "timeZone": "UTC", "acknowledgedWarnings": variant["warnings"]}
        return self.store.build_manifest(state, payload, "actor")

    def test_cjk_counts_double(self):
        with self.assertRaises(AlphaError):
            self.manifest("練" * 141)  # 141 code points, 282 by X's count
        self.assertEqual(self.manifest("練" * 140)["platform"], "X")


class BlueskyIdempotency(unittest.TestCase):
    session = {"v": 1, "at": "AT", "did": DID, "pds": "https://pds.example.com", "iss": "https://auth.example.com", "tokenEndpoint": "x"}

    def social(self, wire):
        bluesky = BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=PUBLIC)
        bluesky.production_reviewed = True
        return HostedSocial(Grants(json.dumps({**self.session, "jwk": generate_jwk()}), ["atproto", "transition:generic"]), {"bluesky": bluesky})

    def test_record_key_is_fixed_by_the_job_and_kept_on_an_uncertain_answer(self):
        job = {**manifest("Bluesky", DID), "timing": {"timestamp": 1_790_000_000}}
        rkey = HostedSocial.bluesky_rkey(job)
        self.assertRegex(rkey, r"^[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}$")
        self.assertEqual(rkey, HostedSocial.bluesky_rkey(copy.deepcopy(job)))
        self.assertNotEqual(rkey, HostedSocial.bluesky_rkey({**job, "idempotencyKey": "j" * 64}))

        def timeout(*args, **kwargs):
            raise AlphaError("The provider is temporarily unreachable.", 503)
        result = self.social(timeout).submit(job)
        self.assertEqual((result["state"], result["reference"]), ("uncertain", f"at://{DID}/app.bsky.feed.post/{rkey}"))
        self.assertEqual(normalize_result(result, {"manifest": job})["reference"], result["reference"])

    def test_a_retry_that_finds_its_own_earlier_record_is_accepted_not_duplicated(self):
        job = manifest("Bluesky", DID)
        wire = Wire([ok({"error": "InvalidRequest", "message": "Record already exists"}, 400), ok({"value": {"text": job["payload"]["text"]}})])
        result = self.social(wire).submit(job)
        self.assertEqual(result["state"], "provider_accepted")
        self.assertEqual(wire.calls[0]["body"]["rkey"], wire.calls[1]["url"].split("rkey=")[1])


class SharedRemoteGrants(unittest.TestCase):
    """Rafii's one bot in a server or channel stays while another unrevoked connection, in any workspace, uses it."""
    def setUp(self):
        self.revoked = []
        discord = DiscordProvider("1234567", "secret", "bot.token", BASE, transport=Wire([]))
        discord.revoke = lambda token: self.revoked.append(token) or True
        flows = ServiceFlows()
        self.service = flows.service({"discord": discord})
        self.repo = flows.repo
        for key, workspace in (("conn", "workspace"), ("other", "workspace-2")):
            ciphertext, key_id = self.service.vault.encrypt(json.dumps({"v": 1, "guild": "555555", "channel": None}))
            self.repo.db.credentials[key] = {"workspace": workspace, "provider": "discord", "account": "555555", "access": ciphertext, "key_id": key_id, "scopes": ["bot"], "expires": None, "revoked": False}

    def test_disconnect_keeps_the_bot_while_another_workspace_uses_it(self):
        result = self.service.disconnect("workspace", "session", "conn")
        self.assertEqual((result["disconnected"], result["remoteRevoked"], self.revoked), (True, False, []))
        self.assertTrue(self.repo.db.credentials["conn"]["revoked"])

    def test_the_last_connection_removes_the_bot(self):
        self.repo.db.credentials["other"]["revoked"] = True
        self.assertTrue(self.service.disconnect("workspace", "session", "conn")["remoteRevoked"])
        self.assertEqual(len(self.revoked), 1)

    def test_account_deletion_applies_the_same_rule(self):
        from postriff_phase2.account_deletion import revoke_remote_grants
        deleting = SimpleNamespace(connection_factory=self.repo.connection_factory, oauth=self.service)
        self.assertEqual((revoke_remote_grants(deleting, "workspace"), self.revoked), ([], []))
        self.repo.db.credentials["other"]["revoked"] = True
        self.assertEqual(revoke_remote_grants(deleting, "workspace"), [])
        self.assertEqual(len(self.revoked), 1)


class StoredEndpointGuard(unittest.TestCase):
    """Stored Bluesky endpoints are re-checked when used: a name that now resolves privately gets no request."""
    def test_pds_token_and_revocation_endpoints(self):
        wire = Wire([])
        bluesky = BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=PRIVATE)
        stored = {"v": 1, "at": "AT", "rt": "RT", "did": DID, "pds": "https://pds.example.com", "iss": "https://auth.example.com",
                  "tokenEndpoint": "https://auth.example.com/oauth/token", "revocationEndpoint": "https://auth.example.com/oauth/revoke", "jwk": generate_jwk()}
        for call in (lambda: bluesky.identity(json.dumps(stored)), lambda: bluesky.refresh(json.dumps(stored)),
                     lambda: bluesky.revoke(json.dumps(stored)), lambda: bluesky.xrpc_post(dict(stored), "com.atproto.repo.createRecord", body={})):
            with self.assertRaises(AlphaError):
                call()
        self.assertEqual(wire.calls, [])

    def test_revoke_ends_the_whole_grant(self):
        wire = Wire([ok({})])
        bluesky = BlueskyProvider(client_jwk(), BASE, transport=wire, resolver=PUBLIC)
        stored = {"v": 1, "at": "AT", "rt": "RT", "did": DID, "pds": "https://pds.example.com", "iss": "https://auth.example.com",
                  "tokenEndpoint": "https://auth.example.com/oauth/token", "revocationEndpoint": "https://auth.example.com/oauth/revoke", "jwk": generate_jwk()}
        self.assertTrue(bluesky.revoke(json.dumps(stored)))
        self.assertEqual((wire.calls[0]["form"]["token"], wire.calls[0]["form"]["token_type_hint"]), ("RT", "refresh_token"))


class XReconcile(unittest.TestCase):
    def social(self, wire):
        x = XProvider("c", "s", transport=wire)
        x.production_reviewed = True
        return HostedSocial(Grants(json.dumps({"v": 1, "at": "AT", "scope": ["tweet.write"]}), ["tweet.write"]), {"x": x})

    def test_links_are_expanded_entities_decoded_and_the_media_link_dropped(self):
        text = "Recital & rehearsal notes https://rafii.example/notes"
        stored = {"id": "1800000000000000001", "author_id": "42", "text": "Recital &amp; rehearsal notes https://t.co/abc123 https://t.co/media99",
                  "entities": {"urls": [{"start": 30, "url": "https://t.co/abc123", "expanded_url": "https://rafii.example/notes"},
                                        {"start": 50, "url": "https://t.co/media99", "expanded_url": "https://x.com/james/status/1800000000000000001/photo/1", "media_key": "3_1"}]}}
        wire = Wire([ok({"data": stored})])
        verified = self.social(wire).reconcile(manifest("X", "42", text=text), {"providerReference": stored["id"], "checks": 1})
        self.assertEqual(verified["state"], "verified")
        self.assertIn("entities", wire.calls[0]["url"])

    def test_billed_reads_stop_after_a_few_inconclusive_checks(self):
        wire = Wire([])
        result = self.social(wire).reconcile(manifest("X", "42"), {"providerReference": "1800000000000000001", "checks": HostedSocial.X_RECONCILE_LIMIT + 1})
        self.assertEqual((result["state"], wire.calls), ("uncertain", []))


class MinorFixes(unittest.TestCase):
    def test_mastodon_polls_the_same_media_instead_of_uploading_again(self):
        image = [{"id": "m1", "mime": "image/png", "alt": "score"}]
        storage = SimpleNamespace(storage=SimpleNamespace(get=lambda *a: b"\x89PNG"))
        wire = Wire([ok({"id": "990"}, 202), ok({"id": "990", "url": None}, 206), ok({"id": "990", "url": "https://files.example/990.png"}), ok({"id": "111"})])
        mastodon = MastodonProvider(BASE, transport=wire, resolver=PUBLIC)
        mastodon.production_reviewed = True
        token = json.dumps({"v": 1, "at": "MT", "instance": "mastodon.social", "clientId": "c", "clientSecret": "s", "scope": ["write:statuses", "write:media"]})
        social = HostedSocial(Grants(token, ["write:statuses", "write:media"]), {"mastodon": mastodon}, storage, sleep=lambda seconds: None)
        self.assertEqual(social.submit(manifest("Mastodon", "1099@mastodon.social", media=image))["state"], "provider_accepted")
        self.assertEqual([c["method"] for c in wire.calls], ["POST", "GET", "GET", "POST"])  # one upload, two polls, the post
        self.assertEqual(wire.calls[-1]["body"]["media_ids"], ["990"])
        slow = Wire([ok({"id": "991"}, 202)] + [ok({"id": "991", "url": None}, 206)] * HostedSocial.MASTODON_MEDIA_POLLS)
        mastodon.transport = slow
        self.assertEqual(social.submit(manifest("Mastodon", "1099@mastodon.social", media=image))["state"], "scheduled")
        self.assertEqual(sum(1 for c in slow.calls if c["method"] == "POST"), 1)

    def test_short_lived_tokens_renew_within_the_margin(self):
        import test_social_voice_services as fixtures
        from unittest.mock import Mock
        for seconds_left, renewed in ((100, True), (1000, False)):
            with self.subTest(seconds_left=seconds_left):
                repo, vault = fixtures.Repository(), CredentialVault(CredentialVault.generate_key())
                access, key = vault.encrypt(json.dumps({"v": 1, "at": "AT", "scope": ["tweet.write"]}))
                refresh = vault.encrypt("RT")[0]
                now = 1_800_000_000
                repo.credential = ("x", access, refresh, key, now + seconds_left, True, False, ["tweet.write"], "42", now - 3600)
                x = XProvider("c", "s", transport=Wire([]))
                x.refresh = Mock(return_value={"accessToken": json.dumps({"v": 1, "at": "AT2", "scope": ["tweet.write"]}), "refreshToken": "RT2", "expiresIn": 7200})
                OAuthService(repo, None, vault, {"x": x}, BASE, clock=lambda: now).token_for_worker("workspace", "conn")
                self.assertEqual(x.refresh.called, renewed)


if __name__ == "__main__":
    unittest.main()
