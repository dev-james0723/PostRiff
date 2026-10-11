"""Official gRPC streaming with durable cursors; bounded REST fallback honors Google's interval."""
import hashlib
import json
from postriff_alpha.domain import AlphaError
from .model import api_error, YouTubeError


def streaming_batch(api, chat_id, cursor):
    import grpc
    from google.protobuf.json_format import MessageToDict
    from . import stream_list_pb2, stream_list_pb2_grpc
    with grpc.secure_channel('youtube.googleapis.com:443', grpc.ssl_channel_credentials()) as channel:
        stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)
        request = stream_list_pb2.LiveChatMessageListRequest(live_chat_id=chat_id, part=['snippet', 'authorDetails'])
        if cursor:
            request.page_token = cursor
        call = stub.StreamList(request, metadata=(('authorization', 'Bearer ' + api.provider.bearer(api.grant['accessToken'])),), timeout=8)
        try:
            response = next(iter(call))
            body = MessageToDict(response)
            # The official gRPC enum spelling differs from the REST JSON spelling.
            for item in body.get('items', []):
                snippet = item.get('snippet', {})
                if isinstance(snippet.get('type'), str):
                    words = snippet['type'].lower().split('_')
                    snippet['type'] = words[0] + ''.join(w.title() for w in words[1:])
            return body
        except StopIteration:
            return {'items': [], 'nextPageToken': cursor}
        except grpc.RpcError as error:
            if error.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                return {'items': [], 'nextPageToken': cursor, 'streamTimeout': True}
            codes = {grpc.StatusCode.UNAUTHENTICATED: 401, grpc.StatusCode.PERMISSION_DENIED: 403,
                     grpc.StatusCode.RESOURCE_EXHAUSTED: 429, grpc.StatusCode.NOT_FOUND: 404}
            raise api_error({'status': codes.get(error.code(), 503)}, 'liveChatMessages.streamList', api.clock()) from None
        finally:
            call.cancel()


def read_chat(service, workspace, connection, api, query):
    chat_id = query['liveChatId']
    key = (workspace, connection, 'live-chat:' + chat_id)
    with service.journal.lock(key):
        with service.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT next_page_token,extract(epoch from next_read_at)::float8,seen_ids FROM public.pr_youtube_chat_cursor WHERE workspace_id=%s AND connection_id=%s AND live_chat_id=%s', (workspace, connection, chat_id))
            row = cur.fetchone()
        cursor, due, seen = row if row else (None, 0, [])
        if due and due > service.clock():
            return {'source': 'YouTube Live Streaming API', 'items': [], 'nextReadAt': due, 'deferred': True}
        injected = getattr(api.provider, 'chat_stream_transport', None)
        try:
            api.account_usage('liveChatMessages.streamList', 'general', None)  # no invented cost for a streaming connection
            body = injected(api, chat_id, cursor) if injected else streaming_batch(api, chat_id, cursor)
            transport = 'official-grpc-streamList'
        except ImportError:
            body = api.call('liveChatMessages.list', {'liveChatId': chat_id, 'part': 'snippet,authorDetails', 'maxResults': 200, **({'pageToken': cursor} if cursor else {})})
            transport = 'official-rest-list-fallback'
        except YouTubeError as error:
            api.on_error(error, 'liveChatMessages.streamList')
            raise
        items, known = [], {x['id']: x for x in seen if isinstance(x, dict) and x.get('id')}
        sequence = max((x.get('sequence', 0) for x in known.values()), default=0)
        for item in body.get('items', []):
            if item.get('snippet', {}).get('liveChatId') != chat_id or not item.get('id'):
                continue
            digest = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
            previous = known.get(item['id'])
            if previous and previous['digest'] == digest:
                continue
            sequence += 1
            items.append({**item, 'sequence': sequence, 'updatesExistingEvent': bool(previous)})
            known[item['id']] = {'id': item['id'], 'digest': digest, 'sequence': sequence}
        # For REST, Google's pollingIntervalMillis is authoritative. No aggressive browser polling.
        interval = max(5000, body.get('pollingIntervalMillis', 5000)) / 1000
        next_read = service.clock() + interval
        cursor = body.get('nextPageToken') or cursor
        retained = sorted(known.values(), key=lambda x: x['sequence'])[-10000:]
        with service.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('INSERT INTO public.pr_youtube_chat_cursor(workspace_id,connection_id,live_chat_id,next_page_token,next_read_at,seen_ids) VALUES(%s,%s,%s,%s,to_timestamp(%s),%s::jsonb) ON CONFLICT(workspace_id,connection_id,live_chat_id) DO UPDATE SET next_page_token=excluded.next_page_token,next_read_at=excluded.next_read_at,seen_ids=excluded.seen_ids,updated_at=now()', (workspace, connection, chat_id, cursor, next_read, json.dumps(retained)))
        previous = service._cached(workspace, connection, 'chat-events:' + chat_id) or {}
        merged = {item['id']: item for item in previous.get('items', []) + items if item.get('id')}
        service._cache(workspace, connection, 'chat-events:' + chat_id,
                       {'items': sorted(merged.values(), key=lambda x: x.get('sequence', 0))[-1000:], 'activePoll': body.get('activePollItem')}, 'YouTube Live Streaming API', 600)
        return {'source': 'YouTube Live Streaming API', 'transport': transport, 'items': items,
                'activePoll': body.get('activePollItem'), 'offlineAt': body.get('offlineAt'), 'nextReadAt': next_read,
                'streamTimeout': body.get('streamTimeout', False),
                'ordering': 'Official arrival order, durable cursor and event revision deduplication'}
