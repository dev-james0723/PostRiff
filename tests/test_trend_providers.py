"""Synthetic adapter/frontier adversarial tests; no live HTTP, DNS or WebSocket calls.

Acceptance anchors: T01/T02/T03/T07/T09/T11/T13/T26/T32.
"""
import copy
import io
import json
import socket
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import test_trend_contracts as F
from postriff_phase2.growth.trends import contracts as C, discovery
from postriff_phase2.growth.trends.providers import base, bluesky, mastodon, web

NOW = F.NOW
ARG_TIMES = dict(received_at=NOW, available_at=NOW, coverage_epoch="fixture-epoch")
DID = "did:plc:abcdefghijklmnopqrstuvwx"


def bpolicy(**kw):
    return F.policy(provider_id="bluesky", operation="live_sample", price_ref=None, **kw)


def frame(seq=10, op="create", **changes):
    data = {"$type":"network.bsky.jetstream.subscribeEvents#commit", "seq":seq,
            "did":DID, "collection":"app.bsky.feed.post", "rkey":"3fixturekey", "operation":op,
            "rev":"revision-"+str(seq), "record":{"$type":"app.bsky.feed.post", "text":"喺度 write 😎 #音樂",
            "createdAt":F.BEFORE, "langs":["yue"]}}
    if op == "delete": data.pop("record")
    data.update(changes)
    return {"$type":"message", "payload":data}


def marker(kind, seq=10, **kw):
    return {"$type":"message", "payload":{"$type":"network.bsky.jetstream.subscribeEvents#"+kind,
            "seq":seq,"did":DID, **kw}}


def status(id="101", **changes):
    data = {"id":id,"uri":"https://social.example/users/fixture/statuses/"+id,
            "url":"https://social.example/@fixture/"+id,"visibility":"public", "created_at":F.BEFORE,
            "content":"<p>喺度 <strong>write</strong> &amp; 樂<img alt='🎹' src='ignored'></p>",
            "account":{"uri":"https://social.example/users/fixture"}, "language":"yue",
            "replies_count":0,"reblogs_count":None,"favourites_count":5}
    data.update(changes); return data


class BlueskyV2(F.OfflineTest):
    def fold(self, frames, **kw):
        return bluesky.fold_frames(frames, policy=bpolicy(), **ARG_TIMES, **kw)

    def test_create_update_delete_preserve_identity_and_native_sequence(self):
        rows=[]
        for seq, op in ((10,"create"),(11,"update"),(12,"delete")):
            with self.subTest(operation=op):
                row, mark, sequence = bluesky.normalize_frame(frame(seq,op),policy=bpolicy(),**ARG_TIMES)
                self.assertEqual(sequence,seq);self.assertIsNone(mark)
                self.assertEqual(row["revision_sequence"],seq);self.assertEqual(row["operation"],op)
                self.assertEqual(row["source_identity"],f"at://{DID}/app.bsky.feed.post/3fixturekey")
                rows.append(row)
        self.assertEqual(len({r["source_identity"] for r in rows}),1)
        self.assertEqual(len({r["observation_id"] for r in rows}),3)
        self.assertNotIn("text",rows[-1]["payload"])

    def test_v1_timestamp_cursor_frame_is_rejected_not_reinterpreted(self):
        legacy={"did":DID,"time_us":12345,"kind":"commit","commit":{"operation":"create"}}
        self.reject(bluesky.normalize_frame,legacy,policy=bpolicy(),**ARG_TIMES)
        batch=self.fold([legacy]);self.assertEqual(batch.observations,())
        self.assertEqual(batch.completeness,"gap");self.assertIsNone(batch.cursor)

    def test_sequence_is_integer_positive_63_bit(self):
        for seq in (None,0,-1,True,1.5,"10",2**63):
            with self.subTest(seq=seq): self.reject(bluesky.normalize_frame,frame(seq),policy=bpolicy(),**ARG_TIMES)

    def test_account_identity_sync_and_gap_markers_not_filtered(self):
        values=[marker("account",11,active=False,status="deactivated"),marker("identity",12),marker("sync",13),
                {"$type":"message","payload":{"$type":"network.bsky.jetstream.subscribeEvents#info"}}]
        batch=self.fold(values)
        self.assertEqual([m["kind"] for m in batch.markers],["account","identity","sync","gap"])
        self.assertFalse(batch.markers[0]["active"])
        self.assertTrue(batch.markers[2]["requires_reconciliation"])
        self.assertEqual(batch.cursor["sequence"],13);self.assertEqual(batch.completeness,"gap")
        self.assertEqual(batch.observations,())

    def test_replayed_duplicate_deduplicated_but_revision_order_preserved(self):
        delete,old=frame(30,"delete"),frame(10,"create")
        batch=self.fold([delete,old,copy.deepcopy(old)])
        self.assertEqual([r["revision_sequence"] for r in batch.observations],[30,10])
        self.assertEqual(batch.observations[0]["operation"],"delete")
        self.assertEqual(batch.cursor["sequence"],30)
        self.assertEqual(len(batch.observations),2)

    def test_broken_frame_stops_before_advancing_past_gap(self):
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":5}
        batch=self.fold([frame(10),{"broken":True},frame(30)],cursor=cursor)
        self.assertEqual(batch.cursor["sequence"],10)
        self.assertEqual([r["revision_sequence"] for r in batch.observations],[10])
        self.assertEqual(batch.quarantined[0]["index"],1)
        self.assertEqual(batch.health,"health_degraded")

    def test_cross_host_protocol_and_untyped_cursor_rejected(self):
        good={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":5}
        for cursor in (dict(good,host="other.example"),dict(good,protocol="v1"),dict(good,sequence="5"),dict(good,sequence=True)):
            with self.subTest(cursor=cursor): self.reject(self.fold,[frame()],cursor=cursor)

    def test_item_byte_bounds_do_not_claim_complete_window(self):
        batch=self.fold([frame(10),frame(11)],max_items=1)
        self.assertEqual(len(batch.observations),1);self.assertEqual(batch.cursor["sequence"],10)
        self.assertEqual(batch.completeness,"partial")
        self.reject(self.fold,[frame()],max_bytes=1)
        self.reject(self.fold,[frame()],max_items=251)

    def test_nonpost_collection_advances_valid_sequence_without_fake_post(self):
        batch=self.fold([frame(10,collection="app.bsky.feed.like")])
        self.assertEqual(batch.observations,());self.assertEqual(batch.cursor["sequence"],10)

    def test_raw_right_unknown_keeps_source_metadata_without_text(self):
        row,_,_=bluesky.normalize_frame(frame(),policy=bpolicy(rights=F.permissions(store_raw="unknown")),**ARG_TIMES)
        self.assertNotIn("text",row["payload"])
        self.assertEqual(row["source_identity"],f"at://{DID}/app.bsky.feed.post/3fixturekey")

    def test_malformed_record_and_identity_are_safe_errors(self):
        for changes in ({"rkey":"../../oops"},{"record":[]},{"did":None},{"did":"https://example.com"}):
            with self.subTest(changes=changes): self.reject(bluesky.normalize_frame,frame(**changes),policy=bpolicy(),**ARG_TIMES)

    def test_disabled_or_unentitled_collect_never_connects(self):
        for enabled,entitled in ((False,True),(True,False)):
            connect=Mock(side_effect=AssertionError("dispatch forbidden"))
            self.reject(bluesky.collect,policy=bpolicy(),enabled=enabled,entitlement_current=entitled,
                        connect=connect,**ARG_TIMES)
            connect.assert_not_called()

    def test_bounded_collect_uses_v2_sequence_and_subprotocol_with_fake_stream(self):
        stream=Mock();stream.recv.side_effect=[json.dumps(frame(21)),TimeoutError()]
        context=Mock();context.__enter__=Mock(return_value=stream);context.__exit__=Mock(return_value=False)
        connect=Mock(return_value=context)
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":20}
        batch=bluesky.collect(policy=bpolicy(),enabled=True,entitlement_current=True,connect=connect,
                              cursor=cursor,seconds=1,**ARG_TIMES)
        args,kw=connect.call_args;query=parse_qs(urlsplit(args[0]).query)
        self.assertEqual(query["cursor"],["20"])
        self.assertEqual(kw["subprotocols"],["xrpc.v1.json"]);self.assertIsNone(kw["proxy"])
        self.assertEqual(batch.cursor["sequence"],21)


class MastodonAdapter(F.OfflineTest):
    def collect(self, rows, *, cursor=None, **changes):
        transport=Mock();transport.get.return_value=(rows,{},100)
        args=dict(instance="https://social.example",policy=F.policy(provider_id="mastodon",operation="public_timeline",price_ref=None),
                  enabled=True,entitlement_current=True,transport=transport,cursor=cursor,**ARG_TIMES)
        args.update(changes)
        return mastodon.collect(**args),transport

    def test_public_html_original_and_nullable_metrics(self):
        batch,_=self.collect([status()]);row=batch.observations[0];p=row["payload"]
        self.assertEqual(p["text"],"喺度 write & 樂🎹")
        self.assertEqual(p["language"],"yue");self.assertEqual(row["source_identity"],status()["uri"])
        self.assertEqual(p["provider_metrics"]["replies_count"]["value"],0)
        self.assertIsNone(p["provider_metrics"]["reblogs_count"]["value"])
        self.assertEqual(p["provider_metrics"]["reblogs_count"]["null_reason"],"not_returned")
        self.assertEqual(batch.completeness,"partial")

    def test_nonpublic_visibility_is_quarantined(self):
        for visibility in ("private","direct","unlisted",None):
            with self.subTest(visibility=visibility):
                batch,_=self.collect([status(visibility=visibility)])
                self.assertEqual(batch.observations,());self.assertTrue(batch.quarantined)

    def test_edit_and_reblog_metadata_do_not_invent_original_event_time(self):
        original=status();edited=status(edited_at=NOW,reblog={"id":"original"})
        before=mastodon.normalize_status(original,policy=F.policy(),**ARG_TIMES)
        after=mastodon.normalize_status(edited,policy=F.policy(),**ARG_TIMES)
        self.assertEqual(after["operation"],"update");self.assertEqual(after["event_at"],F.BEFORE)
        self.assertGreater(after["revision_sequence"],before["revision_sequence"])
        self.assertTrue(after["payload"]["is_repost"])

    def test_malformed_page_never_advances_cursor_past_unstored_item(self):
        cursor={"host":"social.example","protocol":mastodon.VERSION,"max_id":"200"}
        batch,_=self.collect([status("199"),status("198",visibility="private"),status("197")],cursor=cursor)
        # An uncommitted/skipped source row cannot be silently acknowledged.
        self.assertEqual(batch.cursor,cursor)
        self.assertEqual(batch.completeness,"gap")

    def test_nonobject_page_item_is_quarantined_without_attribute_error(self):
        cursor={"host":"social.example","protocol":mastodon.VERSION,"max_id":"200"}
        batch,_=self.collect([None],cursor=cursor)
        self.assertTrue(batch.quarantined);self.assertEqual(batch.cursor,cursor)

    def test_page_item_limit_and_bad_cursor_rejected(self):
        self.reject(self.collect,[status(str(n)) for n in range(41)])
        for cursor in ({"host":"other.example","protocol":mastodon.VERSION},
                       {"host":"social.example","protocol":mastodon.VERSION,"max_id":"x;delete"}):
            with self.subTest(cursor=cursor): self.reject(self.collect,[],cursor=cursor)

    def test_disabled_transport_not_called(self):
        transport=Mock(side_effect=AssertionError("dispatch forbidden"))
        self.reject(mastodon.collect,instance="https://social.example",policy=F.policy(provider_id="mastodon",operation="public_timeline"),
                    enabled=False,entitlement_current=True,transport=transport,**ARG_TIMES)
        transport.get.assert_not_called()

    def test_unknown_raw_and_metric_grants_strip_payload(self):
        p=F.policy(provider_id="mastodon",operation="public_timeline",price_ref=None,
                   rights=F.permissions(store_raw="unknown",store_metrics="unknown"))
        batch,_=self.collect([status()],policy=p)
        self.assertNotIn("text",batch.observations[0]["payload"])
        self.assertNotIn("provider_metrics",batch.observations[0]["payload"])


class WebAdapter(F.OfflineTest):
    def collect(self, result, **changes):
        broker=Mock();broker.search_items.return_value=result
        args=dict(broker=broker,query="synthetic topic",policy=F.policy(provider_id="web",operation="corroborate"),
                  enabled=True,entitlement_current=True,reservation_microusd=50,workspace_consent=True,
                  scope_context={"workspace_id":F.WORKSPACE},resolve_urls=False,**ARG_TIMES)
        args.update(changes)
        return web.collect(**args),broker

    def test_leads_never_turn_search_rank_or_provider_counts_into_mentions(self):
        result={"status":"ok","items":[{"url":"https://example.com/a","snippet":"original words",
                 "rank":1,"mention_count":9000,"engagement":555,"provenance":{"injectionFlags":[{"rule":"fixture-injection"}]}}]}
        batch,_=self.collect(result);row=batch.observations[0]
        self.assertEqual(row["kind"],"search_lead");self.assertIsNone(row["event_at"])
        self.assertEqual(row["time_basis"],"retrieval")
        for key in ("rank","mention_count","engagement","author_key"): self.assertNotIn(key,row["payload"])
        self.assertEqual(row["provenance"]["injection_flags"],["fixture-injection"])
        self.assertEqual(batch.completeness,"partial")

    def test_failed_search_is_gap_not_zero_observations_proof(self):
        batch,_=self.collect({"status":"denied","items":[]})
        self.assertEqual(batch.health,"unavailable");self.assertEqual(batch.completeness,"gap")

    def test_consent_and_disabled_queries_never_reach_broker(self):
        for kwargs in ({"workspace_consent":False},{"enabled":False},{"entitlement_current":False},
                       {"reservation_microusd":0},{"query":"hello\nAuthorization: secret"}):
            with self.subTest(kwargs=kwargs):
                broker=Mock()
                self.reject(self.collect,{"status":"ok"},broker=broker,**kwargs)
                broker.search_items.assert_not_called()

    def test_poisoned_url_is_quarantined_not_echoed_into_evidence(self):
        batch,_=self.collect({"status":"ok","items":[{"url":"https://127.0.0.1/secrets","text":"secret"}]})
        self.assertEqual(batch.observations,());self.assertTrue(batch.quarantined)

    def test_web_items_shape_and_oversized_arrays_fail_closed(self):
        for items in ({"url":"https://example.com"},[None], [{"url":"https://example.com/a"}]*7):
            with self.subTest(items_type=type(items).__name__,length=len(items)):
                self.reject(self.collect,{"status":"ok","items":items})

    def test_scope_context_cannot_select_another_workspace(self):
        broker=Mock()
        self.reject(self.collect,{"status":"ok"},broker=broker,scope_context={"workspace_id":F.OTHER})
        broker.search_items.assert_not_called()


class SafeTransportAndFrontier(F.OfflineTest):
    def test_ssrf_literals_userinfo_ports_protocols_and_internal_names(self):
        urls=["http://example.com","file:///etc/passwd","https://user:password@example.com/",
              "https://127.0.0.1/","https://[::1]/","https://169.254.169.254/","https://10.0.0.1/",
              "https://192.168.1.1/","https://localhost/","https://a.local/","https://metadata.google.internal/",
              "https://example.com:8080/","https://[::ffff:127.0.0.1]/"]
        for url in urls:
            with self.subTest(url=url): self.reject(base.safe_url,url,resolve=False)

    def test_dns_resolution_checks_all_addresses_and_does_not_connect(self):
        answer=[(socket.AF_INET,socket.SOCK_STREAM,6,"",("93.184.216.34",443)),
                (socket.AF_INET,socket.SOCK_STREAM,6,"",("10.0.0.2",443))]
        with patch.object(base.socket,"getaddrinfo",return_value=answer) as dns:
            self.reject(base.safe_url,"https://example.com/a")
            dns.assert_called_once()

    def test_host_allowlist_and_canonical_url(self):
        self.reject(base.safe_url,"https://evil.example/a",allowed_hosts=frozenset({"example.com"}),resolve=False)
        self.assertEqual(base.safe_url("https://EXAMPLE.COM/a?q=b#fragment",resolve=False),"https://example.com/a?q=b")

    def test_redirect_is_rejected_including_to_private_address(self):
        self.reject(base._NoRedirect().redirect_request,None,None,302,"redirect",{},"https://127.0.0.1/")

    def test_transport_rejects_nan_and_oversize_without_real_network(self):
        for data,limit in ((b'{"n":NaN}',100),(b'{"n":Infinity}',100),(b'{}'+b' '*100,10),(b'not-json',100)):
            with self.subTest(data=data[:20]):
                response=io.BytesIO(data);response.headers={}
                opener=Mock();opener.open.return_value=response
                with patch.object(base,"safe_url",return_value="https://example.com"), \
                     patch.object(base.urllib.request,"build_opener",return_value=opener):
                    self.reject(base.JsonTransport(frozenset({"example.com"})).get,"https://example.com",max_bytes=limit,timeout=1)

    def test_failure_classes_keep_unknown_counts_and_bounded_retries(self):
        for status in (400,401,402,403,404,413,422,429,500,None):
            with self.subTest(status=status):
                failure=base.failure(status,retry_after=999999)
                self.assertIsNone(failure["count"]);self.assertEqual(failure["coverage"],"gap")
                self.assertLessEqual(failure["retry_after_seconds"],86400)
                if status in (400,401,402,403,404,413,422): self.assertFalse(failure["retryable"])

    def request(self,query="new conversation",**changes):
        args=dict(scope_key=F.SCOPE,provider_id="fixture",route="watch",query=query,coverage_epoch="v1",
                  policy_version="fixture-v1",window_start=F.BEFORE,window_end=NOW)
        args.update(changes);return discovery.DiscoveryRequest(**args)

    def test_query_injection_urls_control_chars_and_invalid_sampling(self):
        for query in ("https://127.0.0.1", "x; rm -rf", "<script>", "`tool`", "cookie:secret", "a\nb", "x"*301):
            with self.subTest(query=query): self.reject(self.request,query)
        for p in (0,-1,2,float("nan"),float("inf")):
            with self.subTest(probability=p): self.reject(self.request,sampling_probability=p)

    def test_expansion_depth_child_limit_dedup_and_private_scope(self):
        parent=self.request();children=discovery.children(parent,["one"," ONE ","two","three","four","five","six"])
        self.assertEqual(len(children),5)
        self.assertEqual([c.query for c in children],["one","two","three","four","five"])
        for child in children:
            self.assertEqual(child.scope_key,F.SCOPE);self.assertEqual(child.parent_id,parent.id);self.assertEqual(child.depth,1)
        self.assertEqual(discovery.children(replace(parent,depth=2),["never"]),[])

    def test_keyword_independent_exploration_and_deletion_first_budget(self):
        request=discovery.exploration(scope_key=F.SCOPE,provider_id="fixture",policy_version="v1",coverage_epoch="e1",
                                      window_start=F.BEFORE,window_end=NOW)
        self.assertEqual(request.query,"");self.assertEqual(request.route,"keyword_independent_sample")
        for budget,deletion,watch in ((100,0,0),(5,5,100),(5,2,10),(0,0,0)):
            with self.subTest(budget=budget,deletion=deletion):
                a=discovery.allocation(budget,deletion_units=deletion,required_watch_units=watch)
                self.assertEqual(sum(a[k] for k in ("deletion","watch","corroboration","exploration")),budget)
                self.assertEqual(a["deletion"],min(budget,deletion))
        self.reject(discovery.allocation,True)


if __name__ == "__main__": unittest.main()
