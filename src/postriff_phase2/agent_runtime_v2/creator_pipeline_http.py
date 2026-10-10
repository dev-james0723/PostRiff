"""Session/Origin/guard-authenticated native Creator Pipeline routes."""
from postriff_alpha.domain import AlphaError
from . import creator_pipeline as pipeline


def handle(app, environ, start_response, runtime, token, method, workspace_id, rest):
    if not rest and method == 'GET':
        return app._json(start_response, 200, pipeline.listing(runtime, workspace_id, token))
    if rest == ['preview'] and method == 'POST':
        return app._json(start_response, 200, pipeline.preview(runtime, workspace_id, token, app._body(environ)))
    if rest == ['create'] and method == 'POST':
        return app._json(start_response, 201, pipeline.create(runtime, workspace_id, token, app._body(environ)))
    raise AlphaError('Creator Pipeline route unavailable.', 404)
