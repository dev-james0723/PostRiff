"""Authenticated phone product service. Reserve and commit before any provider request."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import re
import time
import uuid

from postriff_alpha.domain import AlphaError, uid

from ..agent_runtime_v2 import live, style
from ..agent_runtime_v2.http import runtime_for
from ..automation_runs import principal_repository
from ..permissions import require
from . import billing, contracts, planner, store
from .config import PhoneConfig


class PhoneService:
    def __init__(self, hosted, values=None, *, provider=None, runtime=None, clock=None):
        self.hosted, self.config = hosted, PhoneConfig(dict(values or {}))
        self.provider, self.runtime = provider, runtime
        self.clock = clock or hosted.clock or time.time
        from ..oauth import CredentialVault
        key = self.config.values.get('RAFII_PHONE_ENCRYPTION_KEY')
        self.vault = CredentialVault(key) if key else hosted.oauth.vault

    def agent(self):
        return self.runtime or runtime_for(self.hosted)

    def _require(self):
        if not self.config.enabled('RAFII_PHONE_ENABLED'):
            raise AlphaError('Phone Mode isn’t available on this deployment.', 404, code='phone_disabled')

    def _lock(self, cur, principal):
        # Serializes limits and idempotency across this person's workspaces and concurrent workers.
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('phone:' + principal,))

    def settings(self, workspace_id, token):
        with self.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self.hosted.ideas._member(row), 'read')
            if not self.config.enabled('RAFII_PHONE_ENABLED'):
                return {'available': False, 'flags': self.config.public(), 'number': None, 'preferences': dict(contracts.DEFAULTS), 'calls': [], 'schedules': []}
            number = store.number(cur, principal)
            cur.execute(f'SELECT {store.SELECT_CALL} FROM public.pr_phone_calls WHERE user_id=%s AND workspace_id=%s ORDER BY requested_at DESC LIMIT 30', (principal, workspace_id))
            calls = [store.public_call(dict(zip(store.CALL_COLUMNS, r))) for r in cur.fetchall()]
            cur.execute('SELECT id::text,schedule,enabled,extract(epoch from next_at) FROM public.pr_phone_schedules WHERE user_id=%s AND workspace_id=%s ORDER BY created_at', (principal, workspace_id))
            schedules = [{'id': r[0], 'schedule': r[1], 'enabled': r[2], 'nextAt': float(r[3])} for r in cur.fetchall()]
            return {'available': True, 'providerReady': bool(self.provider and self.provider.configured), 'flags': self.config.public(),
                    'spending': billing.spending(self, cur, workspace_id),
                    'execution': 'fake' if self.provider and not self.provider.real else 'provider',
                    'number': {'lastFour': number['last_four'], 'verified': number['verified']} if number else None,
                    'preferences': store.prefs(cur, principal, workspace_id), 'calls': calls, 'schedules': schedules}

    def save_preferences(self, workspace_id, token, payload):
        self._require()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self.hosted.ideas._member(row), 'edit')
            self._lock(cur, principal)
            value = contracts.preferences(payload, store.prefs(cur, principal, workspace_id))
            if value['enabled'] and not (store.number(cur, principal) or {}).get('verified'):
                raise AlphaError('Verify your phone number first.', 409, code='phone_unverified')
            store.save_prefs(cur, principal, workspace_id, value)
        return {'preferences': value}

    def start_verification(self, workspace_id, token, payload):
        self._require()
        number = contracts.phone_number(payload.get('number'))
        if not self.provider or not self.provider.configured:
            raise AlphaError('Phone verification isn’t configured.', 503, code='provider_unavailable')
        if self.provider.real and not self.config.enabled('RAFII_PHONE_VERIFICATION_ENABLED'):
            raise AlphaError('Phone verification is disabled on this deployment.', 403, code='verification_disabled')
        ciphertext, key_id = self.vault.encrypt(number)
        fingerprint = hmac.new(self.vault.fernet._signing_key, number.encode(), hashlib.sha256).hexdigest()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self.hosted.ideas._member(row), 'edit')
            self.hosted.repository.assert_fresh(token, principal)
            self._lock(cur, principal)
            cur.execute('SELECT last_sent_at>now()-interval \'1 minute\',CASE WHEN sent_day=current_date THEN sends ELSE 0 END FROM public.pr_phone_verification_limits WHERE user_id=%s', (principal,))
            prior = cur.fetchone()
            if prior and (prior[0] or prior[1] >= 5):
                raise AlphaError('Wait before requesting another verification code.', 429, code='verification_limit')
            cur.execute('INSERT INTO public.pr_phone_verification_limits(user_id,last_sent_at,sent_day,sends) VALUES(%s,now(),current_date,1) '
                        'ON CONFLICT(user_id) DO UPDATE SET last_sent_at=now(),sent_day=current_date,sends=CASE WHEN pr_phone_verification_limits.sent_day=current_date THEN pr_phone_verification_limits.sends+1 ELSE 1 END',(principal,))
            cur.execute('SELECT 1 FROM public.pr_phone_calls WHERE user_id=%s AND NOT(state=ANY(%s)) LIMIT 1', (principal, list(contracts.TERMINAL)))
            if cur.fetchone():
                raise AlphaError('End your current call before changing the number.', 409)
            cur.execute('INSERT INTO public.pr_phone_numbers(user_id,phone_ciphertext,phone_hash,key_id,last_four,verification_started_at,verification_day,verification_sends) '
                        'VALUES(%s,%s,%s,%s,%s,now(),current_date,1) ON CONFLICT(user_id) DO UPDATE SET phone_ciphertext=excluded.phone_ciphertext,phone_hash=excluded.phone_hash,'
                        'key_id=excluded.key_id,last_four=excluded.last_four,verified_at=NULL,verification_ref=NULL,verification_started_at=now(),verification_attempts=0,'
                        'verification_sends=CASE WHEN pr_phone_numbers.verification_day=current_date THEN pr_phone_numbers.verification_sends+1 ELSE 1 END,verification_day=current_date,updated_at=now()',
                        (principal, ciphertext, fingerprint, key_id, number[-4:]))
            cur.execute('UPDATE public.pr_phone_preferences SET preferences=preferences || \'{"enabled":false,"proactiveCalls":false,"scheduledCalls":false}\'::jsonb WHERE user_id=%s', (principal,))
        try:
            ref = self.provider.start_verification(number)
        except Exception:
            raise AlphaError('The verification service didn’t confirm the request. Wait before requesting another code.', 503, code='verification_unconfirmed') from None
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            cur.execute('UPDATE public.pr_phone_numbers SET verification_ref=%s WHERE user_id=%s AND phone_hash=%s', (ref, principal, fingerprint))
        return {'requested': True, 'execution': 'provider' if self.provider.real else 'fake'}

    def confirm_verification(self, workspace_id, token, payload):
        self._require()
        code = payload.get('code')
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{4,10}', code):
            raise AlphaError('Enter the verification code.', 400)
        if not self.provider or (self.provider.real and not self.config.enabled('RAFII_PHONE_VERIFICATION_ENABLED')):
            raise AlphaError('Phone verification is disabled.', 403)
        with self.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self.hosted.ideas._member(row), 'edit')
            self._lock(cur, principal)
            identity = store.number(cur, principal)
            cur.execute('UPDATE public.pr_phone_numbers SET verification_attempts=verification_attempts+1 WHERE user_id=%s AND verification_attempts<5 '
                        'AND verification_started_at>now()-interval \'10 minutes\' AND verification_ref IS NOT NULL RETURNING phone_hash', (principal,))
            if not identity or not cur.fetchone():
                raise AlphaError('Request a new verification code.', 409, code='verification_expired')
            number = self.vault.decrypt(identity['ciphertext'], identity['key_id'])
        try:
            verified = self.provider.check_verification(number, code)
        except Exception:
            raise AlphaError('Phone verification is temporarily unavailable.', 503) from None
        if not verified:
            raise AlphaError('That code wasn’t accepted.', 400, code='verification_invalid')
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            cur.execute('UPDATE public.pr_phone_numbers SET verified_at=now(),verification_ref=NULL WHERE user_id=%s AND phone_hash=%s RETURNING user_id', (principal, identity['hash']))
            if not cur.fetchone():
                raise AlphaError('The phone number changed. Verify it again.', 409)
        return {'verified': True, 'lastFour': number[-4:]}

    def delete_number(self, workspace_id, token):
        self._require()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            self.hosted.repository.assert_fresh(token, principal)
        self.stop_for_user(principal)
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            self._lock(cur, principal)
            cur.execute('DELETE FROM public.pr_phone_numbers WHERE user_id=%s', (principal,))
            cur.execute('UPDATE public.pr_phone_preferences SET preferences=preferences || \'{"enabled":false,"proactiveCalls":false,"scheduledCalls":false}\'::jsonb WHERE user_id=%s', (principal,))
            cur.execute('DELETE FROM public.pr_phone_schedules WHERE user_id=%s', (principal,))
        return {'deleted': True}

    def request(self, workspace_id, token, payload, *, kind='explicit', reason_key=None, event_type=None, dispatch=True):
        self._require()
        key = payload.get('idempotencyKey')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{8,100}', key):
            raise AlphaError('Send a unique call request key.', 400)
        agent = self.agent()
        route = agent.cfg.route('voice_front_end', reason='phone session')
        now = self.clock()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = self.hosted.ideas._member(row)
            require(member, 'edit')
            self._lock(cur, principal)
            cur.execute('SELECT id::text,workspace_id::text FROM public.pr_phone_calls WHERE user_id=%s AND idempotency_key=%s', (principal, key))
            prior = cur.fetchone()
            if prior:
                if prior[1] != workspace_id:
                    raise AlphaError('Call unavailable.', 404)
                return store.public_call(store.call(cur, prior[0]))
            identity, prefs = store.number(cur, principal), store.prefs(cur, principal, workspace_id)
            start = planner.day_start(now, prefs['timeZone'])
            cur.execute('SELECT count(*),coalesce(sum(reserved_usd_micro),0),count(*) FILTER(WHERE kind<>\'explicit\') '
                        'FROM public.pr_phone_calls WHERE user_id=%s AND requested_at>=to_timestamp(%s)', (principal, start))
            count, reserved, automatic = cur.fetchone()
            reason = reason_key or 'explicit'
            cur.execute('SELECT state,reason_key,requested_at>to_timestamp(%s) FROM public.pr_phone_calls WHERE user_id=%s AND (NOT(state=ANY(%s)) OR requested_at>to_timestamp(%s))',
                        (now - 300, principal, list(contracts.TERMINAL), now - 300))
            recent = cur.fetchall()
            estimate_live, estimate_tel = billing.estimates(self)
            estimate = estimate_live + estimate_tel
            blocker = planner.eligibility(kind, prefs, now=now, verified=bool(identity and identity['verified']), membership=member.allows('edit'),
                configured=bool(self.provider and self.provider.configured and (not self.provider.real or self.config.telephony_rate > 0)),
                live_configured=route.available and agent.cfg.enabled('RAFII_AGENT_V2_ENABLED'), flags=self.config.public(), event_type=event_type,
                daily_calls=int(count if kind == 'explicit' else automatic), recent_equivalent=any(r[1] == reason and r[2] for r in recent),
                active=any(r[0] not in contracts.TERMINAL for r in recent), reserved_cost=int(reserved), estimate=estimate, daily_budget=self.config.daily_budget)
            if blocker:
                raise AlphaError('Rafii can’t place this call right now. Check your phone settings.', 409, code=blocker)
            number = self.vault.decrypt(identity['ciphertext'], identity['key_id'])
            if self.provider.real:
                allowed = [c for c in self.config.values.get('RAFII_PHONE_ALLOWED_COUNTRY_CODES', '').split(',') if re.fullmatch(r'\+[1-9][0-9]{0,2}', c)]
                if not any(number.startswith(c) for c in allowed):
                    raise AlphaError('Calls to this country aren’t enabled.', 403, code='phone_country')
            conversation_id = payload.get('conversationId')
            if conversation_id:
                self.hosted.ideas._conversation(cur, workspace_id, conversation_id)
            else:
                cur.execute('INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,\'Phone conversation with Rafii\') RETURNING id::text', (workspace_id, principal))
                conversation_id = cur.fetchone()[0]
            live_authority, tel_authority = billing.authorities(self, cur, workspace_id, principal, row[0],
                maximum=payload.get('maxMilliCredits') if kind == 'explicit' else prefs['maxMilliCreditsPerCall'],
                conversation_id=conversation_id, number_hash=identity['hash'], kind=kind, reason=reason, costs=(estimate_live, estimate_tel))
            call_id = str(uuid.uuid4())
            agent_style = style.load(cur, principal)
            locale, voice = live.locale_and_voice({}, agent_style)
            artifact = {'voice': {'state': 'connecting', 'locale': locale, 'voice': voice, 'startedAt': now, 'transcript': [], 'transport': 'phone'}}
            if live_authority or tel_authority:
                artifact['voice']['creditLimitMilliCredits'] = payload.get('maxMilliCredits') if kind == 'explicit' else prefs['maxMilliCreditsPerCall']
            cur.execute('INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,artifact) '
                        'VALUES(%s,%s,%s,\'running\',%s,\'quick\',%s,%s,%s,%s::jsonb) RETURNING id::text',
                        (conversation_id, workspace_id, principal, route.model, hashlib.sha256(call_id.encode()).hexdigest(), hashlib.sha256(b'phone-v1').hexdigest(), 'voice:phone:' + call_id, json.dumps(artifact)))
            run_id = cur.fetchone()[0]
            live_res = self.hosted.ledger.reserve(cur, workspace_id, principal, 'tool', estimate_live, 'phone-live:' + call_id, charge_batch=False,
                         provider='openai', model=route.model, run_id=run_id, credit_authority=live_authority, meta={'via': 'rafii_phone', 'capSeconds': self.config.cap_seconds})
            tel_res = self.hosted.ledger.reserve(cur, workspace_id, principal, 'tool', estimate_tel, 'phone-tel:' + call_id, charge_batch=False,
                         provider=self.provider.name, model='pstn', run_id=run_id, credit_authority=tel_authority, meta={'via': 'rafii_phone', 'capSeconds': self.config.cap_seconds})
            artifact['voice']['reservationId'] = live_res['reservationId']
            cur.execute('UPDATE public.pr_agent_runs SET artifact=%s::jsonb WHERE id=%s', (json.dumps(artifact), run_id))
            cur.execute('INSERT INTO public.pr_phone_calls(id,user_id,workspace_id,conversation_id,voice_run_id,kind,reason_key,provider,state,idempotency_key,number_hash,max_seconds,'
                        'live_reservation_id,telephony_reservation_id,reserved_usd_micro,requested_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,\'requested\',%s,%s,%s,%s,%s,%s,to_timestamp(%s))',
                        (call_id, principal, workspace_id, conversation_id, run_id, kind, reason, self.provider.name, key, identity['hash'], self.config.cap_seconds,
                         live_res['reservationId'], tel_res['reservationId'], estimate, now))
        if dispatch:
            from .delivery import deliver
            deliver(self, call_id)
        return self.view(workspace_id, token, call_id)

    def view(self, workspace_id, token, call_id):
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            value = store.call(cur, call_id)
            if not value or value['user_id'] != principal or value['workspace_id'] != workspace_id:
                raise AlphaError('Call unavailable.', 404)
            return store.public_call(value)

    def end(self, workspace_id, token, call_id):
        self.view(workspace_id, token, call_id)
        return self.hangup(call_id)

    def hangup(self, call_id, *, live_seconds=None, reason=None):
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            value = store.call(cur, call_id, lock=True)
            if not value or value['state'] in contracts.TERMINAL:
                return {'ended': True}
            store.set_state(cur, value, 'ending')
            db.commit()
        if value['provider_call_ref']:
            try:
                if not self.provider or not self.provider.end_call(value['provider_call_ref']):
                    return {'ended': False, 'state': 'ending'}
            except Exception:
                return {'ended': False, 'state': 'ending'}
        elif value['state'] != 'requested':
            return {'ended': False, 'state': 'ending'}
        self.finish(call_id, reason or ('completed' if value['answered_at'] else 'cancelled'), live_seconds=live_seconds)
        return {'ended': True}

    def finish(self, call_id, state, duration=None, *, live_seconds=None):
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            value = store.call(cur, call_id, lock=True)
            if not value:
                return
            live_seconds = live_seconds if live_seconds is not None else value['live_usage_seconds']
            if value['state'] in contracts.TERMINAL:
                if duration is not None:
                    # A signed final duration may follow our hang-up acknowledgment. Keep history and held usage reconciled.
                    seconds = min(value['max_seconds'],max(0,float(value['ended_at'] or self.clock())-float(value['answered_at'] or self.clock())))
                    tel_cost = math.ceil(max(seconds,duration)/60)*self.config.telephony_rate
                    self.hosted.ledger.settle(cur,value['workspace_id'],value['telephony_reservation_id'],'completed',tel_cost)
                    cur.execute('UPDATE public.pr_phone_calls SET duration_seconds=%s,telephony_cost_usd_micro=coalesce(telephony_cost_usd_micro,%s) WHERE id=%s',(duration,tel_cost,call_id))
                # Twilio's completed callback can arrive before GPT-Live's final usage event.
                if live_seconds is not None and value['media_claimed_at']:
                    seconds = min(value['max_seconds'],max(0,float(value['ended_at'] or self.clock())-float(value['answered_at'] or self.clock())))
                    cost = math.ceil(max(seconds+15,live_seconds)*self.agent().cfg.live_usd_micro_per_minute/60)
                    self.hosted.ledger.settle(cur,value['workspace_id'],value['live_reservation_id'],'completed',cost)
                    cur.execute('UPDATE public.pr_phone_calls SET live_cost_usd_micro=%s,live_usage_seconds=%s WHERE id=%s',(cost,live_seconds,call_id))
                db.commit()
                return
            connected = float(value['answered_at']) if value['answered_at'] else None
            seconds = min(value['max_seconds'], max(0, self.clock() - connected)) if connected else 0
            store.set_state(cur, value, state, duration if duration is not None else math.ceil(seconds))
            # Provider duration can be larger than local observed duration; never reduce the charge from a client hint.
            tel_seconds = max(seconds, duration or 0)
            tel_cost = math.ceil(tel_seconds/60)*self.config.telephony_rate
            tel_unknown = bool(self.provider and self.provider.real and value['provider_call_ref'] and duration is None
                               and state not in ('busy','declined','no_answer','cancelled'))
            billable_live = max(seconds + 15, live_seconds or 0) if value['media_claimed_at'] else 0
            voice_cost = math.ceil(billable_live * self.agent().cfg.live_usd_micro_per_minute / 60)
            unknown = bool(value['media_claimed_at'] and live_seconds is None)
            self.hosted.ledger.settle(cur, value['workspace_id'], value['live_reservation_id'], 'unknown' if unknown else 'completed', None if unknown else voice_cost)
            self.hosted.ledger.settle(cur, value['workspace_id'], value['telephony_reservation_id'], 'unknown' if tel_unknown else 'completed', None if tel_unknown else tel_cost)
            cur.execute('UPDATE public.pr_phone_calls SET live_cost_usd_micro=%s,telephony_cost_usd_micro=%s,live_usage_seconds=%s,billing_basis=%s WHERE id=%s',
                        (None if unknown else voice_cost, None if tel_unknown else tel_cost, live_seconds, 'bounded estimate; provider duration rounded to whole minutes at configured rate ceiling, Live server clock', call_id))
            cur.execute('UPDATE public.pr_agent_runs SET status=%s,artifact=jsonb_set(artifact,\'{voice,state}\',%s::jsonb),updated_at=now() WHERE id=%s',
                        ('failed' if state == 'failed' else 'completed', json.dumps('failed' if state == 'failed' else 'ended'), value['voice_run_id']))
            notifications = getattr(self.hosted,'notifications',None)
            if state in ('busy','declined','no_answer','voicemail','failed') and notifications and notifications.enabled():
                prefs = store.prefs(cur,value['user_id'],value['workspace_id'])
                channels = ['in_app'] + (['push'] if prefs['fallbackToPush'] else []) + (['email'] if prefs['fallbackToEmail'] else [])
                notifications.emit(cur,workspace_id=value['workspace_id'],event_type='phone.call_failed',dedupe_key='phone:'+call_id,
                    actor=value['user_id'],payload={'title':'Your Rafii call didn’t connect','href':'/app/account/notifications'},channel_filter=channels)
            db.commit()

    def record_live_usage(self, call_id, seconds):
        """Server-observed Live usage can arrive while provider hang-up is still uncertain; it never ends a call."""
        if not isinstance(seconds,(int,float)) or not 0 <= seconds <= 86400:
            return
        with self.hosted.connection_factory() as db:
            db.execute('UPDATE public.pr_phone_calls SET live_usage_seconds=%s WHERE id::text=%s AND media_claimed_at IS NOT NULL',(seconds,call_id))

    def notification_context(self, cur, recipient, event):
        if event['event_type'] not in contracts.CALL_EVENTS or not event.get('workspace_id'):
            return None
        principal,workspace_id = recipient['userId'],event['workspace_id']
        if event['event_type'] == 'campaign.approval_required':
            # Only a real approval deadline within 24 hours can escalate to a telephone call.
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(workspace_id,))
            workspace = cur.fetchone()[0]
            review = next((r for r in workspace.get('phase2',{}).get('reviews',[]) if r.get('id') == event.get('entity_id') and r.get('status') == 'needs_review'),{})
            deadline = review.get('manifest',{}).get('timing',{}).get('timestamp')
            if not isinstance(deadline,(int,float)) or not self.clock() <= deadline <= self.clock()+86400:
                return None
        prefs,identity = store.prefs(cur,principal,workspace_id),store.number(cur,principal)
        cur.execute('SELECT count(*) FILTER(WHERE kind<>\'explicit\'),coalesce(sum(reserved_usd_micro),0) FROM public.pr_phone_calls '
                    'WHERE user_id=%s AND requested_at>=to_timestamp(%s)',(principal,planner.day_start(self.clock(),prefs['timeZone'])))
        count,reserved = cur.fetchone()
        cur.execute('SELECT state,reason_key FROM public.pr_phone_calls WHERE user_id=%s AND (NOT(state=ANY(%s)) OR requested_at>now()-interval \'5 minutes\')',
                    (principal,list(contracts.TERMINAL)))
        recent = cur.fetchall()
        estimate = self.agent().cfg.live_usd_micro_per_minute*math.ceil((self.config.cap_seconds+15)/60)+self.config.telephony_rate*math.ceil(self.config.cap_seconds/60)
        return {'prefs':prefs,'verified':bool(identity and identity['verified']),'membership':recipient['membership'].allows('edit'),
                'configured':bool(self.provider and self.provider.configured),'live_configured':self.agent().cfg.route('voice_front_end',reason='phone attention').available
                    and self.agent().cfg.enabled('RAFII_AGENT_V2_ENABLED'),'flags':self.config.public(),'daily_calls':int(count),
                'active':any(r[0] not in contracts.TERMINAL for r in recent),'recent_equivalent':any(r[1]==event['event_type']+':'+event['grouping_key'][:100] for r in recent),
                'reserved_cost':int(reserved),'estimate':estimate,'daily_budget':self.config.daily_budget}

    def stop_for_user(self, principal):
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT to_regclass('public.pr_phone_calls')")
            if cur.fetchone()[0] is None:
                return
            cur.execute('SELECT id::text FROM public.pr_phone_calls WHERE user_id=%s AND NOT(state=ANY(%s))', (principal, list(contracts.TERMINAL)))
            ids = [r[0] for r in cur.fetchall()]
        for call_id in ids:
            if not self.hangup(call_id)['ended']:
                raise AlphaError('The active phone call hasn’t confirmed it ended. Try again shortly.', 409, code='phone_end_unconfirmed')

    def scoped_runtime(self, call_id, *, closed=None):
        with self.hosted.connection_factory() as db, db.cursor() as cur:
            value = store.call(cur, call_id)
        if not value:
            raise AlphaError('Call unavailable.', 404)
        def check(_state):
            if closed and closed():
                raise AlphaError('This phone session ended.',409,code='phone_ended')
            with self.hosted.connection_factory() as db, db.cursor() as cur:
                current = store.call(cur, call_id)
                identity = store.number(cur, value['user_id'])
                prefs = store.prefs(cur, value['user_id'], value['workspace_id'])
            if not current or current['state'] not in ('answered','live') or not identity or not identity['verified'] or identity['hash'] != current['number_hash'] or not prefs['enabled']:
                raise AlphaError('This phone session ended.', 409, code='phone_ended')
            if not self.config.enabled('RAFII_PHONE_ENABLED') or not self.config.enabled('RAFII_PHONE_OUTBOUND_ENABLED'):
                raise AlphaError('Phone Mode is disabled.', 403)
            if current['answered_at'] and self.clock() >= float(current['answered_at']) + current['max_seconds']:
                raise AlphaError('The phone session reached its time limit.', 409, code='phone_expired')
        repository, capability = principal_repository(self.hosted, value['workspace_id'], value['user_id'], 'edit', check)
        scoped = copy.copy(self.hosted)
        scoped.repository, scoped.verify_session = repository, repository.verify_session
        scoped.ideas = copy.copy(self.hosted.ideas)
        scoped.ideas.repository, scoped.ideas.service_ref = repository, scoped
        from ..credit_requests import CreditRequests
        scoped.ideas.credit_requests = CreditRequests(scoped.ideas)
        from ..site_agent.service import SiteAgentService
        scoped.site_agent = SiteAgentService(scoped)
        for name in ('oauth', 'audience', 'data_requests', 'time_savings'):
            obj = copy.copy(getattr(scoped, name))
            obj.repository = repository
            setattr(scoped, name, obj)
        scoped.audience._service = scoped
        if getattr(scoped, 'coworker', None):
            scoped.coworker = copy.copy(scoped.coworker)
            scoped.coworker.hosted = scoped
        runtime = copy.copy(self.agent())
        runtime.service = scoped
        runtime.reservation_approval = billing.manager_approval(self, call_id)
        return runtime, capability, value

    def abort_delegation(self, call_id, key):
        """Close only this phone-owned turn after its capability expired. Lifecycle cleanup never grants tool access."""
        from ..agent_runtime_v2 import contracts as agent_contracts
        from ..site_agent import contracts as site_contracts
        with self.hosted.connection_factory() as db,db.cursor() as cur:
            value=store.call(cur,call_id)
            if not value:
                return
            cur.execute('SELECT id::text,status FROM public.pr_agent_runs WHERE workspace_id=%s AND conversation_id=%s AND actor=%s AND idempotency_key=%s FOR UPDATE',
                        (value['workspace_id'],value['conversation_id'],value['user_id'],'agent:'+key))
            run=cur.fetchone()
            if not run or run[1]!='running':
                return
            cur.execute('SELECT id::text FROM public.pr_usage_ledger WHERE run_id=%s AND kind=\'reserve\'',(run[0],))
            for reservation, in cur.fetchall():
                self.hosted.ledger.settle(cur,value['workspace_id'],reservation,'unknown')
            result=agent_contracts.empty_result(agent_contracts.new_trace_id(),'voice')
            answer='The phone request stopped before its result was confirmed. Anything already saved stays in Rafii. Check this conversation before repeating the action.'
            result.update(answerText=answer,speakableSummary=answer,composedBy='deterministic',errors=[{'code':'phone_interrupted','message':answer}])
            self.agent()._persist(cur,value['workspace_id'],value['conversation_id'],run[0],result,[site_contracts.warning(answer,'phone_interrupted')],[],[],
                trace={'traceId':result['traceId'],'composedBy':'deterministic','fallback':'phone_interrupted'},status='cancelled',usage={'provenance':'phone','billing':'unknown until reconciled'})
            db.commit()

    def save_schedule(self, workspace_id, token, payload):
        self._require()
        from .. import campaigns
        schedule = payload.get('schedule')
        if not isinstance(schedule, dict) or schedule.get('kind', 'weekly') != 'weekly':
            raise AlphaError('Choose a daily or weekly phone briefing.', 400)
        # The existing scheduling parser validates the schedule, zone, DST and next occurrence.
        schedule = campaigns.normalize_schedule(schedule)
        due = campaigns.next_occurrence(schedule, self.clock())
        with self.hosted.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self.hosted.ideas._member(row), 'edit')
            if not store.prefs(cur, principal, workspace_id)['scheduledCalls']:
                raise AlphaError('Enable scheduled calls first.', 409)
            conversation = payload.get('conversationId')
            if conversation:
                self.hosted.ideas._conversation(cur, workspace_id, conversation)
            else:
                cur.execute('INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,\'Scheduled Rafii phone briefing\') RETURNING id::text',(workspace_id,principal))
                conversation=cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM public.pr_phone_schedules WHERE user_id=%s', (principal,))
            if cur.fetchone()[0] >= 4:
                raise AlphaError('You can save up to four phone briefings.', 409)
            cur.execute('INSERT INTO public.pr_phone_schedules(user_id,workspace_id,conversation_id,schedule,next_at) VALUES(%s,%s,%s,%s::jsonb,to_timestamp(%s)) RETURNING id::text',
                        (principal, workspace_id, conversation, json.dumps(schedule), due['scheduledFor']))
            return {'id': cur.fetchone()[0], 'schedule': schedule, 'nextAt': due['scheduledFor']}

    def delete_schedule(self, workspace_id, token, schedule_id):
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            cur.execute('DELETE FROM public.pr_phone_schedules WHERE id::text=%s AND workspace_id=%s AND user_id=%s', (schedule_id, workspace_id, principal))
        return {'deleted': True}
