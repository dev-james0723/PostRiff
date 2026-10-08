"""Authenticated workspace routes; no tokens, upload URLs or stream keys in ordinary responses."""
from urllib.parse import parse_qs
from postriff_alpha.domain import AlphaError


def handle(app, environ, start_response, service, token, method, parts):
    workspace, connection = parts[2], parts[4]
    youtube = service.youtube
    tail = parts[5:]
    if tail and tail[0] == 'agent':
        from .agent import YouTubePublishingAgent
        agent = YouTubePublishingAgent(youtube)
        route = tail[1:]
        if method == 'GET' and route == []:
            data = agent.overview(workspace, token, connection)
        elif method == 'POST' and route == ['drafts']:
            data = agent.prepare(workspace, token, connection, app._body(environ))
        elif method == 'POST' and len(route) == 3 and route[0] == 'drafts' and route[2] == 'approve':
            data = agent.approve(workspace, token, connection, route[1], app._body(environ))
        elif method == 'POST' and route == ['policies', 'preview']:
            data = agent.policy_preview(workspace, token, connection, app._body(environ))
        elif method == 'POST' and len(route) == 3 and route[0] == 'policies' and route[2] in ('activate', 'pause', 'revoke'):
            data = agent.policy_action(workspace, token, connection, route[1], route[2], app._body(environ))
        else:
            raise AlphaError('This YouTube publishing-agent route is unavailable.', 404)
    elif method == 'GET' and tail == []:
        data = youtube.overview(workspace, token, connection)
    elif method == 'GET' and tail == ['actions']:
        data = youtube.actions(workspace, token, connection)
    elif method == 'POST' and tail == ['preview']:
        data = youtube.preview(workspace, token, connection, app._body(environ))
    elif method == 'POST' and len(tail) == 3 and tail[0] == 'actions' and tail[2] == 'approve':
        data = youtube.approve(workspace, token, connection, tail[1], app._body(environ))
    elif method == 'POST' and len(tail) == 3 and tail[0] == 'actions' and tail[2] == 'reconcile':
        app._body(environ)
        data = youtube.reconcile_action(workspace, token, connection, tail[1])
    elif method == 'POST' and len(tail) == 3 and tail[0] == 'actions' and tail[2] == 'stream-key':
        app._body(environ)
        data = youtube.stream_secret(workspace, token, connection, tail[1])
    elif method == 'POST' and tail == ['sensitive-authorization']:
        data = youtube.sensitive(workspace, token, connection, app._body(environ))
    elif method == 'POST' and tail == ['notifications', 'preview']:
        data = youtube.notifications.preview(workspace, token, connection, app._body(environ))
    elif method == 'POST' and len(tail) == 3 and tail[0] == 'notifications' and tail[2] == 'approve':
        data = youtube.notifications.approve(workspace, token, connection, tail[1], app._body(environ))
    elif method == 'POST' and tail == ['stream-configuration']:
        body = app._body(environ)
        data = youtube.stream_configuration(workspace, token, connection, body.get('streamId'))
    elif method == 'POST' and len(tail) == 3 and tail[0] == 'uploads' and tail[2] in ('review-recovery', 'resume'):
        body = app._body(environ)
        data = youtube.upload_recovery(workspace, token, connection, tail[1], body if tail[2] == 'resume' else None)
    elif method == 'POST' and len(tail) == 2 and tail[0] == 'read':
        data = youtube.read(workspace, token, connection, tail[1], app._body(environ))
    elif method == 'GET' and len(tail) == 1:
        query = {k: v[0] for k, v in parse_qs(environ.get('QUERY_STRING', '')).items()}
        data = youtube.read(workspace, token, connection, tail[0], query)
    else:
        raise AlphaError('This YouTube creator route is unavailable.', 404)
    return app._json(start_response, 200, data)


def notification_callback(app, environ, start_response, service, method, identifier):
    from .notifications import MAX_FEED_BYTES
    from .model import resource_id
    resource_id(identifier, 'resource')
    try:
        length = int(environ.get('CONTENT_LENGTH') or '0')
    except ValueError:
        raise AlphaError('Invalid notification length.', 400) from None
    if length < 0 or length > MAX_FEED_BYTES:
        raise AlphaError('Notification exceeds the feed limit.', 413)
    raw = environ['wsgi.input'].read(length) if method == 'POST' else b''
    body = service.youtube.notifications.callback(identifier, method, environ.get('QUERY_STRING', ''), raw,
                                                   environ.get('HTTP_X_HUB_SIGNATURE', '') or environ.get('HTTP_X_HUB_SIGNATURE_256', ''))
    start_response('200 OK' if method == 'GET' else '204 No Content',
                   [('Content-Type', 'text/plain; charset=utf-8'), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store')])
    return [body]
