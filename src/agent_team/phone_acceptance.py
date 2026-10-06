"""Explicitly armed, one-call staging acceptance after genuine native ingress.

The caller must first verify/publish the actual owner guard. Normal observer
acknowledgment is required; this module never collects or manufactures events.
An uncertain phone request is permanently held for reconciliation, not retried.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from .audio_bridge import request_json
from .native_decision import STAGING_NATIVE_WORK, _verifier_token
from .periods import aware
from .recovery import RecoveryBlocked
from .restricted_owner import private, write_private

BASE = STAGING_NATIVE_WORK.removesuffix('/native-work')


def delivered_native_event(canonical_root, mission_id, after, now):
    path = private(Path(canonical_root)/'.runtime/journal.sqlite3')
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=1)
    try:
        rows = db.execute("SELECT payload,observed_at,delivered_at FROM observations WHERE source IN ('claude','codex') "
                          'AND delivered_at IS NOT NULL ORDER BY observed_at DESC LIMIT 200').fetchall()
    finally: db.close()
    for raw, observed, delivered in rows:
        if len(raw.encode()) > 16000: continue
        document = json.loads(raw)
        if (document.get('mission_id') == mission_id and document.get('source') in {'claude','codex'}
                and after <= aware(observed).timestamp() <= aware(delivered).timestamp() <= now
                and now-aware(delivered).timestamp() <= 600
                and isinstance(document.get('key'), str) and re.fullmatch('[0-9a-f]{64}', document['key'])):
            return document['key']
    return None


class PhoneAcceptance:
    def __init__(self, canonical_root, owner_root, acceptance_id, mission_id, *,
                 request=request_json, evidence=delivered_native_event, clock=time.time):
        if str(UUID(acceptance_id)) != acceptance_id: raise RecoveryBlocked('phone_acceptance_identity_invalid')
        self.canonical_root, self.owner_root = Path(canonical_root), private(Path(owner_root), directory=True)
        self.acceptance_id, self.mission_id = acceptance_id, mission_id
        self.request, self.evidence, self.clock = request, evidence, clock
        self.intent = self.owner_root/'phone-acceptance-intent.json'

    def once(self):
        if self.intent.exists():
            document = json.loads(private(self.intent).read_text())
            if (document.get('acceptanceId'),document.get('missionId')) != (self.acceptance_id,self.mission_id):
                raise RecoveryBlocked('phone_acceptance_intent_changed')
            return {'state':document['state'], 'acceptanceId':self.acceptance_id,
                    'callsResent':0, 'callRunId':document.get('callRunId')}
        now = self.clock(); local = datetime.fromtimestamp(now, ZoneInfo('America/Indiana/Indianapolis'))
        if local.hour >= 22 or local.hour < 8:
            return {'state':'quiet_hours_deferred','callsResent':0}
        native = json.loads(private(self.owner_root/'native-result.json').read_text())
        after = native.get('observedAt')
        if native.get('nativeState') != 'finished' or type(after) not in (int,float) or not 0 <= now-after <= 1800:
            raise RecoveryBlocked('fresh_real_native_result_required')
        event = self.evidence(self.canonical_root,self.mission_id,after,now)
        if event is None: return {'state':'waiting_for_normal_native_ingress','callsResent':0}
        token = _verifier_token(self.canonical_root)
        document = {'schemaVersion':1,'acceptanceId':self.acceptance_id,'missionId':self.mission_id,
                    'state':'report_requested','observedAt':now,'nativeEventRef':event,'callsResent':0}
        # Reserve before network I/O; another worker cannot send a second call.
        try: fd = os.open(self.intent, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError: return {'state':'existing_intent_no_resend','callsResent':0}
        with os.fdopen(fd,'w') as stream:
            json.dump(document,stream);stream.flush();os.fsync(stream.fileno())
        try:
            generated = self.request(BASE+'/acceptance/as-of-now',token,{'acceptanceId':self.acceptance_id})
            from .acceptance import acceptance_key
            identity = acceptance_key(generated.get('reportKey')) if isinstance(generated,dict) else None
            if (identity is None or identity[1] != self.acceptance_id
                    or generated.get('executionMode') != 'staging_acceptance'
                    or generated.get('state') not in {'generated','already_generated'}
                    or type(generated.get('version')) is not int or not 1 <= generated['version'] <= 9999
                    or type(generated.get('evidenceCount')) is not int or generated['evidenceCount'] < 1
                    or not isinstance(generated.get('reportId'),str) or not re.fullmatch('[0-9a-f]{64}',generated['reportId'])):
                raise RecoveryBlocked('phone_acceptance_report_unverified')
            document.update(reportKey=generated['reportKey'],reportId=generated['reportId'],state='call_requested')
            write_private(self.intent,document)
            # Server rechecks real mission evidence, immutable question, exact
            # staging flags, quiet hours and owner freshness before Twilio I/O.
            response = self.request(BASE+'/acceptance/'+self.acceptance_id+'/call',token,{'missionId':self.mission_id})
            call_id = response.get('id') if isinstance(response,dict) else None
            if call_id is None or str(UUID(call_id)) != call_id:
                raise RecoveryBlocked('phone_acceptance_call_outcome_unknown')
            document.update(state='call_submitted',callRunId=call_id)
            write_private(self.intent,document)
            return {'state':'call_submitted','acceptanceId':self.acceptance_id,'callRunId':call_id,'callsResent':0,
                    'humanAnswered':False,'decisionConfirmed':False,'nativeResumed':False}
        except Exception:
            document['state'] = 'call_outcome_unknown_no_resend' if document['state']=='call_requested' else 'report_outcome_unverified_no_call'
            write_private(self.intent,document)
            return {'state':document['state'],'acceptanceId':self.acceptance_id,'callsResent':0}
