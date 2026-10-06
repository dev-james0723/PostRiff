"""Server-owned mission questions and private, normalized call evidence.

No HTTP receipt ingress or native dispatch exists here. Media proof must come
from an authenticated owning stream after actual inbound AND outbound packets;
claimed sockets, clock usage, transcripts and machine role tokens are insufficient.
"""
from dataclasses import dataclass,field
import hashlib
import json
import math
import re
import uuid

from postriff_alpha.domain import AlphaError
from agent_team.recovery import Registration,ExecutionBinding,RecoveryBlocked

HASH=re.compile(r'[0-9a-f]{64}')
IDENTITY=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}')
CHOICES=('continue','wait','needs_human')
QUESTION_FIELDS={'schemaVersion','missionId','actorId','workspaceId','scopeVersion','questionVersion',
                 'authorizationSha256','registrationSha256','registrationAuthoritySha256','executionBindingSha256',
                 'completionRequirementRefs','prompt','choices','issuedAt','expiresAt',
                 'reportId','reportVersion','reportKey','questionSha256'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def invalid(code='decision_question_invalid'):
    return AlphaError('Mission decision binding is unavailable.',409,code=code)


def validate_question(document,*,actor_id=None,workspace_id=None,mission_id=None,report_id=None,report_version=None,now=None):
    if not isinstance(document,dict) or set(document)!=QUESTION_FIELDS or type(document['schemaVersion']) is not int or document['schemaVersion']!=1:raise invalid()
    for name in ('missionId','scopeVersion'):
        if not isinstance(document[name],str) or not IDENTITY.fullmatch(document[name]):raise invalid()
    for name in ('actorId','workspaceId'):
        try:
            if str(uuid.UUID(document[name]))!=document[name]:raise ValueError()
        except (ValueError,TypeError,AttributeError):raise invalid() from None
    for name in ('questionVersion','authorizationSha256','registrationSha256','registrationAuthoritySha256',
                 'executionBindingSha256','questionSha256','reportId'):
        if not isinstance(document[name],str) or not HASH.fullmatch(document[name]):raise invalid()
    refs=document['completionRequirementRefs']
    if not isinstance(refs,list) or not 1<=len(refs)<=100 or any(not isinstance(ref,str) or not HASH.fullmatch(ref) for ref in refs) or len(set(refs))!=len(refs):raise invalid()
    if not isinstance(document['prompt'],str) or not document['prompt'].strip() or len(document['prompt'])>800 or '\0' in document['prompt']:raise invalid()
    if document['choices']!=list(CHOICES):raise invalid()
    if type(document['reportVersion']) is not int or not 1<=document['reportVersion']<=9999:raise invalid()
    if not isinstance(document['reportKey'],str) or not re.fullmatch(r'agent-team:v1:20[0-9]{2}-[0-9]{2}-[0-9]{2}:half_day',document['reportKey']):raise invalid()
    for name in ('issuedAt','expiresAt'):
        if type(document[name]) not in (int,float) or not math.isfinite(document[name]) or document[name]<0:raise invalid()
    if not 0<document['expiresAt']-document['issuedAt']<=3600:raise invalid()
    version_body={key:document[key] for key in QUESTION_FIELDS-{'questionVersion','questionSha256','reportId','reportVersion','reportKey'}}
    if digest(version_body)!=document['questionVersion'] or digest({key:value for key,value in document.items() if key!='questionSha256'})!=document['questionSha256']:raise invalid()
    for name,expected in (('actorId',actor_id),('workspaceId',workspace_id),('missionId',mission_id),('reportId',report_id),('reportVersion',report_version)):
        if expected is not None and document[name]!=expected:raise invalid('decision_question_binding_mismatch')
    if now is not None:
        if type(now) not in (int,float) or not math.isfinite(now):raise invalid()
        if document['issuedAt']>now or document['expiresAt']<now:raise invalid('decision_question_expired')
    return json.loads(json.dumps(document))


@dataclass(frozen=True)
class TrustedDecisionQuestion:
    """Internal capability produced from an existing immutable registry binding."""
    _json:str=field(repr=False)
    _registry:object=field(repr=False,compare=False)
    _registration:Registration=field(repr=False,compare=False)

    def document(self,**bindings):
        try:
            execution=self._registry.current_execution(self._registration)
            if not isinstance(execution,ExecutionBinding):raise ValueError()
            execution.runtime_registration(self._registration)
        except (RecoveryBlocked,ValueError,TypeError,AttributeError):raise invalid('decision_registration_unavailable') from None
        document=validate_question(json.loads(self._json),**bindings)
        if (document['registrationSha256'],document['registrationAuthoritySha256'],document['authorizationSha256'],document['executionBindingSha256'])!=(
                self._registration.fingerprint,self._registration.authority_fingerprint,self._registration.authorization_sha256,execution.fingerprint):
            raise invalid('decision_registration_changed')
        return document


def build_question(registry,registration,*,actor_id,workspace_id,report_id,report_version,report_key,prompt,now,expires_at):
    """registry.current_execution MUST verify exact registration already exists.

    RecoveryStore.current_execution implements that check. Do not replace it with
    browser/event input or an adapter that merely echoes caller-provided digests.
    Completion refs identify registered criteria; they are not acceptance results.
    """
    if not isinstance(registration,Registration):raise invalid('decision_registration_unavailable')
    try:
        registration.validate();execution=registry.current_execution(registration)
        if not isinstance(execution,ExecutionBinding):raise ValueError()
        execution.runtime_registration(registration)
    except (RecoveryBlocked,ValueError,TypeError,AttributeError):raise invalid('decision_registration_unavailable') from None
    refs=[criterion if HASH.fullmatch(criterion) else hashlib.sha256(criterion.encode()).hexdigest() for criterion in registration.acceptance_criteria]
    document={'schemaVersion':1,'missionId':registration.mission_id,'actorId':actor_id,'workspaceId':workspace_id,
              'scopeVersion':registration.scope_version,'authorizationSha256':registration.authorization_sha256,
              'registrationSha256':registration.fingerprint,'registrationAuthoritySha256':registration.authority_fingerprint,
              'executionBindingSha256':execution.fingerprint,'completionRequirementRefs':refs,'prompt':prompt,
              'choices':list(CHOICES),'issuedAt':now,'expiresAt':expires_at,
              'reportId':report_id,'reportVersion':report_version,'reportKey':report_key}
    version_body={key:value for key,value in document.items() if key not in ('reportId','reportVersion','reportKey')}
    document['questionVersion']=digest(version_body)
    document['questionSha256']=digest(document)
    validate_question(document,now=now)
    return TrustedDecisionQuestion(json.dumps(document),registry,registration)


def decision_effect_key(call_run_id,question):
    return 'team-decision:'+digest([call_run_id,question['missionId'],question['scopeVersion'],question['questionVersion']])


def _question_call(cur,call):
    reason=call.get('reason_key','')
    if call.get('provider') not in ('twilio','dial','telnyx') or call.get('direction','outbound')!='outbound' or call.get('destination_ref')!='james_env' or not reason.startswith('james_daily:'):return None
    try:run_id=str(uuid.UUID(reason.split(':',1)[1]))
    except (ValueError,AttributeError):return None
    cur.execute('SELECT context,user_id::text,workspace_id::text,origin FROM public.pr_james_daily_call_runs WHERE id=%s',(run_id,))
    row=cur.fetchone()
    if not row or row[3]!='agent_team_report' or row[1]!=call['user_id'] or row[2]!=call['workspace_id']:return None
    report=(row[0] or {}).get('agentTeamReport',{})
    if not isinstance(report,dict) or not all(key in report for key in ('missionId','reportId','version','workday')):return None
    try:
        question=validate_question((row[0] or {}).get('agentTeamDecisionQuestion'),actor_id=row[1],workspace_id=row[2],mission_id=report.get('missionId'),report_id=report.get('reportId'),report_version=report.get('version'))
        if question['reportKey']!='agent-team:v1:'+report['workday']+':half_day':return None
        return question
    except AlphaError:return None


def _insert_evidence(cur,call,kind,source,evidence_hash,observed_at,*,input_frames=None,output_frames=None,playback_ack_sha256=None):
    cur.execute('INSERT INTO public.pr_agent_team_call_evidence(call_id,evidence_kind,provider,source,evidence_sha256,observed_at,input_frames,output_frames,playback_ack_sha256) VALUES(%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s) ON CONFLICT(call_id,evidence_kind) DO NOTHING',
                (call['id'],kind,call['provider'],source,evidence_hash,observed_at,input_frames,output_frames,playback_ack_sha256))
    cur.execute('SELECT provider,source,evidence_sha256,input_frames,output_frames,playback_ack_sha256 FROM public.pr_agent_team_call_evidence WHERE call_id=%s AND evidence_kind=%s',(call['id'],kind))
    old=cur.fetchone()
    if not old or tuple(old)!=(call['provider'],source,evidence_hash,input_frames,output_frames,playback_ack_sha256):raise AlphaError('Immutable call evidence conflict.',409,code='decision_attendance_conflict')


def record_verified_human_answer(cur,call,*,provider,call_ref,answered_by,amd_bypassed,observed_at):
    """Only call AFTER existing provider signature/account/ref validation.

    This private helper has no machine ingress. AMD bypass/unknown/voicemail/fake
    never produce a human receipt. It proves detection, not James authentication.
    """
    if provider.name!='twilio' or provider.real is not True or answered_by!='human' or amd_bypassed is not False:return False
    if call.get('provider')!=provider.name or (call.get('provider_call_ref') and call['provider_call_ref']!=call_ref) or not re.fullmatch(r'CA[0-9a-fA-F]{32}',call_ref):return False
    if not _question_call(cur,call):return False
    if type(observed_at) not in (int,float) or not math.isfinite(observed_at) or observed_at<0:raise invalid('decision_attendance_invalid')
    evidence=digest(['provider-human:v1',call['id'],provider.name,call_ref,'human','amd_not_bypassed'])
    _insert_evidence(cur,call,'human','signed_provider_human_detection',evidence,observed_at)
    return True


def record_verified_bidirectional_media(cur,call,*,call_ref,input_frames,output_frames,observed_at,evidence_sha256,playback_ack_sha256=None):
    """Private port for the authenticated Twilio packet/uncleared-mark adapter.

    Counters MUST count actual valid received/successfully sent packets, never
    silence timers, queue attempts, socket claims or model-generated transcripts.
    Twilio's signed ASGI stream connects this port via TeamMediaEvidence.
    """
    if not isinstance(call_ref,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',call_ref) or call.get('provider_call_ref')!=call_ref or not _question_call(cur,call):return False
    if type(input_frames) is not int or type(output_frames) is not int or not 1<=min(input_frames,output_frames)<=max(input_frames,output_frames)<=1_000_000:raise invalid('decision_bidirectional_media_required')
    if not isinstance(evidence_sha256,str) or not HASH.fullmatch(evidence_sha256):raise invalid('decision_attendance_invalid')
    if not isinstance(playback_ack_sha256,str) or not HASH.fullmatch(playback_ack_sha256):raise invalid('decision_playback_ack_required')
    if type(observed_at) not in (int,float) or not math.isfinite(observed_at) or observed_at<0:raise invalid('decision_attendance_invalid')
    _insert_evidence(cur,call,'media','authenticated_bidirectional_media',evidence_sha256,observed_at,input_frames=input_frames,output_frames=output_frames,playback_ack_sha256=playback_ack_sha256)
    return True
