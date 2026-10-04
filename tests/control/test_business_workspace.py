"""Database-backed business workspace acceptance, exclusively on disposable PostgreSQL."""
import io
import hashlib
import json
import os
import time
import unittest
import uuid
import psycopg
from psycopg.types.json import Jsonb
from rafii_control import demo_dataset
from rafii_control.auth import Boundary,Config,VerifiedIdentity,ControlError,CAPABILITIES,READ_BUDGET
from rafii_control.store import PostgresStore,connection_factory
from rafii_control.workspace import WorkspaceService
from rafii_control.http import ControlApplication
from rafii_control.intelligence import QueryService
from postriff_phase2.hosted import PostgresWorkspaceRepository


@unittest.skipUnless(os.environ.get('RAFII_CONTROL_TEST_DSN'),'disposable database required')
class BusinessWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['RAFII_CONTROL_TEST_DSN']
        self.user=str(uuid.uuid4())
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('INSERT INTO auth.users(id) VALUES(%s)',(self.user,))
            self.workspace=str(con.execute("SELECT public.pr_bootstrap(%s,'studio')",(self.user,)).fetchone()[0])
            con.execute("UPDATE public.pr_profiles SET display_name='Fictional Founder Test' WHERE user_id=%s",(self.user,))
            con.execute("INSERT INTO rafii_control.platform_operators(user_id,environment,role,status,capabilities) VALUES(%s,'local','founder','active',%s)",(self.user,list(CAPABILITIES)))
            con.execute("INSERT INTO rafii_control.test_workspace_grants VALUES(%s,'local',%s,'disposable-test-only',now()+interval '1 hour')",(self.user,self.workspace))
        self.repository=PostgresWorkspaceRepository(lambda:psycopg.connect(self.dsn,prepare_threshold=None),lambda token:self.user)
        snapshot=self.repository.get(self.workspace,'synthetic-owner')
        self.repository.command(self.workspace,'synthetic-owner',snapshot['revision'],lambda data,actor:{**data,'workspace':{'id':self.workspace,'name':'Fictional Canonical Workspace'},'privateCanary':'DO_NOT_DISCLOSE_PRIVATE_731'})
        self.store=PostgresStore(connection_factory(self.dsn,'rafii_control_session','local'),connection_factory(self.dsn,'rafii_control_reader','local'),'local')
        self.boundary=Boundary(Config(True,'local','http://localhost:4449'),self.store,lambda token:VerifiedIdentity(self.user,'aal2','synthetic-session-'+self.user,time.time()))
        self.token,self.session=self.boundary.exchange('synthetic-identity','http://localhost:4449')
        self.principal=self.boundary.authorize(self.token,'control.read')
        self.service=WorkspaceService(self.store)

    def tearDown(self):
        # Fresh test actors share the global exchange limiter; isolate fixture budgets between cases.
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.request_budgets WHERE bucket=%s',(hashlib.sha256(b'exchange:global').hexdigest(),))

    def action(self,kind,target,value=''):
        return dict(action=kind,targetId=target,value=value,revision=self.service.demo(self.principal)['revision'],requestId=str(uuid.uuid4()))

    def request(self,path,method='GET',body=None,token=None):
        raw=json.dumps(body or {}).encode(); response={}
        env=dict(PATH_INFO='/api/control/v2'+path,REQUEST_METHOD=method,CONTENT_LENGTH=str(len(raw)),CONTENT_TYPE='application/json',HTTP_HOST='localhost:4449',HTTP_ORIGIN='http://localhost:4449',HTTP_COOKIE='__Host-rafii-control='+(token if token is not None else self.token),HTTP_X_CSRF_TOKEN=self.session['csrfToken'],**{'wsgi.input':io.BytesIO(raw)})
        app=ControlApplication(self.boundary,QueryService(self.store))
        result=json.loads(b''.join(app(env,lambda status,headers:response.update(status=int(status[:3])))))
        return response['status'],result

    def exhaust_read_budget(self):
        """Fill this minute's read budget. The window resets on the minute, so start with at least 30 s of it left:
        otherwise a slow run crosses the boundary and the budget is fresh again before the assertions run."""
        remaining=60-time.time()%60
        if remaining<30: time.sleep(remaining+0.25)
        bucket=hashlib.sha256(('control.read:'+self.user).encode()).hexdigest()
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute("INSERT INTO rafii_control.request_budgets(bucket,environment,window_start,attempts) VALUES(%s,'local',floor(extract(epoch from now())/60),%s) ON CONFLICT(bucket,environment) DO UPDATE SET window_start=excluded.window_start,attempts=excluded.attempts",(bucket,READ_BUDGET))

    def test_logout_remains_authorized_when_read_budget_is_exhausted(self):
        self.exhaust_read_budget()
        self.assertEqual(self.request('/session')[0],429)
        # Session termination still needs its ordinary founder, origin and CSRF checks.
        csrf=self.session['csrfToken'];self.session['csrfToken']='invalid'
        self.assertEqual(self.request('/session/logout','POST')[0],403)
        self.session['csrfToken']=csrf
        status,result=self.request('/session/logout','POST')
        self.assertEqual(status,200,result.get('code'))
        self.assertTrue(result['data']['loggedOut'])
        self.assertEqual(self.request('/session')[0],401)
        with psycopg.connect(self.dsn) as con:
            audit=con.execute("SELECT result FROM rafii_control.admin_audit_log WHERE request_id=%s",(result['requestId'],)).fetchall()
        self.assertIn(('succeeded',),audit)

    def test_canonical_rafii_creation_appears_and_reader_hides_private_content(self):
        status,result=self.request('/workspace/live')
        self.assertEqual(status,200)
        data=result['data']
        customer=next(c for c in data['customers'] if c['id']==self.user)
        workspace=next(w for w in data['workspaces'] if w['id']==self.workspace)
        self.assertEqual(customer['name'],'Fictional Founder Test')
        self.assertIn(self.workspace,customer['workspaceIds'])
        self.assertEqual(workspace['name'],'Fictional Canonical Workspace')
        self.assertNotIn('DO_NOT_DISCLOSE',json.dumps(data))
        self.assertEqual(data['mode'],'live')
        self.assertEqual(data['paymentState'],'not_configured')

    def test_approved_rename_persists_back_to_rafii_and_restores_with_one_retry_record(self):
        snapshot=self.repository.get(self.workspace,'synthetic-owner')
        payload=dict(workspaceId=self.workspace,name='Fictional Renamed Workspace',revision=snapshot['revision'],requestId=str(uuid.uuid4()))
        status,first=self.request('/workspace/live/rename','POST',payload)
        self.assertEqual(status,200,first)
        status,retry=self.request('/workspace/live/rename','POST',payload)
        self.assertEqual(status,200,retry)
        self.assertEqual(first['data'],retry['data'])
        reflected=self.repository.get(self.workspace,'synthetic-owner')
        self.assertEqual(reflected['state']['workspace']['name'],payload['name'])
        self.assertEqual(reflected['state']['privateCanary'],'DO_NOT_DISCLOSE_PRIVATE_731')
        changed={**payload,'name':'Conflicting retry'}
        self.assertEqual(self.request('/workspace/live/rename','POST',changed)[0],409)
        restore=dict(workspaceId=self.workspace,name='Fictional Canonical Workspace',revision=reflected['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.request('/workspace/live/rename','POST',restore)[0],200)
        self.assertEqual(self.repository.get(self.workspace,'synthetic-owner')['state']['workspace']['name'],'Fictional Canonical Workspace')
        with psycopg.connect(self.dsn) as con:
            count=con.execute("SELECT count(*) FROM rafii_control.workspace_actions WHERE operator_id=%s AND mode='live'",(self.user,)).fetchone()[0]
            self.assertEqual(count,2)

    def test_unapproved_workspace_stale_mfa_revoked_operator_and_unauthorized_http_fail_closed(self):
        payload=dict(workspaceId=self.workspace,name='Forbidden',revision=2,requestId=str(uuid.uuid4()))
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('DELETE FROM rafii_control.test_workspace_grants WHERE operator_id=%s',(self.user,))
        self.assertEqual(self.request('/workspace/live/rename','POST',payload)[0],403)
        self.assertEqual(self.request('/workspace/live',token='invalid')[0],401)
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('UPDATE rafii_control.founder_sessions SET mfa_at=created_at-299,created_at=created_at-2,expires_at=expires_at-2,last_seen_at=last_seen_at-2 WHERE user_id=%s',(self.user,))
            con.execute("UPDATE rafii_control.founder_sessions SET mfa_at=created_at-299 WHERE user_id=%s",(self.user,))
        self.assertEqual(self.request('/workspace/live/rename','POST',payload)[0],403)
        with psycopg.connect(self.dsn,autocommit=True) as con: con.execute("UPDATE rafii_control.platform_operators SET status='revoked' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.request('/workspace/live')[0],403)

    def test_pending_account_deletion_and_direct_reader_mutation_are_rejected(self):
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute("UPDATE public.pr_workspaces SET state=jsonb_set(state,'{accountDeletion}','true'::jsonb) WHERE id=%s",(self.workspace,))
        payload=dict(workspaceId=self.workspace,name='Forbidden',revision=2,requestId=str(uuid.uuid4()))
        self.assertEqual(self.request('/workspace/live/rename','POST',payload)[0],403)
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('SET ROLE rafii_control_reader')
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                con.execute('SELECT rafii_control.rename_test_workspace(%s,%s,%s,%s,%s,%s,%s)',(self.user,self.principal['session']['id'],'local',self.workspace,'Forbidden',2,str(uuid.uuid4())))

    def test_demo_linked_workflows_retry_reset_and_live_isolation(self):
        before=self.repository.get(self.workspace,'synthetic-owner')
        demo=self.service.demo(self.principal)
        renamed=self.action('rename_workspace','workspace-1','Demo only')
        response=self.service.demo(self.principal,renamed)
        self.assertEqual(response,self.service.demo(self.principal,renamed))
        self.assertEqual(self.service.demo(self.principal)['workspaces'][0]['name'],'Demo only')
        self.assertEqual(demo['summary']['currentPaidSubscriptions'],10000)
        self.assertEqual(len(demo['invoices']),30000)
        self.service.demo(self.principal,self.action('resolve_ticket','ticket-1'))
        self.assertEqual(self.service.demo(self.principal)['summary']['openRequests'],demo['summary']['openRequests']-1)
        self.service.demo(self.principal,self.action('reset','all'))
        self.assertEqual(self.service.demo(self.principal)['workspaces'][0]['name'],'Fern Studio')
        self.assertEqual(self.repository.get(self.workspace,'synthetic-owner'),before)
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('SET ROLE rafii_control_session')
            con.execute("SELECT set_config('rafii_control.environment','local',false)")
            self.assertEqual(con.execute('SELECT count(*) FROM rafii_control.demo_workspaces').fetchone()[0],0)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege): con.execute('SELECT state FROM public.pr_workspaces')

    def test_database_failure_is_an_explicit_error_not_an_empty_dataset(self):
        with psycopg.connect(self.dsn,autocommit=True) as con: con.execute('REVOKE SELECT ON rafii_control.business_customers FROM rafii_control_reader')
        try:
            status,result=self.request('/workspace/live')
            self.assertEqual(status,503)
            self.assertEqual(result['code'],'WORKSPACE_ACCESS_REQUIRED')
            self.assertNotIn('data',result)
        finally:
            with psycopg.connect(self.dsn,autocommit=True) as con: con.execute('GRANT SELECT ON rafii_control.business_customers TO rafii_control_reader')

    def customer_detail(self):
        return self.request('/workspace/live/query','POST',dict(collection='customers',search='',status='all',page=1,recordId=self.user))

    def test_live_customer_detail_reads_linked_canonical_records_without_other_tenants_or_private_content(self):
        ticket=str(uuid.uuid4()); invoice='fictional-invoice-'+uuid.uuid4().hex
        other=str(uuid.uuid4()); other_ticket=str(uuid.uuid4())
        with psycopg.connect(self.dsn,autocommit=True) as con:
            con.execute('INSERT INTO auth.users(id) VALUES(%s)',(other,))
            other_workspace=str(con.execute("SELECT public.pr_bootstrap(%s,'studio')",(other,)).fetchone()[0])
            con.execute("INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,provider,status) VALUES(%s,'studio-v1','fixture','active')",(self.workspace,))
            con.execute("INSERT INTO public.pr_connection_health(workspace_id,connection_id,provider,capability,level,state,connection_state) VALUES(%s,'fictional-link','fixture','analytics','Direct','ok','read_verified')",(self.workspace,))
            for wid,uid,tid,label in ((self.workspace,self.user,ticket,invoice),(other_workspace,other,other_ticket,'unrelated-'+invoice)):
                con.execute("INSERT INTO public.pr_invoices(invoice_id,provider,workspace_id,amount_due,amount_paid,currency,status,livemode,event_id,event_at) VALUES(%s,'stripe',%s,2500,2500,'usd','paid',false,%s,now())",(label,wid,'event-'+label))
                con.execute("INSERT INTO public.pr_support_tickets(id,workspace_id,created_by,category) VALUES(%s,%s,%s,'billing')",(tid,wid,uid))
                con.execute("INSERT INTO public.pr_support_messages(workspace_id,ticket_id,actor_id,actor_role,body,request_id,fingerprint) VALUES(%s,%s,%s,'customer','DO_NOT_DISCLOSE_PRIVATE_SUPPORT_731',%s,'local-only')",(wid,tid,uid,str(uuid.uuid4())))
            usage=str(con.execute("INSERT INTO public.pr_usage_ledger(workspace_id,kind,dimension,unit,cost_state,idempotency_key,meta) VALUES(%s,'adjust','action','credit','actual',%s,%s) RETURNING id",(self.workspace,uuid.uuid4().hex,Jsonb(dict(credits=dict(op='grant',milli=12500,source='test'),privateCanary='DO_NOT_DISCLOSE_RAW_LEDGER_731')))).fetchone()[0])
            event=str(con.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,meta) VALUES(%s,%s,'mfa.enabled',%s) RETURNING id",(self.workspace,self.user,Jsonb(dict(privateCanary='DO_NOT_DISCLOSE_AUDIT_731')))).fetchone()[0])
        status,response=self.customer_detail()
        self.assertEqual(status,200,response)
        data=response['data']; linked=data['linkedRecords']; coverage=data['linkedRecordCoverage']
        self.assertEqual(data['rows'][0]['id'],self.user)
        self.assertEqual(linked['subscriptions'][0]['workspaceId'],self.workspace)
        self.assertIsNone(linked['subscriptions'][0]['amountMinor'],'unapproved plan prices are never displayed as active terms')
        self.assertEqual([(r['id'],r['amountMinor'],r['currency']) for r in linked['invoices']],[(invoice,2500,'USD')])
        self.assertEqual([r['id'] for r in linked['tickets']],[ticket])
        self.assertEqual(linked['tickets'][0]['identityVisibility'],'masked')
        self.assertEqual([r['id'] for r in linked['credits']],[usage])
        self.assertEqual(linked['credits'][0]['quantity'],12.5)
        self.assertEqual(linked['credits'][0]['op'],'grant')
        self.assertEqual([r['id'] for r in linked['usage']],[usage])
        self.assertEqual(linked['usage'][0]['quantity'],1.0)
        self.assertEqual([r['id'] for r in linked['activity']],[event])
        self.assertEqual(linked['members'][0]['memberId'],self.user)
        self.assertEqual(linked['members'][0]['name'],'Fictional Founder Test')
        self.assertEqual(linked['connections'][0]['connectionId'],'fictional-link')
        for rows in linked.values():
            self.assertTrue(all(r['workspaceId']==self.workspace for r in rows))
        for section in ('subscriptions','invoices','tickets','credits','usage','activity','members','connections'):
            self.assertEqual(coverage[section],dict(state='connected',total=1,limit=50,truncated=False))
        # A missing required payment source remains explicit, never an invented zero or Demo fallback.
        self.assertNotIn('payments',linked)
        self.assertEqual(coverage['payments']['state'],'not_configured')
        self.assertIsNone(coverage['payments']['total'])
        encoded=json.dumps(data)
        for private in ('DO_NOT_DISCLOSE',other_workspace,other_ticket,'unrelated-'+invoice):self.assertNotIn(private,encoded)
        self.assertNotIn('body',linked['tickets'][0])
        self.assertNotIn('meta',linked['usage'][0])
        self.assertNotIn('email',linked['members'][0])

    def test_live_customer_history_is_bounded_and_reports_older_records(self):
        prefix='fictional-bounded-'+uuid.uuid4().hex
        with psycopg.connect(self.dsn,autocommit=True) as con:
            for index in range(54):
                con.execute("INSERT INTO public.pr_invoices(invoice_id,provider,workspace_id,amount_due,amount_paid,currency,status,livemode,event_id,event_at,recorded_at) VALUES(%s,'stripe',%s,100,0,'usd','open',false,%s,now(),now()+%s*interval '1 second')",(prefix+'-'+str(index),self.workspace,prefix+'-event-'+str(index),index))
        status,response=self.customer_detail()
        self.assertEqual(status,200,response)
        data=response['data']
        self.assertEqual(data['linkedRecordCoverage']['invoices'],dict(state='connected',total=54,limit=50,truncated=True))
        self.assertEqual(len(data['linkedRecords']['invoices']),50)
        self.assertEqual(data['linkedRecords']['invoices'][0]['id'],prefix+'-53')
        self.assertNotIn(prefix+'-0',{r['id'] for r in data['linkedRecords']['invoices']})

    def test_customer_detail_permission_failure_does_not_become_empty_history(self):
        with psycopg.connect(self.dsn,autocommit=True) as con:con.execute('REVOKE SELECT ON rafii_control.business_invoices FROM rafii_control_reader')
        try:
            status,response=self.customer_detail()
            self.assertEqual(status,503,response)
            self.assertEqual(response['code'],'WORKSPACE_ACCESS_REQUIRED')
            self.assertNotIn('data',response)
        finally:
            with psycopg.connect(self.dsn,autocommit=True) as con:con.execute('GRANT SELECT ON rafii_control.business_invoices TO rafii_control_reader')

    def test_global_search_pagination_literal_inputs_and_linked_record_lookup(self):
        prefix='Fictional Global '+str(uuid.uuid4())
        identifiers=[str(uuid.UUID(int=(1<<128)-400+i)) for i in range(205)]
        with psycopg.connect(self.dsn,autocommit=True) as con:
            for i,identifier in enumerate(identifiers):
                con.execute('INSERT INTO auth.users(id) VALUES(%s)',(identifier,))
                con.execute('INSERT INTO public.pr_profiles(user_id,display_name,deleted_at) VALUES(%s,%s,CASE WHEN %s THEN now() ELSE NULL END)',(identifier,prefix+str(i),i==204))
        query=dict(collection='customers',search=prefix,status='all',page=1,recordId='')
        first_status,first=self.request('/workspace/live/query','POST',query)
        self.assertEqual(first_status,200,first)
        self.assertEqual(first['data']['total'],205)
        self.assertEqual(len(first['data']['rows']),50)
        _,second=self.request('/workspace/live/query','POST',{**query,'page':2})
        self.assertFalse({r['id'] for r in first['data']['rows']} & {r['id'] for r in second['data']['rows']})
        _,deleted=self.request('/workspace/live/query','POST',{**query,'status':'deleted'})
        self.assertEqual([r['id'] for r in deleted['data']['rows']],[identifiers[-1]])
        _,literal=self.request('/workspace/live/query','POST',{**query,'search':"%_'; SELECT state FROM public.pr_workspaces;--"})
        self.assertEqual(literal['data']['total'],0)
        _,detail=self.request('/workspace/live/query','POST',{**query,'search':'','recordId':identifiers[-1]})
        self.assertEqual(detail['data']['rows'][0]['id'],identifiers[-1])
        _,linked=self.request('/workspace/live/query','POST',{**query,'search':'Fictional Founder Test'})
        self.assertTrue(any(w['id']==self.workspace for w in linked['data']['workspaces']))
        _,workspace=self.request('/workspace/live/query','POST',{**query,'collection':'workspaces','search':'','recordId':self.workspace})
        self.assertTrue(workspace['data']['rows'][0]['renameAllowed'])
        self.assertEqual(self.request('/workspace/live/query','POST',{**query,'collection':'pr_workspaces'})[0],400)
        self.assertEqual(self.request('/workspace/live/query','POST',{**query,'page':True})[0],400)
        _,demo=self.request('/workspace/demo/query','POST',{**query,'collection':'payments','search':'Northline'})
        self.assertEqual(demo['data']['mode'],'demo')
        # The Demo dataset is generated (10,000 subscribers); the expected count comes from the same fictional records, not a literal.
        dataset=demo_dataset.sample_data()
        customers={c['id']:c for c in dataset['customers']}; workspaces={w['id']:w for w in dataset['workspaces']}
        owner=lambda p: p.get('customerId') or workspaces.get(p.get('workspaceId'),{}).get('ownerId')
        expected=sum('northline' in str(customers.get(owner(p),{}).get('company','')).casefold() for p in dataset['payments'])
        self.assertGreater(expected,0)
        self.assertEqual(demo['data']['total'],expected)
        self.assertEqual(len(demo['data']['rows']),min(expected,50))
        self.assertNotIn('DO_NOT_DISCLOSE',json.dumps(linked))

    def test_founder_action_replay_requires_current_capabilities(self):
        before=self.repository.get(self.workspace,'synthetic-owner')
        for revoked in ('copilot.use','metrics.query'):
            snapshot=self.service.demo(self.principal)
            payload=self.action('founder_turn','founder',json.dumps(dict(
                message='Which plan has the most subscribers?',conversationId=None,
                chartContext=dict(chartId='plan-distribution',viewVersion=1,
                                  queryReceiptId=snapshot['receipt']['id'],mode='demo',environment='local'))))
            status,first=self.request('/workspace/demo/action','POST',payload)
            self.assertEqual(status,200,first)
            self.assertEqual(self.request('/workspace/demo/action','POST',payload)[1]['data'],first['data'])
            ordinary=self.action('rename_workspace','workspace-1','Demo replay permission check')
            self.assertEqual(self.request('/workspace/demo/action','POST',ordinary)[0],200)
            with psycopg.connect(self.dsn,autocommit=True) as con:
                con.execute('UPDATE rafii_control.platform_operators SET capabilities=%s WHERE user_id=%s',
                            ([cap for cap in CAPABILITIES if cap!=revoked],self.user))
            status,denied=self.request('/workspace/demo/action','POST',payload)
            self.assertEqual(status,403,denied)
            self.assertNotIn('data',denied)
            status,redacted=self.request('/workspace/demo/action','POST',ordinary)
            self.assertEqual(status,200,redacted)
            self.assertNotIn('messages',redacted['data']['intelligence'])
            with psycopg.connect(self.dsn,autocommit=True) as con:
                con.execute('UPDATE rafii_control.platform_operators SET capabilities=%s WHERE user_id=%s',(list(CAPABILITIES),self.user))
        self.assertEqual(self.repository.get(self.workspace,'synthetic-owner'),before)

    def test_demo_stop_remains_authorized_after_read_throttling(self):
        snapshot=self.service.demo(self.principal)
        turn=self.action('founder_turn','founder',json.dumps(dict(
            message='Explain the plan chart',conversationId=None,
            chartContext=dict(chartId='plan-distribution',viewVersion=1,
                              queryReceiptId=snapshot['receipt']['id'],mode='demo',environment='local'))))
        status,response=self.request('/workspace/demo/action','POST',turn)
        self.assertEqual(status,200,response)
        conversation=response['data']['intelligence']['conversations'][-1]['id']
        start=self.action('founder_voice','founder',json.dumps(dict(conversationId=conversation,operation='start')))
        self.assertEqual(self.request('/workspace/demo/action','POST',start)[0],200)
        report=self.action('founder_report_schedule','founder',json.dumps(dict(
            conversationId=conversation,kind='daily',dueLocal='2027-01-02T09:00:00',
            timeZone='America/Indiana/Indianapolis',confirmed=True)))
        status,response=self.request('/workspace/demo/action','POST',report)
        self.assertEqual(status,200,response)
        source=response['data']['intelligence']['reports'][-1]['id']
        call=self.action('founder_delivery','founder',json.dumps(dict(operation='start',channel='call',sourceId=source)))
        status,response=self.request('/workspace/demo/action','POST',call)
        self.assertEqual(status,200,response)
        attempt=response['data']['intelligence']['contactAttempts'][-1]['id']
        self.exhaust_read_budget()
        self.assertEqual(self.request('/session')[0],429)
        stop=self.action('founder_voice','founder',json.dumps(dict(conversationId=conversation,operation='stop')))
        csrf=self.session['csrfToken'];self.session['csrfToken']='wrong'
        self.assertEqual(self.request('/workspace/demo/action','POST',stop)[0],403)
        self.session['csrfToken']=csrf
        self.assertEqual(self.request('/workspace/demo/action','POST',stop)[0],200)
        cancel=self.action('founder_delivery','founder',json.dumps(dict(operation='cancel',channel='call',sourceId=source,attemptId=attempt)))
        status,response=self.request('/workspace/demo/action','POST',cancel)
        self.assertEqual(status,200,response)
        self.assertEqual(response['data']['intelligence']['contactAttempts'][-1]['state'],'cancelled')
        self.assertEqual(self.request('/workspace/demo/action','POST',start)[0],429)

    def test_demo_rejects_free_text_audit_targets_and_unused_action_payloads(self):
        for changes in ({'targetId':'private message text'},{'targetId':'customer-1'},{'value':'unused private text'}):
            body={**self.action('reset','all'),**changes}
            self.assertEqual(self.request('/workspace/demo/action','POST',body)[0],400)
        with psycopg.connect(self.dsn) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM rafii_control.workspace_actions WHERE operator_id=%s',(self.user,)).fetchone()[0],0)
