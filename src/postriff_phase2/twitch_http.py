"""Authenticated native routes and the byte-authenticated public EventSub route."""
from postriff_alpha.domain import AlphaError
from .twitch_eventsub import TwitchWebhookVerifier


def handle(app, environ, start_response, service, token, method, parts):
    twitch = service.twitch
    ws = parts[2]
    if len(parts) == 4 and method == 'GET':
        return app._json(start_response, 200, twitch.list_connections(ws, token))
    if len(parts) < 5:
        raise AlphaError('Twitch route unavailable.', 404)
    conn, tail = parts[4], parts[5:]
    if method == 'GET' and not tail:
        data = twitch.overview(ws, token, conn)
    elif method == 'POST' and tail == ['preview']:
        data = twitch.preview(ws, token, conn, app._body(environ))
    elif method == 'POST' and len(tail) == 2 and tail[0] == 'read':
        data = twitch.read(ws, token, conn, tail[1], app._body(environ))
    elif method == 'POST' and len(tail) == 3 and tail[0] == 'actions':
        identifier, operation = tail[1:]
        body = app._body(environ)
        if operation == 'approve':
            data = twitch.approve(ws, token, conn, identifier, body)
        elif operation in ('cancel', 'pause'):
            data = twitch.cancel(ws, token, conn, identifier, body, pause=operation == 'pause')
        elif operation == 'reconcile':
            data = twitch.reconcile(ws, token, conn, identifier, body)
        elif operation == 'secret-access':
            data = twitch.secret_access(ws, token, conn, identifier, body)
        else:
            raise AlphaError('Twitch action route unavailable.', 404)
    else:
        raise AlphaError('Twitch route unavailable.', 404)
    return app._json(start_response, 200, data)


def webhook(app, environ, start_response, service, identifier):
    try:
        length = int(environ.get('CONTENT_LENGTH') or '0')
    except (ValueError, TypeError):
        raise AlphaError('Invalid webhook length.', 400) from None
    if not 0 < length <= 262144:
        raise AlphaError('Webhook body exceeds the limit.', 413)
    raw = environ['wsgi.input'].read(length)
    if len(raw) != length:
        raise AlphaError('Incomplete webhook body.', 400)
    # WSGI joins repeated HTTP headers. A joined signature/type/id fails the pure
    # verifier; ingress must not silently choose one of repeated Twitch headers.
    headers = [(name, environ.get('HTTP_' + name.upper().replace('-', '_'), '')) for name in TwitchWebhookVerifier.REQUIRED]
    body, _duplicate = service.twitch.webhook(identifier, headers, raw)
    start_response('200 OK' if body else '204 No Content', [('Content-Type','text/plain; charset=utf-8'),
        ('Content-Length',str(len(body))),('Cache-Control','no-store'),('Referrer-Policy','no-referrer')])
    return [body]
