"""Phone HTTP endpoints under the existing hosted auth/origin guard. Webhooks authenticate separately."""
from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from ..agent_runtime_v2.api_guard import require_session_token
from . import contracts, store, webhooks


def phone_for(hosted):
    if getattr(hosted, 'phone', None) is None:
        from .runtime import attach
        import os
        attach(hosted, os.environ)
    return hosted.phone


def form_body(environ):
    try:
        size = int(environ.get('CONTENT_LENGTH') or 0)
    except ValueError:
        raise AlphaError('Invalid phone webhook.', 400) from None
    if not 0 < size <= 65536:
        raise AlphaError('Phone webhook is too large.', 413)
    return parse_qs(environ['wsgi.input'].read(size).decode('utf-8'), keep_blank_values=True)


def answer(service, call_id, url, parameters, signature):
    provider = service.provider
    if not provider or provider.name != 'twilio' or not provider.verify_webhook(url, parameters, signature):
        raise AlphaError('Invalid phone webhook signature.', 401)
    ref = (parameters.get('CallSid') or [''])[0]
    import re
    if (parameters.get('AccountSid') or [''])[0] != provider.account or not re.fullmatch(r'CA[0-9a-fA-F]{32}',ref):
        raise AlphaError('Invalid provider call identity.',403)
    answered_by = (parameters.get('AnsweredBy') or ['unknown'])[0]
    voicemail = answered_by != 'human'
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        value = store.call(cur, call_id, lock=True)
        if not value or value['provider'] != provider.name or (value['provider_call_ref'] and value['provider_call_ref'] != ref):
            raise AlphaError('Call unavailable.', 404)
        cur.execute('UPDATE public.pr_phone_calls SET provider_call_ref=coalesce(provider_call_ref,%s) WHERE id=%s', (ref, call_id))
        if value['state'] in contracts.TERMINAL or value['state'] == 'ending' or not service.config.enabled('RAFII_PHONE_ENABLED'):
            return provider.answer_xml(call_id, voicemail=True)
        if not voicemail:
            store.set_state(cur, value, 'answered')
        db.commit()
    if voicemail:
        service.finish(call_id, 'voicemail')
    return provider.answer_xml(call_id, voicemail=voicemail)


def public(app, environ, start_response, method, path):
    parts = path.strip('/').split('/')
    if len(parts)!=4 or parts[:2]!=['api','phone'] or parts[2] not in ('webhooks','answer') or method!='POST':
        return None
    service = phone_for(app._runtime())
    parameters = form_body(environ)
    url = service.config.base_url + path
    signature = environ.get('HTTP_X_TWILIO_SIGNATURE', '')
    if parts[2]=='webhooks':
        return app._json(start_response, 200, webhooks.apply(service, parts[3], url, parameters, signature))
    body = answer(service, parts[3], url, parameters, signature).encode()
    start_response('200 OK', [('Content-Type','application/xml'),('Cache-Control','no-store'),('Content-Length',str(len(body)))])
    return [body]


def handle(app, environ, start_response, hosted, token, method, parts):
    require_session_token(token)
    service = phone_for(hosted)
    workspace_id, rest = parts[2], parts[4:]
    result, status = None, 200
    if not rest and method=='GET':
        result = service.settings(workspace_id, token)
    elif rest==['preferences'] and method=='PATCH':
        result = service.save_preferences(workspace_id, token, app._body(environ))
    elif rest==['verification'] and method=='POST':
        result = service.start_verification(workspace_id, token, app._body(environ))
    elif rest==['verification','confirm'] and method=='POST':
        result = service.confirm_verification(workspace_id, token, app._body(environ))
    elif rest==['number'] and method=='DELETE':
        result = service.delete_number(workspace_id, token)
    elif rest==['calls'] and method=='POST':
        result, status = service.request(workspace_id, token, app._body(environ)), 201
    elif len(rest)==2 and rest[0]=='calls' and method=='GET':
        result = service.view(workspace_id, token, rest[1])
    elif len(rest)==3 and rest[0]=='calls' and rest[2]=='end' and method=='POST':
        result = service.end(workspace_id, token, rest[1])
    elif rest==['schedules'] and method=='POST':
        result, status = service.save_schedule(workspace_id, token, app._body(environ)), 201
    elif len(rest)==2 and rest[0]=='schedules' and method=='DELETE':
        result = service.delete_schedule(workspace_id, token, rest[1])
    else:
        raise AlphaError('Phone route unavailable.', 404)
    return app._json(start_response, status, result)
