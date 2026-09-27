"""Server equivalent of voice-session.ts: transport events → the existing AgentRuntimeService.turn."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time

from postriff_alpha.domain import AlphaError

from ..agent_runtime_v2 import live, style
from . import contracts, store
from .providers.base import TelephonyMediaTransport

FAREWELL = re.compile(
    r'^\s*(?:(?:please|okay|ok|can you|could you|would you)[,\s]+)?'
    r'(?:goodbye|bye(?: bye)?|hang up(?: (?:the )?(?:phone|call))?|end (?:the |this )?call|stop (?:the |this )?call|'
    r'(?:唔該|幫我|帮我|請|请)?(?:收線|收线|拜拜|再見|再见|挂断(?:电话)?|掛斷(?:電話)?))'
    r'(?:[,\s]+(?:please|now|thank you))?[.!?。！？，\s]*$', re.I)


class PhoneSessionController:
    def __init__(self, service, call_id):
        self.service, self.call_id = service, call_id
        self.closed, self.user_text, self.lock = False, '', threading.Lock()
        self.transcript_role, self.transcript_text = None, ''
        self.last_input_at=0
        self.runtime, self.capability, self.call = service.scoped_runtime(call_id,closed=lambda:self.closed)
        self.voice = live.VoiceSessions(self.runtime)

    def configuration(self):
        value = self.call
        with self.runtime.service.repository.transaction(self.capability, value['workspace_id']) as (cur, _row, principal):
            agent_style = style.load(cur, principal)
            locale, voice = live.locale_and_voice({}, agent_style)
            history = self.voice._history(cur, value['workspace_id'], value['conversation_id'])
        config = live.session_config(self.runtime.cfg.route('voice_front_end', reason='phone media').model, locale, voice, agent_style, history)
        config['audio']['format'] = {'type': 'audio/pcmu', 'rate': 8000}
        config['instructions'] += '\nThe person is on the telephone. Identify yourself as Rafii, an AI assistant. No browser screen is attached. Put visual results in the same Rafii conversation. No audio recording.'
        return config

    def started(self, session_id):
        with self.runtime.service.repository.transaction(self.capability, self.call['workspace_id']) as (cur, _row, _principal):
            artifact = self.voice._artifact(cur, self.call['workspace_id'], self.call['voice_run_id'])
            artifact['voice'].update(state='live', connectedAt=self.service.clock(), liveSessionId=session_id)
            self.voice._save(cur, self.call['workspace_id'], self.call['voice_run_id'], artifact)
            cur.execute('UPDATE public.pr_phone_calls SET state=\'live\' WHERE id=%s', (self.call_id,))

    def transcript(self, event):
        if self.closed:
            return
        role = 'user' if event.get('type') == 'session.input_transcript.delta' else 'assistant'
        text = event.get('delta')
        if not isinstance(text, str) or not text:
            return
        if role == 'user':
            self.last_input_at=time.monotonic()
            self.user_text = (self.user_text + text)[-8000:]
        continuing = self.transcript_role == role
        self.transcript_text = (self.transcript_text + text if continuing else text)[-1000:]
        self.transcript_role = role
        # Live sends deltas, not complete turns. Keep one readable line per speaker turn under the existing transcript cap.
        with self.runtime.service.repository.transaction(self.capability,self.call['workspace_id']) as (cur,_row,_principal):
            artifact=self.voice._artifact(cur,self.call['workspace_id'],self.call['voice_run_id'])
            turns=artifact['voice'].setdefault('transcript',[])
            line={'role':role,'text':self.transcript_text,'at':self.service.clock()}
            if continuing and turns and turns[-1].get('role')==role:
                turns[-1]=line
            else:
                turns.append(line)
            del turns[:-live.MAX_TRANSCRIPT_TURNS]
            self.voice._save(cur,self.call['workspace_id'],self.call['voice_run_id'],artifact)

    def delegate(self, event):
        delegation = event.get('delegation') or {}
        delegation_id = delegation.get('id')
        if delegation.get('target', 'client') != 'client' or not isinstance(delegation_id, str) or not 1 <= len(delegation_id) <= 120:
            raise AlphaError('Invalid Live delegation.', 400)
        with self.lock:
            if self.closed:
                return None
            text = self.user_text.strip()
            with self.runtime.service.repository.transaction(self.capability, self.call['workspace_id']) as (cur, _row, principal):
                cur.execute('SELECT state,summary FROM public.pr_phone_delegations WHERE call_id=%s AND delegation_id=%s', (self.call_id, delegation_id))
                previous = cur.fetchone()
                if previous:
                    return self._commentary(delegation_id, previous[1] or 'That request is still being checked in Rafii. Please check the conversation before repeating it.')
                cur.execute('INSERT INTO public.pr_phone_delegations(call_id,delegation_id,state) VALUES(%s,%s,\'running\') ON CONFLICT DO NOTHING RETURNING delegation_id', (self.call_id, delegation_id))
                if not cur.fetchone():
                    return None
                prefs = store.prefs(cur, principal, self.call['workspace_id'])
            self.user_text = ''
            if not text:
                summary, result, state = 'I didn’t catch that request. Please say it again.', {}, 'failed'
            else:
                key='phone:' + self.call_id + ':' + hashlib_id(delegation_id)
                try:
                    result = self.runtime.turn(self.call['workspace_id'], self.capability,
                        {**live.delegation_payload(self.call['conversation_id'], text, key, time_zone=prefs['timeZone']),
                         'delegationId':delegation_id,'voiceSessionId':self.call['voice_run_id']})
                    summary, state = live.speakable_result(result), 'completed'
                except Exception:
                    self.service.abort_delegation(self.call_id,key)
                    # A transport error may follow a real mutation; do not claim that nothing changed.
                    summary, result, state = 'I couldn’t confirm the result. Check this conversation in Rafii before repeating the action.', {}, 'failed'
            with self.service.hosted.connection_factory() as db, db.cursor() as cur:
                cur.execute('UPDATE public.pr_phone_delegations SET state=%s,summary=%s,run_id=%s WHERE call_id=%s AND delegation_id=%s',
                            (state, summary, result.get('runId'), self.call_id, delegation_id))
                db.commit()
            if self.closed:
                return None
            return self._commentary(delegation_id, summary)

    @staticmethod
    def _commentary(delegation_id, content):
        return {'type':'session.commentary.append', 'delegation_id':delegation_id, 'content':content}

    def close(self):
        self.closed = True
        return self.service.hangup(self.call_id)


def hashlib_id(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:24]


async def bridge(controller, transport: TelephonyMediaTransport, connection):
    """No audio retained. Keep reading audio while delegated work runs; clear provider playback on interruption."""
    pending, finished = set(), asyncio.Event()
    final_usage, final_reason = None, 'failed'
    await connection.send({'type':'session.start', 'session':controller.configuration()})
    ready = asyncio.Event()

    async def delegation(event):
        try:
            # As in browser voice: delegation can precede the final transcript delta. Wait for words to settle.
            started=time.monotonic()
            while time.monotonic()-controller.last_input_at < .35 and time.monotonic()-started < 2:
                await asyncio.sleep(.05)
            result = await asyncio.to_thread(controller.delegate, event)
            if result and not controller.closed:
                await connection.send(result)
        except Exception:
            if not controller.closed:
                await connection.send({'type':'session.commentary.append','content':'The request could not be confirmed. Check this Rafii conversation before repeating it.'})

    def dispatch(event):
        task = asyncio.create_task(delegation(event))
        pending.add(task)
        task.add_done_callback(pending.discard)

    async def from_live():
        nonlocal final_usage, final_reason
        async for raw in connection:
            event = raw if isinstance(raw, dict) else raw.model_dump()
            kind = event.get('type')
            if kind == 'session.started':
                await asyncio.to_thread(controller.started, event['session']['id'])
                ready.set()
                await connection.send({'type':'session.instructions.append', 'content':'Greet the caller now: ' + contracts.GREETING})
                if controller.call['kind'] == 'scheduled':
                    controller.user_text = 'Give me a short weekly social-media briefing from this workspace: verified publications, performance, approvals and blockers. Do not publish or schedule anything.'
                    dispatch({'delegation':{'id':'scheduled-briefing','target':'client'}})
                elif controller.call['kind'] == 'proactive':
                    controller.user_text = 'Explain the current ' + controller.call['reason_key'].split(':',1)[0] + ' update in this workspace. Read the actual current state. Do not publish or schedule anything.'
                    dispatch({'delegation':{'id':'attention-briefing','target':'client'}})
            elif kind == 'session.output_audio.delta' and not controller.closed:
                await transport.send_audio(event['delta'])
            elif kind in ('session.input_transcript.delta','session.output_transcript.delta'):
                await asyncio.to_thread(controller.transcript, event)
                if kind == 'session.input_transcript.delta':
                    await transport.interrupt()
                    if FAREWELL.fullmatch(controller.user_text):
                        controller.closed = True
                        await connection.send({'type':'session.close'})
            elif kind == 'session.delegation.created' and not controller.closed:
                dispatch(event)
            elif kind == 'session.closed':
                seconds = (event.get('usage') or {}).get('seconds')
                final_usage = seconds if isinstance(seconds,(int,float)) and 0 <= seconds <= 86400 else None
                final_reason = 'completed'
                finished.set()
                break
            elif kind == 'error':
                finished.set()
                break

    async def from_phone():
        await asyncio.wait_for(ready.wait(), 20)
        try:
            while not controller.closed:
                audio = await transport.receive_audio()
                if audio is None:
                    break
                await connection.send({'type':'session.input_audio.append','audio':audio})
        finally:
            # A stop/disconnect or spoken hang-up must fence tools immediately, then allow final Live usage to arrive.
            controller.closed = True
            try:
                await connection.send({'type':'session.close'})
                await asyncio.wait_for(finished.wait(), 5)
            except Exception:
                pass

    async def watchdog():
        while not controller.closed:
            await asyncio.sleep(1)
            try:
                # Recheck identity, membership, switches and expiry even during a quiet call.
                await asyncio.to_thread(controller.runtime.service.get, controller.call['workspace_id'], controller.capability)
            except Exception:
                controller.closed = True
                await connection.send({'type':'session.close'})
                try:
                    await asyncio.wait_for(finished.wait(), 5)
                except TimeoutError:
                    pass
                break

    tasks = [asyncio.create_task(from_live()),asyncio.create_task(from_phone()),asyncio.create_task(watchdog())]
    try:
        done, _ = await asyncio.wait(tasks, timeout=controller.call['max_seconds'], return_when=asyncio.FIRST_COMPLETED)
        if not done:
            await connection.send({'type':'session.close'})
            try:
                await asyncio.wait_for(finished.wait(), 5)
            except TimeoutError:
                pass
        for task in done:
            task.result()
    finally:
        controller.closed = True
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Running tools keep normal Rafii task state. Their next transaction fails the closed-call capability check.
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        # Dial's documented hang-up is a media frame. Ledger/REST confirmation still decides settlement.
        end_transport = getattr(transport, 'end_call', None)
        if end_transport:
            try:
                await end_transport()
            except Exception:
                pass
        result = await asyncio.to_thread(controller.service.hangup, controller.call_id, live_seconds=final_usage, reason=final_reason)
        if result['ended']:
            await asyncio.to_thread(controller.service.finish, controller.call_id, final_reason, live_seconds=final_usage)
        else:
            await asyncio.to_thread(controller.service.record_live_usage, controller.call_id, final_usage)


class FakeLiveConnection:
    """In-process Live event transport for deterministic acceptance, never a live model."""
    def __init__(self):
        self.sent = []

    async def send(self, event):
        self.sent.append(event)
