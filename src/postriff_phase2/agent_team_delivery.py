"""Private report readiness via the existing transactional notification outbox.

Queue admission and delivery receipts commit together. This adapter never sends,
calls a provider, generates an audio file, or chooses another person/workspace.
Notification availability/acceptance does not prove that a report was viewed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid

from agent_team.events import canonical
from agent_team.periods import aware, period
from agent_team.acceptance import document_period
from postriff_alpha.domain import AlphaError

EVENT_TYPE = 'james.team_report_ready'
EFFECT_KIND = 'notification'
READY_TITLE = 'James Agent Team report ready'
READY_DETAIL = 'Your report is ready. Sign in to review it.'
MAX_SUMMARY_BYTES = 4096


def report_identity(document):
    """Validate a generated report identity; DB read-back supplies its authority."""
    try:
        p = document['period']
        expected = document_period(document)
        if any(p.get(key) != value for key, value in expected.as_dict().items()):
            raise ValueError('report_period_mismatch')
        fingerprint = document['fingerprint']
        version = document['version']
        summary = document['summary']
        if (document.get('executionState') != 'generated'
                or not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint)
                or type(version) is not int or not 1 <= version <= 9999
                or not isinstance(summary, str) or not summary.strip()
                or len(summary.encode('utf-8')) > MAX_SUMMARY_BYTES
                or aware(document['generatedAt']) < expected.cutoff):
            raise ValueError('report_identity_invalid')
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError):
        raise AlphaError('Invalid generated report.', 400, code='agent_team_delivery_report_invalid') from None
    return expected, fingerprint, version


def report_href(document):
    p, _, version = report_identity(document)
    # The shared short-payload sanitizer redacts long digit/hyphen runs. Percent
    # encoded separators preserve the date and URLSearchParams decodes it.
    workday = p.workday.replace('-', '%2D')
    acceptance = '&acceptanceId=' + p.acceptance_id if hasattr(p, 'acceptance_id') else ''
    return f'/app/agent-team?workday={workday}&kind={p.kind}&version={version}' + acceptance


def browser_voice_payload(document):
    """Private, exact report summary for an explicit browser playback gesture."""
    _, fingerprint, version = report_identity(document)
    return {'audioState': 'unavailable', 'audioReason': 'generated_audio_backend_not_connected',
            'playbackState': 'on_demand_browser_speech', 'method': 'browser_speech_synthesis',
            'label': '播放本機語音摘要（按需）', 'text': document['summary'], 'lang': 'zh-Hant',
            'autoplay': False, 'requiresUserGesture': True, 'reportId': fingerprint, 'version': version,
            'voiceSource': 'device_browser', 'audioFileGenerated': False}


def browser_voice_controls(document):
    """Controls for an authenticated report page; no playback before a click.

    Device/browser support is checked there, rather than claiming cloud audio
    generation. The exact summary is escaped for a script text context.
    """
    payload = browser_voice_payload(document)
    encoded = json.dumps(payload, ensure_ascii=True).replace('<', '\\u003c')
    return ('<section aria-label="按需本機語音摘要">'
            '<button type="button" id="team-voice-play" disabled>播放本機語音摘要（按需）</button>'
            '<button type="button" id="team-voice-stop" disabled>停止播放</button>'
            '<p id="team-voice-status" role="status">尚未建立音訊檔案；本機語音需按下播放。</p>'
            '</section><script type="application/json" id="team-voice-payload">' + encoded + '</script>'
            '<script>(()=>{const p=JSON.parse(document.getElementById("team-voice-payload").textContent);'
            'const play=document.getElementById("team-voice-play"),stop=document.getElementById("team-voice-stop"),'
            'status=document.getElementById("team-voice-status");'
            'if(!("speechSynthesis" in window)||!("SpeechSynthesisUtterance" in window))'
            '{status.textContent="此瀏覽器未提供本機語音播放；音訊檔案仍未建立。";return;}'
            'play.disabled=false;let current=null;'
            'play.addEventListener("click",()=>{window.speechSynthesis.cancel();'
            'current=new SpeechSynthesisUtterance(p.text);current.lang=p.lang;current.rate=1;current.pitch=1;'
            'current.onstart=()=>{status.textContent="正在播放本機語音摘要。";stop.disabled=false;};'
            'current.onend=()=>{status.textContent="本機播放已結束；沒有建立音訊檔案。";stop.disabled=true;};'
            'current.onerror=()=>{status.textContent="本機語音播放未完成；音訊檔案仍未建立。";stop.disabled=true;};'
            'status.textContent="本機語音播放已要求。";window.speechSynthesis.speak(current);});'
            'stop.addEventListener("click",()=>{window.speechSynthesis.cancel();stop.disabled=true;'
            'status.textContent="本機播放已停止；沒有建立音訊檔案。";});})();</script>')


def delivery_plan(document, now):
    p, _, version = report_identity(document)
    now = aware(now)
    if aware(document['generatedAt']) > now + timedelta(seconds=60):
        raise AlphaError('Future report generation.', 400, code='agent_team_delivery_report_invalid')
    key = f'{p.key}:notice:v{version}'
    # No late half-day supplement can create a night push or next-day catchup.
    push_window = p.kind == 'half_day' and p.cutoff <= now < p.cutoff + timedelta(hours=5)
    channels = ('in_app', 'push') if push_window else ('in_app',)
    return {'effectKey': key, 'reportKey': p.key, 'dedupeKey': key, 'channels': channels,
            'groupingKey': 'jtr_' + hashlib.sha256(key.encode()).hexdigest()[:28],
            'expiresAt': (p.cutoff + timedelta(hours=5)).timestamp() if push_window else None,
            'href': report_href(document)}


def delivery_receipt(document, plan, event_id, effect_state, rows, *, created=False, failure=None):
    """Actual stored rows, not the planner's intended or a device's guessed state."""
    pending = False
    acknowledged = False
    accepted = False
    delivered = False
    available = False
    receipts = []
    for row in rows:
        identifier, channel, mode, status, provider, failure_class, next_attempt = row
        if channel not in ('in_app', 'push') or (document['period']['kind'] == 'whole_day' and channel != 'in_app'):
            raise AlphaError('Unexpected report delivery channel.', 409, code='agent_team_delivery_receipt_mismatch')
        real_provider = provider in ('push', 'webpush')
        pending |= status in ('pending', 'claimed', 'uncertain')
        acknowledged |= channel == 'in_app' and status in ('read', 'acted')
        accepted |= channel == 'push' and status == 'sent' and real_provider
        delivered |= channel == 'push' and status in ('delivered', 'read', 'acted') and real_provider
        available |= channel == 'in_app' and status in ('delivered', 'read', 'acted', 'dismissed')
        proof = ('notification_acknowledged' if channel == 'in_app' and status in ('read', 'acted') else
                 'in_app_persisted' if channel == 'in_app' and status in ('delivered', 'dismissed') else
                 'provider_accepted' if channel == 'push' and status == 'sent' and real_provider else
                 'provider_delivery_receipt' if channel == 'push' and status in ('delivered', 'read', 'acted') and real_provider else
                 'simulation' if provider == 'recording' else 'none')
        receipts.append({'deliveryId': identifier, 'channel': channel, 'mode': mode, 'status': status,
                         'provider': provider, 'failureClass': failure_class,
                         'nextAttemptAt': float(next_attempt) if next_attempt is not None else None, 'proof': proof})
    if acknowledged:
        delivery_state = 'notification_acknowledged'
    elif delivered:
        delivery_state = 'provider_delivered'
    elif pending:
        delivery_state = 'queued'
    elif accepted:
        delivery_state = 'provider_accepted'
    elif available:
        delivery_state = 'in_app_available'
    elif receipts and all(r['status'] in ('suppressed', 'cancelled') for r in receipts):
        delivery_state = 'suppressed'
    elif receipts and any(r['status'] in ('failed', 'dead') for r in receipts):
        delivery_state = 'failed'
    else:
        delivery_state = 'disabled' if effect_state == 'disabled' else 'reconciliation_required' if failure else 'not_queued'
    return {'state': 'queued' if pending else 'persisted', 'deliveryState': delivery_state,
            'reportKey': plan['reportKey'], 'reportId': document['fingerprint'], 'version': document['version'],
            'effectKey': plan['effectKey'], 'effectState': effect_state, 'eventId': event_id,
            'created': bool(created), 'deliveries': receipts, 'notificationAcknowledged': acknowledged,
            'reportViewState': 'unverified', 'href': plan['href'], 'requiresAuthentication': True,
            'audioState': 'unavailable', 'playbackState': 'on_demand_browser_speech',
            'failureClass': failure}


def with_stored_audio(receipt, document, asset):
    """Reconcile asset availability without claiming delivery or playback."""
    if asset is None:
        return receipt
    p, fingerprint, version = report_identity(document)
    if (asset.get('reportKey') != p.key or asset.get('fingerprint') != fingerprint
            or asset.get('version') != version or asset.get('audioState') != 'ready'
            or asset.get('summaryHash') != hashlib.sha256(document['summary'].encode('utf-8')).hexdigest()
            or not isinstance(asset.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', asset['sha256'])):
        raise AlphaError('Report audio receipt identity mismatch.', 409, code='agent_team_audio_receipt_mismatch')
    return {**receipt, 'audioState': 'ready', 'audioAsset': asset,
            'playbackState': 'on_demand_authenticated_wav', 'audioPlaybackState': 'unverified'}


class TeamDeliveryStore:
    def __init__(self, connection_factory, user_id, *, clock):
        # Only the configured James principal enters this store, never a body or
        # observer token claim. The service facade below has no recipient arg.
        try:
            if not isinstance(user_id, str) or str(uuid.UUID(user_id)) != user_id:
                raise ValueError('invalid_user')
        except (ValueError, TypeError, AttributeError):
            raise AlphaError('James delivery identity is not configured.', 409, code='agent_team_delivery_identity_unbound') from None
        self.connection_factory, self.user_id, self.clock = connection_factory, user_id, clock

    def _manifest(self, cur, document, plan):
        cur.execute('SELECT document FROM public.pr_agent_team_reports WHERE report_key=%s AND fingerprint=%s',
                    (plan['reportKey'], document['fingerprint']))
        row = cur.fetchone()
        if not row or canonical(row[0]) != canonical(document):
            raise AlphaError('Delivery must match an immutable stored report.', 409, code='agent_team_delivery_report_mismatch')

    def _effect(self, cur, plan):
        cur.execute('SELECT report_key,kind,state,external_id,failure_class FROM public.pr_agent_team_effects WHERE effect_key=%s',
                    (plan['effectKey'],))
        row = cur.fetchone()
        if row and (row[0] != plan['reportKey'] or row[1] != EFFECT_KIND):
            raise AlphaError('Report effect identity mismatch.', 409, code='agent_team_delivery_receipt_mismatch')
        return row

    def _event(self, cur, document, plan):
        cur.execute('SELECT id::text,event_type,entity_id,workspace_id::text,payload FROM public.pr_notification_events WHERE scope_key=%s AND dedupe_key=%s',
                    ('user:' + self.user_id, plan['dedupeKey']))
        row = cur.fetchone()
        if row and (row[1] != EVENT_TYPE or row[2] != document['fingerprint'] or row[3] is not None
                    or (row[4] or {}).get('href') != plan['href']):
            raise AlphaError('Report notification identity mismatch.', 409, code='agent_team_delivery_receipt_mismatch')
        return row[0] if row else None

    def _rows(self, cur, event_id):
        if not event_id:
            return []
        cur.execute('SELECT id::text,channel,mode,status,provider,failure_class,extract(epoch from next_attempt_at),user_id::text,workspace_id::text '
                    'FROM public.pr_notification_deliveries WHERE event_id=%s ORDER BY channel,id', (event_id,))
        rows = cur.fetchall()
        if any(row[7] != self.user_id or row[8] is not None for row in rows):
            raise AlphaError('Report delivery recipient mismatch.', 409, code='agent_team_delivery_receipt_mismatch')
        return [row[:7] for row in rows]

    def _save_receipt(self, cur, document, plan, event_id, effect, *, created=False, disabled=False):
        rows = self._rows(cur, event_id)
        missing = bool(not event_id and effect and (effect[3] or effect[2] in ('submitted', 'confirmed', 'unknown')))
        disabled = disabled and not event_id
        state = 'unknown' if missing else 'disabled' if disabled else 'submitted' if event_id else effect[2] if effect else None
        failure = 'notification_receipt_missing' if missing else 'notifications_disabled' if disabled else None
        receipt = delivery_receipt(document, plan, event_id, state, rows, created=created, failure=failure)
        if receipt['notificationAcknowledged'] or receipt['deliveryState'] == 'provider_delivered':
            state = 'confirmed'
        elif event_id and not rows:
            state, failure = 'failed', 'notification_recipient_unavailable'
        elif receipt['deliveryState'] == 'failed':
            state, failure = 'failed', 'notification_delivery_failed'
        receipt.update(effectState=state, failureClass=failure)
        if effect:
            cur.execute('UPDATE public.pr_agent_team_effects SET state=%s,external_id=%s,failure_class=%s,updated_at=now() WHERE effect_key=%s',
                        (state, event_id or effect[3], failure, plan['effectKey']))
        return receipt

    def queue(self, document, notifications):
        plan = delivery_plan(document, datetime.fromtimestamp(self.clock(), timezone.utc))
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (plan['effectKey'],))
            self._manifest(cur, document, plan)
            effect = self._effect(cur, plan)
            event_id = self._event(cur, document, plan)
            if effect and event_id and effect[3] and effect[3] != event_id:
                raise AlphaError('Report effect receipt mismatch.', 409, code='agent_team_delivery_receipt_mismatch')
            if not effect:
                cur.execute("INSERT INTO public.pr_agent_team_effects(effect_key,report_key,kind,state) VALUES(%s,%s,%s,'reserved') ON CONFLICT DO NOTHING",
                            (plan['effectKey'], plan['reportKey'], EFFECT_KIND))
                effect = self._effect(cur, plan)
            created = disabled = False
            # A missing previously submitted receipt is reconciled, never emitted
            # again. A reserved/disabled row has no external send to duplicate.
            missing = bool(effect[3] or effect[2] in ('submitted', 'confirmed', 'unknown'))
            if not event_id and not missing:
                if notifications is None:
                    disabled = True
                else:
                    emit_report=getattr(notifications,'emit_james_report_in_app',None)
                    emit=(lambda cursor,**event:emit_report(cursor,document=document,**event)) if callable(emit_report) else notifications.emit
                    result = emit(cur, workspace_id=None, user_id=self.user_id, actor=self.user_id,
                        event_type=EVENT_TYPE, dedupe_key=plan['dedupeKey'], grouping_key=plan['groupingKey'],
                        entity_type='agent_team_report', entity_id=document['fingerprint'],
                        payload={'title': READY_TITLE, 'detail': READY_DETAIL, 'href': plan['href'], 'count': document['version']},
                        channel_filter=plan['channels'], expires_at=plan['expiresAt'])
                    disabled = bool(result.get('disabled'))
                    created = bool(result.get('created'))
                    event_id = self._event(cur, document, plan)
                    if not event_id and not disabled:
                        raise AlphaError('Notification persistence could not be verified.', 409, code='agent_team_delivery_receipt_mismatch')
            receipt = self._save_receipt(cur, document, plan, event_id, effect, created=created, disabled=disabled)
            db.commit()
        return receipt

    def receipt(self, document):
        """Reconcile existing notification outcomes; never queue or send."""
        plan = delivery_plan(document, datetime.fromtimestamp(self.clock(), timezone.utc))
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (plan['effectKey'],))
            self._manifest(cur, document, plan)
            effect = self._effect(cur, plan)
            event_id = self._event(cur, document, plan)
            if effect and event_id and effect[3] and effect[3] != event_id:
                raise AlphaError('Report effect receipt mismatch.', 409, code='agent_team_delivery_receipt_mismatch')
            result = self._save_receipt(cur, document, plan, event_id, effect, disabled=bool(effect and effect[2] == 'disabled'))
            db.commit()
        return result


class TeamDeliveryService:
    """Hosted-service facade: recipient is always its configured James UUID."""
    def __init__(self, service):
        self.service = service
        self.notifications = getattr(service, 'notifications', None)
        cfg = getattr(getattr(service, 'james_daily_call', None), 'cfg', None)
        self.store = TeamDeliveryStore(service.connection_factory, getattr(cfg, 'user_id', None), clock=service.clock)

    def queue(self, document):
        if document.get('executionMode') == 'staging_acceptance':
            from .agent_team_acceptance import require_acceptance
            require_acceptance(getattr(self.service.james_daily_call, 'values', {}))
        return self._surface(self.store.queue(document, self.notifications))

    def receipt(self, document):
        return self._surface(self.store.receipt(document))

    def _surface(self,receipt):
        enabled=getattr(self.notifications,'enabled',False)
        enabled=enabled() if callable(enabled) else enabled
        # A persisted private report receipt does not turn on the general bell
        # or show that James read either the report or its notification.
        return {**receipt,'generalNotificationCenterEnabled':bool(enabled),
                'inAppReceiptSurface':'general_notification_center' if enabled else 'private_agent_team_report'}
