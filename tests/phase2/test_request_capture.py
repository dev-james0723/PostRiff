"""Offline crypto and disposable local PostgreSQL acceptance, never provider I/O.
POSTRIFF_CAPTURE_TEST_DSN may only target loopback and a fresh disposable database.
"""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from postriff_phase2.request_capture import (
    AuditCaptureBlocked, AuditCaptureOutcomeUnknown, CaptureScope, CaptureService,
    PostgresCaptureRepository, active, capture_scope, prepare_request, verify_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
DSN = os.environ.get('POSTRIFF_CAPTURE_TEST_DSN', '')
ROUTE = 'https://ai-gateway.vercel.sh/v1/chat/completions'


@unittest.skipUnless(DSN, 'Disposable local PostgreSQL DSN not supplied')
class CaptureDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        opts = conninfo_to_dict(DSN)
        if opts.get('host') not in ('127.0.0.1', 'localhost') or opts.get('port') != '55448':
            raise RuntimeError('Capture tests require dedicated loopback port 55448')
        cls.connect = staticmethod(lambda: psycopg.connect(DSN,client_encoding="utf8"))
        with cls.connect() as db:
            db.execute("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN; END IF; END $$")
            db.execute('CREATE TABLE public.pr_profiles(user_id uuid PRIMARY KEY,deleted_at timestamptz)')
            db.execute("CREATE TABLE public.pr_workspaces(id uuid PRIMARY KEY,revision bigint NOT NULL DEFAULT 1,state jsonb NOT NULL DEFAULT '{}')")
            db.execute('CREATE TABLE public.pr_memberships(workspace_id uuid,user_id uuid,role text,status text)')
            db.execute('CREATE TABLE public.pr_agent_runs(id uuid PRIMARY KEY,workspace_id uuid,actor uuid,status text,idempotency_key text,policy_epoch text)')
            for table in ('pr_profiles','pr_workspaces','pr_memberships','pr_agent_runs'):
                db.execute(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY; ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY')
        with cls.connect() as db:
            db.execute((ROOT / 'migrations/postriff/089_private_request_capture.sql').read_text())

    def setUp(self):
        self.wid, self.aid, self.rid = [str(uuid.uuid4()) for _ in range(3)]
        with self.connect() as db:
            db.execute('INSERT INTO pr_profiles VALUES(%s,NULL)', (self.aid,))
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)', (self.wid,))
            db.execute("INSERT INTO pr_memberships VALUES(%s,%s,'owner','active')", (self.wid,self.aid))
            db.execute("INSERT INTO pr_agent_runs VALUES(%s,%s,%s,'running','controlled-idempotency',%s)", (self.rid,self.wid,self.aid,'a'*64))
        self.service = CaptureService(PostgresCaptureRepository(self.connect), b'e'*32,b's'*32,'offline-unit-key','6'*40,self.wid)
        self.grant = self.service.create_grant(workspace_id=self.wid,actor_id=self.aid,route=ROUTE,reader_ids=[self.aid],confirmed=True)
        with self.connect() as db:
            with db.cursor() as cur:
                self.service.bind_grant(cur,grant_id=self.grant['id'],server_nonce=self.grant['server_nonce'],workspace_id=self.wid,
                    actor_id=self.aid,run_id=self.rid,idempotency_key='controlled-idempotency')
        self.scope = CaptureScope(self.wid,self.aid,self.rid,self.grant['id'],self.grant['server_nonce'],ROUTE)
        self.body = json.dumps({'model':'test/model','messages':[{'role':'system','content':'廣東話 🧪\r\n'}, {'role':'user','content':'a'}, {'role':'assistant','content':'b'}, {'role':'user','content':'c'}],
                               'temperature':0.4,'max_tokens':100,'providerOptions':{'routing':'test'}}).encode()

    def prepare(self, scope=None, body=None, attempt=1):
        with capture_scope(self.service,scope or self.scope):
            self.assertTrue(active())
            result=prepare_request(self.body if body is None else body,method='POST',url=ROUTE,timeout=20,model='test/model',
                logical_call_id=str(uuid.uuid4()),workload='draft',attempt_no=attempt)
        self.assertFalse(active())
        return result

    def read(self, handle, **overrides):
        return self.service.read_capture(**{'capture_id':handle.physical_attempt_id,'workspace_id':self.wid,
            'reader_id':self.aid,'grant_nonce':self.grant['server_nonce'],**overrides})

    def test_exact_bytes_receipts_and_response(self):
        handle=self.prepare(); handle.authorize_dispatch()
        response=b'{"id":"response-1","model":"test/model","usage":{"prompt_tokens":4,"completion_tokens":3},"providerMetadata":{"gateway":{"generationId":"generation-1","cost":"0.001"}}}'
        handle.record_response(response,200,{'x-request-id':'request-1','authorization':'never-capture'})
        result=self.read(handle)
        self.assertEqual(base64.b64decode(result['request_base64']),self.body)
        self.assertEqual(base64.b64decode(result['response_base64']),response)
        prepared=verify_receipt(result['prepared'],self.service.public_key)
        outcome=verify_receipt(result['outcome'],self.service.public_key)
        self.assertEqual(prepared['body_sha256'],hashlib.sha256(self.body).hexdigest())
        self.assertEqual(outcome['endpoint_request_id'],'request-1')
        self.assertEqual(outcome['endpoint_response_id'],'response-1')
        self.assertEqual(outcome['gateway_generation_id'],'generation-1')
        self.assertNotIn('authorization',outcome['headers'])
        self.assertFalse(outcome['provider_body_digest_attested'])
        spec=importlib.util.spec_from_file_location('independent_capture_verifier', ROOT/'scripts/verify_request_capture.py')
        verifier=importlib.util.module_from_spec(spec); spec.loader.exec_module(verifier)
        verification=verifier.verify(result,self.service.public_key,'6'*40,{'required':['廣東話'],'forbidden':['MISSING_PRIVATE_CANARY']})
        self.assertTrue(verification['verified']); self.assertTrue(verification['content_checks_passed'])
        encrypted=copy.deepcopy(result); del encrypted['request_base64']; del encrypted['response_base64']
        encrypted['prepared']['manifest']['timeout_seconds']=20.0  # browser JSON numeric normalization is harmless
        self.assertTrue(verifier.verify(encrypted,self.service.public_key,'6'*40,encryption_key=b'e'*32)['verified'])
        with self.assertRaises(Exception): verifier.verify(encrypted,self.service.public_key,'6'*40,encryption_key=b'w'*32)
        tampered=copy.deepcopy(result); tampered['response_base64']=base64.b64encode(b'{}').decode()
        with self.assertRaises(ValueError): verifier.verify(tampered,self.service.public_key,'6'*40)
        missing=copy.deepcopy(result); del missing['network_started']
        with self.assertRaises(KeyError): verifier.verify(missing,self.service.public_key,'6'*40)
        with self.connect() as db:
            rec=db.execute('SELECT record::text FROM audit_private.model_request_captures WHERE id=%s',(handle.physical_attempt_id,)).fetchone()[0]
            self.assertNotIn('廣東話',rec)
            self.assertNotIn('"role"',rec)
        listing=self.service.list_captures(grant_id=self.grant['id'],workspace_id=self.wid,reader_id=self.aid,grant_nonce=self.grant['server_nonce'])
        self.assertEqual(listing['captures'][0]['capture_id'],handle.physical_attempt_id)

    def test_untrusted_response_metadata_is_not_persisted_plaintext(self):
        h=self.prepare(); h.authorize_dispatch()
        response=json.dumps({'id':'response-2','model':'test/model','usage':{'prompt_tokens':3,'private_text':'SECRET-RESPONSE-CONTENT'},
            'providerMetadata':{'gateway':{'generationId':'gen-2','cost':'0.002','prompt':'SECRET-RESPONSE-CONTENT','routing':{'finalProvider':'openai','secret':'SECRET-RESPONSE-CONTENT'}}}}).encode()
        h.record_response(response,200,{})
        exported=self.read(h)
        self.assertNotIn('SECRET-RESPONSE-CONTENT',json.dumps(exported['outcome']))
        self.assertEqual(exported['outcome']['manifest']['upstream_provider'],'openai')
        self.assertEqual(base64.b64decode(exported['response_base64']),response)

    def test_signature_aead_tampering_and_wrong_key(self):
        handle=self.prepare(); record=copy.deepcopy(handle.record)
        record['prepared']['manifest']['body_bytes']+=1
        with self.assertRaises(AuditCaptureBlocked): verify_receipt(record['prepared'],self.service.public_key)
        with self.assertRaises(AuditCaptureBlocked): verify_receipt(handle.record['prepared'],b'k'*32)
        sealed=copy.deepcopy(handle.record['request']); sealed['nonce']=base64.b64encode(b'0'*12).decode()
        with self.assertRaises(AuditCaptureBlocked): self.service._open(sealed,self.scope,handle.record['prepared']['manifest'])

    def test_editor_can_purge_after_authorized_privacy_change_only(self):
        h=self.prepare(); editor=str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO pr_profiles VALUES(%s,NULL)',(editor,))
            db.execute("INSERT INTO pr_memberships VALUES(%s,%s,'editor','active')",(self.wid,editor))
        with self.assertRaises(AuditCaptureBlocked): self.read(h,reader_id=editor)
        with self.assertRaises(AuditCaptureBlocked):
            self.service.create_grant(workspace_id=self.wid,actor_id=editor,route=ROUTE,reader_ids=[editor],confirmed=True)
        with self.connect() as db:
            with db.cursor() as cur:
                self.assertEqual(self.service.revoke_workspace(cur,workspace_id=self.wid,actor_id=editor)['purged_grants'],1)
        with self.assertRaises(AuditCaptureBlocked): h.authorize_dispatch()
        with self.assertRaises(AuditCaptureBlocked): self.read(h)

    def test_revoke_prevents_dispatch_and_read(self):
        handle=self.prepare()
        self.service.revoke_grant(grant_id=self.grant['id'],workspace_id=self.wid,actor_id=self.aid,server_nonce=self.grant['server_nonce'])
        with self.assertRaises(AuditCaptureBlocked): handle.authorize_dispatch()
        with self.assertRaises(AuditCaptureBlocked): self.read(handle)

    def test_policy_change_and_membership_revocation(self):
        handle=self.prepare()
        with self.connect() as db: db.execute('UPDATE pr_workspaces SET revision=revision+1 WHERE id=%s',(self.wid,))
        with self.assertRaises(AuditCaptureBlocked): handle.authorize_dispatch()
        with self.assertRaises(AuditCaptureBlocked): self.read(handle)
        with self.connect() as db: db.execute("UPDATE pr_memberships SET status='revoked' WHERE user_id=%s",(self.aid,))
        with self.assertRaises(AuditCaptureBlocked): self.read(handle)

    def test_expiry_nonce_reader_and_tenant_denial(self):
        handle=self.prepare()
        with self.assertRaises(AuditCaptureBlocked): self.read(handle,grant_nonce='x'*43)
        with self.assertRaises(AuditCaptureBlocked): self.read(handle,reader_id=str(uuid.uuid4()))
        with self.assertRaises(AuditCaptureBlocked): self.read(handle,workspace_id=str(uuid.uuid4()))
        with self.connect() as db:
            db.execute("UPDATE audit_private.model_capture_grants SET confirmed_at=now()-interval '2 hour',start_before=now()-interval '110 minutes',expires_at=now()-interval '1 hour' WHERE id=%s",(self.grant['id'],))
        with self.assertRaises(AuditCaptureBlocked): self.read(handle)
        with self.assertRaises(AuditCaptureBlocked): handle.authorize_dispatch()
        self.assertGreaterEqual(self.service.purge_expired()['purged_grants'],1)

    def test_quota_unknown_outcome_and_single_dispatch(self):
        h=self.prepare(); h.authorize_dispatch()
        with self.assertRaises(AuditCaptureBlocked): h.authorize_dispatch()
        with self.assertRaises(AuditCaptureBlocked): self.prepare()
        h.record_response(b'{}',200,{})
        second=self.prepare(attempt=2); second.authorize_dispatch(); second.record_response(b'{}',200,{})
        third=self.prepare(attempt=3); third.authorize_dispatch(); third.record_response(b'{}',200,{})
        with self.assertRaises(AuditCaptureBlocked): self.prepare()
        self.assertEqual(len({h.physical_attempt_id,second.physical_attempt_id,third.physical_attempt_id}),3)

    def test_unknown_stops_further_attempts(self):
        h=self.prepare(); h.authorize_dispatch(); h.record_failure('TimeoutError')
        self.assertEqual(self.read(h)['state'],'dispatch_unknown')
        with self.assertRaises(AuditCaptureBlocked): self.prepare()

    def test_size_credentials_and_unsupported_body_deny(self):
        for body in (b'x'*524289,b'[]',b'not json',json.dumps({'model':'test/model','messages':[],'token':'sk-'+('a'*30)}).encode()):
            with self.assertRaises(AuditCaptureBlocked): self.prepare(body=body)
        h=self.prepare(); h.authorize_dispatch()
        with self.assertRaises(AuditCaptureOutcomeUnknown): h.record_response(b'x'*524289,200,{})

    def test_runtime_and_browser_capability_boundaries(self):
        for role in ('anon','authenticated','service_role','pr_capture_runtime'):
            with self.connect() as db:
                db.execute(f'SET LOCAL ROLE {role}')
                with self.assertRaises(Exception): db.execute('SELECT * FROM audit_private.model_request_captures')
        for role in ('anon','authenticated','service_role'):
            with self.connect() as db:
                db.execute(f'SET LOCAL ROLE {role}')
                with self.assertRaises(Exception): db.execute("SELECT audit_private.capture_operation('purge','{}')")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT rolsuper,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname='pr_capture_runtime'").fetchone(),(False,False,False))

    def test_persistence_error_never_authorizes_and_restores_role(self):
        h=self.prepare()
        with self.connect() as db:
            with db.cursor() as cur:
                original=db.execute('SELECT current_user').fetchone()[0]
                with self.assertRaises(AuditCaptureBlocked): self.service.repository.call('unknown',self.scope.payload(),cursor=cur)
                self.assertEqual(db.execute('SELECT current_user').fetchone()[0],original)
        bad=copy.copy(self.scope)
        object.__setattr__(bad,'server_nonce','x'*43)
        with self.assertRaises(AuditCaptureBlocked): self.prepare(scope=bad)


if __name__=='__main__': unittest.main()
