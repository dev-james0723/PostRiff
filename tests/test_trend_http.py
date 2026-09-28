import io
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from postriff_phase2.coworker import http as coworker_http
from test_trend_service import make_service, WID, TID, RID, OID, assert_schema
from test_trend_opportunities import PAYLOAD


class AppStub:
    @staticmethod
    def _json(start, status, value):
        start(str(status)+" Status", [("Content-Type", "application/json"), ("Cache-Control", "public")])
        return [json.dumps(value).encode()]

    @staticmethod
    def _body(environ):
        return json.loads(environ["wsgi.input"].read())


class TrendHTTPTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.store = make_service()
        self.hosted = SimpleNamespace(coworker=self.svc.coworker, notifications=SimpleNamespace())

    def request(self, tail, *, method="GET", payload=None, query="", token="session"):
        seen = []
        env = {"QUERY_STRING": query, "wsgi.input": io.BytesIO(json.dumps(payload or {}).encode())}
        with patch.object(self.hosted.coworker, "_broker", side_effect=AssertionError("GET egress")):
            raw = coworker_http.handle(AppStub(), env, lambda s,h: seen.append((s,h)), self.hosted, token, method, ["api", "workspaces", WID, "coworker", "trends", *tail])
        self.assertEqual(dict(seen[0][1])["Cache-Control"], "private, no-store")
        return int(seen[0][0].split()[0]), json.loads(b"".join(raw))

    def test_mount_real_dispatch_detail_receipt_and_list(self):
        for path, definition in [([], "trends_response"), ([TID], "trend_response"), ([TID,"receipts",RID], "receipt_response"), (["opportunities",OID], "opportunity_response")]:
            status, data = self.request(path)
            self.assertEqual(status, 200)
            assert_schema(self, definition, data)

    def test_static_paths_never_interpreted_as_trend_ids(self):
        for tail in (["methodology"], ["calibration"], ["language-patterns"], ["opportunities","whitespace"]):
            status, result = self.request(tail)
            self.assertIn(status, (403, 503))
            self.assertNotEqual(result["code"], "invalid_request")
        self.assertEqual(self.request(["watches"])[0], 200)

    def test_safe_auth_disabled_expired_and_foreign_errors(self):
        self.assertEqual(self.request([], token="")[0], 401)
        self.assertEqual(self.request([], token="prt_forbidden")[0], 403)
        self.assertEqual(self.request(["11111111-1111-4111-8111-111111111111"])[0], 404)
        self.store.rows["receipt", RID].update(validity="revoked", payload=None)
        self.assertEqual(self.request([TID])[0], 410)
        self.svc.values["RAFII_TREND_INTELLIGENCE_ENABLED"] = "0"
        self.assertEqual(self.request([])[0], 403)

    def test_mutations_exact_envelope_and_role(self):
        status, accepted = self.request(["opportunities", OID, "accept"], method="POST", payload=PAYLOAD)
        self.assertEqual(status, 200)
        assert_schema(self, "accepted_opportunity_response", accepted)
        watch = {"trend_id": TID, "platforms": ["bluesky"], "threshold": "stage_change", "notification_policy": "in_app", "idempotency_key": "watch-1"}
        status, response = self.request(["watches"], method="POST", payload=watch)
        self.assertEqual(status, 201)
        assert_schema(self, "watch_response", response)
        status, removed = self.request(["watches", response["data"]["id"]], method="DELETE", query="expected_revision=1&idempotency_key=delete-1")
        self.assertEqual(status, 200)
        assert_schema(self, "watch_response", removed)
        self.assertFalse(removed["data"]["active"])
        self.repo.role = "viewer"
        self.assertEqual(self.request(["refreshes"], method="POST")[0], 403)

    def test_duplicate_query_and_unknown_fields_rejected_without_reflection(self):
        for query in ("query=x&query=y", "limit=999", "query=%3Cscript%3E&secret=value"):
            status, result = self.request([], query=query)
            self.assertEqual(status, 400)
            self.assertNotIn("script", json.dumps(result))

    def test_fractional_clock_empty_opportunity_query_has_no_rounding_rejection(self):
        from postriff_phase2.growth.trends.service import filters
        from postriff_phase2.growth.trends.opportunities import iso
        for at in (1800000000.1234567, 1800000000.123456, 1800000000.9999998):
            self.assertEqual(filters({}, at)["until"], iso(at))
            self.svc.clock = lambda: at
            status, result = self.request(["opportunities"])
            self.assertEqual(status, 200)
            assert_schema(self, "opportunities_response", result)

    def test_unsupported_watch_patch_never_creates_a_second_watch(self):
        self.assertEqual(self.request(["watches", RID], method="PATCH", payload={})[0], 503)
        self.assertEqual(self.store.watches, [])

    def test_exposure_and_dismiss_dispatch_are_post_only_and_no_store(self):
        body = {"wire": "owned-adapter"}
        with patch.object(self.svc, "exposure", return_value=body) as record:
            self.assertEqual(self.request(["exposures"], method="POST", payload={"event_id": RID}), (200,body))
            record.assert_called_once_with(WID,"session",{"event_id":RID})
            self.assertEqual(self.request(["exposures"])[0],404)
            self.assertEqual(self.request(["exposures"],method="POST",query="unknown=1")[0],400)
            self.assertEqual(record.call_count,1)
        with patch.object(self.svc,"dismiss",return_value=body) as dismiss:
            self.assertEqual(self.request(["opportunities",OID,"dismiss"],method="POST",payload={"revision":1}), (200,body))
            dismiss.assert_called_once_with(WID,"session",OID,{"revision":1})
            self.assertEqual(self.request(["opportunities",OID,"dismiss"])[0],404)
            self.assertEqual(self.request(["opportunities",OID,"dismiss"],method="POST",query="reason=no")[0],400)

    def test_learning_and_forecast_operator_routes_never_dispatch_on_get(self):
        with patch.object(self.svc,'learning',return_value={'data':{}}) as learning:
            self.assertEqual(self.request(['learning'],query='window=24h')[0],200)
            learning.assert_called_once_with(WID,'session',window='24h')
            self.assertEqual(self.request(['learning','metric-choices'])[0],404)
            self.assertEqual(self.request(['learning','treatment-assessments'])[0],404)
            self.assertEqual(learning.call_count,1)
            self.assertEqual(self.request(['learning','metric-choices'],method='POST',payload={'metric':'views'})[0],200)
            self.assertEqual(self.request(['learning','treatment-assessments'],method='POST',payload={'treatment_changed':False})[0],200)
            learning.assert_called_with(WID,'session',payload={'treatment_changed':False},assessment=True)
        with patch.object(self.svc,'forecast_operation',return_value={'data':{}}) as forecast:
            self.assertEqual(self.request(['forecasts','evaluate'])[0],400)
            self.assertEqual(self.request(['forecasts','admit'])[0],400)
            self.assertEqual(self.request(['forecasts',RID])[0],400)
            forecast.assert_not_called()
            self.assertEqual(self.request(['forecasts',RID],query='revision=1')[0],200)
            forecast.assert_called_once_with(WID,'session',object_id=RID,revision=1)
            self.assertEqual(self.request(['forecasts','evaluate'],method='POST',payload={'candidates':[]})[0],200)
            self.assertEqual(self.request(['forecasts','admit'],method='POST',query='override=true')[0],400)
