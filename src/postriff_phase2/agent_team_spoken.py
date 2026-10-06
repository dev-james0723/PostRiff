"""Phone speech is a candidate until the existing James session route confirms it.

Signed media, AMD and a configured destination prove limited call attendance;
they never authenticate James. This private Live adapter stores only a bounded
choice and hashes, and cannot record a decision or dispatch native execution.
"""
import json
import re
import uuid

from postriff_alpha.domain import AlphaError
from .agent_team_decision import _question_call, digest, invalid, validate_question
from .agent_team_cutover import team_enabled

CHOICE_PHRASES={
    'continue':('continue','please continue','continue the original task','i choose continue','繼續','继续','繼續原本任務','继续原本任务'),
    'wait':('wait','please wait','i choose wait','wait for now','等一等','等一下','暫時等候','暂时等候'),
    'needs_human':('needs human','needs_human','i choose needs human','request human help','需要人工協助','需要人工协助'),
}


def spoken_choice(text):
    if not isinstance(text,str) or not 1<=len(text)<=160:return None
    normalized=text.strip().lower().rstrip('.!。！').strip()
    return next((choice for choice,phrases in CHOICE_PHRASES.items() if normalized in phrases),None)


def question_for_call(service,call):
    daily=getattr(service.hosted,'james_daily_call',None)
    if daily is None or call.get('user_id')!=daily.cfg.user_id or call.get('workspace_id')!=daily.cfg.workspace_id:return None
    with service.hosted.connection_factory() as db,db.cursor() as cur:return _question_call(cur,call)


def capture_spoken_choice(service,call,text):
    choice=spoken_choice(text)
    if choice is None:return None
    if not team_enabled(service.config.values):return None
    provider=getattr(service,'provider',None)
    if not provider or provider.name!='twilio' or provider.real is not True:return None
    daily=getattr(service.hosted,'james_daily_call',None)
    if daily is None:return None
    from .phone import store
    with service.hosted.connection_factory() as db,db.cursor() as cur:
        current=store.call(cur,call['id'],lock=True)
        if not current or current.get('user_id')!=daily.cfg.user_id or current.get('workspace_id')!=daily.cfg.workspace_id:return None
        question=_question_call(cur,current)
        if question is None:return None
        question=validate_question(question,now=service.clock())
        if (current.get('state') not in ('answered','live') or not current.get('media_claimed_at')
                or current.get('media_generation',0)!=call.get('media_generation',0) or current.get('media_resume_until')
                or current.get('provider')!='twilio' or not re.fullmatch(r'CA[0-9a-fA-F]{32}',current.get('provider_call_ref') or '')):
            raise invalid('spoken_choice_live_call_required')
        cur.execute("SELECT (SELECT evidence_sha256 FROM public.pr_agent_team_call_evidence WHERE call_id=%s AND provider='twilio' AND evidence_kind='human' AND source='signed_provider_human_detection'),(SELECT evidence_sha256 FROM public.pr_agent_team_call_evidence WHERE call_id=%s AND provider='twilio' AND evidence_kind='media' AND source='authenticated_bidirectional_media' AND input_frames>0 AND output_frames>0 AND playback_ack_sha256 ~ '^[0-9a-f]{64}$'),(SELECT playback_ack_sha256 FROM public.pr_agent_team_call_evidence WHERE call_id=%s AND provider='twilio' AND evidence_kind='media')",
                    (current['id'],current['id'],current['id']))
        evidence=cur.fetchone()
        if not evidence or any(not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value) for value in evidence):raise invalid('spoken_choice_attendance_unverified')
        run_id=str(uuid.UUID(current['reason_key'].split(':',1)[1]))
        document={'schemaVersion':1,'callRunId':run_id,'callId':current['id'],'questionSha256':question['questionSha256'],
            'choice':choice,'spokenTextSha256':digest(text),'humanEvidenceSha256':evidence[0],
            'mediaEvidenceSha256':evidence[1],'playbackAckSha256':evidence[2],'source':'live_input_transcript_candidate'}
        candidate_hash=digest(document)
        cur.execute('INSERT INTO public.pr_agent_team_spoken_choices(call_run_id,question_sha256,call_id,choice,candidate_sha256,document,captured_at) VALUES(%s,%s,%s,%s,%s,%s::jsonb,to_timestamp(%s)) ON CONFLICT(call_run_id,question_sha256) DO NOTHING',
            (run_id,question['questionSha256'],current['id'],choice,candidate_hash,json.dumps(document),service.clock()))
        cur.execute('SELECT choice,call_id::text,candidate_sha256 FROM public.pr_agent_team_spoken_choices WHERE call_run_id=%s AND question_sha256=%s',
                    (run_id,question['questionSha256']))
        old=cur.fetchone()
        if not old or old[0]!=choice or old[1]!=current['id']:raise invalid('spoken_choice_conflict')
        db.commit()
    return {'status':'needs_confirmation','kind':'agent_team_decision','state':'pending_confirmation','choice':choice,
            'candidateSha256':old[2],'executionState':'not_dispatched',
            'speakable':'I captured your choice for the original Agent Team question. Confirm that same choice in your authenticated James session. No task has resumed.'}


def pending_choice(cur,run_id,question,choice):
    """The caller MUST already be the actual authenticated James session principal."""
    cur.execute('SELECT choice,call_id::text,candidate_sha256 FROM public.pr_agent_team_spoken_choices WHERE call_run_id=%s AND question_sha256=%s',
                (run_id,question['questionSha256']))
    candidate=cur.fetchone()
    if candidate and (candidate[0]!=choice or not isinstance(candidate[2],str) or not re.fullmatch(r'[0-9a-f]{64}',candidate[2])):
        raise AlphaError('Confirm the same immutable choice captured by this mission call.',409,code='spoken_choice_confirmation_mismatch')
    return candidate


def read_pending_choice(connection_factory,run_id,actor_id,workspace_id,now):
    """A human session can review the exact bounded confirmation payload."""
    try:
        if str(uuid.UUID(run_id))!=run_id:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise AlphaError('Invalid call identity.',400) from None
    with connection_factory() as db,db.cursor() as cur:
        cur.execute("SELECT r.context,s.choice,s.call_id::text,s.candidate_sha256 FROM public.pr_james_daily_call_runs r JOIN public.pr_agent_team_spoken_choices s ON s.call_run_id=r.id WHERE r.id=%s AND r.user_id=%s AND r.workspace_id=%s AND r.origin='agent_team_report' AND s.question_sha256=(r.context->'agentTeamDecisionQuestion'->>'questionSha256') LIMIT 1",
                    (run_id,actor_id,workspace_id))
        row=cur.fetchone()
    if not row:raise AlphaError('Pending phone choice unavailable.',404,code='spoken_choice_unavailable')
    context=row[0] or {};report=context.get('agentTeamReport') or {}
    question=validate_question(context.get('agentTeamDecisionQuestion'),actor_id=actor_id,workspace_id=workspace_id,
        mission_id=report.get('missionId'),report_id=report.get('reportId'),report_version=report.get('version'),now=now)
    return {'state':'pending_confirmation','executionState':'not_dispatched','prompt':question['prompt'],
        'capturedChoice':row[1],'candidateSha256':row[3],
        'confirmation':{'decisionKey':'phone-confirm:'+row[3],'missionId':question['missionId'],'scopeVersion':question['scopeVersion'],
                        'callRunId':run_id,'questionVersion':question['questionVersion'],'choice':row[1]}}
