"""Synthetic, no-network Meta public source contract tests.

These tests prove only that an API-capable adapter is coded and gated. They do
NOT prove App Review, token rights, production source admission or live coverage.
"""
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import unittest

import test_trend_contracts as F
from postriff_phase2.growth.trends.contracts import ContractError
from postriff_phase2.growth.trends.providers import meta_public as M

TIMES = dict(received_at=F.NOW, available_at=F.NOW, coverage_epoch="synthetic-meta-public")

GRANTS = {
    "threads": ("threads_basic", "threads_keyword_search"),
    "instagram": ("instagram_basic", "instagram_public_content_access"),
    "facebook": ("pages_public_content_access",),
}
OPERATIONS = {"threads": "keyword_search", "instagram": "hashtag_discovery",
              "facebook": "page_public_posts"}
TOKEN = "synthetic-not-a-real-token-987654321"


def policy(name, *, scopes=None, **kw):
    return F.policy(provider_id=name, operation=OPERATIONS[name], price_ref=None,
                    verified_scopes=GRANTS[name] if scopes is None else tuple(scopes), **kw)


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
        quota = Mock()
        common = dict(policy=policy(name), token=TOKEN,
                      enabled=True, entitlement_current=True,
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
        self.assertEqual(quota.call_count, 2)
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
                self.invoke(name, response, policy=policy(name, scopes=owned_scopes[name]))
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
