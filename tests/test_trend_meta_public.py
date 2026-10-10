"""Synthetic, no-network Meta public source contract tests.

These tests prove only that an API-capable adapter is coded and gated. They do
NOT prove App Review, token rights, production source admission or live coverage.
"""
from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError
import unittest

import test_trend_contracts as F
from postriff_phase2.growth.trends.contracts import ContractError
from postriff_phase2.growth.trends.providers import meta_public as M

TIMES = dict(received_at=F.NOW, available_at=F.NOW, coverage_epoch="synthetic-meta-public")

GRANTS = {
    "threads": ("threads_basic", "threads_keyword_search"),
    "instagram": ("instagram_basic",),
    "facebook": (),
}
OPERATIONS = {"threads": "keyword_search", "instagram": "hashtag_discovery",
              "facebook": "page_public_posts"}
TOKEN = "synthetic-not-a-real-token-987654321"


def policy(name, *, scopes=None, **kw):
    return F.policy(provider_id=name, operation=OPERATIONS[name], price_ref=None,
                    verified_scopes=GRANTS[name] if scopes is None else tuple(scopes), **kw)


def proof(name, **changes):
    values = dict(review_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", review_ref="synthetic:review",
        app_id="1234567", provider_id=name, operation=OPERATIONS[name],
        api_version="v1.0" if name == "threads" else M.GRAPH_VERSION, scope_key=F.SCOPE,
        login_kind="threads_login" if name == "threads" else "facebook_login",
        account_id="178400009999" if name == "instagram" else "123456",
        account_kind={"threads":"user", "instagram":"business", "facebook":"app"}[name],
        token_fingerprint=M.token_fingerprint(TOKEN), verified_scopes=GRANTS[name],
        approved_scopes=GRANTS[name], approved_features={"threads":(),
            "instagram":("instagram_public_content_access",), "facebook":("pages_public_content_access",)}[name],
        verified_at=F.NOW, expires_at=F.AFTER, quota_rule_ref="synthetic:quota",
        quota_limit=30, quota_window_seconds=604800 if name == "instagram" else 86400,
        reviewed_page_ids=("12345",) if name == "facebook" else (), page_public=name == "facebook",
        page_restricted=False, consent_current=True)
    values.update(changes)
    return M.ReviewProof(**values)


def threads_row(native_id="123456789", **changes):
    value = {"id": native_id, "text": "Cantonese music",
             "permalink": "https://www.threads.net/@synthetic/post/abc",
             "timestamp": "2026-09-26T12:00:00Z"}
    value.update(changes)
    return value


def instagram_row(native_id="17840000000000", **changes):
    value = {"id": native_id, "caption": "Synthetic #music",
             "permalink": "https://www.instagram.com/p/synthetic/",
             "timestamp": "2026-09-26T12:00:00+0000"}
    value.update(changes)
    return value


def page_row(native_id="12345_67890", **changes):
    value = {"id": native_id, "message": "Synthetic Page post",
             "permalink_url": "https://www.facebook.com/page/posts/67890",
             "created_time": "2026-09-26T14:00:00+0200"}
    value.update(changes)
    return value


class MetaPublic(F.OfflineTest):
    def invoke(self, name, response, **changes):
        transport = Mock()
        transport.get.side_effect = [(item, {}, 135) for item in (
            response if isinstance(response, list) else [response])]
        quota = Mock(return_value=True)
        common = dict(policy=policy(name), token=TOKEN,
                      enabled=True, entitlement_current=True, review=proof(name),
                      quota_reserve=quota, limit=2,
                      transport=transport, **TIMES)
        if name == "threads":
            common["query"] = "piano"
            fn = M.collect_threads_keyword
        elif name == "instagram":
            common["ig_user_id"] = "178400009999"
            common["hashtag"] = "music"
            fn = M.collect_instagram_hashtag
        else:
            common["reviewed_page_id"] = "12345"
            fn = M.collect_facebook_public_page
        common.update(changes)
        result = fn(**common)
        return result, transport, quota

    def test_policy_scope_claims_without_review_proof_never_dispatch(self):
        # Removing independent app/token proof admission must let this fail.
        for name in ("threads", "instagram", "facebook"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, {"data": []}, review=None)

    def test_three_separate_capabilities_are_inert_until_reviewed(self):
        expected = set((name, OPERATIONS[name]) for name in GRANTS)
        self.assertEqual(set(M.CAPABILITIES), expected)
        for name, operation in expected:
            cap = M.CAPABILITIES[name, operation]
            self.assertEqual(cap.provider_id, name)
            self.assertEqual(cap.operation, operation)
            self.assertEqual(set(cap.required_scopes), set(GRANTS[name]))
            self.assertEqual(cap.max_items, 50)
            self.assertEqual(cap.max_attempts, 1)
            self.assertEqual(cap.evidence_kinds, ("raw_post",))
        from postriff_phase2.growth.trends.providers.runtime import binding
        for name, operation in expected:
            self.assertIsNone(binding(None, {"provider_id": name, "operation": operation},
                                      M.PROTOCOL),
                              "A code module must not silently register live Meta sources")

    def test_threads_keyword_search_is_only_a_sample(self):
        batch, transport, quota = self.invoke(
            "threads", {"data": [threads_row()], "paging": {"cursors": {"after": "abc=="}}})
        self.assertEqual(batch.completeness, "partial")
        self.assertEqual(batch.reason_code, "meta_sample_not_platform_population")
        self.assertEqual(len(batch.observations), 1)
        row = batch.observations[0]
        self.assertEqual(row["kind"], "raw_post")
        self.assertEqual(row["payload"]["platform"], "threads")
        self.assertEqual(row["payload"]["author_status"], "unknown")
        self.assertEqual(row["payload"]["text"], "Cantonese music")
        self.assertNotIn("author_key", row["payload"])
        self.assertNotIn("provider_metrics", row["payload"])
        url = transport.get.call_args.args[0]
        self.assertEqual(urlsplit(url).hostname, M.THREADS_HOST)
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["search_type"], ["RECENT"])
        self.assertEqual(params["limit"], ["2"])
        self.assertNotIn("access_token", params)
        self.assertNotIn(TOKEN, url)
        self.assertEqual(transport.get.call_args.kwargs["headers"], {"Authorization": "Bearer " + TOKEN})
        quota.assert_called_once_with("threads_keyword_search", F.SCOPE, 1)
        self.assertEqual(batch.cursor["after"], "abc==")

    def test_threads_page_cursor_is_bound_to_query_and_never_follows_provider_url(self):
        data = {"data": [], "paging": {
            "cursors": {"after": "safe_abc=="}, "next": "https://169.254.169.254/private"}}
        first, _, _ = self.invoke("threads", data)
        second, transport, _ = self.invoke("threads", {"data": []}, cursor=first.cursor)
        self.assertEqual(second.observations, ())
        self.assertEqual(parse_qs(urlsplit(transport.get.call_args.args[0]).query)["after"],
                         ["safe_abc=="])
        self.assertEqual(transport.get.call_args.args[0].split("?")[0], M.THREADS_URL)
        with self.assertRaises(ContractError):
            self.invoke("threads", {"data": []}, cursor=first.cursor, query="violin")

    def test_instagram_two_step_resolves_only_reviewed_hashtag_results(self):
        response = [{"data": [{"id": "17841230000"}]},
                    {"data": [instagram_row()]}]
        batch, transport, quota = self.invoke("instagram", response)
        self.assertEqual(len(batch.observations), 1)
        post = batch.observations[0]
        self.assertEqual(post["payload"]["author_status"], "unknown")
        self.assertNotIn("author_key", post["payload"])
        self.assertEqual(post["payload"]["platform"], "instagram")
        self.assertEqual(post["event_at"], F.BEFORE)
        first, second = transport.get.call_args_list
        self.assertEqual(urlsplit(first.args[0]).path, f"/{M.GRAPH_VERSION}/ig_hashtag_search")
        self.assertEqual(urlsplit(second.args[0]).path, f"/{M.GRAPH_VERSION}/17841230000/recent_media")
        self.assertNotIn(TOKEN, first.args[0] + second.args[0])
        self.assertEqual(quota.call_count, 3)
        self.assertEqual(quota.call_args_list[0].args,
                         ("instagram_distinct_hashtag_7d", "178400009999:music", 1))

    def test_facebook_ppca_is_page_scoped_not_a_public_person_feed(self):
        batch, transport, quota = self.invoke("facebook", {"data": [page_row()]})
        self.assertEqual(len(batch.observations), 1)
        post = batch.observations[0]
        self.assertEqual(post["payload"]["platform"], "facebook")
        self.assertEqual(post["payload"]["author_key"], "facebook-page:12345")
        self.assertEqual(post["event_at"], F.BEFORE)
        self.assertEqual(post["source_identity"], "facebook:12345_67890")
        self.assertEqual(urlsplit(transport.get.call_args.args[0]).path,
                         f"/{M.GRAPH_VERSION}/12345/posts")
        quota.assert_called_once_with("facebook_public_page_read", "12345", 1)

    def test_account_ownership_scopes_cannot_grant_public_discovery(self):
        fixtures = {"threads": {"data": [threads_row()]},
                    "instagram": [{"data": [{"id": "1"}]}, {"data": [instagram_row()]}],
                    "facebook": {"data": [page_row()]}}
        owned_scopes = {"threads": ("threads_basic", "threads_manage_insights"),
                        "instagram": ("instagram_business_basic", "instagram_business_manage_insights"),
                        "facebook": ("pages_show_list", "pages_read_engagement")}
        for name, response in fixtures.items():
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, response, policy=policy(name, scopes=owned_scopes[name]),
                            review=proof(name, approved_features=()))
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, response, policy=policy(name, readiness="revoked"))
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, response, enabled=False)
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, response, entitlement_current=False)

    def test_policy_rejects_cross_workspace_shared_and_unreviewed_operation(self):
        for name in ("threads", "instagram", "facebook"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, {"data": []}, policy=policy(
                    name, scope_key="shared:rafii",
                    rights=F.permissions("shared:rafii")))
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, {"data": []}, policy=F.policy(
                    provider_id=name, operation="owned_read", price_ref=None,
                    verified_scopes=GRANTS[name]))

    def test_no_request_without_durable_quota_callback(self):
        for name in ("threads", "instagram", "facebook"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, {"data": []}, quota_reserve=None)

    def test_invalid_page_identity_and_ig_pro_account_never_go_out(self):
        for value in ("123/../../secrets", "https://evil.invalid", "a", ""):
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.invoke("facebook", {"data": []}, reviewed_page_id=value)
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.invoke("instagram", {"data": []}, ig_user_id=value)

    def test_bad_tokens_and_query_texts_fail_closed(self):
        for name in ("threads", "instagram", "facebook"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                self.invoke(name, {"data": []}, token="Bearer leaked\r\nsecret")
        for query in ("", "foo\rbar", "  foo", "foo\u007fbar"):
            with self.subTest(query=query), self.assertRaises(ContractError):
                self.invoke("threads", {"data": []}, query=query)
        for query in ("a b", "#😎", "", "two;hashtags"):
            with self.subTest(query=query), self.assertRaises(ContractError):
                self.invoke("instagram", {"data": []}, hashtag=query)

    def test_unreturned_metrics_are_not_fabricated_and_unknown_raw_is_stripped(self):
        low = policy("threads", rights=F.permissions(store_raw="unknown"))
        batch, _, _ = self.invoke("threads", {"data": [threads_row()]}, policy=low)
        self.assertNotIn("text", batch.observations[0]["payload"])
        self.assertNotIn("mention_count", batch.observations[0]["payload"])
        self.assertNotIn("engagement", batch.observations[0]["payload"])

    def test_bad_provider_item_quarantines_without_advancing_cursor(self):
        for name, response in (
            ("threads", {"data": [threads_row(), threads_row("garbage")],
                         "paging": {"cursors": {"after": "next"}}}),
            ("instagram", [{"data": [{"id": "5"}]},
                           {"data": [instagram_row(), instagram_row("not-an-id")],
                            "paging": {"cursors": {"after": "next"}}}]),
            ("facebook", {"data": [page_row(), page_row("bad")],
                          "paging": {"cursors": {"after": "next"}}})):
            with self.subTest(name=name):
                batch, _, _ = self.invoke(name, response)
                self.assertEqual(batch.completeness, "gap")
                self.assertEqual(batch.health, "health_degraded")
                self.assertTrue(batch.quarantined)
                self.assertIsNone(batch.cursor)
                self.assertEqual(len(batch.observations), 1)

    def test_malicious_post_urls_quarantined_not_fetched(self):
        for name, response in (
            ("threads", {"data": [threads_row(permalink="https://127.0.0.1/private")]}),
            ("instagram", [{"data": [{"id": "5"}]},
                           {"data": [instagram_row(permalink="https://127.0.0.1/private")]}]),
            ("facebook", {"data": [page_row(permalink_url="https://127.0.0.1/private")]})):
            with self.subTest(name=name):
                batch, transport, _ = self.invoke(name, response)
                self.assertEqual(batch.observations, ())
                self.assertEqual(batch.completeness, "gap")
                self.assertLessEqual(transport.get.call_count, 2)

    def test_cross_keyword_duplicate_canonical_identity_is_stable(self):
        first, _, _ = self.invoke("threads", {"data": [threads_row()]}, query="piano")
        other, _, _ = self.invoke("threads", {"data": [threads_row()]}, query="violin")
        self.assertEqual(first.observations[0]["source_identity"],
                         other.observations[0]["source_identity"])

    def test_false_or_ambiguous_quota_admission_prevents_external_call(self):
        # A callback returning False/None cannot be mistaken for a durable reservation.
        for value in (False, None, 1):
            transport = Mock(); transport.get.return_value = ({"data":[]}, {}, 1)
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.invoke("threads", {"data": []}, quota_reserve=lambda *a: value, transport=transport)
            transport.get.assert_not_called()

    def test_unchanged_post_revision_is_stable_across_retrievals_and_queries(self):
        first, _, _ = self.invoke("threads", {"data": [threads_row()]})
        other, _, _ = self.invoke("threads", {"data": [threads_row()]}, query="violin",
                               received_at="2026-09-27T12:01:00Z", available_at="2026-09-27T12:01:00Z")
        self.assertEqual(first.observations[0]["revision_identity"], other.observations[0]["revision_identity"])
        self.assertEqual(first.observations[0]["observation_id"], other.observations[0]["observation_id"])

    def test_top_sample_provenance_preserves_query_and_synthetic_evidence(self):
        batch, _, _ = self.invoke("threads", {"data": [threads_row()]}, search_type="TOP")
        provenance = batch.observations[0]["provenance"]
        self.assertEqual(provenance.get("sampling_mode"), "TOP")
        self.assertEqual(provenance["query"], "piano")
        self.assertEqual(provenance["api_version"], "v1.0")
        self.assertEqual(provenance["evidence_kind"], "synthetic")
        self.assertEqual(provenance["third_party"], "unverified")
        self.assertEqual(provenance["review_id"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

    def test_provider_error_and_exception_never_echo_secrets(self):
        for error in (ValueError(TOKEN), ContractError(TOKEN)):
            transport = Mock(); transport.get.side_effect = error
            with self.assertRaises(Exception) as caught:
                self.invoke("threads", {"data": []}, transport=transport)
            self.assertIsInstance(caught.exception, ContractError)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
        with self.assertRaises(ContractError) as caught:
            self.invoke("threads", {"error": {"message": TOKEN, "code": 190}})
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_instagram_lookup_and_read_each_reserve_graph_capacity(self):
        _, _, quota = self.invoke("instagram", [{"data":[{"id":"5"}]}, {"data":[]}])
        self.assertEqual([call.args[0] for call in quota.call_args_list],
                         ["instagram_distinct_hashtag_7d", "instagram_graph_request", "instagram_graph_request"])

    def test_review_is_exact_current_token_account_feature_and_operation(self):
        for name, mutations in {
            "threads": ({"verified_scopes":("threads_basic",)}, {"approved_scopes":("threads_basic",)},
                        {"provider_id":"instagram"}, {"api_version":M.GRAPH_VERSION}),
            "instagram": ({"login_kind":"instagram_login"}, {"account_kind":"personal"},
                          {"approved_features":()}, {"account_id":"another"}),
            "facebook": ({"approved_features":()}, {"account_kind":"user"},
                         {"reviewed_page_ids":()}, {"page_public":False}, {"page_restricted":True}),
        }.items():
            for mutation in (*mutations, {"scope_key":"workspace:foreign"}, {"token_fingerprint":"0"*64},
                             {"verified_at":F.BEFORE}, {"consent_current":False}):
                transport = Mock()
                with self.subTest(name=name, mutation=mutation), self.assertRaises(ContractError):
                    self.invoke(name, {"data":[]}, review=proof(name, **mutation), transport=transport)
                transport.get.assert_not_called()

    def test_instagram_provenance_identifies_hashtag_sample(self):
        batch, _, _ = self.invoke("instagram", [{"data":[{"id":"5"}]}, {"data":[instagram_row()]}])
        self.assertEqual(batch.observations[0]["provenance"].get("query"), "music")

    def test_cursor_cannot_cross_reviewed_connection(self):
        first, _, _ = self.invoke("threads", {"data":[], "paging":{"cursors":{"after":"abc"}}})
        with self.assertRaises(ContractError):
            self.invoke("threads", {"data":[]}, cursor=first.cursor, review=proof("threads", account_id="654321"))

    def test_falsy_malformed_paging_and_cursor_are_refused(self):
        for paging in ([], "", {"cursors":[]}):
            with self.subTest(paging=paging), self.assertRaises(ContractError):
                self.invoke("threads", {"data":[], "paging":paging})
        with self.assertRaises(ContractError):
            self.invoke("threads", {"data":[]}, cursor=[])

    def test_numeric_platform_ids_are_not_page_post_ids(self):
        batch, _, _ = self.invoke("threads", {"data":[threads_row("123_456")]})
        self.assertEqual(batch.observations, ())
        self.assertEqual(batch.quarantined[0]["reason_code"], "meta_identity_invalid")

    def test_credential_parameters_in_public_links_are_quarantined(self):
        batch, _, _ = self.invoke("threads", {"data":[threads_row(
            permalink="https://www.threads.net/@a/post/x?access_token=foreign-secret")]})
        self.assertEqual(batch.observations, ())
        self.assertEqual(batch.quarantined[0]["reason_code"], "meta_post_url_invalid")

    def test_instagram_request_timeouts_share_one_wall_clock_budget(self):
        with unittest.mock.patch.object(M.time, "monotonic", side_effect=[0, 1, 8, 14, 14.5]):
            _, transport, _ = self.invoke("instagram", [{"data":[{"id":"5"}]}, {"data":[]}])
        self.assertEqual([call.kwargs["timeout"] for call in transport.get.call_args_list], [14, 1])

    def test_duplicate_posts_collapse_without_inventing_counts(self):
        batch, _, _ = self.invoke("threads", {"data":[threads_row(), threads_row()]})
        self.assertEqual(len(batch.observations), 1)
        self.assertNotIn("engagement", batch.observations[0]["payload"])

    def test_token_echo_in_cursor_is_never_returned(self):
        with self.assertRaises(ContractError) as caught:
            self.invoke("threads", {"data":[], "paging":{"cursors":{"after":TOKEN}}})
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_malformed_public_url_quarantines_instead_of_escaping_validation(self):
        try:
            batch, _, _ = self.invoke("threads", {"data":[threads_row(permalink="https://[broken")]})
        except Exception as error:
            self.fail("Malformed provider URL escaped quarantine: " + type(error).__name__)
        self.assertEqual(batch.observations, ())
        self.assertEqual(batch.completeness, "gap")

    def test_http_denial_status_and_retry_survive_sanitization(self):
        for status, code in ((401,"meta_access_pending"), (403,"meta_rights_suspended"), (429,"meta_rate_limited")):
            transport = Mock(); transport.get.side_effect = HTTPError(
                "https://graph.threads.net/private?access_token=" + TOKEN, status, TOKEN,
                {"Retry-After":"120", "Secret":TOKEN}, None)
            with self.subTest(status=status), self.assertRaises(ContractError) as caught:
                self.invoke("threads", {"data":[]}, transport=transport)
            self.assertEqual(getattr(caught.exception, "status", None), status)
            self.assertEqual(getattr(caught.exception, "retry_after_seconds", None), 120)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn(TOKEN, repr(vars(caught.exception)))
            self.assertIsNone(caught.exception.__cause__)
            self.assertIsNone(caught.exception.__context__)

    def test_http_retry_after_is_bounded_and_supports_http_dates(self):
        for value, expected in (("999999999999",86400), ("Sun, 27 Sep 2026 12:02:00 GMT",120),
                                ("Sun, 27 Sep 2026 11:59:00 GMT",0), (TOKEN,None)):
            transport = Mock(); transport.get.side_effect = HTTPError(
                "https://graph.threads.net/private",429,TOKEN,{"Retry-After":value},None)
            with unittest.mock.patch.object(M.time,"time",return_value=1790510400):
                with self.subTest(value=value), self.assertRaises(ContractError) as caught:
                    self.invoke("threads", {"data":[]}, transport=transport)
            self.assertEqual(getattr(caught.exception,"retry_after_seconds",None),expected)

    def test_safe_quota_exhaustion_is_distinct_from_unavailable(self):
        for code, expected in (("meta_provider_quota_exhausted","meta_provider_quota_exhausted"),
                               (TOKEN,"meta_quota_unavailable")):
            quota = Mock(side_effect=ContractError(code))
            with self.subTest(code=code), self.assertRaises(ContractError) as caught:
                self.invoke("threads", {"data":[]}, quota_reserve=quota)
            self.assertEqual(caught.exception.code,expected)
            self.assertIsNone(caught.exception.__context__)

    def test_http_error_response_is_closed_without_reading_its_body(self):
        body = BytesIO(TOKEN.encode())
        transport = Mock(); transport.get.side_effect = HTTPError(
            "https://graph.threads.net/private",429,TOKEN,{"Retry-After":"120"},body)
        with self.assertRaises(ContractError):
            self.invoke("threads", {"data":[]}, transport=transport)
        self.assertTrue(body.closed)

    def test_http_start_tracker_stays_zero_on_quota_denial(self):
        import inspect
        self.assertIn("on_http_start", inspect.signature(M.collect_threads_keyword).parameters)
        starts = []
        with self.assertRaises(ContractError):
            self.invoke("threads", {"data":[]}, quota_reserve=lambda *a: False,
                        on_http_start=lambda: starts.append(1))
        self.assertEqual(starts, [])

    def test_http_start_tracker_counts_only_first_instagram_request_on_second_quota_denial(self):
        import inspect
        self.assertIn("on_http_start", inspect.signature(M.collect_instagram_hashtag).parameters)
        starts = []
        quota = Mock(side_effect=[True, True, False])
        with self.assertRaises(ContractError):
            self.invoke("instagram", [{"data":[{"id":"5"}]}, {"data":[]}],
                        quota_reserve=quota, on_http_start=lambda: starts.append(1))
        self.assertEqual(starts, [1])

    def test_default_deadline_transport_kills_and_reaps_slow_child(self):
        self.assertTrue(hasattr(M,"MetaDeadlineTransport"), "DNS/slow body lacks a killable deadline boundary")
        import subprocess, sys, time
        original_popen = subprocess.Popen
        children = []
        def slow_process(*args, **kwargs):
            child = original_popen([sys.executable,"-I","-S","-c","import time; time.sleep(10)"], **kwargs)
            children.append(child)
            return child
        with unittest.mock.patch.object(M.subprocess,"Popen",side_effect=slow_process):
            started = time.monotonic()
            with self.assertRaises(ContractError) as caught:
                M.MetaDeadlineTransport(frozenset({M.THREADS_HOST})).get(
                    M.THREADS_URL + "?q=piano",max_bytes=1000,timeout=0.1,
                    headers={"Authorization":"Bearer " + TOKEN})
        self.assertEqual(caught.exception.code,"meta_time_budget_exceeded")
        self.assertLess(time.monotonic()-started,1)
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_default_transport_receives_original_attempt_deadline(self):
        transport = M.MetaDeadlineTransport(frozenset({M.THREADS_HOST}))
        with unittest.mock.patch.object(transport,"get",return_value=({"data":[]},{},2)) as get:
            with unittest.mock.patch.object(M.time,"monotonic",return_value=1):
                M._fetch(transport,M.THREADS_URL,max_bytes=1000,deadline=15,
                         headers={"Authorization":"Bearer " + TOKEN})
        self.assertEqual(get.call_args.kwargs.get("deadline"),15)

    def test_deadline_transport_contains_credentials_only_in_stdin(self):
        child = Mock(returncode=0); child.poll.return_value=0
        child.communicate.return_value=(b'{"data":{"data":[]},"bytes":11}',None)
        with unittest.mock.patch.object(M.subprocess,"Popen",return_value=child) as popen:
            data, headers, size = M.MetaDeadlineTransport(frozenset({M.THREADS_HOST})).get(
                M.THREADS_URL + "?q=piano", max_bytes=1000,timeout=1,
                headers={"Authorization":"Bearer " + TOKEN})
        self.assertEqual((data,headers,size),({"data":[]},{},11))
        self.assertNotIn(TOKEN,repr(popen.call_args))
        self.assertEqual(popen.call_args.kwargs["env"],{})
        self.assertEqual(popen.call_args.kwargs["stderr"],M.subprocess.DEVNULL)
        self.assertIn(TOKEN,child.communicate.call_args_list[0].args[0].decode())

    def test_deadline_transport_rejects_invalid_boundary_before_process_start(self):
        with unittest.mock.patch.object(M.subprocess,"Popen") as popen:
            for url, headers, maximum in (
                ("https://127.0.0.1/private", {"Authorization":"Bearer " + TOKEN},1000),
                (M.THREADS_URL + "?access_token=" + TOKEN,{"Authorization":"Bearer " + TOKEN},1000),
                (M.THREADS_URL,{"Authorization":"Bearer " + TOKEN,"extra":TOKEN},1000),
                (M.THREADS_URL,{"Authorization":"Bearer " + TOKEN},M.MAX_BYTES+1)):
                with self.subTest(url=url), self.assertRaises(ContractError):
                    M.MetaDeadlineTransport(frozenset({M.THREADS_HOST})).get(
                        url,max_bytes=maximum,timeout=1,headers=headers)
            popen.assert_not_called()

    def test_deadline_transport_rejects_child_response_size_and_sanitizes_denial(self):
        for output, expected, status in (
            (b'{"data":{"data":[]},"bytes":1001}',"meta_response_byte_limit",None),
            (b'{"error":"private-secret","status":429,"retry_after":"120"}',"meta_rate_limited",429)):
            child = Mock(returncode=0); child.poll.return_value=0
            child.communicate.return_value=(output,None)
            with unittest.mock.patch.object(M.subprocess,"Popen",return_value=child):
                with self.assertRaises(ContractError) as caught:
                    M.MetaDeadlineTransport(frozenset({M.THREADS_HOST})).get(
                        M.THREADS_URL,max_bytes=1000,timeout=1,headers={"Authorization":"Bearer " + TOKEN})
            self.assertEqual(caught.exception.code,expected)
            self.assertEqual(getattr(caught.exception,"status",None),status)
            self.assertNotIn("private-secret",str(caught.exception))

    def test_isolated_worker_round_trip_with_synthetic_http_boundary(self):
        import subprocess
        original_popen = subprocess.Popen
        prefix = """import urllib.request
class FakeResponse:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, maximum): return b'{"data":[]}'[:maximum]
class FakeOpener:
    def open(self, *args, **kwargs): return FakeResponse()
urllib.request.build_opener = lambda *args: FakeOpener()
"""
        def synthetic_process(command, **kwargs):
            command = list(command); command[-1] = prefix + command[-1]
            return original_popen(command, **kwargs)
        with unittest.mock.patch.object(M.subprocess,"Popen",side_effect=synthetic_process):
            data, headers, size = M.MetaDeadlineTransport(frozenset({M.THREADS_HOST})).get(
                M.THREADS_URL,max_bytes=1000,timeout=1,headers={"Authorization":"Bearer " + TOKEN})
        self.assertEqual((data,headers,size),({"data":[]},{},11))

    def test_empty_sample_is_partial_not_population_zero(self):
        for name, response in (
            ("threads", {"data": []}),
            ("instagram", [{"data": []}]),
            ("facebook", {"data": []})):
            batch, _, _ = self.invoke(name, response)
            self.assertEqual(batch.observations, ())
            self.assertEqual(batch.completeness, "partial")
            self.assertIn("not_", batch.reason_code)


if __name__ == "__main__":
    unittest.main()
