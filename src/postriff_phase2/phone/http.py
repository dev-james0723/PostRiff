"""Phone HTTP endpoints under the existing hosted auth/origin guard. Webhooks authenticate separately."""
from urllib.parse import parse_qs

from postriff_alpha.domain import AlphaError

from ..agent_runtime_v2.api_guard import require_session_token
from . import contracts, inbound, call_auth, store, webhooks


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
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        value = store.call(cur, call_id, lock=True)
        if not value or value['provider'] != provider.name or (value['provider_call_ref'] and value['provider_call_ref'] != ref):
            raise AlphaError('Call unavailable.', 404)
        bypass_amd = (
            value.get('destination_ref') == 'james_env'
            and str(service.config.values.get('JAMES_DAILY_CALL_ACCEPTANCE_BYPASS_AMD', '')).lower() in ('1','true','yes','on')
        )
        voicemail = False if bypass_amd else answered_by != 'human'
        cur.execute('UPDATE public.pr_phone_calls SET provider_call_ref=coalesce(provider_call_ref,%s) WHERE id=%s', (ref, call_id))
        if value['state'] in contracts.TERMINAL or value['state'] == 'ending' or not service.config.enabled('RAFII_PHONE_ENABLED'):
            return provider.answer_xml(call_id, voicemail=True)
        if not voicemail:
            from ..agent_team_decision import record_verified_human_answer
            record_verified_human_answer(cur,value,provider=provider,call_ref=ref,answered_by=answered_by,
                                         amd_bypassed=bool(bypass_amd),observed_at=service.clock())
            store.set_state(cur, value, 'answered')
        db.commit()
    if voicemail:
        service.finish(call_id, 'voicemail')
    return provider.answer_xml(call_id, voicemail=voicemail)


def public(app, environ, start_response, method, path):
    if path == '/api/phone/dial/events' and method == 'POST':
        return dial_events(app, environ, start_response)
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


def dial_events(app, environ, start_response):
    import json
    service = phone_for(app._runtime())
    provider = service.provider
    try:
        size = int(environ.get('CONTENT_LENGTH') or 0)
    except ValueError:
        raise AlphaError('Invalid phone webhook.',400) from None
    if not 0 < size <= 65536:
        raise AlphaError('Phone webhook is too large.',413)
    raw = environ['wsgi.input'].read(size)
    url, signature = service.config.base_url + '/api/phone/dial/events', environ.get('HTTP_X_DIAL_SIGNATURE','')
    if not (provider and provider.name == 'dial' and provider.verify_webhook(url, {'_raw':raw}, signature)):
        raise AlphaError('Invalid phone webhook signature.',401)
    try:
        event = json.loads(raw)
        if not isinstance(event,dict) or event.get('id') != environ.get('HTTP_X_DIAL_EVENT_ID') or event.get('type') != environ.get('HTTP_X_DIAL_EVENT_TYPE'):
            raise ValueError('Invalid event envelope')
        event['_raw'] = raw
    except (ValueError,TypeError):
        raise AlphaError('Invalid phone event.',400) from None
    if event.get('type') == 'webhook.ping':
        return app._json(start_response,200,{'verified':True})
    try:
        normalized = provider.normalize_event(event)
    except (ValueError,TypeError,KeyError,AttributeError):
        raise AlphaError('Invalid phone event.',400) from None
    with service.hosted.connection_factory() as db,db.cursor() as cur:
        cur.execute('SELECT id::text FROM public.pr_phone_calls WHERE provider=\'dial\' AND provider_call_ref=%s',(normalized.call_ref,))
        bound = cur.fetchone()
    if not bound:
        if normalized.direction == 'inbound':
            # No account is available before keypad authentication. Unauthenticated calls never gain a ledger identity.
            if normalized.state in contracts.TERMINAL:
                inbound.ended(service, normalized.call_ref)
            return app._json(start_response, 200, {'ignored': True})
        # A callback may precede create's response or a lost response's cron reconciliation. Let Dial retry.
        raise AlphaError('Phone call binding is pending.',503)
    return app._json(start_response,200,webhooks.apply(service,bound[0],url,event,signature))


def handle(app, environ, start_response, hosted, token, method, parts):
    require_session_token(token)
    service = phone_for(hosted)
    workspace_id, rest = parts[2], parts[4:]
    result, status = None, 200
    if not rest and method=='GET':
        result = service.settings(workspace_id, token)
    elif rest==['provider-readiness'] and method=='GET':
        result = service.provider_readiness(workspace_id, token)
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
    elif rest==['trusted-callers'] and method=='GET':
        result = call_auth.trusted(service, workspace_id, token)
    elif len(rest)==3 and rest[0]=='trusted-callers' and rest[2]=='revoke' and method=='POST':
        body = app._body(environ)
        if not isinstance(body, dict):
            raise AlphaError('Send valid call verification options.', 400)
        result = call_auth.trusted(service, workspace_id, token, revoke=rest[1], proof_token=body.get('passkeyToken'))
    elif rest==['inbound-codes'] and method=='POST':
        result, status = inbound.issue(service, workspace_id, token, app._body(environ)), 201
    elif len(rest)==2 and rest[0]=='inbound-codes' and method=='GET':
        result = inbound.status(service, workspace_id, token, rest[1])
    elif len(rest)==2 and rest[0]=='inbound-codes' and method=='DELETE':
        result = inbound.revoke(service, workspace_id, token, rest[1])
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


def verify_call(app, environ, start_response, hosted, token, method, parts):
    require_session_token(token)
    service = phone_for(hosted)
    challenge = parts[3]
    if len(parts) == 4 and method == 'GET':
        result = call_auth.status(service, token, challenge)
    elif len(parts) == 5 and method == 'POST':
        action = parts[4]
        body = app._body(environ)
        if not isinstance(body, dict):
            raise AlphaError('Send valid call verification options.', 400)
        if action == 'approve':
            result = call_auth.approve(service, token, challenge, body)
        else:
            result = call_auth.dismiss(service, token, challenge, action)
    else:
        raise AlphaError('Call verification unavailable.', 404)
    return app._json(start_response, 200, result)
