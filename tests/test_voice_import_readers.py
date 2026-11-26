"""Provider page readers for voice import (spec 5.2, IMP-2). Canned responses through a fake transport: no network,
and every account, handle and post text here is synthetic."""
import json
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2 import voice_import_readers as R
from postriff_phase2.provider_base import GRAPH_VERSION

DID = "did:plc:abcdefghijklmnopqrstuvwx"
PDS = "https://pds.example.com"
BSKY = json.dumps({"did": DID, "pds": PDS})
TEXT = "We moved the launch to Friday so the beta group gets one more week."


def PUBLIC(host, port, type=None):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def PRIVATE(host, port, type=None):
    return [(2, 1, 6, "", ("10.0.0.5", 443))]


class Wire:
    """Replies in order; an exception in the queue is raised instead."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def query(self, index=-1):
        return {key: values[0] for key, values in parse_qs(urlsplit(self.calls[index]["url"]).query).items()}


def ok(body, headers=None):
    return {"status": 200, "headers": headers or {}, "body": body}


def read(provider, wire, **kwargs):
    options = {"token": BSKY if provider == "bluesky" else "tok", "account": DID if provider == "bluesky" else "acct", "cursor": None,
               "since": None, "transport": wire, "resolver": PUBLIC, **kwargs}
    return R.read_page(provider, **options)


class ContractTests(unittest.TestCase):
    def test_supported_providers_and_page_shape(self):
        self.assertEqual(R.SUPPORTED, ("threads", "instagram", "bluesky", "mastodon", "linkedin"))
        page = R.Page([], None, False)
        self.assertEqual((page.items, page.next_cursor, page.more, page.skipped), ([], None, False, 0))
        with self.assertRaises(ValueError):
            read("x", Wire())

    def test_rate_limit_carries_retry_after(self):
        for provider, account in (("threads", "1"), ("bluesky", DID), ("mastodon", "109@social.example.org"), ("instagram", "17841400000000")):
            with self.subTest(provider=provider):
                with self.assertRaises(R.ReaderHTTP) as caught:
                    read(provider, Wire({"status": 429, "headers": {"retry-after": "90"}, "body": {}}), account=account)
                self.assertEqual((caught.exception.status, caught.exception.retry_after), (429, 90))
        with self.assertRaises(R.ReaderHTTP) as caught:
            read("threads", Wire({"status": 503, "headers": {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, "body": {}}))
        self.assertEqual((caught.exception.status, caught.exception.retry_after), (503, None))   # only whole seconds are trusted
        self.assertNotIn("tok", str(caught.exception))

    def test_meta_reports_rate_limits_as_errors_with_codes(self):
        limited = {"status": 403, "headers": {}, "body": {"error": {"message": "limit", "code": 4}}}
        transient = {"status": 500, "headers": {}, "body": {"error": {"message": "later", "code": 2, "is_transient": True}}}
        denied = {"status": 400, "headers": {}, "body": {"error": {"message": "expired", "code": 190}}}
        for reply, status in ((limited, 429), (transient, 503), (denied, 400)):
            with self.assertRaises(R.ReaderHTTP) as caught:
                read("threads", Wire(reply))
            self.assertEqual(caught.exception.status, status)

    def test_a_malformed_body_is_a_provider_fault_not_an_empty_history(self):
        for provider, account, body in (("threads", "1", {"data": {"wrong": 1}}), ("threads", "1", "text"), ("bluesky", DID, {"records": "x"}),
                                        ("mastodon", "109@social.example.org", {"not": "a list"})):
            with self.subTest(provider=provider, body=body):
                with self.assertRaises(R.ReaderHTTP) as caught:
                    read(provider, Wire(ok(body)), account=account)
                self.assertEqual(caught.exception.status, 502)

    def test_a_repeated_cursor_is_a_paging_error(self):
        with self.assertRaises(R.ReaderPaging):
            read("threads", Wire(ok({"data": [], "paging": {"next": "https://n", "cursors": {"after": "SAME"}}})), cursor="SAME")
        record = {"uri": f"at://{DID}/app.bsky.feed.post/aaa", "value": {"text": TEXT}}
        with self.assertRaises(R.ReaderPaging):
            read("bluesky", Wire(ok({"records": [record], "cursor": "SAME"})), cursor="SAME")
        with self.assertRaises(R.ReaderPaging):   # a next page announced without a usable cursor
            read("threads", Wire(ok({"data": [], "paging": {"next": "https://n", "cursors": {}}})))

    def test_an_oversized_response_is_asked_again_as_a_smaller_page(self):
        wire = Wire(AlphaError("Provider response limit exceeded.", 502), ok({"data": []}))
        page = read("threads", wire)
        self.assertEqual((page.items, page.more), ([], False))
        first, second = int(wire.query(0)["limit"]), int(wire.query(1)["limit"])
        self.assertLess(second, first)
        with self.assertRaises(AlphaError):          # still too large, or the provider is unreachable: the caller retries later
            read("threads", Wire(AlphaError("Provider response limit exceeded.", 502), AlphaError("Provider response limit exceeded.", 502)))
        unreachable = Wire(AlphaError("The provider is temporarily unreachable.", 503))
        with self.assertRaises(AlphaError):
            read("threads", unreachable)
        self.assertEqual(len(unreachable.calls), 1)

    def test_posts_older_than_since_are_dropped_and_end_the_run(self):
        rows = [{"id": "3", "text": TEXT, "timestamp": "2026-09-20T10:00:00+0000"}, {"id": "2", "text": TEXT, "timestamp": "2026-08-01T10:00:00+0000"},
                {"id": "1", "text": TEXT}]
        body = {"data": rows, "paging": {"next": "https://n", "cursors": {"after": "NEXT"}}}
        page = read("threads", Wire(ok(body)), since=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual([item["externalId"] for item in page.items], ["3", "1"])      # an undated post is kept
        self.assertEqual((page.more, page.next_cursor), (False, None))
        everything = read("threads", Wire(ok(body)), since=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual((len(everything.items), everything.more, everything.next_cursor), (3, True, "NEXT"))


class ThreadsTests(unittest.TestCase):
    def test_request_shape_kinds_and_skipped_posts(self):
        wire = Wire(ok({"data": [
            {"id": "11", "text": TEXT, "timestamp": "2026-09-20T10:00:00+0000", "media_type": "TEXT_POST", "permalink": "https://www.threads.net/@studio/post/11"},
            {"id": "12", "text": "Someone else's words that must not be kept.", "timestamp": "2026-09-19T10:00:00+0000", "media_type": "REPOST_FACADE"},
            {"id": "13", "text": TEXT + " Agreed.", "media_type": "IMAGE", "is_quote_post": True, "permalink": "javascript:alert(1)"},
            {"id": "14", "media_type": "IMAGE", "timestamp": "bad"}, "junk", {"text": "no id"}],
            "paging": {"next": "https://untrusted.invalid/next", "cursors": {"after": "CUR2"}}}))
        page = read("threads", wire, cursor="CUR1")
        call = wire.calls[0]
        # The same host and version constant as the existing metadata-only history import.
        self.assertTrue(call["url"].startswith(f"https://graph.threads.net/{GRAPH_VERSION}/me/threads?"))
        self.assertNotIn("headers", call)
        query = wire.query()
        self.assertEqual(query["fields"], "id,text,timestamp,media_type,permalink,is_quote_post")
        self.assertEqual((query["access_token"], query["after"]), ("tok", "CUR1"))
        self.assertEqual([(i["externalId"], i["kind"], i["contentType"]) for i in page.items],
                         [("11", "original", "text"), ("12", "repost", "post"), ("13", "quote", "image")])
        self.assertEqual(set(page.items[0]), {"externalId", "text", "publishedAt", "permalink", "kind", "contentType"})
        self.assertEqual(page.items[0]["publishedAt"], "2026-09-20T10:00:00+00:00")
        self.assertEqual(page.items[0]["permalink"], "https://www.threads.net/@studio/post/11")
        self.assertEqual(page.items[1]["text"], "")                 # a repost is recorded without the other author's words
        self.assertIsNone(page.items[2]["permalink"])
        self.assertIsNone(page.items[2]["publishedAt"])
        self.assertEqual((page.skipped, page.next_cursor, page.more), (3, "CUR2", True))
        self.assertNotIn("untrusted.invalid", json.dumps([c["url"] for c in wire.calls]))

    def test_last_page(self):
        wire = Wire(ok({"data": [{"id": "1", "text": TEXT}], "paging": {"cursors": {"after": "IGNORED"}}}))
        page = read("threads", wire)
        self.assertEqual((page.next_cursor, page.more, len(page.items)), (None, False, 1))
        self.assertNotIn("after", wire.query())            # the first page is asked for without a cursor
        self.assertEqual(wire.query()["limit"], "50")


class InstagramTests(unittest.TestCase):
    ACCOUNT = "17841400000000"

    def test_captionless_media_is_skipped_and_counted(self):
        wire = Wire(ok({"data": [
            {"id": "21", "caption": TEXT, "timestamp": "2026-09-20T10:00:00+0000", "media_type": "CAROUSEL_ALBUM", "permalink": "https://www.instagram.com/p/abc/"},
            {"id": "22", "media_type": "IMAGE", "timestamp": "2026-09-19T10:00:00+0000"},
            {"id": "23", "caption": "   ", "media_type": "VIDEO"}],
            "paging": {"next": "https://n", "cursors": {"after": "IG2"}}}))
        page = read("instagram", wire, account=self.ACCOUNT)
        call = wire.calls[0]
        self.assertIn(f"/{self.ACCOUNT}/media?", call["url"])
        self.assertTrue(call["url"].startswith("https://graph.instagram.com/"))
        self.assertNotIn("tok", call["url"])
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(page.items, [{"externalId": "21", "text": TEXT, "publishedAt": "2026-09-20T10:00:00+00:00",
                                       "permalink": "https://www.instagram.com/p/abc/", "kind": "original", "contentType": "carousel"}])
        self.assertEqual((page.skipped, page.next_cursor, page.more), (2, "IG2", True))

    def test_identity_shape_and_cursor_shape_are_checked_before_any_request(self):
        wire = Wire()
        with self.assertRaises(R.ReaderHTTP) as caught:
            read("instagram", wire, account="not-a-number")
        self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(R.ReaderPaging):
            read("instagram", wire, account=self.ACCOUNT, cursor="has spaces")
        self.assertEqual(wire.calls, [])

    def test_denied_and_a_next_page_without_a_cursor(self):
        with self.assertRaises(R.ReaderHTTP) as caught:
            read("instagram", Wire({"status": 403, "headers": {}, "body": {"error": {"message": "no", "code": 10}}}), account=self.ACCOUNT)
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(R.ReaderPaging):
            read("instagram", Wire(ok({"data": [], "paging": {"next": "https://n", "cursors": {}}})), account=self.ACCOUNT)


class BlueskyTests(unittest.TestCase):
    def record(self, rkey, text=TEXT, repo=DID, **value):
        return {"uri": f"at://{repo}/app.bsky.feed.post/{rkey}", "cid": "bafyrei" + rkey,
                "value": {"$type": "app.bsky.feed.post", "text": text, "createdAt": "2026-09-20T10:00:00.000Z", "langs": ["en"], **value}}

    def test_the_accounts_own_repository_is_read_with_no_authorization(self):
        wire = Wire(ok({"cursor": "3lcursor2", "records": [
            self.record("3laaa"),
            self.record("3lbbb", reply={"root": {"uri": "at://x"}, "parent": {"uri": "at://x"}}),
            self.record("3lccc", embed={"$type": "app.bsky.embed.record", "record": {"uri": "at://y"}}),
            self.record("3lddd", embed={"$type": "app.bsky.embed.images", "images": []}),
            self.record("3leee", embed={"$type": "app.bsky.embed.recordWithMedia", "record": {}, "media": {"$type": "app.bsky.embed.video"}}),
            self.record("3lfff", text=""),                                   # a picture with no words
            self.record("3lggg", repo="did:plc:zzzzzzzzzzzzzzzzzzzzzzzz"),   # never another repository's record
            {"uri": "junk"}, "junk"]}))
        page = read("bluesky", wire, cursor="3lcursor1")
        call = wire.calls[0]
        self.assertTrue(call["url"].startswith(PDS + "/xrpc/com.atproto.repo.listRecords?"))
        self.assertNotIn("headers", call)                       # public read: no Authorization header at all
        query = wire.query()
        self.assertEqual((query["repo"], query["collection"], query["limit"], query["cursor"]), (DID, "app.bsky.feed.post", "100", "3lcursor1"))
        self.assertEqual([(i["externalId"], i["kind"], i["contentType"]) for i in page.items],
                         [("3laaa", "original", "text"), ("3lbbb", "reply", "text"), ("3lccc", "quote", "text"), ("3lddd", "original", "image"),
                          ("3leee", "quote", "video")])
        first = page.items[0]
        self.assertEqual((first["permalink"], first["publishedAt"], first["text"]),
                         (f"https://bsky.app/profile/{DID}/post/3laaa", "2026-09-20T10:00:00+00:00", TEXT))
        self.assertEqual((page.skipped, page.next_cursor, page.more), (4, "3lcursor2", True))

    def test_the_end_of_the_repository(self):
        for body in ({"records": []}, {"records": [], "cursor": "3lold"}, {"records": [self.record("3laaa")]}):
            page = read("bluesky", Wire(ok(body)))
            self.assertEqual((page.more, page.next_cursor), (False, None))

    def test_only_did_and_server_are_read_from_the_stored_connection(self):
        stored = json.dumps({"v": 1, "did": DID, "pds": PDS, "at": "access-must-stay", "rt": "refresh-must-stay",
                             "jwk": {"kty": "EC", "d": "private-must-stay"}, "iss": "https://auth.example.com"})
        wire = Wire(ok({"records": [self.record("3laaa")], "cursor": "3lnext"}))
        read("bluesky", wire, token=stored)
        self.assertNotIn("must-stay", json.dumps(wire.calls))
        self.assertEqual(set(wire.calls[0]), {"method", "url"})

    def test_the_data_server_must_be_this_accounts_plain_public_https_origin(self):
        refused = [None, "not json", json.dumps({"did": DID}), json.dumps({"did": "did:plc:zzzzzzzzzzzzzzzzzzzzzzzz", "pds": PDS}),
                   *(json.dumps({"did": DID, "pds": pds}) for pds in (
                       "http://pds.example.com", "https://pds.example.com/elsewhere", "https://user:secret@pds.example.com",
                       "https://pds.example.com:8443", "https://127.0.0.1", "https://localhost", "https://pds.internal",
                       "https://pds.example.com?x=1", "ftp://pds.example.com", 5))]
        for token in refused:
            wire = Wire()
            with self.subTest(token=token):
                with self.assertRaises(R.ReaderHTTP) as caught:
                    read("bluesky", wire, token=token)
                self.assertEqual((caught.exception.status, wire.calls), (400, []))
        with self.assertRaises(R.ReaderHTTP):
            read("bluesky", Wire(), account="someone.example.com")

    def test_a_server_name_that_resolves_to_a_private_address_is_never_contacted(self):
        wire = Wire()
        with self.assertRaises(AlphaError):          # not a ReaderHTTP: the importer retries later and sends nothing meanwhile
            read("bluesky", wire, resolver=PRIVATE)
        self.assertEqual(wire.calls, [])

        def unresolved(host, port, type=None):
            raise OSError("no such host")
        with self.assertRaises(AlphaError):
            read("bluesky", wire, resolver=unresolved)
        self.assertEqual(wire.calls, [])


class MastodonTests(unittest.TestCase):
    ACCOUNT = "109000000000000001@social.example.org"

    def status(self, status_id, content="<p>" + TEXT + "</p>", **fields):
        return {"id": status_id, "content": content, "created_at": "2026-09-20T10:00:00.000Z", "visibility": "public",
                "url": f"https://social.example.org/@studio/{status_id}", "in_reply_to_id": None, "reblog": None, "media_attachments": [], **fields}

    def test_html_becomes_plain_text_and_boosts_are_reposts(self):
        html = ('<p>First line<br />second line &amp; more</p><p>Thanks <span class="h-card"><a href="https://social.example.org/@friend" class="u-url mention">'
                '@<span>friend</span></a></span> <a href="https://example.com/long/path"><span class="invisible">https://</span><span class="ellipsis">example.com/lo</span>'
                '<span class="invisible">ng/path</span></a></p>')
        wire = Wire(ok([
            self.status("5", html),
            self.status("4", "", reblog={"id": "900", "content": "<p>Another person's post.</p>"}),
            self.status("3", in_reply_to_id="2"),
            self.status("2", visibility="private"), self.status("1", visibility="direct"),
            self.status("0", "<p></p>"), self.status("00", media_attachments=[{"type": "gifv"}]), "junk"],
            headers={"link": '<https://social.example.org/api/v1/accounts/109000000000000001/statuses?limit=40&max_id=00>; rel="next", <https://social.example.org/x?min_id=5>; rel="prev"'}))
        page = read("mastodon", wire, account=self.ACCOUNT, cursor="6")
        call = wire.calls[0]
        self.assertTrue(call["url"].startswith("https://social.example.org/api/v1/accounts/109000000000000001/statuses?"))
        query = wire.query()
        self.assertEqual((query["exclude_reblogs"], query["max_id"]), ("false", "6"))
        self.assertEqual(call["headers"], {"Authorization": "Bearer tok"})
        self.assertEqual(page.items[0]["text"], "First line\nsecond line & more\n\nThanks @friend https://example.com/long/path")
        self.assertEqual([(i["externalId"], i["kind"], i["contentType"]) for i in page.items],
                         [("5", "original", "text"), ("4", "repost", "post"), ("3", "reply", "text"), ("00", "original", "video")])
        self.assertEqual(page.items[1]["text"], "")
        self.assertEqual(page.items[0]["permalink"], "https://social.example.org/@studio/5")
        self.assertEqual((page.skipped, page.next_cursor, page.more), (4, "00", True))     # private, direct, empty and junk

    def test_without_a_token_the_read_is_public_and_the_session_token_stays_on_its_own_server(self):
        wire = Wire(ok([]))
        page = read("mastodon", wire, account=self.ACCOUNT, token=None)
        self.assertNotIn("headers", wire.calls[0])
        self.assertEqual((page.more, page.next_cursor), (False, None))
        session = json.dumps({"v": 1, "at": "bearer-123", "instance": "social.example.org", "clientSecret": "must-not-leave"})
        wire = Wire(ok([]))
        read("mastodon", wire, account=self.ACCOUNT, token=session)
        self.assertEqual(wire.calls[0]["headers"], {"Authorization": "Bearer bearer-123"})
        self.assertNotIn("must-not-leave", json.dumps(wire.calls))
        elsewhere = json.dumps({"v": 1, "at": "bearer-123", "instance": "other.example.org"})
        wire = Wire()
        with self.assertRaises(R.ReaderHTTP):
            read("mastodon", wire, account=self.ACCOUNT, token=elsewhere)
        self.assertEqual(wire.calls, [])

    def test_only_a_public_server_name_is_ever_contacted(self):
        for account in ("1@localhost", "1@127.0.0.1", "1@intranet.internal", "1@", "no-server", "1@bad host.example.org",
                        "1@social.example.org/elsewhere", "1@social.example.org:8443"):
            wire = Wire()
            with self.subTest(account=account):
                with self.assertRaises(R.ReaderHTTP) as caught:
                    read("mastodon", wire, account=account)
                self.assertEqual((caught.exception.status, wire.calls), (400, []))
        wire = Wire()
        with self.assertRaises(AlphaError):          # resolves to a private address: nothing is sent, the importer retries later
            read("mastodon", wire, account=self.ACCOUNT, resolver=PRIVATE)
        self.assertEqual(wire.calls, [])

    def test_paging_without_a_link_header_uses_the_last_id_until_an_empty_page(self):
        page = read("mastodon", Wire(ok([self.status("9"), self.status("8")])), account=self.ACCOUNT)
        self.assertEqual((page.next_cursor, page.more), ("8", True))
        last = read("mastodon", Wire(ok([self.status("7")], headers={"link": '<https://social.example.org/x?min_id=7>; rel="prev"'})), account=self.ACCOUNT)
        self.assertEqual((last.next_cursor, last.more), (None, False))


class LinkedInTests(unittest.TestCase):
    URN = "urn:li:person:abc123"

    def test_goes_through_the_existing_gated_reader(self):
        wire = Wire(ok({"elements": [
            {"id": "urn:li:share:1", "author": self.URN, "lifecycleState": "PUBLISHED", "commentary": TEXT + " {hashtag|\\#|launch}", "publishedAt": 1790000000000},
            {"id": "urn:li:share:2", "author": self.URN, "lifecycleState": "PUBLISHED", "commentary": "Reshared words.", "reshareContext": {"parent": "urn:li:share:9"}},
            {"id": "urn:li:share:3", "author": "urn:li:person:someone", "lifecycleState": "PUBLISHED", "commentary": "Not this member."}],
            "paging": {"links": [{"rel": "next", "href": "/rest/posts?start=25"}]}}))
        page = read("linkedin", wire, account=self.URN)
        call = wire.calls[0]
        self.assertTrue(call["url"].startswith("https://api.linkedin.com/rest/posts?"))
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok")
        self.assertEqual([(i["externalId"], i["kind"], i["text"]) for i in page.items], [("urn:li:share:1", "original", TEXT + " #launch")])
        self.assertEqual((page.skipped, page.next_cursor, page.more), (2, "25", True))
        with self.assertRaises(R.ReaderHTTP):
            read("linkedin", Wire(), account="urn:li:organization:5")


if __name__ == "__main__":
    unittest.main()
