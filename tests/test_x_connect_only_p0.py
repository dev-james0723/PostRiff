"""Zero-network Rafii X Connect-only P0 gates. External customer acceptance remains NOT_RUN."""
import hashlib
import json
import unittest
from types import SimpleNamespace
from postriff_phase2.x_direct_cost import bind_x_cost_context
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from test_hosted_wave1_connectors import BASE, Repository, Wire, ok, manifest, Grants
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.social_connectors import XProvider

SCOPES = "tweet.read users.read offline.access"
CONFIG = {
    "POSTRIFF_PUBLIC_BASE_URL": BASE,
    "POSTRIFF_OAUTH_X_CLIENT_ID": "synthetic-client",
    "POSTRIFF_OAUTH_X_CLIENT_SECRET": "synthetic-secret",
}
PILOT = {
    **CONFIG,
    "POSTRIFF_OAUTH_X_CONNECT_PILOT_ENABLED": "true",
    "POSTRIFF_OAUTH_X_CUSTOMER_ACCESS_APPROVED": "true",  # synthetic only
    "POSTRIFF_OAUTH_X_MAX_DAILY_IDENTITY_CALLS": "3",
    "POSTRIFF_OAUTH_X_CONNECT_PILOT_WORKSPACES": "workspace",
}


def state_of(result):
    return parse_qs(urlparse(result["authorizeUrl"]).query)["state"][0]


def xwire(identity="42", scopes=SCOPES, refresh="SYN_RT"):
    response = {"access_token": "SYN_AT", "scope": scopes, "expires_in": 7200}
    if refresh is not None:
        response["refresh_token"] = refresh
    return Wire([ok(response), ok({"data": {"id": identity, "username": "synthetic"}})])


class ConnectP0(unittest.TestCase):
    def service(self, values=PILOT, wire=None):
        self.now = 1790000000
        registry = registry_from_environment(values)
        self.wire = wire if wire is not None else xwire()
        if "x" in registry:
            registry["x"].transport = self.wire
        self.repo = Repository(lambda: self.now)
        self.svc = OAuthService(self.repo, HostedPhase2Commands(lambda: self.now),
                                CredentialVault(CredentialVault.generate_key()), registry, BASE, clock=lambda: self.now)
        self.cost_requests = []
        def reserve(request):
            self.cost_requests.append(request)  # Synthetic only; production uses durable PG admission.
            return request.request_id
        self.svc.x_direct = SimpleNamespace(request_context=lambda ws, conn, op:
            bind_x_cost_context(workspace_id=ws, connection_id=conn, operation=op, reserve=reserve))
        return self.svc

    def test_default_off_requires_operator_and_bounded_allowance(self):
        for values in (
            CONFIG,
            {**PILOT, "POSTRIFF_OAUTH_X_CONNECT_PILOT_ENABLED": "false"},
            {**PILOT, "POSTRIFF_OAUTH_X_CUSTOMER_ACCESS_APPROVED": "false"},
            {**PILOT, "POSTRIFF_OAUTH_X_MAX_DAILY_IDENTITY_CALLS": "0"},
            {**PILOT, "POSTRIFF_OAUTH_X_MAX_DAILY_IDENTITY_CALLS": "999999"},
            {**PILOT, "POSTRIFF_OAUTH_X_MAX_DAILY_IDENTITY_CALLS": "invalid"},
            {**PILOT, "POSTRIFF_OAUTH_X_CONNECT_PILOT_WORKSPACES": ""},
            {**PILOT, "POSTRIFF_OAUTH_X_CONNECT_PILOT_WORKSPACES": "not@valid"},
            {**PILOT, "POSTRIFF_OAUTH_X_CONNECT_PILOT_WORKSPACES": ",".join(str(n) for n in range(11))},
        ):
            with self.subTest(values={k:v for k,v in values.items() if k not in ("POSTRIFF_OAUTH_X_CLIENT_SECRET",)}):
                svc=self.service(values, Wire([]))
                with self.assertRaises(AlphaError) as caught:
                    svc.start("workspace", "session", "x", "identity")
                self.assertEqual(caught.exception.status, 503)
                self.assertEqual(self.wire.calls, [])

    def test_pilot_allowlist_denies_other_workspace_before_external_calls(self):
        svc=self.service({**PILOT, "POSTRIFF_OAUTH_X_CONNECT_PILOT_WORKSPACES":"different_workspace"}, Wire([]))
        with self.assertRaises(AlphaError) as caught:
            svc.start("workspace", "session", "x", "identity")
        self.assertEqual(caught.exception.status,503)
        self.assertEqual(self.wire.calls,[])

    def test_identity_scopes_only_and_pkce_s256_and_secret_custody(self):
        svc=self.service()
        started=svc.start("workspace", "session", "x", "identity")
        query=parse_qs(urlparse(started["authorizeUrl"]).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(set(query["scope"][0].split()), set(SCOPES.split()))
        self.assertNotIn("tweet.write", query["scope"][0])
        self.assertEqual(query["redirect_uri"], [BASE+"/api/oauth/x/callback"])
        self.assertEqual(self.wire.calls, [])
        rawnext=next(iter(self.repo.db.txns.values()))
        self.assertNotIn("pkce", rawnext["ciphertext"])
        self.assertNotIn(query["state"][0], rawnext["state_hash"])

    def test_no_publish_capability_even_with_legacy_owner_review(self):
        svc=self.service({**PILOT, "POSTRIFF_OAUTH_X_REVIEWED":"true"})
        with self.assertRaises(AlphaError) as caught:
            svc.start("workspace", "session", "x", "publish")
        self.assertEqual(caught.exception.status, 409)
        catalog={p["id"]:p for p in svc.provider_catalog()}
        self.assertTrue(catalog["x"]["connectReady"])
        self.assertFalse(catalog["x"]["capabilities"]["publish"])
        grant=Grants(json.dumps({"v":1,"at":"SYN_AT","scope":["tweet.write"]}),["tweet.write"])
        self.assertEqual(HostedSocial(grant, svc.providers).submit(manifest("X","42"))["state"], "held")
        self.assertEqual(self.wire.calls, [])

    def test_policy_attestation_not_inferred_from_owner_review(self):
        svc=self.service({**CONFIG, "POSTRIFF_OAUTH_X_REVIEWED":"true"})
        catalog={p["id"]:p for p in svc.provider_catalog()}
        self.assertFalse(catalog["x"]["connectReady"])
        self.assertFalse(catalog["x"]["publicConnectionReady"])
        self.assertTrue(any("independent" in i for i in catalog["x"]["setupIssues"]))

    @patch("postriff_phase2.billing.require_plan_capacity",lambda *a,**k:None)
    def test_success_custody_grant_identity_and_single_use(self):
        svc=self.service()
        start=svc.start("workspace","session","x","identity")
        state=state_of(start)
        done=svc.complete("workspace","session","x",state,"SYN_CODE")
        self.assertTrue(done["connected"])
        self.assertEqual(done["providerAccountId"], "42")
        self.assertEqual(done["connectionId"], hashlib.sha256(b"x:42").hexdigest()[:32])
        saved=self.repo.db.credentials[done["connectionId"]]
        self.assertEqual(saved["workspace"],"workspace")
        self.assertNotIn("SYN_AT",saved["access"])
        self.assertEqual(set(saved["scopes"]),set(SCOPES.split()))
        self.assertFalse(done["capabilities"]["publish"]["level"]=="Direct")
        self.assertEqual(len(self.wire.calls),2)
        with self.assertRaises(AlphaError) as replay:
            svc.complete("workspace","session","x",state,"SYN_CODE")
        self.assertEqual(replay.exception.status,404)
        self.assertEqual(len(self.wire.calls),2)

    def test_state_workspace_and_principal_isolation_before_provider(self):
        svc=self.service(wire=Wire([]))
        state=state_of(svc.start("workspace","session","x","identity"))
        for workspace,token,nonce in (
            ("other_workspace","session",state),
            ("workspace","wrong_session",state),
            ("workspace","session","Z"*len(state)),
        ):
            with self.subTest(workspace=workspace,token=token):
                with self.assertRaises(AlphaError):
                    svc.complete(workspace,token,"x",nonce,"CODE")
        self.assertEqual(self.wire.calls, [])

    def test_expired_state_fails_before_api(self):
        svc=self.service(wire=Wire([]))
        state=state_of(svc.start("workspace","session","x","identity"))
        self.now += 601
        with self.assertRaises(AlphaError) as caught:
            svc.complete("workspace","session","x",state,"CODE")
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(self.wire.calls,[])

    def test_pilot_disabled_between_start_and_callback_blocks_network(self):
        svc=self.service(wire=Wire([]))
        state=state_of(svc.start("workspace","session","x","identity"))
        svc.providers["x"].customer_connect_enabled=False
        with self.assertRaises(AlphaError) as caught:
            svc.complete("workspace","session","x",state,"CODE")
        self.assertEqual(caught.exception.status,503)
        self.assertEqual(self.wire.calls,[])

    def test_billed_identity_allowance_is_admitted_before_exchange(self):
        svc=self.service(wire=Wire([]))
        state=state_of(svc.start("workspace","session","x","identity"))
        from postriff_phase2.hosted import throttle as real_throttle
        def guard(cur, scope, limit, window):
            if scope=="oauth-x-identity-global":
                self.assertEqual((limit,window),(3,86400))
                raise AlphaError("Budget exceeded",429)
            return real_throttle(cur,scope,limit,window)
        with patch("postriff_phase2.hosted.throttle",side_effect=guard), self.assertRaises(AlphaError) as caught:
            svc.complete("workspace","session","x",state,"CODE")
        self.assertEqual(caught.exception.status,429)
        self.assertEqual(self.wire.calls,[])

    @patch("postriff_phase2.billing.require_plan_capacity",lambda *a,**k:None)
    def test_missing_scopes_or_refresh_never_persists(self):
        for wire, calls in ((xwire(scopes="users.read offline.access"),1),(xwire(refresh=None),2)):
            with self.subTest(calls=len(wire.calls)):
                svc=self.service(wire=wire)
                state=state_of(svc.start("workspace","session","x","identity"))
                with self.assertRaises(AlphaError) as caught:
                    svc.complete("workspace","session","x",state,"CODE")
                self.assertEqual(caught.exception.status,409)
                self.assertEqual(self.repo.db.credentials,{})
                self.assertEqual(len(self.wire.calls),calls)
                with self.assertRaises(AlphaError):
                    svc.complete("workspace","session","x",state,"CODE")
                self.assertEqual(len(self.wire.calls),calls)

    def test_wrong_reconnect_connection_not_found_before_network(self):
        svc=self.service(wire=Wire([]))
        with self.assertRaises(AlphaError) as caught:
            svc.start("workspace","session","x","identity",inputs={"connectionId":"0"*32})
        self.assertEqual(caught.exception.status,404)
        self.assertEqual(self.wire.calls,[])

    @patch("postriff_phase2.billing.require_plan_capacity",lambda *a,**k:None)
    def test_reconnect_cannot_replace_account_when_x_user_changes(self):
        svc=self.service(wire=xwire("42"))
        begin=svc.start("workspace","session","x","identity")
        first=svc.complete("workspace","session","x",state_of(begin),"CODE")
        same=first["connectionId"]
        prior=self.repo.db.credentials[same]["access"]
        svc.providers["x"].transport=xwire("43")
        reconnect=svc.start("workspace","session","x","identity",inputs={"connectionId":same})
        with self.assertRaises(AlphaError) as error:
            svc.complete("workspace","session","x",state_of(reconnect),"CODE")
        self.assertEqual(error.exception.status,409)
        self.assertEqual(len(self.repo.db.credentials),1)
        self.assertEqual(self.repo.db.credentials[same]["access"],prior)

    def test_app_binding_rotated_during_callback_fails_closed(self):
        svc=self.service(wire=Wire([]))
        state=state_of(svc.start("workspace","session","x","identity"))
        svc.providers["x"].client_id="CHANGED_CLIENT"
        with self.assertRaises(AlphaError) as caught:
            svc.complete("workspace","session","x",state,"CODE")
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(self.wire.calls,[])

    def test_manual_verify_is_budgeted_before_any_x_call(self):
        svc=self.service(wire=Wire([]))
        from test_hosted_wave1_connectors import Cursor
        actual=Cursor.execute
        def statement(cur, sql, params=()):
            if sql.startswith("SELECT provider,provider_account_id,scopes,access_ciphertext,key_id FROM public.pr_encrypted_credentials"):
                cur.result=("x","42",["users.read"],"SYN_CT","SYN_KEY")
                return
            return actual(cur,sql,params)
        from postriff_phase2.hosted import throttle as baseline
        def guard(cur, scope, limit, window):
            if scope=="oauth-x-identity-global":
                self.assertEqual((limit,window),(3,86400))
                raise AlphaError("Budget exceeded",429)
            return baseline(cur,scope,limit,window)
        with patch.object(Cursor,"execute",statement), patch("postriff_phase2.hosted.throttle",side_effect=guard):
            with self.assertRaises(AlphaError) as caught:
                svc.verify("workspace","session","f"*32)
        self.assertEqual(caught.exception.status,429)
        self.assertEqual(self.wire.calls,[])

    @patch("postriff_phase2.billing.require_plan_capacity",lambda *a,**k:None)
    def test_disconnect_uses_official_revoke_and_erases_local_authority(self):
        svc=self.service()
        start=svc.start("workspace","session","x","identity")
        done=svc.complete("workspace","session","x",state_of(start),"CODE")
        before=len(self.wire.calls)
        self.wire.responses.extend([ok({}), ok({})])  # Official refresh + access revoke acknowledgements.
        with patch("postriff_phase2.x_resource_evidence.purge_connection",return_value=0) as purge, patch(
            "postriff_phase2.growth.history_import.mark_for_purge",return_value=None), patch(
            "postriff_phase2.growth.history_import.purge_after_disconnect",return_value=None), patch(
            "postriff_phase2.account_pictures.guarded",return_value=None), patch(
            "postriff_phase2.product_events.record",return_value=None):
            result=svc.disconnect("workspace","session",done["connectionId"])
        self.assertTrue(result["disconnected"])
        self.assertTrue(result["remoteRevoked"])
        self.assertNotIn("X Connected Apps",result["note"])
        purge.assert_called_once()
        self.assertTrue(self.repo.db.credentials[done["connectionId"]]["revoked"])
        self.assertEqual(len(self.wire.calls),before+2)
        self.assertTrue(all(call["url"] == XProvider.REVOKE for call in self.wire.calls[before:]))
        self.assertEqual(self.repo.db.credentials[done["connectionId"]]["access"], "")
        self.assertIsNone(self.repo.db.credentials[done["connectionId"]]["refresh"])

    def test_public_callback_no_host_header_redirect(self):
        target=OAuthService.callback_redirect(BASE,"x",{"state":"foo","code":"bar","to":"https://attacker.invalid"})
        self.assertEqual(urlparse(target).netloc,"app.example")
        self.assertNotIn("attacker.invalid",target)


if __name__=="__main__":
    unittest.main()
