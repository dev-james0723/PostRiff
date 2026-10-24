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
    """Official v2 lexicon shape: #account/#identity/#sync nest their fields under data[kind]."""
    return {"$type":"message", "payload":{"$type":"network.bsky.jetstream.subscribeEvents#"+kind,
            "seq":seq,"did":DID,"time":F.BEFORE, kind:{"seq":seq,"did":DID,"time":F.BEFORE, **kw}}}


def flat_marker(kind, seq=10, **kw):
    """The pre-fix (wrong) flat shape; it must never be read as an account decision."""
    return {"$type":"message", "payload":{"$type":"network.bsky.jetstream.subscribeEvents#"+kind,
            "seq":seq,"did":DID, **kw}}


def info(name):
    return {"$type":"message", "payload":{"$type":"network.bsky.jetstream.subscribeEvents#info", "name":name,
            "message":"synthetic advisory"}}


def stream_of(*frames):
    """Fake websockets.sync context manager returning frames, then the receive timeout."""
    stream = Mock(); stream.recv.side_effect = [json.dumps(f) for f in frames] + [TimeoutError()]
    context = Mock(); context.__enter__ = Mock(return_value=stream); context.__exit__ = Mock(return_value=False)
    return context


def handshake_rejection(status, body):
    """Pin websockets==16.1.1: a non-101 handshake raises InvalidStatus(Response)."""
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    return InvalidStatus(Response(status, "Bad Request", Headers({"Content-Type": "application/json"}), body))


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
        values=[marker("account",11,active=False,status="deactivated"),marker("identity",12,handle="fixture.bsky.social"),
                marker("sync",13,rev="3fixture"),
                {"$type":"message","payload":{"$type":"network.bsky.jetstream.subscribeEvents#info"}}]
        batch=self.fold(values)
        self.assertEqual([m["kind"] for m in batch.markers],["account","identity","sync","gap"])
        self.assertIs(batch.markers[0]["active"],False)
        self.assertEqual(batch.markers[0]["status"],"deactivated")
        self.assertEqual(batch.markers[1]["handle"],"fixture.bsky.social")
        self.assertTrue(batch.markers[2]["requires_reconciliation"])
        self.assertEqual(batch.cursor["sequence"],13);self.assertEqual(batch.completeness,"gap")
        self.assertEqual(batch.observations,())

    def test_v2_account_marker_reads_nested_account_object_not_flat_fields(self):
        nested=self.fold([marker("account",11,active=False,status="deleted")])
        self.assertIs(nested.markers[0]["active"],False)
        self.assertEqual(nested.markers[0]["status"],"deleted")
        active=self.fold([marker("account",11,active=True)])
        self.assertIs(active.markers[0]["active"],True)
        # The old flat fixture shape can no longer produce a revocation decision:
        # the envelope is unusable, so the fold stops before advancing past it.
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":10}
        flat=self.fold([flat_marker("account",11,active=False,status="deactivated")],cursor=cursor)
        self.assertEqual(flat.markers,())
        self.assertEqual(flat.cursor["sequence"],10)
        self.assertEqual(flat.quarantined,({"index":0,"reason_code":"jetstream_invalid_marker"},))
        for bad in (None,"deactivated",[False]):
            with self.subTest(account=bad):
                frame_=marker("account",11);frame_["payload"]["account"]=bad
                self.assertEqual(self.fold([frame_],cursor=cursor).cursor["sequence"],10)
        # Unknown status strings are not echoed; non-boolean active is not a decision.
        odd=self.fold([marker("account",11,active="false",status="x"*500)])
        self.assertIsNone(odd.markers[0]["active"]);self.assertIsNone(odd.markers[0]["status"])

    def test_identity_and_sync_markers_never_filtered_even_with_sparse_subobject(self):
        for kind in ("identity","sync"):
            with self.subTest(kind=kind):
                sparse=marker(kind,21);sparse["payload"].pop(kind)
                batch=self.fold([sparse])
                self.assertEqual([m["kind"] for m in batch.markers],[kind])
                self.assertEqual(batch.cursor["sequence"],21)

    def test_info_frames_map_lexicon_names_to_explicit_gap_reasons(self):
        batch=self.fold([info("OutdatedCursor"),info("FutureCursor"),info("SomethingNew"),frame(30)])
        self.assertEqual([(m["kind"],m["reason_code"]) for m in batch.markers],
                         [("gap","cursor_outdated"),("gap","cursor_future"),("gap","cursor_clamped")])
        self.assertEqual(batch.completeness,"gap");self.assertEqual(batch.cursor["sequence"],30)

    def test_inclusive_cursor_redelivery_then_record_poison_does_not_stall(self):
        # Production shape: the cursor's own event is re-sent first (inclusive v2
        # cursor), then a record-level poison. The cursor must move past it.
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":5}
        naive=frame(6,record={"$type":"app.bsky.feed.post","text":"x","createdAt":"2026-09-26T12:00:00","langs":["en"]})
        batch=self.fold([frame(5),naive,frame(7)],cursor=cursor)
        self.assertEqual([r["revision_sequence"] for r in batch.observations],[5,7])
        self.assertEqual(batch.quarantined,({"index":1,"reason_code":"timestamp_must_be_utc"},))
        self.assertEqual(batch.cursor["sequence"],7)
        self.assertEqual(batch.completeness,"gap")
        stuck={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":26613419375}
        poison=frame(26613419376,record={"$type":"app.bsky.feed.post","text":"x","createdAt":"not-a-time"})
        replay=self.fold([frame(26613419375),poison],cursor=stuck)
        self.assertEqual(replay.cursor["sequence"],26613419376)
        self.assertEqual(replay.quarantined,({"index":1,"reason_code":"invalid_timestamp"},))
        # The next inclusive redelivery starts at the poison itself and still advances.
        again=self.fold([poison,frame(26613419377)],cursor=replay.cursor)
        self.assertEqual(again.cursor["sequence"],26613419377)
        self.assertEqual([r["revision_sequence"] for r in again.observations],[26613419377])

    def test_record_level_failures_quarantine_with_precise_code_and_advance(self):
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":40}
        record=lambda **kw:{"$type":"app.bsky.feed.post","text":"ok","createdAt":F.BEFORE,"langs":["en"],**kw}
        cases=[("invalid_text_field",frame(41,record=record(text=123))),
               ("jetstream_invalid_record",frame(41,record=[])),
               ("jetstream_invalid_record",frame(41,record={**record(),"$type":"app.bsky.feed.like"})),
               ("jetstream_invalid_record",frame(41,rkey="../escape")),
               ("payload_limit",frame(41,record=record(text="😀"*15999))),
               ("invalid_text_field",frame(41,rev="r"*400)),
               ("invalid_timestamp",frame(41,record=record(createdAt=12345)))]
        for expected,poison in cases:
            with self.subTest(expected=expected,changes=sorted(poison["payload"])):
                batch=self.fold([poison,frame(42)],cursor=cursor)
                self.assertEqual(batch.quarantined,({"index":0,"reason_code":expected},))
                self.assertEqual(batch.cursor["sequence"],42)
                self.assertEqual([r["revision_sequence"] for r in batch.observations],[42])
                self.assertEqual(batch.health,"health_degraded")
                self.assertEqual(batch.completeness,"gap")

    def test_systemic_policy_failure_stops_instead_of_skipping_every_record(self):
        # A policy/clock-wide contract failure is not a poison record: advancing
        # would silently discard every post, so it keeps stop-before-advance.
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":40}
        batch=bluesky.fold_frames([frame(41),frame(42)],policy=bpolicy(),received_at=F.AFTER,available_at=NOW,
                                  coverage_epoch="fixture-epoch",cursor=cursor)
        self.assertEqual(batch.cursor["sequence"],40)
        self.assertEqual(batch.quarantined,({"index":0,"reason_code":"invalid_knowledge_or_retention_time"},))

    def test_envelope_failures_still_stop_before_advancing(self):
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":40}
        cases=[frame(41,did="https://example.com"),frame(None),frame(41,operation="purge"),
               frame(41,"delete",rkey="../escape"),
               {"$type":"message","payload":{"$type":"network.bsky.jetstream.subscribeEvents#mystery","seq":41,"did":DID}},
               None,{"broken":True}]
        for poison in cases:
            with self.subTest(poison=poison):
                batch=self.fold([poison,frame(42)],cursor=cursor)
                self.assertEqual(batch.cursor["sequence"],40)
                self.assertEqual(batch.observations,())
                self.assertEqual(batch.quarantined[0]["index"],0)

    def test_non_utc_offset_created_at_is_normalized_not_quarantined(self):
        cases={"2026-09-26T21:00:00+09:00":"2026-09-26T12:00:00Z","2026-09-26T08:00:00-04:00":"2026-09-26T12:00:00Z",
               # Already-UTC values stay byte-identical to the pre-fix behaviour.
               "2026-09-26T12:00:00.123456789Z":"2026-09-26T12:00:00.123456789Z",
               "2026-09-26T21:00:00.123456789+09:00":"2026-09-26T12:00:00.123456Z",
               "2026-09-26T17:30:00.5+05:30":"2026-09-26T12:00:00.500000Z",
               F.BEFORE:F.BEFORE, "2026-09-26T12:00:00.000Z":"2026-09-26T12:00:00.000Z"}
        for created,expected in cases.items():
            with self.subTest(created=created):
                value=frame(10,record={"$type":"app.bsky.feed.post","text":"x","createdAt":created,"langs":["en"]})
                batch=self.fold([value])
                self.assertEqual(batch.quarantined,())
                self.assertEqual(batch.observations[0]["event_at"],expected)
                self.assertEqual(batch.observations[0]["time_basis"],"provider_event")

    def test_langs_null_or_non_list_does_not_escape_fold(self):
        for langs,expected in ((None,"und"),("yue","und"),({"en":True},"und"),([1,None,["en"],"en"],"en"),([],"und")):
            with self.subTest(langs=langs):
                value=frame(10,record={"$type":"app.bsky.feed.post","text":"x","createdAt":F.BEFORE,"langs":langs})
                batch=self.fold([value])
                self.assertEqual(batch.quarantined,())
                self.assertEqual(batch.observations[0]["payload"]["language"],expected)

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

    def collect(self, connect, cursor=None, **kw):
        return bluesky.collect(policy=bpolicy(),enabled=True,entitlement_current=True,connect=connect,
                               cursor=cursor,seconds=kw.pop("seconds",5),**ARG_TIMES,**kw)

    def test_collect_requests_server_side_max_message_size_matching_client_limit(self):
        connect=Mock(return_value=stream_of(frame(21)))
        self.collect(connect)
        args,kw=connect.call_args;query=parse_qs(urlsplit(args[0]).query)
        self.assertEqual(query["maxMessageSizeBytes"],[str(kw["max_size"])])
        self.assertEqual(query["collections"],["app.bsky.feed.post"])
        self.assertNotIn("cursor",query)

    def test_cursor_too_old_reanchors_at_live_tip_with_explicit_gap(self):
        stale={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":26613419375}
        body=json.dumps({"error":"CursorTooOld","message":"floor 26700000000 SECRET-BODY"}).encode()
        connect=Mock(side_effect=[handshake_rejection(400,body),stream_of(frame(26800000001),frame(26800000002))])
        with self.assertNoLogs("postriff.trends",level="DEBUG"):
            batch=self.collect(connect,cursor=stale)
        self.assertEqual(connect.call_count,2)
        first=parse_qs(urlsplit(connect.call_args_list[0].args[0]).query)
        second=parse_qs(urlsplit(connect.call_args_list[1].args[0]).query)
        self.assertEqual(first["cursor"],["26613419375"]);self.assertNotIn("cursor",second)
        self.assertEqual(batch.markers[0],{"kind":"gap","reason_code":"cursor_too_old","previous_sequence":26613419375})
        self.assertEqual(batch.completeness,"gap");self.assertEqual(batch.health,"health_degraded")
        self.assertEqual(batch.reason_code,"stream_cursor_reanchored")
        self.assertEqual(batch.cursor,{"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":26800000002})
        self.assertEqual([r["revision_sequence"] for r in batch.observations],[26800000001,26800000002])
        self.assertNotIn("SECRET-BODY",repr(batch))
        # The reconnect stays inside the one admitted time budget.
        self.assertLessEqual(connect.call_args_list[1].kwargs["open_timeout"],5)

    def test_cursor_too_old_reanchor_with_empty_live_tip_records_gap_without_cursor(self):
        stale={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":100}
        connect=Mock(side_effect=[handshake_rejection(400,b'{"error":"CursorTooOld"}'),stream_of()])
        batch=self.collect(connect,cursor=stale)
        self.assertIsNone(batch.cursor)
        self.assertEqual(batch.markers,({"kind":"gap","reason_code":"cursor_too_old","previous_sequence":100},))
        self.assertEqual(batch.completeness,"gap")

    def test_other_handshake_status_raises_typed_transport_error_without_body(self):
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":20}
        for status,body in ((400,b'{"error":"InvalidRequest","message":"SECRET-BODY"}'),(400,b"SECRET-BODY not json"),
                            (400,b'{"error":"CursorTooOld"}'),(503,b"SECRET-BODY"),(429,b""),(404,b"{}")):
            with self.subTest(status=status,body=body):
                connect=Mock(side_effect=[handshake_rejection(status,body)])
                # CursorTooOld without a supplied cursor is not re-anchorable.
                use_cursor=None if b"CursorTooOld" in body else cursor
                with self.assertRaises(base.ProviderTransportError) as caught:
                    self.collect(connect,cursor=use_cursor)
                self.assertEqual(caught.exception.status,status)
                self.assertEqual(caught.exception.code,"provider_handshake_rejected")
                self.assertNotIn("SECRET",str(caught.exception)+repr(caught.exception.args))
                self.assertIsNone(caught.exception.__cause__)
                self.assertEqual(connect.call_count,1)

    def test_second_cursor_too_old_after_reanchor_is_not_retried_again(self):
        cursor={"host":bluesky.HOST,"protocol":bluesky.PROTOCOL,"sequence":20}
        rejection=lambda:handshake_rejection(400,b'{"error":"CursorTooOld"}')
        connect=Mock(side_effect=[rejection(),handshake_rejection(503,b"")])
        with self.assertRaises(base.ProviderTransportError) as caught:
            self.collect(connect,cursor=cursor)
        self.assertEqual(caught.exception.status,503);self.assertEqual(connect.call_count,2)

    def test_connection_failures_are_typed_transient_transport_errors(self):
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close
        for error in (OSError("SECRET-HOST unreachable"),TimeoutError("SECRET handshake timeout")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(base.ProviderTransportError) as caught:
                    self.collect(Mock(side_effect=[error]))
                self.assertIsNone(caught.exception.status)
                self.assertEqual(caught.exception.code,"provider_transport_unavailable")
                self.assertNotIn("SECRET",str(caught.exception))
        # A close before any frame is a typed failure carrying only the close code.
        closed=stream_of();closed.__enter__.return_value.recv.side_effect=ConnectionClosedError(Close(1009,"SECRET too big"),None)
        with self.assertRaises(base.ProviderTransportError) as caught:
            self.collect(Mock(return_value=closed))
        self.assertEqual(caught.exception.close_code,1009);self.assertIsNone(caught.exception.status)
        # A close after frames keeps the bounded partial sample instead of failing the job.
        partial=stream_of(frame(30));partial.__enter__.return_value.recv.side_effect=[json.dumps(frame(30)),
            ConnectionClosedError(Close(1011,"SECRET"),None)]
        batch=self.collect(Mock(return_value=partial))
        self.assertEqual(batch.cursor["sequence"],30)

    def test_undecodable_frame_stops_reading_and_is_quarantined_not_raised(self):
        context=stream_of();stream=context.__enter__.return_value
        stream.recv.side_effect=[json.dumps(frame(30)),"{not json SECRET",json.dumps(frame(31))]
        batch=self.collect(Mock(return_value=context))
        self.assertEqual(batch.cursor["sequence"],30)
        self.assertEqual(batch.quarantined,({"index":1,"reason_code":"jetstream_invalid_frame"},))
        self.assertEqual(stream.recv.call_count,2)


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
