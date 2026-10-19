"""Maintained AT Protocol SDK encoding with Rafii's existing bound DPoP transport.

The SDK never creates password sessions or makes independent HTTP requests. OAuth
and DNS-pinned egress remain in BlueskyProvider; this adapter is per account/call.
"""
import json
import re
from urllib.parse import urlencode
from postriff_alpha.domain import AlphaError

_NSID = re.compile(r'[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*){2,}\Z')


def invoke(provider, session, verb, nsid, *, params=None, body=None, data=None, content_type=None):
    from atproto_client.client.base import ClientBase
    from atproto_client.request import Response
    from atproto_client.models.dot_dict import DotDict
    if not isinstance(nsid, str) or not _NSID.fullmatch(nsid) or verb not in ('GET', 'POST'):
        raise AlphaError('Choose a supported Bluesky API method.', 400)
    endpoint = session['pds'].rstrip('/') + '/xrpc/' + nsid
    # ClientBase only delegates to this object. It has no login, password-session
    # refresh, hidden retry or HTTP pool that can bypass the approved transport.
    class BoundRequest:
        def finish(self, raw):
            return Response(200 <= raw.get('status', 0) < 300, raw.get('status', 0), raw.get('body'), raw.get('headers') or {})

        def get(self, *, url, params=None, **kwargs):
            if url != endpoint:
                raise AlphaError('The Bluesky SDK changed the bound endpoint.', 409)
            query = urlencode(params or {}, doseq=True)
            return self.finish(provider._dpop_get(url + ('?' + query if query else ''), session))

        def post(self, *, url, content=None, data=None, headers=None, **kwargs):
            if url != endpoint:
                raise AlphaError('The Bluesky SDK changed the bound endpoint.', 409)
            encoded_body = json.loads(content) if content is not None else None
            if content is None and isinstance(data, (dict, DotDict)):
                encoded_body, data = data.to_dict() if isinstance(data, DotDict) else data, None
            return self.finish(provider._xrpc_post_bound(session, url, body=encoded_body, data=data,
                                                       content_type=(headers or {}).get('content-type')))

    client = ClientBase(base_url=session['pds'], request=BoundRequest())
    if verb == 'GET':
        response = client.invoke_query(nsid, params=DotDict(params) if isinstance(params, dict) else params)
    else:
        payload = data if data is not None else DotDict(body) if isinstance(body, dict) else body
        response = client.invoke_procedure(nsid, data=payload,
                                           input_encoding=content_type or 'application/json')
    return {'status': response.status_code, 'body': response.content, 'headers': response.headers}


def link_facets(text, pattern):
    from atproto import client_utils
    builder, cursor = client_utils.TextBuilder(), 0
    for match in pattern.finditer(text):
        url = match.group(0).rstrip('.,;:!?)')
        builder.text(text[cursor:match.start()]).link(url, url)
        cursor = match.start() + len(url)
    builder.text(text[cursor:])
    if builder.build_text() != text:
        raise AlphaError('Bluesky rich text changed the approved wording.', 409)
    # Keep Rafii's previously approved wire shape, including optional $type fields.
    return [{'index': {'byteStart': f.index.byte_start, 'byteEnd': f.index.byte_end},
             'features': [{'$type': 'app.bsky.richtext.facet#link', 'uri': f.features[0].uri}]}
            for f in builder.build_facets()]


def valid_post(record):
    from atproto import models
    from pydantic import ValidationError
    try:
        models.AppBskyFeedPost.Record.model_validate(record, context={'strict_string_format': True})
    except (ValidationError, ValueError, TypeError):
        return False
    return True
