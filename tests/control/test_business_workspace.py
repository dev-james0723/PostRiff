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
from rafii_control.auth import Boundary,Config,VerifiedIdentity,ControlError,CAPABILITIES
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

    def test_logout_remains_authorized_when_read_budget_is_exhausted(self):
        with psycopg.connect(self.dsn,autocommit=True) as con:
            bucket=hashlib.sha256(('control.read:'+self.user).encode()).hexdigest()
            con.execute("INSERT INTO rafii_control.request_budgets(bucket,environment,window_start,attempts) VALUES(%s,'local',floor(extract(epoch from now())/60),120) ON CONFLICT(bucket,environment) DO UPDATE SET window_start=excluded.window_start,attempts=120",(bucket,))
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
        self.service.demo(self.principal,self.action('simulate_payment','payment-2'))
        self.assertEqual(self.service.demo(self.principal)['subscriptions'][1]['status'],'active')
        self.service.demo(self.principal,self.action('resolve_ticket','ticket-1'))
        self.assertEqual(self.service.demo(self.principal)['summary']['openRequests'],1)
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
        self.assertEqual(demo['data']['total'],1)
        self.assertNotIn('DO_NOT_DISCLOSE',json.dumps(linked))

    def test_demo_rejects_free_text_audit_targets_and_unused_action_payloads(self):
        for changes in ({'targetId':'private message text'},{'targetId':'customer-1'},{'value':'unused private text'}):
            body={**self.action('reset','all'),**changes}
            self.assertEqual(self.request('/workspace/demo/action','POST',body)[0],400)
        with psycopg.connect(self.dsn) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM rafii_control.workspace_actions WHERE operator_id=%s',(self.user,)).fetchone()[0],0)
