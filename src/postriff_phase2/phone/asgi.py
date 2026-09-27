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

    return Starlette(routes=[WebSocketRoute('/api/phone/media/{call_id}', media)])


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

    routes = [WebSocketRoute('/api/phone/media/{call_id}',media)]
    if not media_only:
        routes.append(Mount('/',app=WSGIMiddleware(wsgi)))
    return Starlette(routes=routes)
