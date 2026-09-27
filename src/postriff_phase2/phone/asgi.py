"""Phone media host; the existing WSGI app continues serving text/browser voice unchanged.

Run with: uvicorn postriff_phase2.phone.asgi:create_app --factory --host 127.0.0.1 --port 4752 --no-access-log
Vercel uses api.phone:app with a media-only route and lazy, fail-closed initialization.
"""
import asyncio
import os

from postriff_alpha.domain import AlphaError

from . import contracts, store
from .session import PhoneSessionController, bridge
from .providers.twilio import TwilioMediaTransport


def create_lazy_app(*, values=None, application_factory=None):
    """Import/build/lifespan needs no credentials, database or provider connection.

    The deployment exposes only signed media; HTTP and cron remain on the existing API.
    An unavailable runtime refuses the upgrade without disclosing configuration errors.
    """
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    from .config import PhoneConfig

    delegate = None
    initialize = asyncio.Lock()

    async def media(socket):
        nonlocal delegate
        if not PhoneConfig(os.environ if values is None else values).enabled('RAFII_PHONE_ENABLED'):
            await socket.close(code=1008)
            return
        async with initialize:
            if delegate is None:
                try:
                    factory = application_factory or (lambda: create_app(media_only=True))
                    delegate = await asyncio.to_thread(factory)
                except Exception:
                    await socket.close(code=1008)
                    return
        await delegate(socket.scope, socket.receive, socket.send)

    return Starlette(routes=[WebSocketRoute('/api/phone/media/{call_id}', media),
                             WebSocketRoute('/api/phone/dial/media/{call_id}', media)])


def create_app(hosted=None, phone=None, live_connect=None, *, media_only=False):
    from starlette.applications import Starlette
    from starlette.middleware.wsgi import WSGIMiddleware
    from starlette.routing import Mount, WebSocketRoute
    from ..hosted_app import HostedApplication, runtime_from_environment
    from .runtime import attach
    if hosted is None:
        hosted,worker,auth=runtime_from_environment()
        wsgi=HostedApplication(hosted,worker,auth,os.environ.get('CRON_SECRET'))
    else:
        wsgi=HostedApplication(hosted)
    phone=phone or getattr(hosted,'phone',None) or attach(hosted,os.environ)

    async def media(socket):
        call_id=socket.path_params['call_id']
        provider=phone.provider
        signature=socket.headers.get('x-twilio-signature','')
        if not provider or provider.name!='twilio' or not provider.verify_media('/api/phone/media/'+call_id,signature):
            await socket.close(code=1008)
            return
        await socket.accept()
        controller=None
        try:
            async with asyncio.timeout(10):
                start=await socket.receive_json()
                if start.get('event')=='connected':
                    start=await socket.receive_json()
            meta=start.get('start') or {}
            if start.get('event')!='start' or meta.get('accountSid')!=provider.account or meta.get('mediaFormat')!={'encoding':'audio/x-mulaw','sampleRate':8000,'channels':1}:
                raise AlphaError('Invalid phone stream.',403)
            with hosted.connection_factory() as db,db.cursor() as cur:
                value=store.call(cur,call_id,lock=True)
                if not value or value['state']!='answered' or value['provider_call_ref']!=meta.get('callSid') or value['media_claimed_at']:
                    raise AlphaError('Phone stream unavailable.',403)
                cur.execute('UPDATE public.pr_phone_calls SET media_claimed_at=now() WHERE id=%s',(call_id,))
                db.commit()
            controller=PhoneSessionController(phone,call_id)
            transport=TwilioMediaTransport(socket,meta['streamSid'])
            if live_connect:
                async with live_connect() as connection:
                    await bridge(controller,transport,connection)
            else:
                from openai import AsyncOpenAI
                async with AsyncOpenAI(api_key=controller.runtime.cfg.credential('openai'),max_retries=0) as client:
                    async with client.live.connect() as connection:
                        await bridge(controller,transport,connection)
        except Exception:
            if controller:
                controller.closed=True
                await asyncio.to_thread(phone.hangup,call_id,reason='failed')
        finally:
            try:
                await socket.close()
            except RuntimeError:
                pass

    def claim_dial_stream(provider, call_ref, meta, *, accepted=False):
        call_id = provider.local_call_id(meta.get('instruction'))
        with hosted.connection_factory() as db, db.cursor() as cur:
            value = store.call(cur, call_id, lock=True)
            identity = store.number(cur, value['user_id']) if value else None
            if not (value and value['provider'] == 'dial' and value['state'] in ('dialing','ambiguous','ringing','answered') and
                    value['provider_call_ref'] in (None, call_ref) and not value['media_claimed_at'] and identity and
                    identity['verified'] and identity['hash'] == value['number_hash'] and
                    phone.vault.decrypt(identity['ciphertext'], identity['key_id']) == meta.get('to')):
                raise AlphaError('Phone stream unavailable.', 403)
            store.set_state(cur, value, 'answered')
            cur.execute('UPDATE public.pr_phone_calls SET provider_call_ref=%s,media_claimed_at=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s', (call_ref,accepted,call_id))
            db.commit()
        return call_id

    async def dial_media(socket):
        from .providers.dial import DialMediaTransport
        provider, call_ref = phone.provider, socket.path_params['call_id']
        if not (provider and provider.name == 'dial' and provider.configured and
                phone.config.enabled('RAFII_PHONE_ENABLED') and
                provider.verify_media(call_ref, socket.headers.get('x-dial-signature', ''))):
            await socket.close(code=1008)
            return
        await socket.accept()
        controller, transport, call_id = None, None, None
        try:
            import json
            async with asyncio.timeout(10):
                raw = await socket.receive_text()
            if len(raw) > 65536:
                raise ValueError('Dial frame too large')
            meta = json.loads(raw)
            if not (meta.get('type') == 'call_connected' and meta.get('call_id') == call_ref and
                    meta.get('direction') == 'outbound' and meta.get('from') == provider.originating_number and
                    meta.get('formats') == {'inbound':'mulaw_8000','outbound':'mulaw_8000'} and not meta.get('reconnect')):
                raise AlphaError('Invalid Dial phone stream.', 403)
            # Starts keepalive before DB/model initialization; never reinitialize a claimed call on reconnect.
            transport = DialMediaTransport(socket)
            call_id = await asyncio.to_thread(claim_dial_stream, provider, call_ref, meta)
            if not await transport.accept_call():
                await transport.end_call()
                await asyncio.to_thread(phone.hangup, call_id, live_seconds=0, reason='declined')
                await asyncio.to_thread(phone.record_live_usage, call_id, 0)
                return
            await asyncio.to_thread(claim_dial_stream, provider, call_ref, meta, accepted=True)
            controller = await asyncio.to_thread(PhoneSessionController, phone, call_id)
            if live_connect:
                async with live_connect() as connection:
                    await bridge(controller, transport, connection)
            else:
                from openai import AsyncOpenAI
                async with AsyncOpenAI(api_key=controller.runtime.cfg.credential('openai'),max_retries=0) as client:
                    async with client.live.connect() as connection:
                        await bridge(controller, transport, connection)
        except Exception:
            if controller:
                controller.closed = True
            try:
                if transport:
                    await transport.end_call()
                else:
                    await socket.send_json({'type':'end_call'})
            except Exception:
                pass
            if call_id:
                await asyncio.to_thread(phone.hangup, call_id, reason='failed', live_seconds=0 if controller is None else None)
                if controller is None:
                    await asyncio.to_thread(phone.record_live_usage, call_id, 0)
        finally:
            if transport:
                await transport.close()
            try:
                await socket.close()
            except RuntimeError:
                pass

    routes = [WebSocketRoute('/api/phone/media/{call_id}',media),
              WebSocketRoute('/api/phone/dial/media/{call_id}',dial_media)]
    if not media_only:
        routes.append(Mount('/',app=WSGIMiddleware(wsgi)))
    return Starlette(routes=routes)
