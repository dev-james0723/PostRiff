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
from .agent_team_cutover import call_enabled as agent_team_call_enabled, cutover_source, team_enabled
from agent_team.events import Event, canonical
from agent_team.periods import aware, latest_due, period
from agent_team.reports import EXPECTED_SOURCES, report, svg, html

PREFIX='/api/internal/james-agent-team'


def enabled(values):
    return team_enabled(values)


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


READINESS_MIGRATIONS={
    '091':{
        'pr_agent_team_events':('event_key','source','source_id','revision','happened_at','observed_at','received_at','mission_id','project_id','document','immutable_digest'),
        'pr_agent_team_reports':('report_key','fingerprint','kind','workday','cutoff','generated_at','document'),
        'pr_agent_team_effects':('effect_key','report_key','kind','state','external_id','failure_class','created_at','updated_at'),
        'pr_agent_team_leases':('scope','owner','generation','expires_at','updated_at'),
        'pr_agent_team_decisions':('decision_key','mission_id','scope_version','call_run_id','question_version','choice','authenticated_user_id','received_at','execution_state'),
    },
    '092':{'pr_agent_team_audio_assets':('report_key','fingerprint','report_version','summary_hash','narration_hash','excerpt','sha256','mime','producer','observed_at','byte_count','duration_ms','wav_data','created_at')},
    '093':{
        'pr_agent_team_call_evidence':('call_id','evidence_kind','provider','source','evidence_sha256','observed_at','input_frames','output_frames','playback_ack_sha256','created_at'),
        'pr_agent_team_decisions':('workspace_id','question_sha256','authorization_sha256','registration_sha256','execution_binding_sha256','completion_requirement_refs','attended_call_id','effect_key'),
    },
    '094':{
        'pr_agent_team_mission_registry':('mission_id','actor_id','workspace_id','registration_sha256','execution_sha256','ordinal','registration_document','execution_document','attestation_document','attestation_sha256','observed_at','created_at'),
        'pr_agent_team_native_receipts':('decision_key','resume_request_id','receipt_sha256','execution_state','document','observed_at','created_at'),
    },
    '095':{
        'pr_agent_team_spoken_choices':('call_run_id','question_sha256','call_id','choice','candidate_sha256','document','captured_at'),
        'pr_agent_team_decisions':('spoken_choice_sha256',),
    },
}
READINESS_BINDING_COLUMNS={
    'pr_profiles':('user_id','deleted_at'),
    'pr_memberships':('user_id','workspace_id','status','role'),
    'pr_connector_credentials':('workspace_id','member_id','provider','connection_id','provider_account_id','revoked_at'),
}


def _readiness_reader(environ,values):
    # Readiness has no human-session fallback, including while the feature is off.
    authorize(environ,values,'reader')
    supplied=environ.get('HTTP_AUTHORIZATION','')
    for role in ('observer','verifier'):
        token=str(values.get('JAMES_AGENT_TEAM_'+role.upper()+'_TOKEN') or '')
        if 32<=len(token)<=512 and hmac.compare_digest(supplied,'Bearer '+token):
            raise AlphaError('Agent Team authorization failed.',401,code='agent_team_unauthorized')


def readiness(service,values):
    """Bounded metadata/EXISTS reads. This never admits a call or native action."""
    from .james_daily_call import DailyCallConfig
    cfg=getattr(getattr(service,'james_daily_call',None),'cfg',None) or DailyCallConfig(values)
    team_enabled=enabled(values)
    team_call_enabled=agent_team_call_enabled(values)
    tokens=[str(values.get('JAMES_AGENT_TEAM_'+role.upper()+'_TOKEN') or '') for role in ('observer','reader','verifier')]
    roles_ready=all(32<=len(token)<=512 for token in tokens) and len(set(tokens))==3
    blockers=[]
    policy={}
    for name,attribute in (('dailyCallEnabled','enabled'),('outboundEnabled','outbound_enabled'),
            ('dailyScheduledEnabled','scheduled_enabled'),('acceptanceEnabled','acceptance_enabled'),
            ('requireBriefingSources','require_sources'),('maxSeconds','max_seconds'),
            ('dailyCapUsdMicro','daily_cap'),('monthlyCapUsdMicro','monthly_cap'),
            ('quietStartMinute','quiet_start'),('quietEndMinute','quiet_end'),('timeZone','time_zone')):
        try:policy[name]=getattr(cfg,attribute)
        except (AlphaError,ValueError,TypeError,AttributeError):
            policy[name]=None
            if 'call_policy_invalid' not in blockers:blockers.append('call_policy_invalid')
    policy['reportCallMaxSeconds']=min(policy['maxSeconds'],90) if policy['maxSeconds'] is not None else None
    if not policy['dailyCallEnabled']:blockers.append('daily_call_disabled')
    if not policy['outboundEnabled']:blockers.append('outbound_disabled')
    if not policy['dailyCapUsdMicro'] or not policy['monthlyCapUsdMicro']:blockers.append('cost_cap_unset')
    if policy['timeZone']!='America/Indiana/Indianapolis':blockers.append('report_time_zone_mismatch')
    try:
        user_id=cfg.user_id;workspace_id=cfg.workspace_id
        # Keep invalid configuration away from row queries, even with test doubles.
        user_id=str(uuid.UUID(user_id));workspace_id=str(uuid.UUID(workspace_id))
        principal_configured=True
    except (AlphaError,ValueError,TypeError,AttributeError):
        user_id=workspace_id=None;principal_configured=False
        blockers.append('principal_unconfigured')
    try:bindings=cfg.briefing_bindings;bindings_configured=True
    except (AlphaError,ValueError,TypeError,AttributeError):
        bindings={};bindings_configured=False;blockers.append('personal_binding_unconfigured')
    binding={'principalConfigured':principal_configured,'profileActive':False,'membershipActive':False,
             'membershipCanEdit':False,'personalBindingsConfigured':bindings_configured,
             'gmailConnectionBound':False,'calendarConnectionBound':False,
             'providerIdentityState':'unverified'}
    required={**READINESS_BINDING_COLUMNS}
    for tables in READINESS_MIGRATIONS.values():
        for table,columns in tables.items():required[table]=tuple(sorted(set(required.get(table,()))|set(columns)))
    present={table:set() for table in required}
    database_available=False
    try:
        if service is None:raise RuntimeError('runtime_unavailable')
        with service.connection_factory() as db,db.cursor() as cur:
            cur.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=ANY(%s) AND column_name=ANY(%s) LIMIT 256",
                        (list(required),sorted({column for columns in required.values() for column in columns})))
            for table,column in cur.fetchall():
                if table in required and column in required[table]:present[table].add(column)
            database_available=True
            profile_schema=set(READINESS_BINDING_COLUMNS['pr_profiles'])<=present['pr_profiles']
            member_schema=set(READINESS_BINDING_COLUMNS['pr_memberships'])<=present['pr_memberships']
            if principal_configured and profile_schema and member_schema:
                cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL), EXISTS(SELECT 1 FROM public.pr_memberships WHERE user_id=%s AND workspace_id=%s AND status='active'), EXISTS(SELECT 1 FROM public.pr_memberships WHERE user_id=%s AND workspace_id=%s AND status='active' AND role IN ('owner','admin','editor'))",
                            (user_id,user_id,workspace_id,user_id,workspace_id))
                row=cur.fetchone()
                if row:binding.update(profileActive=row[0] is True,membershipActive=row[1] is True,membershipCanEdit=row[2] is True)
            connector_schema=set(READINESS_BINDING_COLUMNS['pr_connector_credentials'])<=present['pr_connector_credentials']
            if principal_configured and bindings_configured and connector_schema:
                for provider,field in (('gmail','gmailConnectionBound'),('google_calendar','calendarConnectionBound')):
                    expected=bindings[provider]
                    cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_connector_credentials WHERE workspace_id=%s AND member_id=%s AND provider=%s AND connection_id=%s AND lower(provider_account_id)=%s AND revoked_at IS NULL)",
                                (workspace_id,user_id,provider,expected['connectionId'],expected['account']))
                    row=cur.fetchone();binding[field]=bool(row and row[0] is True)
    except Exception:
        # No SQL, endpoint, identity, provider error or private value reaches the receipt.
        database_available=False
        for field in ('profileActive','membershipActive','membershipCanEdit','gmailConnectionBound','calendarConnectionBound'):binding[field]=False
    migrations={}
    for migration,tables in READINESS_MIGRATIONS.items():
        missing_tables=sorted(table for table in tables if not present[table])
        missing_columns=sorted(table+'.'+column for table,columns in tables.items() if present[table] for column in columns if column not in present[table])
        migrations[migration]={'ready':database_available and not missing_tables and not missing_columns,
                               'missingTables':missing_tables,'missingColumns':missing_columns}
    binding_schema=all(set(columns)<=present[table] for table,columns in READINESS_BINDING_COLUMNS.items())
    if not database_available:blockers.append('database_unavailable')
    if not all(item['ready'] for item in migrations.values()):blockers.append('database_migrations_incomplete')
    if not binding_schema:blockers.append('binding_schema_incomplete')
    if not roles_ready:blockers.append('role_secrets_unconfigured')
    for field,problem in (('profileActive','profile_inactive'),('membershipActive','membership_inactive'),
                          ('membershipCanEdit','membership_cannot_edit'),('gmailConnectionBound','gmail_binding_unverified'),
                          ('calendarConnectionBound','calendar_binding_unverified')):
        if not binding[field]:blockers.append(problem)
    configuration_ready=not blockers
    if not team_enabled:blockers.append('team_disabled')
    if not team_call_enabled:blockers.append('team_call_disabled')
    # Configuration and transport freshness are separate evidence. A role flag,
    # a newly received backlog, or an empty successful scan is not activity or
    # full-day coverage. Read only bounded metadata; never return event bodies.
    now=datetime.now(timezone.utc);window_start=now-timedelta(seconds=600)
    ingress={'state':'unavailable','healthy':False,'checkedAt':now.isoformat(),
             'windowStart':window_start.isoformat(),'windowSeconds':600,'rowLimit':1000,
             'boundedRowCount':0,'recentObservedRowCount':0,'countsComplete':False,
             'sourceCounts':{},'latestReceivedAt':None,'latestObservedAt':None,
             'receivedAgeSeconds':None,'observedAgeSeconds':None,
             'dailyCoverageComplete':False,'gaps':['bounded_metadata_only','full_day_screen_audio_unverified'],
             'coverageHealth':[]}
    ingress_columns={'source','source_id','observed_at','received_at','document','event_key'}
    ingress_binding=principal_configured and all(binding[field] for field in
        ('profileActive','membershipActive','membershipCanEdit','gmailConnectionBound','calendarConnectionBound'))
    if not database_available:ingress['reason']='database_unavailable'
    elif not ingress_binding:ingress['reason']='binding_unverified'
    elif not ingress_columns<=present['pr_agent_team_events']:ingress['reason']='ingress_schema_incomplete'
    else:
        try:
            with service.connection_factory() as db,db.cursor() as cur:
                cur.execute("SELECT source,CASE WHEN source='health' THEN source_id END,observed_at,received_at,document#>>'{payload,kind}',document#>>'{payload,sourceStatus}',document#>>'{payload,sourceFreshAt}',CASE WHEN source='health' THEN document#>'{payload,gaps}' END FROM public.pr_agent_team_events WHERE received_at>=%s AND received_at<=%s ORDER BY received_at DESC,event_key LIMIT 1001",
                            (window_start,now))
                rows=cur.fetchall()
            truncated=len(rows)>1000;latest_received=None;latest_observed=None;health={}
            safe_gaps={'bounded_scan_only','source_freshness_unknown','source_missing','source_stale',
                       'source_timestamp_unknown_or_future','permission_denied','query_limit','event_limit',
                       'line_limit','record_size_limit','tail_window_only','incomplete_jsonl_tail',
                       'thread_page_limit','thread_timestamp_unknown','exact_workspace_mismatch',
                       'codex_metadata_query_failed','workspace_not_connected','native_poll_failed',
                       'writer_ownership_unproven','budget_unknown','recorded_state_not_live_writer_proof',
                       'untracked_files_not_scanned','submodules_not_scanned','gh_metadata_not_authorized',
                       'gh_metadata_unavailable','gh_ci_page_limit','gh_deployment_page_limit',
                       'token_pilot_usage_receipt_unavailable','source_not_verified'}
            for source,source_id,observed,received,kind,status,fresh,gaps in rows[:1000]:
                observed=aware(observed);received=aware(received)
                if not window_start<=received<=now:continue
                if source not in (*EXPECTED_SOURCES,'health','acceptance','incident'):continue
                ingress['boundedRowCount']+=1
                ingress['sourceCounts'][source]=ingress['sourceCounts'].get(source,0)+1
                latest_received=max(latest_received or received,received)
                latest_observed=max(latest_observed or observed,observed)
                if window_start<=observed<=now:ingress['recentObservedRowCount']+=1
                if observed>now:ingress['gaps'].append('future_observation_not_fresh')
                if source!='health' or source_id not in EXPECTED_SOURCES or kind!='source_coverage':continue
                if source_id in health and observed<=aware(health[source_id]['observedAt']):continue
                status=status if status in ('ok','partial','not_connected','unavailable','blocked','disabled','unknown') else 'unknown'
                reported_gaps=gaps if isinstance(gaps,list) else ['invalid_source_coverage']
                known_gaps=sorted({gap for gap in reported_gaps if isinstance(gap,str) and gap in safe_gaps})
                if len(known_gaps)!=len(set(gap for gap in reported_gaps if isinstance(gap,str))):known_gaps.append('additional_reported_coverage_gaps')
                try:fresh_at=aware(fresh) if fresh is not None else None
                except (TypeError,ValueError):fresh_at=None
                if fresh_at is not None and (fresh_at>observed or fresh_at>now):fresh_at=None
                if fresh_at is None:known_gaps.append('source_freshness_unknown')
                health[source_id]={'source':source_id,'status':status,'observedAt':observed.isoformat(),
                    'receivedAt':received.isoformat(),'freshAt':fresh_at.isoformat() if fresh_at else None,
                    'fresh':fresh_at is not None and window_start<=fresh_at<=now,
                    'dailyCoverageComplete':False,'gaps':sorted(set(known_gaps))}
            ingress['countsComplete']=not truncated
            if latest_received is not None:
                ingress.update(latestReceivedAt=latest_received.isoformat(),latestObservedAt=latest_observed.isoformat(),
                    receivedAgeSeconds=(now-latest_received).total_seconds(),observedAgeSeconds=(now-latest_observed).total_seconds())
            ingress['healthy']=bool(ingress['recentObservedRowCount']) and not truncated
            ingress['state']='partial' if truncated else 'healthy' if ingress['healthy'] else 'stale' if ingress['boundedRowCount'] else 'empty'
            if truncated:ingress['gaps'].append('recent_ingress_query_limit')
            if ingress['boundedRowCount'] and not ingress['recentObservedRowCount']:ingress['gaps'].append('recent_upload_contains_only_stale_observations')
            for source in EXPECTED_SOURCES:
                ingress['coverageHealth'].append(health.get(source,{'source':source,'status':'unknown',
                    'observedAt':None,'receivedAt':None,'freshAt':None,'fresh':False,
                    'dailyCoverageComplete':False,'gaps':['recent_source_health_missing']}))
        except Exception:
            # An ingress read failure does not rewrite already verified config.
            ingress.update(state='unavailable',healthy=False,countsComplete=False,reason='ingress_query_unavailable')
    ingress['gaps']=sorted(set(ingress['gaps']))
    return {'readiness':'ready' if not blockers else 'blocked','configurationReady':configuration_ready,
            'enabled':team_enabled,'callEnabled':team_call_enabled,'cutoverSource':cutover_source(values),'roleSecretsConfigured':roles_ready,
            'databaseAvailable':database_available,'databaseMigrations':migrations,
            'migrationCheck':'required_tables_and_columns','binding':binding,'callPolicy':policy,
            'blockers':blockers,'nativeState':'unverified','scheduleState':'unverified',
            'callAdmissionState':'not_evaluated','ingress':ingress}


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

    def get_acceptance(self, acceptance_id):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT document FROM public.pr_agent_team_reports WHERE report_key LIKE %s ORDER BY generated_at LIMIT 2",
                        ('agent-team:acceptance:v1:%:' + acceptance_id + ':half_day',))
            rows = cur.fetchall()
        if len(rows) > 1:
            raise AlphaError('Acceptance identity conflict.', 409)
        return rows[0][0] if rows else None

    def reserve_effect(self,key,report_key,kind):
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('INSERT INTO public.pr_agent_team_effects(effect_key,report_key,kind,state) VALUES(%s,%s,%s,\'reserved\') ON CONFLICT DO NOTHING RETURNING effect_key',(key,report_key,kind));new=cur.fetchone()
            db.commit()
        # Unknown or abandoned reservation is reconciled externally; never blindly repeat it.
        return bool(new)

    def effect(self,key,state,external_id=None,failure_class=None):
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('UPDATE public.pr_agent_team_effects SET state=%s,external_id=%s,failure_class=%s,updated_at=now() WHERE effect_key=%s',(state,external_id,failure_class,key));db.commit()

    def decision(self,d,user_id,workspace_id=None,now=None):
        from .agent_team_decision import HASH,validate_question,decision_effect_key
        required={'decisionKey','missionId','scopeVersion','callRunId','questionVersion','choice'}
        if not isinstance(d,dict) or set(d)!=required or d['choice'] not in ('continue','wait','needs_human'):raise AlphaError('Invalid decision.',400)
        for key in required-{'callRunId'}:
            if not isinstance(d[key],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',d[key]):raise AlphaError('Invalid decision identity.',400)
        try:
            uuid.UUID(d['callRunId']);uuid.UUID(user_id)
            if workspace_id is None:return {'state':'blocked','executionState':'not_dispatched','reason':'decision_binding_unconfigured'}
            workspace_id=str(uuid.UUID(workspace_id))
        except (ValueError,TypeError):raise AlphaError('Invalid call identity.',400) from None
        now=datetime.now(timezone.utc).timestamp() if now is None else now
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute('SELECT context,user_id::text,workspace_id::text,origin,first_call_id::text,retry_call_id::text FROM public.pr_james_daily_call_runs WHERE id=%s',(d['callRunId'],));row=cur.fetchone()
            if not row or row[1]!=user_id or row[2]!=workspace_id or row[3]!='agent_team_report':
                raise AlphaError('Decision does not match the authenticated mission call.',403)
            context=row[0] if row and isinstance(row[0],dict) else {}
            team=context.get('agentTeamReport',{})
            if not isinstance(team,dict) or not all(key in team for key in ('missionId','reportId','version','workday')):
                return {'state':'blocked','executionState':'not_dispatched','reason':'decision_report_binding_unavailable'}
            try:
                question=validate_question(context.get('agentTeamDecisionQuestion'),actor_id=user_id,workspace_id=workspace_id,
                    mission_id=team.get('missionId'),report_id=team.get('reportId'),report_version=team.get('version'),now=now)
            except AlphaError as error:
                return {'state':'blocked','executionState':'not_dispatched','reason':error.code or 'decision_question_unavailable'}
            from agent_team.acceptance import question_report_key
            if question['reportKey']!=question_report_key(context) or (question['missionId'],question['scopeVersion'],question['questionVersion'])!=(d['missionId'],d['scopeVersion'],d['questionVersion']):
                raise AlphaError('Decision does not match the authenticated mission call.',403)
            from .agent_team_spoken import pending_choice
            spoken=pending_choice(cur,d['callRunId'],question,d['choice'])
            # completed/answered/socket/clock alone do not prove an attended call.
            # Positive human + bidirectional receipts are private server observations.
            call_ids=list(dict.fromkeys(value for value in row[4:6] if value))
            cur.execute("SELECT c.id::text,c.provider,c.state,c.answered_at IS NOT NULL,c.ended_at IS NOT NULL,coalesce(c.duration_seconds,0)>0,c.media_claimed_at IS NOT NULL,EXISTS(SELECT 1 FROM public.pr_phone_provider_events e WHERE e.call_id=c.id AND e.provider=c.provider AND e.state='completed'),(SELECT e.evidence_sha256 FROM public.pr_agent_team_call_evidence e WHERE e.call_id=c.id AND e.provider=c.provider AND e.evidence_kind='human' AND e.source='signed_provider_human_detection'),(SELECT e.evidence_sha256 FROM public.pr_agent_team_call_evidence e WHERE e.call_id=c.id AND e.provider=c.provider AND e.evidence_kind='media' AND e.source='authenticated_bidirectional_media' AND e.input_frames>0 AND e.output_frames>0 AND e.playback_ack_sha256 ~ '^[0-9a-f]{64}$') FROM public.pr_phone_calls c WHERE c.id=ANY(%s::uuid[]) AND c.user_id=%s AND c.workspace_id=%s AND c.direction='outbound' AND c.destination_ref='james_env' AND c.reason_key=%s AND c.provider IN ('twilio','dial','telnyx') AND c.provider_call_ref IS NOT NULL AND c.state='completed' ORDER BY c.ended_at DESC LIMIT 2",
                        (call_ids,user_id,workspace_id,'james_daily:'+d['callRunId']))
            attended=next((call for call in cur.fetchall() if call[1] in ('twilio','dial','telnyx') and call[2]=='completed' and
                           all(value is True for value in call[3:8]) and all(isinstance(value,str) and HASH.fullmatch(value) for value in call[8:10]) and
                           (not spoken or call[0]==spoken[1])),None)
            if not attended:return {'state':'blocked','executionState':'not_dispatched','reason':'attended_call_unverified'}
            effect_key=decision_effect_key(d['callRunId'],question)
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(effect_key,))
            expected=(question['missionId'],question['scopeVersion'],d['callRunId'],question['questionVersion'],d['choice'],user_id,
                      workspace_id,question['questionSha256'],question['authorizationSha256'],question['registrationSha256'],
                      question['executionBindingSha256'],question['completionRequirementRefs'],attended[0],effect_key,spoken[2] if spoken else None)
            cur.execute('INSERT INTO public.pr_agent_team_decisions(decision_key,mission_id,scope_version,call_run_id,question_version,choice,authenticated_user_id,workspace_id,question_sha256,authorization_sha256,registration_sha256,execution_binding_sha256,completion_requirement_refs,attended_call_id,effect_key,spoken_choice_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(call_run_id,mission_id,scope_version,question_version) DO NOTHING RETURNING decision_key',
                        (effect_key,)+expected)
            created=bool(cur.fetchone())
            cur.execute('SELECT mission_id,scope_version,call_run_id::text,question_version,choice,authenticated_user_id::text,workspace_id::text,question_sha256,authorization_sha256,registration_sha256,execution_binding_sha256,completion_requirement_refs,attended_call_id::text,effect_key,spoken_choice_sha256 FROM public.pr_agent_team_decisions WHERE call_run_id=%s AND mission_id=%s AND scope_version=%s AND question_version=%s',
                        (d['callRunId'],question['missionId'],question['scopeVersion'],question['questionVersion']))
            old=cur.fetchone()
            if not old or tuple(old)!=expected:raise AlphaError('This mission question already records another immutable choice.',409,code='decision_choice_conflict')
            db.commit()
        return {'state':'recorded','executionState':'not_dispatched','decisionKey':effect_key,'effectKey':effect_key,'replayed':not created,
                'decisionSource':'authenticated_session_confirmed_phone_choice' if spoken else 'authenticated_session',
                'spokenChoiceSha256':spoken[2] if spoken else None}


def source_coverage(events,p,generated_at=None):
    generated=aware(generated_at or datetime.now(timezone.utc))
    result={source:{'status':'unknown','freshAt':None,'complete':False,'gaps':['source_not_verified']} for source in EXPECTED_SOURCES}
    latest={}
    for e in events:
        if e['source']!='health' or e['payload'].get('kind')!='source_coverage':continue
        source=e['source_id'];payload=e['payload']
        if source not in result:continue
        try:
            observed=aware(e['observed_at'])
            effective=aware(payload['sourceFreshAt']) if payload.get('sourceFreshAt') is not None else None
            # Scan/observation clocks rank unknown evidence but never prove source freshness.
            rank_at=effective or aware(payload.get('scannedAt') or e['happened_at'])
        except (TypeError,ValueError):continue
        if observed>generated or rank_at>p.cutoff or (effective is not None and effective>observed):continue
        rank=(rank_at,observed,e['revision'],e['key'])
        if source in latest and rank<=latest[source]:continue
        latest[source]=rank
        gaps=payload.get('gaps',[])
        if not isinstance(gaps,list) or any(not isinstance(gap,str) for gap in gaps):gaps=['invalid_source_coverage']
        if effective is None:
            if 'source_freshness_unknown' not in gaps:gaps=gaps+['source_freshness_unknown']
            result[source]={'status':'unknown','freshAt':None,'complete':False,'gaps':gaps}
            continue
        age=(p.cutoff-effective).total_seconds()
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
        status=_with_delivery(service,prior,{'state':'already_generated','reportKey':p.key,'fingerprint':prior['fingerprint'],
                'version':prior.get('version',1),'deliveryState':'inspect_effect_receipt','callState':'disabled'})
        return _report_call(service,values,store,p,now,prior,status,historical=historical)
    doc,created=store.put_report(doc)
    if not created:
        status=_with_delivery(service,doc,{'state':'already_generated','reportKey':p.key,'fingerprint':doc['fingerprint'],
                'version':doc.get('version',1),'deliveryState':'inspect_effect_receipt','callState':'disabled'})
        return _report_call(service,values,store,p,now,doc,status,historical=historical)
    # Persist report independently of call/delivery; unavailable connector cannot hold it indefinitely.
    supplement=bool(prior or doc.get('supplementOf'))
    status={'state':'supplemented' if supplement else 'generated','reportKey':p.key,'fingerprint':doc['fingerprint'],
            'version':doc['version'],'deliveryState':'not_delivered','callState':'disabled','audioState':'unavailable'}
    status=_with_delivery(service,doc,status)
    return _report_call(service,values,store,p,now,doc,status,supplement=supplement,historical=historical)


def _report_call(service,values,store,p,now,doc,status,supplement=False,historical=False):
    if p.kind=='whole_day':return status
    if supplement or doc.get('supplementOf') or historical:
        status['callState']='supplement_no_call';return status
    if not agent_team_call_enabled(values):return status
    if (now-p.cutoff).total_seconds()>900:
        status['callState']='missed_window';return status
    try:
        question=_report_question(service,doc)
        question_document=question.document(now=now.timestamp())
    except AlphaError as error:
        # No phone effect is reserved until the original native mission binding
        # is verified. A generic report call cannot collect decision evidence.
        status.update(callState='blocked',callFailure=error.code or 'decision_registration_unavailable');return status
    except Exception:
        status.update(callState='blocked',callFailure='decision_registry_unavailable');return status
    effect=p.key+':call'
    if not store.reserve_effect(effect,p.key,'phone'):status['callState']='reconciliation_required';return status
    try:
        result=service.james_daily_call.call_report(report_id=doc['fingerprint'],mission_id=question_document['missionId'],workday=p.workday,version=doc['version'],briefing={
            'kind':p.kind,'verified':True,'timeZone':'America/Indiana/Indianapolis','cutoffLocalTime':'17:00',
            'generatedAt':aware(doc.get('initialGeneratedAt') or doc['generatedAt']).timestamp(),'summary':doc['summary'],'coverageGaps':doc['gaps'][:20],'evidenceRefs':[x['id'] for x in doc['evidence']][:20]},decision_question=question)
        store.effect(effect,'submitted',result.get('id'));status['callState']=result.get('state','unknown')
    except AlphaError as error:
        store.effect(effect,'failed',failure_class=error.code or 'admission_blocked');status['callState']='blocked'
    except Exception:
        store.effect(effect,'unknown',failure_class='reconciliation_required');status['callState']='unknown'
    return status


def _report_question(service,document,mission_id=None):
    from .agent_team_registry import CloudMissionRegistry
    cfg=service.james_daily_call.cfg
    return CloudMissionRegistry(service.connection_factory,cfg.user_id,cfg.workspace_id,service.clock).for_report(document,mission_id)


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
    tail=path[len(PREFIX):]
    if tail=='/readiness' and method=='GET':
        _readiness_reader(environ,values)
        try:service=app._runtime()
        except Exception:service=None
        return app._json(start_response,200,readiness(service,values),extra_headers=[('Cache-Control','private, no-store')])
    if not enabled(values):raise AlphaError('Agent Team is disabled.',503,code='agent_team_disabled')
    service=app._runtime();store=TeamStore(service.connection_factory)
    if tail.startswith('/acceptance/'):
        from .agent_team_acceptance import require_acceptance, acceptance_report, call_acceptance
        require_acceptance(values)
        if tail == '/acceptance/as-of-now' and method == 'POST':
            authorize(environ, values, 'verifier')
            doc, created = acceptance_report(service, values, store, body(environ))
            result = _with_delivery(service, doc, {'state': 'generated' if created else 'already_generated',
                'executionMode': 'staging_acceptance', 'reportKey': doc['period']['key'],
                'reportId': doc['fingerprint'], 'version': doc['version'], 'evidenceCount': len(doc['evidence'])})
            return app._json(start_response, 200, result, extra_headers=[('Cache-Control', 'private, no-store')])
        match = re.fullmatch(r'/acceptance/([0-9a-f-]{36})/(json|svg|html|wav|delivery|call)', tail)
        try:
            valid_id = bool(match and str(uuid.UUID(match[1])) == match[1])
        except ValueError:
            valid_id = False
        if not valid_id:
            raise AlphaError('Unknown acceptance route.', 404)
        acceptance_id, fmt = match.groups()
        if fmt == 'call' and method == 'POST':
            authorize(environ, values, 'verifier')
            request = body(environ)
            if set(request) != {'missionId'} or not isinstance(request['missionId'], str):
                raise AlphaError('Invalid acceptance call request.', 400)
        elif method == 'GET':
            authorize_reader(app, environ, service, values)
        else:
            raise AlphaError('Unknown acceptance method.', 404)
        doc = store.get_acceptance(acceptance_id)
        if not doc:
            raise AlphaError('Acceptance report unavailable.', 404)
        if fmt == 'call':
            result = call_acceptance(service, values, store, doc, request['missionId'])
            return app._json(start_response, 200, result, extra_headers=[('Cache-Control', 'private, no-store')])
        if fmt == 'delivery':
            from .agent_team_delivery import TeamDeliveryService, with_stored_audio
            from .agent_team_audio import TeamAudioStore
            receipt = TeamDeliveryService(service).receipt(doc)
            asset = TeamAudioStore(service.connection_factory).get_metadata(doc['period']['key'], doc['fingerprint'])
            return app._json(start_response, 200, with_stored_audio(receipt, doc, asset), extra_headers=[('Cache-Control', 'private, no-store')])
        headers = [('Cache-Control', 'private, no-store'), ('X-Agent-Team-Report-Version', str(doc['version'])),
                   ('X-Agent-Team-Report-Fingerprint', doc['fingerprint'])]
        if fmt == 'json':
            return app._json(start_response, 200, doc, extra_headers=headers)
        if fmt == 'wav':
            from .agent_team_audio import TeamAudioStore
            asset = TeamAudioStore(service.connection_factory).get(doc['period']['key'], doc['fingerprint'])
            if not asset: raise AlphaError('Acceptance audio unavailable.', 404)
            metadata, data = asset
            start_response('200 OK', headers + [('Content-Type', 'audio/wav'), ('Content-Length', str(len(data))),
                ('X-Agent-Team-Audio-Sha256', metadata['sha256']), ('X-Agent-Team-Audio-Narration-Sha256', metadata['narrationHash'])])
            return [data]
        data = (svg(doc) if fmt == 'svg' else html(doc)).encode()
        mime = 'image/svg+xml' if fmt == 'svg' else 'text/html; charset=utf-8'
        start_response('200 OK', headers + [('Content-Type', mime), ('Content-Length', str(len(data))),
            ('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'")])
        return [data]
    if tail=='/mission-registry' and method=='POST':
        # A projection is native verifier authority, never ordinary observation.
        authorize(environ,values,'verifier')
        from .agent_team_registry import CloudMissionRegistry
        cfg=service.james_daily_call.cfg
        result=CloudMissionRegistry(service.connection_factory,cfg.user_id,cfg.workspace_id,service.clock).put(body(environ))
        return app._json(start_response,200,result,extra_headers=[('Cache-Control','private, no-store')])
    if tail in ('/native-work','/native-receipts'):
        authorize(environ,values,'verifier')
        from .agent_team_native import NativeDecisionBridge
        bridge=NativeDecisionBridge(service)
        if tail=='/native-work' and method=='GET':result=bridge.work()
        elif tail=='/native-receipts' and method=='POST':result=bridge.receipt(body(environ))
        else:raise AlphaError('Unknown native verifier route.',404)
        return app._json(start_response,200,result,extra_headers=[('Cache-Control','private, no-store')])
    if tail=='/audio-work' and method=='GET':
        authorize(environ,values,'observer')
        from .agent_team_audio import TeamAudioStore
        audio_store=TeamAudioStore(service.connection_factory)
        query=parse_qs(environ.get('QUERY_STRING',''),keep_blank_values=True)
        if query:
            from .agent_team_acceptance import require_acceptance
            require_acceptance(values)
            if set(query)!={'acceptanceId'} or len(query['acceptanceId'])!=1:
                raise AlphaError('Invalid acceptance audio query.',400)
            try:
                acceptance_id=str(uuid.UUID(query['acceptanceId'][0]))
                if acceptance_id!=query['acceptanceId'][0]:raise ValueError()
            except ValueError:raise AlphaError('Invalid acceptance audio identity.',400) from None
            document=store.get_acceptance(acceptance_id)
            if not document:raise AlphaError('Acceptance unavailable.',404)
            job=audio_store.work_for_report(document,datetime.fromtimestamp(service.clock(),timezone.utc))
        else:
            job=audio_store.work(datetime.fromtimestamp(service.clock(),timezone.utc))
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
        return app._json(start_response,200,store.decision(body(environ),principal,service.james_daily_call.cfg.workspace_id,service.clock()))
    if tail.startswith('/decisions/') and method=='GET':
        principal=authenticated_user(app,environ,service,values)
        from .agent_team_spoken import read_pending_choice
        result=read_pending_choice(service.connection_factory,tail[len('/decisions/'):],principal,service.james_daily_call.cfg.workspace_id,service.clock())
        return app._json(start_response,200,result,extra_headers=[('Cache-Control','private, no-store')])
    if tail=='/status' and method=='GET':
        authorize_reader(app,environ,service,values)
        return app._json(start_response,200,{'state':'enabled','schedulerOwner':'existing_vercel_worker','timezone':'America/Indiana/Indianapolis',
            'workdayBoundary':'01:00','cutoffs':['17:00','01:00'],'nightPhone':False,'callEnabled':agent_team_call_enabled(values),'cutoverSource':cutover_source(values),
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
            start_response('200 OK',identity_headers+[('Content-Type','audio/wav'),('Content-Length',str(len(data))),('Cache-Control','private, no-store'),('X-Content-Type-Options','nosniff'),('X-Agent-Team-Audio-Sha256',metadata['sha256']),('X-Agent-Team-Audio-Narration-Sha256',metadata['narrationHash'])])
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
