"""Actual X service/journal/cost PostgreSQL. Synthetic identity, billing and provider."""
import copy,json,os,re,threading,time,unittest,uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.social_connectors import XProvider
from postriff_phase2.x_direct_service import XDirectService
from postriff_phase2 import x_direct_journal as journal
from postriff_phase2.x_direct_cost import XCostController
from test_x_direct_cost import policy
DSN=os.environ.get("RAFII_X_TEST_DATABASE_DSN","")
class Repository:
    def __init__(self,dsn,actor):
        import psycopg
        self.connection_factory=lambda:psycopg.connect(dsn)
        self.actor=actor
    @contextmanager
    def transaction(self,token,workspace):
        if token!="synthetic-interactive-session":raise AlphaError("Invalid fixture session",403)
        with self.connection_factory() as db,db.cursor() as cur:
            cur.execute("SELECT w.revision,w.state,m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id WHERE w.id=%s AND m.user_id=%s AND m.status='active' FOR UPDATE OF w",(workspace,self.actor))
            row=cur.fetchone()
            if not row:raise AlphaError("Workspace unavailable",403)
            yield cur,row,self.actor
    def assert_fresh(self,token,actor):
        if token!="synthetic-interactive-session" or actor!=self.actor:raise AlphaError("Fresh session required",403)
class Wire:
    def __init__(self):
        self.calls=[];self.posts={};self.answers=[];self.lock=threading.Lock();self.entered=None;self.release=None
    def __call__(self,method,url,**kwargs):
        with self.lock:
            call={"method":method,"path":urlsplit(url).path,"body":copy.deepcopy(kwargs.get("body"))}
            self.calls.append(call);answer=self.answers.pop(0) if self.answers else None
        if isinstance(answer,Exception):raise answer
        if answer is not None:return copy.deepcopy(answer)
        if method=="POST" and call["path"]=="/2/tweets":
            if self.entered:
                self.entered.set()
                if not self.release.wait(5):raise RuntimeError("Fixture concurrency wait expired")
            with self.lock:
                rid=str(1800000000000000000+len(self.posts)+1);self.posts[rid]=copy.deepcopy(call["body"])
            return {"status":201,"body":{"data":{"id":rid,"text":call["body"].get("text","")}}}
        if method=="GET" and call["path"].startswith("/2/tweets/"):
            rid=call["path"].split("/")[-1];post=self.posts.get(rid)
            if post is None:return {"status":404,"body":{"errors":[{"title":"Not found"}]}}
            data={"id":rid,"author_id":"123","text":post.get("text","")}
            if post.get("reply"):data["referenced_tweets"]=[{"type":"replied_to","id":post["reply"]["in_reply_to_tweet_id"]}]
            if post.get("quote_tweet_id"):data["referenced_tweets"]=[{"type":"quoted","id":post["quote_tweet_id"]}]
            return {"status":200,"body":{"data":data}}
        raise AssertionError("Unexpected fixture request: "+method+" "+url)
@unittest.skipUnless(DSN,"Explicit disposable X database required")
class DirectServicePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict,make_conninfo
        from psycopg import sql
        cls.psycopg=psycopg;opts=conninfo_to_dict(DSN)
        if not re.fullmatch(r"/tmp/rafii-x-g14-pg-[A-Za-z0-9_-]+/socket",opts.get("host","")) or opts.get("hostaddr"):raise RuntimeError("Dedicated UNIX-only cluster required")
        cls.name="x_service_test_"+uuid.uuid4().hex[:12];cls.admin=psycopg.connect(DSN,autocommit=True)
        cls.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.name)));cls.dsn=make_conninfo(DSN,dbname=cls.name)
        with psycopg.connect(cls.dsn) as db:
            db.execute("""CREATE TABLE public.pr_workspaces(id uuid PRIMARY KEY,state jsonb NOT NULL DEFAULT '{}',revision integer NOT NULL DEFAULT 1);
            CREATE TABLE public.pr_profiles(user_id uuid PRIMARY KEY,deleted_at timestamptz);
            CREATE TABLE public.pr_memberships(workspace_id uuid,user_id uuid,role text,status text DEFAULT 'active',can_publish boolean DEFAULT false,can_reply boolean DEFAULT false,can_moderate boolean DEFAULT false,can_manage_connections boolean DEFAULT false,PRIMARY KEY(workspace_id,user_id));
            CREATE TABLE public.pr_encrypted_credentials(workspace_id uuid REFERENCES public.pr_workspaces(id),connection_id text,provider text,provider_account_id text,access_ciphertext text,key_id text,scopes text[],revoked_at timestamptz,PRIMARY KEY(workspace_id,connection_id));
            CREATE TABLE public.pr_audit_events(workspace_id uuid,actor uuid,kind text,subject text,meta jsonb);""")
        with psycopg.connect(cls.dsn,autocommit=True) as db:
            for name in ("131_x_direct_cost.sql","132_x_direct_operations.sql","133_x_cost_approval_grants.sql","134_x_resource_evidence.sql"):db.execute((Path("migrations/postriff")/name).read_text())
    @classmethod
    def tearDownClass(cls):
        from psycopg import sql
        cls.admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(cls.name)));cls.admin.close()
    def setUp(self):
        self.ws=str(uuid.uuid4());self.actor=str(uuid.uuid4());self.conn=uuid.uuid4().hex
        self.repo=Repository(self.dsn,self.actor);self.wire=Wire();self.vault=CredentialVault(CredentialVault.generate_key())
        self.provider=XProvider("synthetic-"+uuid.uuid4().hex,"fixture-not-real",transport=self.wire)
        self.provider.public_connect_enabled=True;self.provider.direct_management_enabled=True;self.provider.publishing_release_enabled=True
        self.provider.x_access_evidence={"entitlements":frozenset(("x_api_v2","enterprise")),"expiresAt":time.time()+3600,"publicCustomerVerified":True,"evidenceRef":"synthetic:integration-only"}
        self.scopes=sorted({s for row in self.provider.SCOPES.values() for s in row})
        self.grant=self.provider._grant({"access_token":"synthetic-access","refresh_token":"synthetic-refresh","scope":" ".join(self.scopes),"expires_in":7200})
        access,key=self.vault.encrypt(self.grant["accessToken"])
        with self.repo.connection_factory() as db:
            db.execute("INSERT INTO public.pr_workspaces(id) VALUES(%s)",(self.ws,));db.execute("INSERT INTO public.pr_profiles(user_id) VALUES(%s)",(self.actor,))
            db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role) VALUES(%s,%s,'owner')",(self.ws,self.actor))
            db.execute("INSERT INTO public.pr_encrypted_credentials VALUES(%s,%s,'x','123',%s,%s,%s,NULL)",(self.ws,self.conn,access,key,self.scopes))
        def token_for_worker(ws,conn):
            with self.repo.connection_factory() as db:row=db.execute("SELECT access_ciphertext,key_id,scopes,provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL",(ws,conn)).fetchone()
            if not row:raise AlphaError("Connection unavailable",404)
            token=self.vault.decrypt(row[0],row[1])
            return {"accessToken":token,"scopes":row[2],"providerAccountId":row[3],"authorizationGeneration":self.provider.authorization_generation(token)}
        self.oauth=SimpleNamespace(vault=self.vault,providers={"x":self.provider},token_for_worker=token_for_worker)
        self.cost=XCostController(self.repo.connection_factory,policy(app_budget_micros=10000000,workspace_budget_micros=10000000),"synthetic-"+uuid.uuid4().hex)
        self.cost.activate("synthetic:service-integration");self.service=SimpleNamespace(repository=self.repo,oauth=self.oauth,clock=time.time)
        self.engine=XDirectService(self.service,self.cost);self.session="synthetic-interactive-session"
        self.billing=patch("postriff_phase2.billing.require_publishing",lambda *a:None);self.billing.start();self.addCleanup(self.billing.stop)
        with self.repo.connection_factory() as db:db.execute("UPDATE public.pr_x_direct_operations SET state='held' WHERE workspace_id<>%s AND state IN ('queued','accepted','dispatching')",(self.ws,))
    def preview(self,body=None,operation="posts.create",**extra):
        return self.engine.preview(self.ws,self.session,self.conn,{"operation":operation,"body":body or {"text":"Synthetic approved content"},"requestKey":uuid.uuid4().hex,**extra})
    def approve(self,item):return self.engine.approve(self.ws,self.session,self.conn,item["id"],{"digest":item["digest"],"confirmed":True})
    def row(self,item):
        with self.repo.connection_factory() as db,db.cursor() as cur:return journal.read(cur,self.ws,item["id"])
    def due(self,item):
        with self.repo.connection_factory() as db:db.execute("UPDATE public.pr_x_direct_operations SET next_at=now()-interval '1 second' WHERE workspace_id=%s AND id=%s",(self.ws,item["id"]))
    def test_preview_approval_dispatch_and_exact_receipts(self):
        item=self.preview();self.assertEqual(self.wire.calls,[]);queued=self.approve(item)
        self.assertEqual(queued["state"],"queued");self.assertEqual(self.wire.calls,[])
        self.assertEqual(self.engine.dispatch_one().get("state"),"accepted");self.assertEqual(self.engine.dispatch_one().get("state"),"verified")
        row=self.row(item);self.assertEqual([r["method"] for r in row["receipts"]],["POST","GET"]);self.assertTrue(row["receipts"][-1]["readbackVerified"])
        self.assertEqual([c["method"] for c in self.wire.calls],["POST","GET"]);self.assertFalse(self.engine.dispatch_one()["selected"])
    def test_schedule_waits_and_survives_service_restart(self):
        item=self.preview(scheduleAt=time.time()+3600);self.approve(item);self.assertFalse(self.engine.dispatch_one()["selected"]);self.assertEqual(self.wire.calls,[])
        self.due(item) # Controlled test-clock simulation only, never production.
        fresh=XDirectService(self.service,self.cost);self.assertEqual(fresh.dispatch_one().get("state"),"accepted");self.assertEqual(fresh.dispatch_one().get("state"),"verified")
    def test_two_workers_never_create_twice(self):
        item=self.preview();self.approve(item);self.wire.entered=threading.Event();self.wire.release=threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.engine.dispatch_one);self.assertTrue(self.wire.entered.wait(4));second=pool.submit(self.engine.dispatch_one)
            try:self.assertFalse(second.result(timeout=4)["selected"])
            finally:self.wire.release.set()
            self.assertEqual(first.result(timeout=4).get("state"),"accepted")
        self.assertEqual(sum(c["method"]=="POST" for c in self.wire.calls),1);self.assertEqual(self.engine.dispatch_one().get("state"),"verified")
    def test_cancel_before_dispatch_sends_nothing(self):
        item=self.preview();self.approve(item);self.engine.cancel(self.ws,self.session,self.conn,item["id"])
        self.assertFalse(self.engine.dispatch_one()["selected"]);self.assertEqual(self.wire.calls,[])
    def test_removed_approver_and_reconnect_block_dispatch(self):
        item=self.preview();self.approve(item)
        with self.repo.connection_factory() as db:db.execute("UPDATE public.pr_memberships SET status='removed' WHERE workspace_id=%s",(self.ws,))
        self.engine.dispatch_one();self.assertEqual(self.row(item)["state"],"held");self.assertEqual(self.wire.calls,[])
        with self.repo.connection_factory() as db:db.execute("UPDATE public.pr_memberships SET status='active' WHERE workspace_id=%s",(self.ws,))
        item=self.preview();self.approve(item);other=self.provider._grant({"access_token":"new-grant","scope":" ".join(self.scopes),"expires_in":3600});ct,key=self.vault.encrypt(other["accessToken"])
        with self.repo.connection_factory() as db:db.execute("UPDATE public.pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s WHERE workspace_id=%s",(ct,key,self.ws))
        self.engine.dispatch_one();self.assertEqual(self.row(item)["state"],"held");self.assertEqual(self.wire.calls,[])
    def test_timeout_after_write_is_never_replayed(self):
        item=self.preview();self.approve(item);self.wire.answers=[AlphaError("synthetic response lost",503)]
        self.assertEqual(self.engine.dispatch_one().get("state"),"uncertain")
        for _ in range(3):self.assertFalse(self.engine.dispatch_one()["selected"])
        self.assertEqual(len(self.wire.calls),1)
    def test_429_retry_then_readback_is_bounded(self):
        item=self.preview();self.approve(item);self.wire.answers=[{"status":429,"headers":{"retry-after":"15"},"body":{"errors":[{}]}}]
        self.assertEqual(self.engine.dispatch_one().get("state"),"queued");self.assertFalse(self.engine.dispatch_one()["selected"])
        self.due(item);self.assertEqual(self.engine.dispatch_one().get("state"),"accepted");self.assertEqual(self.engine.dispatch_one().get("state"),"verified");self.assertEqual(self.row(item)["attempts"],2)
    def test_thread_waits_for_each_exact_readback(self):
        item=self.preview({"posts":[{"text":"First approved"},{"text":"Second approved"}]},operation="posts.thread");self.approve(item)
        for state in ("accepted","queued","accepted","verified"):self.assertEqual(self.engine.dispatch_one().get("state"),state)
        self.assertEqual([c["method"] for c in self.wire.calls],["POST","GET","POST","GET"]);self.assertEqual(self.wire.calls[2]["body"]["reply"]["in_reply_to_tweet_id"],next(iter(self.wire.posts)))
    def test_thread_cancellation_preserves_first_receipt_without_second_post(self):
        item=self.preview({"posts":[{"text":"First approved"},{"text":"Never send second"}]},operation="posts.thread");self.approve(item)
        self.assertEqual(self.engine.dispatch_one().get("state"),"accepted");self.engine.cancel(self.ws,self.session,self.conn,item["id"])
        self.assertEqual(self.engine.dispatch_one().get("state"),"canceled");self.assertEqual([c["method"] for c in self.wire.calls],["POST","GET"]);self.assertEqual(len(self.row(item)["receipts"]),2)
    def test_foreign_tenant_and_unconfirmed_approval_rejected(self):
        item=self.preview()
        with self.assertRaises(AlphaError):self.engine.overview(str(uuid.uuid4()),self.session,self.conn)
        with self.assertRaises(AlphaError):self.engine.approve(self.ws,self.session,self.conn,item["id"],{"digest":item["digest"],"confirmed":False})
        self.assertEqual(self.wire.calls,[])
    def test_full_workflow_budget_is_bound_in_preview(self):
        item=self.preview();self.assertEqual(item["request"]["maximumApiRequests"],6);self.assertGreater(item["request"]["estimatedMaxCostMicros"],item["request"]["estimatedCostMicros"])
        with self.repo.connection_factory() as db:db.execute("UPDATE public.pr_x_direct_operations SET request=jsonb_set(request,'{estimatedMaxCostMicros}','0') WHERE workspace_id=%s AND id=%s",(self.ws,item["id"]))
        with self.assertRaises(AlphaError):self.approve(item)
        self.assertEqual(self.wire.calls,[])
