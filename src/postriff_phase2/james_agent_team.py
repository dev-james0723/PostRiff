"""Dedicated authenticated orchestration ingress; personal queries stay read-only.

Feature disabled until explicit cutover. No provider/model call occurs on ingest,
status, report preview or decision recording. Only existing cloud cron owns reports.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import uuid
from urllib.parse import parse_qs
from postriff_alpha.domain import AlphaError
from agent_team.events import Event, canonical
from agent_team.periods import aware, latest_due, period
from agent_team.reports import EXPECTED_SOURCES, report, svg, html

PREFIX='/api/internal/james-agent-team'


def enabled(values):
    return str(values.get('JAMES_AGENT_TEAM_ENABLED','0')).lower() in ('1','true')


def authorize(environ, values, role):
    key={'observer':'JAMES_AGENT_TEAM_OBSERVER_TOKEN','reader':'JAMES_AGENT_TEAM_READER_TOKEN','verifier':'JAMES_AGENT_TEAM_VERIFIER_TOKEN'}[role]
    expected=str(values.get(key) or '')
    supplied=environ.get('HTTP_AUTHORIZATION','')
    if len(expected)<32 or len(expected)>512 or not hmac.compare_digest(supplied,'Bearer '+expected):
        raise AlphaError('Agent Team authorization failed.',401,code='agent_team_unauthorized')


def authenticated_user(app,environ,service,values):
    # Machine role tokens are never evidence that a human has authenticated.
    supplied=environ.get('HTTP_AUTHORIZATION','')
    for role in ('observer','reader','verifier'):
        expected=str(values.get('JAMES_AGENT_TEAM_'+role.upper()+'_TOKEN') or '')
        if 32<=len(expected)<=512 and hmac.compare_digest(supplied,'Bearer '+expected):
            raise AlphaError('An authenticated James session is required.',401,code='agent_team_session_required')
    try:
        principal=service.verify_session(app._token(environ))
    except AlphaError:
        raise
    except Exception:
        raise AlphaError('An authenticated James session is required.',401,code='agent_team_session_required') from None
    if str(principal)!=service.james_daily_call.cfg.user_id:
        raise AlphaError('This session cannot access James Agent Team.',403,code='agent_team_principal_mismatch')
    return str(principal)


def authorize_reader(app,environ,service,values):
    try:
        authorize(environ,values,'reader')
    except AlphaError:
        authenticated_user(app,environ,service,values)


def content_fingerprint(document):
    # Generation time changes every cron tick. Observed-at and late-arrival facts
    # remain in the content because they change cutoff/evidence semantics.
    metadata={'generatedAt','fingerprint','version','supplementOf','initialGeneratedAt'}
    stable={k:v for k,v in document.items() if k not in metadata}
    return hashlib.sha256(canonical(stable).encode()).hexdigest()


def body(environ,max_bytes=256*1024):
    try:length=int(environ.get('CONTENT_LENGTH') or 0)
    except ValueError:raise AlphaError('Invalid body.',400)
    if length<=0 or length>max_bytes:raise AlphaError('Body limit.',413)
    raw=environ['wsgi.input'].read(length)
    if len(raw)!=length:raise AlphaError('Incomplete body.',400)
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):raise AlphaError('Invalid JSON.',400) from None
    if not isinstance(value,dict):raise AlphaError('Invalid object.',400)
    return value


class TeamStore:
    def __init__(self,connection_factory):self.connection_factory=connection_factory

    def ingest(self, rows, verifier=False):
        if not isinstance(rows,list) or len(rows)>100:raise AlphaError('Event batch limit.',400)
        validated=[]
        for row in rows:
            if not isinstance(row,dict):raise AlphaError('Invalid event.',400)
            if set(row)-{'key','source','source_id','revision','happened_at','observed_at','payload','mission_id','project_id'}:raise AlphaError('Invalid event fields.',400)
            try:
                ev=Event(**{k:v for k,v in row.items() if k!='key'});doc=ev.cloud()
                if doc['payload'].get('sourceFreshAt') is not None and aware(doc['payload']['sourceFreshAt'])>aware(ev.observed_at):
                    raise ValueError('source_freshness_after_observation')
            except (TypeError,ValueError):raise AlphaError('Invalid event.',400) from None
            if ev.source in ('acceptance','incident') and not verifier:raise AlphaError('Verifier authority required.',403)
            if row.get('key')!=ev.key:raise AlphaError('Event key mismatch.',400)
            # Local observing clocks may be slightly ahead, but future forged events are rejected.
            if (aware(ev.observed_at)-datetime.now(timezone.utc)).total_seconds()>60:raise AlphaError('Future observation.',400)
            immutable={k:v for k,v in doc.items() if k!='observed_at'}
            digest=hashlib.sha256(canonical(immutable).encode()).hexdigest()
            validated.append((ev,doc,digest))
        accepted=[]
        with self.connection_factory() as db,db.cursor() as cur:
            for ev,doc,digest in validated:
                cur.execute('INSERT INTO public.pr_agent_team_events(event_key,source,source_id,revision,happened_at,observed_at,mission_id,project_id,document,immutable_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT(event_key) DO NOTHING',
                    (ev.key,ev.source,ev.source_id,ev.revision,ev.happened_at,ev.observed_at,ev.mission_id,ev.project_id,canonical(doc),digest))
                cur.execute('SELECT immutable_digest FROM public.pr_agent_team_events WHERE event_key=%s',(ev.key,))
                old=cur.fetchone()
                if not old or old[0]!=digest:raise AlphaError('Immutable observation conflict.',409)
                accepted.append(ev.key)
            db.commit()
        return {'accepted':accepted,'state':'persisted'}

    def observations(self,p,observed_by=None):
        observed_by=aware(observed_by or datetime.now(timezone.utc))
        with self.connection_factory() as db,db.cursor() as cur:
            # Pull one overlap day for freshness but never raw local transcripts or screenshots.
            # Coverage scans may arrive after cutoff with an explicit pre-cutoff
            # source watermark. Ordinary post-cutoff edits remain excluded.
            cur.execute("SELECT document FROM public.pr_agent_team_events WHERE happened_at>=%s::timestamptz-interval '24 hours' AND (happened_at<%s OR source='health') AND observed_at<=%s ORDER BY observed_at,event_key LIMIT 10001",(p.start,p.cutoff,observed_by))
            rows=[x[0] for x in cur.fetchall()]
        return rows[:10000],len(rows)>10000

    def put_report(self,document):
        p=document['period']
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('agent-team-report:'+p['key'],))
            cur.execute("SELECT document FROM public.pr_agent_team_reports WHERE report_key=%s ORDER BY coalesce((document->>'version')::integer,1) DESC,generated_at DESC LIMIT 1",(p['key'],))
            row=cur.fetchone();prior=row[0] if row else None
            fingerprint=content_fingerprint(document)
            if prior and content_fingerprint(prior)==fingerprint:
                db.commit()
                return prior,False
            if prior and int(prior.get('version',1))>=9999:
                raise AlphaError('Report version limit requires reconciliation.',409)
            document={**document,'fingerprint':fingerprint,'version':int((prior or {}).get('version',1 if prior else 0))+1}
            document['initialGeneratedAt']=(prior or {}).get('initialGeneratedAt',(prior or {}).get('generatedAt',document['generatedAt']))
            if prior:document['supplementOf']=prior['fingerprint']
            cur.execute('INSERT INTO public.pr_agent_team_reports(report_key,fingerprint,kind,workday,cutoff,generated_at,document) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',
                        (p['key'],document['fingerprint'],p['kind'],p['workday'],p['cutoff'],document['generatedAt'],canonical(document)))
            db.commit()
        return document,True

    def get_report(self,key,version=None):
        with self.connection_factory() as db,db.cursor() as cur:
            if version is None:
                cur.execute("SELECT document FROM public.pr_agent_team_reports WHERE report_key=%s ORDER BY coalesce((document->>'version')::integer,1) DESC,generated_at DESC LIMIT 1",(key,))
            else:
                if type(version) is not int or not 1<=version<=9999:raise AlphaError('Invalid report version.',400)
                cur.execute("SELECT document FROM public.pr_agent_team_reports WHERE report_key=%s AND coalesce((document->>'version')::integer,1)=%s LIMIT 1",(key,version))
            row=cur.fetchone()
        return row[0] if row else None

    def reserve_effect(self,key,report_key,kind):
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('INSERT INTO public.pr_agent_team_effects(effect_key,report_key,kind,state) VALUES(%s,%s,%s,\'reserved\') ON CONFLICT DO NOTHING RETURNING effect_key',(key,report_key,kind));new=cur.fetchone()
            db.commit()
        # Unknown or abandoned reservation is reconciled externally; never blindly repeat it.
        return bool(new)

    def effect(self,key,state,external_id=None,failure_class=None):
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('UPDATE public.pr_agent_team_effects SET state=%s,external_id=%s,failure_class=%s,updated_at=now() WHERE effect_key=%s',(state,external_id,failure_class,key));db.commit()

    def decision(self,d,user_id):
        required={'decisionKey','missionId','scopeVersion','callRunId','questionVersion','choice'}
        if set(d)!=required or d['choice'] not in ('continue','wait','needs_human'):raise AlphaError('Invalid decision.',400)
        for key in required-{'callRunId'}:
            if not isinstance(d[key],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',d[key]):raise AlphaError('Invalid decision identity.',400)
        try:uuid.UUID(d['callRunId']);uuid.UUID(user_id)
        except (ValueError,TypeError):raise AlphaError('Invalid call identity.',400) from None
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('SELECT context,user_id::text,state FROM public.pr_james_daily_call_runs WHERE id=%s',(d['callRunId'],));row=cur.fetchone()
            context=row[0] if row and isinstance(row[0],dict) else {}
            team=context.get('agentTeamReport',{})
            if not row or row[1]!=user_id or row[2] not in ('dialing','completed') or team.get('missionId')!=d['missionId'] or str(team.get('version'))!=d['scopeVersion'] or str(team.get('questionVersion',team.get('version')))!=d['questionVersion']:
                raise AlphaError('Decision does not match the authenticated mission call.',403)
            cur.execute('INSERT INTO public.pr_agent_team_decisions(decision_key,mission_id,scope_version,call_run_id,question_version,choice,authenticated_user_id) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                        tuple(d[k] for k in ('decisionKey','missionId','scopeVersion','callRunId','questionVersion','choice'))+(user_id,))
            cur.execute('SELECT mission_id,scope_version,call_run_id::text,question_version,choice,authenticated_user_id::text FROM public.pr_agent_team_decisions WHERE decision_key=%s',(d['decisionKey'],));old=cur.fetchone()
            expected=tuple(d[k] for k in ('missionId','scopeVersion','callRunId','questionVersion','choice'))+(user_id,)
            if tuple(old)!=expected:raise AlphaError('Decision key already records another choice.',409)
            db.commit()
        return {'state':'recorded','executionState':'not_dispatched'}


def source_coverage(events,p,generated_at=None):
    generated=aware(generated_at or datetime.now(timezone.utc))
    result={source:{'status':'unknown','freshAt':None,'complete':False,'gaps':['source_not_verified']} for source in EXPECTED_SOURCES}
    latest={}
    for e in events:
        if e['source']!='health' or e['payload'].get('kind')!='source_coverage':continue
        source=e['source_id'];payload=e['payload']
        if source not in result:continue
        try:
            observed=aware(e['observed_at']);effective=aware(payload.get('sourceFreshAt') or e['happened_at'])
        except (TypeError,ValueError):continue
        if observed>generated or effective>p.cutoff:continue
        rank=(effective,observed,e['revision'],e['key'])
        if source in latest and rank<=latest[source]:continue
        latest[source]=rank
        age=(p.cutoff-effective).total_seconds();gaps=payload.get('gaps',[])
        if not isinstance(gaps,list) or any(not isinstance(gap,str) for gap in gaps):gaps=['invalid_source_coverage']
        status=payload.get('sourceStatus','unknown')
        if age>120:status='stale';gaps=['local_source_stale_or_offline']
        complete=payload.get('scanComplete') is True and age<=120 and status=='ok' and not gaps
        if not complete and not gaps:gaps=['source_scan_incomplete']
        result[source]={'status':status,'freshAt':effective.isoformat(),'complete':complete,'gaps':gaps}
    return result


def cron(service,values=None):
    values=dict(values if values is not None else getattr(getattr(service,'james_daily_call',None),'values',{}))
    if not enabled(values):return {'state':'disabled'}
    now=datetime.fromtimestamp(service.clock(),timezone.utc);p=latest_due(now);store=TeamStore(service.connection_factory)
    status=_generate_period(service,values,store,p,now)
    supplements=[]
    # Revisit at most two previous cutoffs. Existing historical reports can gain
    # late evidence, but a restart never creates catch-up calls or new old reports.
    previous=p
    for _ in range(2):
        previous=latest_due(previous.cutoff-timedelta(seconds=1))
        prior=store.get_report(previous.key)
        if not prior:continue
        update=_generate_period(service,values,store,previous,now,prior=prior,historical=True)
        if update['state']=='supplemented':supplements.append(update)
    if supplements:status['supplements']=supplements
    return status


def _generate_period(service,values,store,p,now,prior=None,historical=False):
    if prior is None:prior=store.get_report(p.key)
    events,truncated=store.observations(p,now);sources=source_coverage(events,p,now)
    if truncated:
        for meta in sources.values():meta.update(complete=False,gaps=meta.get('gaps',[])+['observation_query_limit'])
    doc=report(p,events,now,sources)
    if prior and content_fingerprint(prior)==content_fingerprint(doc):
        return _with_delivery(service,prior,{'state':'already_generated','reportKey':p.key,'fingerprint':prior['fingerprint'],
                'version':prior.get('version',1),'deliveryState':'inspect_effect_receipt'})
    doc,created=store.put_report(doc)
    if not created:
        return _with_delivery(service,doc,{'state':'already_generated','reportKey':p.key,'fingerprint':doc['fingerprint'],
                'version':doc.get('version',1),'deliveryState':'inspect_effect_receipt'})
    # Persist report independently of call/delivery; unavailable connector cannot hold it indefinitely.
    supplement=bool(prior or doc.get('supplementOf'))
    status={'state':'supplemented' if supplement else 'generated','reportKey':p.key,'fingerprint':doc['fingerprint'],
            'version':doc['version'],'deliveryState':'not_delivered','callState':'disabled','audioState':'unavailable'}
    status=_with_delivery(service,doc,status)
    if p.kind=='whole_day':return status
    if supplement or historical:
        status['callState']='supplement_no_call';return status
    if str(values.get('JAMES_AGENT_TEAM_CALL_ENABLED','0')).lower() not in ('1','true'):return status
    if (now-p.cutoff).total_seconds()>900:
        status['callState']='missed_window';return status
    effect=p.key+':call'
    if not store.reserve_effect(effect,p.key,'phone'):status['callState']='reconciliation_required';return status
    try:
        result=service.james_daily_call.call_report(report_id=doc['fingerprint'],mission_id='james-agent-team',workday=p.workday,version=doc['version'],briefing={
            'kind':p.kind,'verified':True,'timeZone':'America/Indiana/Indianapolis','cutoffLocalTime':'17:00',
            'generatedAt':now.timestamp(),'summary':doc['summary'],'coverageGaps':doc['gaps'][:20],'evidenceRefs':[x['id'] for x in doc['evidence']][:20]})
        store.effect(effect,'submitted',result.get('id'));status['callState']=result.get('state','unknown')
    except AlphaError as error:
        store.effect(effect,'failed',failure_class=error.code or 'admission_blocked');status['callState']='blocked'
    except Exception:
        store.effect(effect,'unknown',failure_class='reconciliation_required');status['callState']='unknown'
    return status


def _with_delivery(service,document,status):
    # This call persists/reconciles the existing outbox; its worker performs
    # actual sends under current notification preferences and quiet hours.
    from .agent_team_delivery import TeamDeliveryService
    try:
        receipt=TeamDeliveryService(service).queue(document)
        status.update(deliveryState=receipt['deliveryState'],deliveryReceipt=receipt)
    except Exception:
        status.update(deliveryState='unavailable',deliveryFailure='notification_receipt_unavailable')
    status['audioState']='unavailable';status['playbackState']='on_demand_browser_speech'
    return status


def route(app,environ,start_response,method,path):
    if path!=PREFIX and not path.startswith(PREFIX+'/'):return None
    import os
    values=os.environ
    if not enabled(values):raise AlphaError('Agent Team is disabled.',503,code='agent_team_disabled')
    tail=path[len(PREFIX):]
    service=app._runtime();store=TeamStore(service.connection_factory)
    if tail=='/audio-work' and method=='GET':
        authorize(environ,values,'observer')
        from .agent_team_audio import TeamAudioStore
        job=TeamAudioStore(service.connection_factory).work(datetime.fromtimestamp(service.clock(),timezone.utc))
        if job.get('state')=='pending':
            document=store.get_report(job['reportKey'],job['version'])
            if not document or document['fingerprint']!=job['fingerprint']:
                raise AlphaError('Audio report changed.',409)
            return app._json(start_response,200,{'state':'ready','job':job,'report':document},extra_headers=[('Cache-Control','private, no-store')])
        return app._json(start_response,200,{'state':'idle','audioState':job.get('audioState','ready' if job.get('state')=='already_stored' else 'unavailable')},extra_headers=[('Cache-Control','private, no-store')])
    if tail=='/audio' and method=='POST':
        authorize(environ,values,'observer')
        from .agent_team_audio import TeamAudioStore
        return app._json(start_response,200,TeamAudioStore(service.connection_factory).put(body(environ,3*1024*1024)))
    if tail in ('/events','/verification-events') and method=='POST':
        role='observer' if tail=='/events' else 'verifier'
        authorize(environ,values,role)
        return app._json(start_response,200,store.ingest(body(environ).get('events'),role=='verifier'))
    if tail=='/decisions' and method=='POST':
        principal=authenticated_user(app,environ,service,values)
        return app._json(start_response,200,store.decision(body(environ),principal))
    if tail=='/status' and method=='GET':
        authorize_reader(app,environ,service,values)
        return app._json(start_response,200,{'state':'enabled','schedulerOwner':'existing_vercel_worker','timezone':'America/Indiana/Indianapolis',
            'workdayBoundary':'01:00','cutoffs':['17:00','01:00'],'nightPhone':False,'callEnabled':str(values.get('JAMES_AGENT_TEAM_CALL_ENABLED','0')).lower() in ('1','true'),
            'nativeRecoveryState':'not_connected','audioState':'not_connected','reportDeliveryState':'not_connected'})
    if tail.startswith('/reports/') and method=='GET':
        authorize_reader(app,environ,service,values)
        parts=tail.split('/')
        if len(parts)!=5 or parts[3] not in ('half_day','whole_day') or parts[4] not in ('json','svg','html','wav'):raise AlphaError('Unknown report route.',404)
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',parts[2]):raise AlphaError('Invalid workday.',400)
        try:p=period(parts[2],parts[3])
        except ValueError:raise AlphaError('Invalid period.',400) from None
        query=parse_qs(environ.get('QUERY_STRING',''),keep_blank_values=True)
        if set(query)-{'version'} or ('version' in query and (len(query['version'])!=1 or not re.fullmatch(r'[1-9]\d{0,3}',query['version'][0]))):
            raise AlphaError('Invalid report query.',400)
        d=store.get_report(p.key,int(query['version'][0])) if 'version' in query else store.get_report(p.key)
        if not d:raise AlphaError('Report unavailable.',404)
        identity_headers=[('X-Agent-Team-Report-Version',str(d.get('version',1))),('X-Agent-Team-Report-Fingerprint',d['fingerprint'])]
        if parts[4]=='wav':
            from .agent_team_audio import TeamAudioStore
            asset=TeamAudioStore(service.connection_factory).get(p.key,d['fingerprint'])
            if not asset:raise AlphaError('Report audio unavailable.',404,code='agent_team_audio_unavailable')
            metadata,data=asset
            start_response('200 OK',identity_headers+[('Content-Type','audio/wav'),('Content-Length',str(len(data))),('Cache-Control','private, no-store'),('X-Content-Type-Options','nosniff'),('X-Agent-Team-Audio-Sha256',metadata['sha256'])])
            return [data]
        if parts[4]=='json':
            def private_response(status,headers,exc_info=None):
                private_headers=[(k,v) for k,v in headers if k.lower()!='cache-control']+[('Cache-Control','private, no-store')]
                return start_response(status,private_headers,exc_info) if exc_info else start_response(status,private_headers)
            return app._json(private_response,200,d,extra_headers=identity_headers)
        result=svg(d) if parts[4]=='svg' else html(d)
        mime='image/svg+xml' if parts[4]=='svg' else 'text/html'
        start_response('200 OK',identity_headers+[('Content-Type',mime+'; charset=utf-8'),('Cache-Control','private, no-store'),('X-Content-Type-Options','nosniff'),('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")])
        return [result.encode()]
    raise AlphaError('Unknown Agent Team route.',404)
