"""Native recipe settings; same interactive session and origin guards as agent routes."""
from postriff_alpha.domain import AlphaError
from .service import Recipes


def handle(app, environ, start_response, runtime, token, method, w, rest):
    domain = Recipes(runtime.service, runtime.cfg)
    if not rest and method == 'GET':
        return app._json(start_response, 200, domain.list(w, token))
    if not rest and method == 'POST':
        return app._json(start_response, 201, domain.save(w, token, app._body(environ)))
    if len(rest) == 1 and method == 'PUT':
        return app._json(start_response, 200, domain.save(w, token, app._body(environ), rest[0]))
    if len(rest) == 2 and method == 'GET' and rest[0] == 'reports':
        return app._json(start_response, 200, domain.report(w, token, rest[1]))
    if len(rest) == 2 and method == 'POST':
        body = app._body(environ)
        if rest[1] == 'enable':
            return app._json(start_response, 200, domain.enable(w, token, rest[0], body))
        if rest[1] == 'stop':
            return app._json(start_response, 200, domain.stop(w, token, rest[0], body))
        if rest[1] == 'run':
            return app._json(start_response, 200, domain.run(runtime, w, token, rest[0], body))
    raise AlphaError('Recipe route unavailable.', 404)
