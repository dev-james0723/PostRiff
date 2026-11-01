"""Actual PostgreSQL acceptance; synthetic Twitch transport, no live endpoints.

Run only with RAFII_TWITCH_TEST_DSN pointing to localhost:55439/rafii_twitch_test.
The fixture refuses any other database before executing SQL. It creates only its
own disposable schema. RLS, row locks, rollback and unique constraints are real.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.twitch_oauth import TwitchProvider
from postriff_phase2.twitch_eventsub import EVENT_TYPES
from postriff_phase2.twitch_native import union_supported_scopes
from postriff_phase2.twitch_service import TwitchService, _right

DSN = os.environ.get('RAFII_TWITCH_TEST_DSN')
ROOT = Path(__file__).resolve().parents[1]
WS = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'
ALICE = '10000000-0000-0000-0000-000000000001'
BOB = '10000000-0000-0000-0000-000000000002'
EVE = '10000000-0000-0000-0000-000000000003'
ADMIN = '10000000-0000-0000-0000-000000000004'
CONN = 'twitch-owned-connection'
GEN = 'a' * 32
ALL_SCOPES = sorted(union_supported_scopes() | {s for spec in EVENT_TYPES.values() for s in spec['scopes']})

BOOTSTRAP = """
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT USAGE ON SCHEMA public TO PUBLIC;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF;
END $$;
CREATE TABLE pr_workspaces(id uuid PRIMARY KEY,revision int NOT NULL DEFAULT 1,state jsonb NOT NULL);
CREATE TABLE pr_profiles(user_id uuid PRIMARY KEY,deleted_at timestamptz);
CREATE TABLE pr_memberships(workspace_id uuid,user_id uuid,role text,status text DEFAULT 'active',can_publish bool DEFAULT false,can_reply bool DEFAULT false,can_moderate bool DEFAULT false,can_manage_connections bool DEFAULT false,PRIMARY KEY(workspace_id,user_id));
CREATE TABLE pr_encrypted_credentials(workspace_id uuid,connection_id text,provider text,provider_account_id text,access_ciphertext text,refresh_ciphertext text,key_id text,scopes text[],access_expires_at timestamptz,refresh_supported bool DEFAULT true,revoked_at timestamptz,rotated_at timestamptz,updated_at timestamptz DEFAULT now(),created_at timestamptz DEFAULT now(),PRIMARY KEY(workspace_id,connection_id));
CREATE TABLE pr_audit_events(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,workspace_id uuid,actor uuid,kind text,subject text,meta jsonb);
CREATE TABLE pr_channel_capabilities(workspace_id uuid,connection_id text,level text,evidence text,updated_at timestamptz);
"""


class Clock:
    def __init__(self): self.now = 1_800_000_000.0
    def __call__(self): return self.now


class Session:
    def __init__(self, clock): self.clock, self.stale = clock, False
    def __call__(self, token):
        if token not in ('alice', 'bob', 'eve', 'admin'): raise AlphaError('Session unavailable.', 401)
        return {'alice': ALICE, 'bob': BOB, 'eve': EVE, 'admin': ADMIN}[token]
    def auth_time(self, token, actor): return self.clock() - (1000 if self.stale else 0)


class Wire:
    def __init__(self, clock):
        self.clock, self.calls, self.writes = clock, [], []
        self.scopes = list(ALL_SCOPES)
        self.failure = None
        self.live = True
        self.service = None
        self.inline_challenge = False
        self.block_write = None
    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url))
        parsed = urlsplit(url); query = parse_qs(parsed.query)
        auth = kwargs.get('headers', {}).get('Authorization', '')
        subject = '456' if auth.endswith('456') else '123'
        if url == TwitchProvider.VALIDATE:
            return {'status': 200, 'body': {'client_id': 'client_test', 'user_id': subject, 'login': 'synthetic', 'scopes': self.scopes, 'expires_in': 7200}}
        if url == TwitchProvider.TOKEN:
            if kwargs.get('form', {}).get('grant_type') == 'client_credentials':
                return {'status': 200, 'body': {'access_token': 'synthetic_app_token', 'token_type': 'bearer', 'expires_in': 3600}}
            return {'status': 200, 'body': {'access_token': 'access-'+subject, 'refresh_token': 'refresh-'+subject, 'expires_in': 7200, 'token_type': 'bearer'}}
        if parsed.path == '/helix/users':
            return {'status': 200, 'body': {'data': [{'id': subject, 'broadcaster_type': 'affiliate'}]}}
        if parsed.path == '/helix/streams':
            return {'status': 200, 'body': {'data': [{'id': 'stream123','user_id': subject,'viewer_count': 7,'type':'live'}] if self.live else []}}
        if parsed.path == '/helix/channels' and method == 'GET':
            return {'status': 200, 'body': {'data': [{'broadcaster_id': subject, 'title': 'Synthetic channel'}]}}
        if parsed.path == '/helix/streams/key':
            return {'status': 200, 'body': {'data': [{'stream_key': 'synthetic-private-encoder-key'}]}}
        if parsed.path == '/helix/clips' and method == 'GET':
            return {'status': 200, 'body': {'data': [{'id': item,'broadcaster_id':subject} for item in query.get('id', [])]}}
        if parsed.path == '/helix/clips/downloads':
            return {'status': 200, 'body': {'data': [{'clip_id': item,'landscape_download_url':'https://production.assets.clips.twitchcdn.net/clip.mp4','portrait_download_url':None} for item in query.get('clip_id', [])]}}
        if parsed.path == '/helix/channels' and method == 'PATCH':
            self.writes.append((method, parsed.path, kwargs.get('body')))
            if self.block_write: self.block_write()
            if self.failure: raise self.failure
            return {'status': 204, 'body': {}}
        if parsed.path == '/helix/eventsub/subscriptions' and method == 'POST':
            body = kwargs['body']; identifier = str(uuid.uuid4())
            self.writes.append((method, parsed.path, {'type': body['type']}))
            if self.inline_challenge:
                sub = {'id': identifier,'type':body['type'],'version':body['version'],'condition':body['condition'],'status':'webhook_callback_verification_pending'}
                headers, raw = signed(self.clock(), sub, body['transport']['secret'], kind='webhook_callback_verification', challenge='synthetic-challenge')
                local = body['transport']['callback'].rsplit('/',1)[1]
                answer, duplicate = self.service.webhook(local, headers, raw)
                if answer != b'synthetic-challenge' or duplicate: raise AssertionError('Callback did not durably authenticate')
            return {'status': 202, 'body': {'data': [{'id':identifier,'type':body['type'],'version':body['version'],'condition':body['condition']}]}}
        if parsed.path == '/helix/eventsub/subscriptions' and method == 'DELETE':
            self.writes.append((method, parsed.path, query))
            return {'status': 204, 'body': {}}
        raise AssertionError('Unexpected synthetic route '+method+' '+parsed.path)


def signed(now, sub, secret, *, kind='notification', message='message-id-1', event=None, challenge=None):
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00','Z')
    body = {'subscription': sub}
    if kind == 'notification': body['event'] = event or {'broadcaster_user_id':'123','text':'untrusted viewer content'}
    if challenge is not None: body['challenge'] = challenge
    raw = json.dumps(body,separators=(',',':')).encode()
    signature = 'sha256='+hmac.new(secret.encode(),message.encode()+stamp.encode()+raw,hashlib.sha256).hexdigest()
    headers = {'Twitch-Eventsub-Message-Id':message,'Twitch-Eventsub-Message-Timestamp':stamp,
        'Twitch-Eventsub-Message-Signature':signature,'Twitch-Eventsub-Message-Type':kind,
        'Twitch-Eventsub-Subscription-Type':sub['type'],'Twitch-Eventsub-Subscription-Version':sub['version']}
    return headers, raw


@unittest.skipUnless(DSN, 'Set the explicitly isolated RAFII_TWITCH_TEST_DSN to run real PostgreSQL acceptance.')
class PostgresAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        config = conninfo_to_dict(DSN)
        if config.get('host') != '127.0.0.1' or config.get('port') != '55439' or config.get('dbname') != 'rafii_twitch_test':
            raise RuntimeError('Refusing a non-disposable PostgreSQL target')
        cls.psycopg = psycopg
        with psycopg.connect(DSN,autocommit=True) as db:
            db.execute(BOOTSTRAP)
            db.execute((ROOT/'migrations/postriff/134_twitch_native.sql').read_text())

    def setUp(self):
        self.clock = Clock(); self.verify = Session(self.clock); self.wire = Wire(self.clock)
        self.factory = lambda: self.psycopg.connect(DSN)
        self.vault = CredentialVault(CredentialVault.generate_key())
        self.provider = TwitchProvider('client_test','synthetic_client_secret',self.wire,public_connect_enabled=True,commercial_approved=True,clock=self.clock)
        self.repository = PostgresWorkspaceRepository(self.factory,self.verify,clock=self.clock)
        self.oauth = OAuthService(self.repository,SimpleNamespace(),self.vault,{'twitch':self.provider},'https://rafii.io',clock=self.clock)
        host = SimpleNamespace(connection_factory=self.factory,repository=self.repository,oauth=self.oauth,clock=self.clock)
        self.service = TwitchService(host,content_storage_approved=True,agent_processing_approved=True)
        host.twitch = self.service; self.wire.service = self.service; self.host = host
        with self.factory() as db:
            db.execute('TRUNCATE pr_twitch_events,pr_twitch_subscriptions,pr_twitch_actions,pr_twitch_context,pr_twitch_maintenance,pr_encrypted_credentials,pr_memberships,pr_profiles,pr_workspaces,pr_audit_events,pr_channel_capabilities RESTART IDENTITY CASCADE')
            for ws,subject in ((WS,'123'),(OTHER,'456')):
                state={'phase2':{'channels':[{'id':CONN,'platform':'Twitch','account':'Synthetic '+subject,'configured':True,'identityVerified':True,'providerAccountId':subject,'scopes':ALL_SCOPES}]}}
                db.execute('INSERT INTO pr_workspaces(id,state) VALUES(%s,%s::jsonb)',(ws,json.dumps(state)))
                access,key=self.vault.encrypt(self.provider._seal('access-'+subject,'at',subject,GEN))
                refresh=self.vault.encrypt(self.provider._seal('refresh-'+subject,'rt',subject,GEN))[0]
                db.execute('INSERT INTO pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,refresh_ciphertext,key_id,scopes,access_expires_at) VALUES(%s,%s,\'twitch\',%s,%s,%s,%s,%s,to_timestamp(%s))',(ws,CONN,subject,access,refresh,key,ALL_SCOPES,self.clock()+7200))
            for actor in (ALICE,BOB,EVE,ADMIN): db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)',(actor,))
            for ws,actor,role in ((WS,ALICE,'owner'),(OTHER,BOB,'owner'),(WS,EVE,'viewer'),(WS,ADMIN,'owner')):
                db.execute('INSERT INTO pr_memberships(workspace_id,user_id,role) VALUES(%s,%s,%s)',(ws,actor,role))

    def sql(self, statement, params=()):
        with self.factory() as db:
            cur=db.execute(statement,params)
            return cur.fetchall() if cur.description else cur.rowcount

    def preview(self, **changes):
        body={'action':'twitch.channel.update','payload':{'title':'Approved title'},**changes}
        return self.service.preview(WS,'alice',CONN,body)

    def approved(self, **changes):
        p=self.preview(**changes)
        self.service.approve(WS,'alice',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True})
        return p

    def assert_denied(self, call, *, code=None):
        with self.assertRaises(AlphaError) as ctx: call()
        if code: self.assertEqual(ctx.exception.code,code)
        return ctx.exception

    def subscription(self):
        identifier=str(uuid.uuid4()); provider_id=str(uuid.uuid4()); secret='synthetic-webhook-secret-123456789'
        ciphertext,key=self.vault.encrypt(secret)
        self.sql("INSERT INTO pr_twitch_subscriptions(id,workspace_id,connection_id,generation,provider_subscription_id,type,version,condition,state,secret_ciphertext,secret_key_id) VALUES(%s,%s,%s,%s,%s,'channel.chat.message','1',%s::jsonb,'enabled',%s,%s)",(identifier,WS,CONN,GEN,provider_id,json.dumps({'broadcaster_user_id':'123','user_id':'123'}),ciphertext,key))
        sub={'id':provider_id,'type':'channel.chat.message','version':'1','condition':{'broadcaster_user_id':'123','user_id':'123'},'status':'enabled'}
        return identifier,sub,secret

    def test_01_migration_enables_and_forces_rls_on_every_native_table(self):
        rows=self.sql("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('pr_twitch_actions','pr_twitch_subscriptions','pr_twitch_events','pr_twitch_context','pr_twitch_maintenance')")
        self.assertEqual(len(rows),5)
        self.assertTrue(all(r[1] and r[2] for r in rows))

    def test_02_authenticated_browser_cannot_select_or_write_native_tables(self):
        for role in ('anon','authenticated'):
            for table in ('pr_twitch_actions','pr_twitch_subscriptions','pr_twitch_events','pr_twitch_context','pr_twitch_maintenance'):
                with self.subTest(role=role,table=table):
                    for privilege in ('SELECT','INSERT','UPDATE','DELETE'):
                        self.assertFalse(self.sql('SELECT has_table_privilege(%s,%s,%s)',(role,'public.'+table,privilege))[0][0])
        with self.factory() as db:
            db.execute('SET LOCAL ROLE authenticated')
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege): db.execute('SELECT * FROM pr_twitch_actions')

    def test_03_service_role_can_use_real_rls_runtime_policy(self):
        self.preview()
        with self.factory() as db:
            db.execute('SET LOCAL ROLE service_role')
            self.assertEqual(db.execute('SELECT count(*) FROM pr_twitch_actions').fetchone()[0],1)

    def test_04_cross_tenant_connections_identical_local_ids_stay_distinct(self):
        a=self.service.list_connections(WS,'alice')['connections'][0]
        b=self.service.list_connections(OTHER,'bob')['connections'][0]
        self.assertEqual((a['id'],b['id']),(CONN,CONN))
        self.assertEqual((a['providerAccountId'],b['providerAccountId']),('123','456'))
        error=self.assert_denied(lambda:self.service.overview(WS,'bob',CONN))
        self.assertEqual((error.status,str(error)),(403,'Workspace unavailable.'))
        self.assertEqual(self.wire.calls,[])

    def test_05_preview_has_no_native_mutation_and_encrypts_content(self):
        p=self.preview()
        self.assertEqual(p['state'],'draft'); self.assertEqual(self.wire.writes,[])
        raw=self.sql('SELECT payload::text,manifest::text FROM pr_twitch_actions')[0]
        self.assertNotIn('Approved title',' '.join(raw)); self.assertIn('ciphertext',raw[0])
        audit=self.sql('SELECT meta::text FROM pr_audit_events')
        self.assertNotIn('Approved title',str(audit)); self.assertNotIn('access-123',str(audit))

    def test_06_wrong_hash_cannot_approve(self):
        p=self.preview()
        self.assert_denied(lambda:self.service.approve(WS,'alice',CONN,p['id'],{'confirmed':True,'payloadHash':'b'*64}),code='twitch_approval_payload_changed')
        self.assertEqual(self.sql('SELECT state FROM pr_twitch_actions')[0][0],'draft')

    def test_07_actor_bound_even_another_owner_cannot_approve(self):
        p=self.preview()
        self.assert_denied(lambda:self.service.approve(WS,'admin',CONN,p['id'],{'confirmed':True,'payloadHash':p['payloadHash']}),code='twitch_approval_actor_mismatch')

    def test_08_viewer_cannot_prepare_or_approve(self):
        self.assert_denied(lambda:self.service.preview(WS,'eve',CONN,{'action':'twitch.channel.update','payload':{'title':'No'}}))
        self.assertEqual(self.wire.calls,[])

    def test_09_recent_interactive_session_required(self):
        p=self.preview(); self.verify.stale=True
        self.assert_denied(lambda:self.service.approve(WS,'alice',CONN,p['id'],{'confirmed':True,'payloadHash':p['payloadHash']}),code='step_up_required')

    def test_10_agent_cannot_approve_own_preview_even_full_permission(self):
        from postriff_phase2.agent_runtime_v2 import authz
        with authz.in_tool(): p=self.preview()
        with authz.in_tool():
            self.assert_denied(lambda:self.service.approve(WS,'alice',CONN,p['id'],{'confirmed':True,'payloadHash':p['payloadHash']}),code='twitch_human_approval_required')

    def test_11_expired_preview_cannot_approve(self):
        p=self.preview(); self.clock.now+=601
        self.assert_denied(lambda:self.service.approve(WS,'alice',CONN,p['id'],{'confirmed':True,'payloadHash':p['payloadHash']}),code='twitch_approval_expired')

    def test_12_encrypted_payload_tampering_fails_exact_consent(self):
        p=self.preview()
        self.sql('UPDATE pr_twitch_actions SET payload=%s::jsonb WHERE id=%s',(json.dumps(self.service._seal({'title':'Changed title'})),p['id']))
        self.assert_denied(lambda:self.service.approve(WS,'alice',CONN,p['id'],{'confirmed':True,'payloadHash':p['payloadHash']}),code='twitch_approval_integrity_failed')

    def test_13_concurrent_workers_issue_exactly_one_mutation(self):
        p=self.approved()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.service.dispatch_one(WS,CONN,p['id']),range(2)))
        self.assertEqual(len(self.wire.writes),1)
        self.assertEqual(self.sql('SELECT state FROM pr_twitch_actions')[0][0],'succeeded')
        self.assertTrue(any(r['state']=='succeeded' for r in results))

    def test_14_unknown_write_never_retries(self):
        p=self.approved(); self.wire.failure=TimeoutError('sensitive upstream text')
        r=self.service.dispatch_one(WS,CONN,p['id'])
        self.assertEqual(r['state'],'outcome_unknown')
        self.service.dispatch_one(WS,CONN,p['id'])
        self.assertEqual(len(self.wire.writes),1)
        self.assertNotIn('sensitive upstream',str(self.sql('SELECT error,meta FROM pr_twitch_actions JOIN pr_audit_events ON subject=pr_twitch_actions.id::text')))

    def test_15_generation_change_revokes_queued_authority(self):
        p=self.approved(); access,key=self.vault.encrypt(self.provider._seal('access-123','at','123','b'*32))
        self.sql('UPDATE pr_encrypted_credentials SET access_ciphertext=%s,key_id=%s WHERE workspace_id=%s',(access,key,WS))
        self.service.dispatch_one(WS,CONN,p['id']); self.assertEqual(self.wire.writes,[])

    def test_16_scope_reduction_purges_approved_payload_and_stops_write(self):
        p=self.approved(); self.wire.scopes=[]
        self.service.dispatch_one(WS,CONN,p['id'])
        row=self.sql('SELECT state,payload,manifest FROM pr_twitch_actions')[0]
        self.assertEqual(row,('revoked',{},{})); self.assertEqual(self.wire.writes,[])

    def test_17_current_membership_is_checked_before_provider_call(self):
        p=self.approved(); before=len(self.wire.calls)
        self.sql("UPDATE pr_memberships SET status='removed' WHERE user_id=%s",(ALICE,))
        self.service.dispatch_one(WS,CONN,p['id'])
        self.assertEqual(len(self.wire.calls),before); self.assertEqual(self.wire.writes,[])

    def test_18_current_workspace_block_stops_dispatch(self):
        p=self.approved()
        self.sql("UPDATE pr_workspaces SET state=jsonb_set(state,'{accountBlock}','true') WHERE id=%s",(WS,))
        self.service.dispatch_one(WS,CONN,p['id']); self.assertEqual(self.wire.writes,[])

    def test_19_schedule_does_not_dispatch_early(self):
        future=datetime.fromtimestamp(self.clock()+3600,timezone.utc).isoformat()
        p=self.approved(executeAt=future)
        r=self.service.dispatch_one(WS,CONN,p['id']); self.assertFalse(r['dispatched'])
        self.assertEqual(self.wire.writes,[])
        self.clock.now+=3600
        self.assertEqual(self.service.dispatch_one(WS,CONN,p['id'])['state'],'succeeded')

    def test_20_postgres_microsecond_precision_does_not_change_consent(self):
        self.clock.now+=0.1234567
        p=self.approved(); self.assertEqual(self.service.dispatch_one(WS,CONN,p['id'])['state'],'succeeded')

    def test_21_cancellation_stops_native_mutation(self):
        p=self.approved(); self.service.cancel(WS,'alice',CONN,p['id'],{})
        self.service.dispatch_one(WS,CONN,p['id']); self.assertEqual(self.wire.writes,[])

    def test_22_release_disabled_causes_zero_egress(self):
        self.provider.execution_enabled=False
        self.assert_denied(lambda:self.preview(),code='twitch_release_blocked')
        self.service.maintenance()
        self.assertEqual(self.wire.calls,[])

    def test_23_stale_dispatch_recovery_is_unknown_not_replay(self):
        p=self.approved()
        self.sql("UPDATE pr_twitch_actions SET state='dispatching',dispatched_at=to_timestamp(%s) WHERE id=%s",(self.clock()-301,p['id']))
        self.service.maintenance(limit=1)
        self.assertEqual(self.sql('SELECT state FROM pr_twitch_actions')[0][0],'outcome_unknown')
        self.assertEqual(self.wire.writes,[])

    def test_24_registered_challenge_can_race_create_response_without_deadlock(self):
        self.wire.inline_challenge=True
        p=self.approved(action='twitch.eventsub.subscribe.stream.online',payload={})
        result=self.service.dispatch_one(WS,CONN,p['id'])
        self.assertIn(result['state'],('accepted','succeeded'))
        self.assertEqual(self.sql('SELECT state FROM pr_twitch_subscriptions')[0][0],'enabled')
        self.assertEqual(len(self.wire.writes),1)

    def test_25_duplicate_event_is_durable_once_and_encrypted(self):
        identifier,sub,secret=self.subscription(); headers,raw=signed(self.clock(),sub,secret)
        self.assertEqual(self.service.webhook(identifier,headers,raw),(b'',False))
        self.assertEqual(self.service.webhook(identifier,headers,raw),(b'',True))
        rows=self.sql('SELECT payload_ciphertext FROM pr_twitch_events')
        self.assertEqual(len(rows),1); self.assertNotIn('viewer content',rows[0][0])
        view=self.service.events(WS,'alice',CONN,{})
        self.assertEqual(len(view['data']),1)

    def test_26_tampered_webhook_has_no_durable_receipt(self):
        identifier,sub,secret=self.subscription(); headers,raw=signed(self.clock(),sub,secret)
        self.assert_denied(lambda:self.service.webhook(identifier,headers,raw+b' '),code='twitch_webhook_authentication_failed')
        self.assertEqual(self.sql('SELECT count(*) FROM pr_twitch_events')[0][0],0)

    def test_27_foreign_generation_webhook_fails_closed(self):
        identifier,sub,secret=self.subscription()
        self.sql('UPDATE pr_twitch_subscriptions SET generation=%s WHERE id=%s',('c'*32,identifier))
        headers,raw=signed(self.clock(),sub,secret)
        self.assert_denied(lambda:self.service.webhook(identifier,headers,raw),code='twitch_webhook_generation_revoked')

    def test_28_database_constraint_rejects_event_tenant_substitution(self):
        identifier,sub,secret=self.subscription(); cipher,key=self.vault.encrypt('{}')
        with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
            self.sql("INSERT INTO pr_twitch_events(subscription_id,workspace_id,connection_id,generation,message_id,type,message_kind,payload_ciphertext,payload_key_id) VALUES(%s,%s,%s,%s,'foreign','channel.chat.message','notification',%s,%s)",(identifier,OTHER,CONN,GEN,cipher,key))

    def test_29_disconnect_purges_content_even_with_inflight_callback(self):
        identifier,sub,secret=self.subscription(); headers,raw=signed(self.clock(),sub,secret)
        reached=threading.Event(); release=threading.Event(); original=self.service.verifier.verify
        def delayed(*a,**k):
            result=original(*a,**k); reached.set()
            if not release.wait(5): raise AssertionError('Test synchronization timed out')
            return result
        def revoke():
            with self.factory() as db,db.cursor() as cur:
                cur.execute('SELECT id FROM pr_workspaces WHERE id=%s FOR UPDATE',(WS,))
                cur.execute('SELECT connection_id FROM pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s FOR UPDATE',(WS,CONN))
                self.service.lifecycle(cur,WS,CONN,'disconnected',None)
                cur.execute("UPDATE pr_encrypted_credentials SET revoked_at=now(),access_ciphertext='' WHERE workspace_id=%s AND connection_id=%s",(WS,CONN))
        with patch.object(self.service.verifier,'verify',side_effect=delayed),ThreadPoolExecutor(max_workers=2) as pool:
            callback=pool.submit(self.service.webhook,identifier,headers,raw)
            self.assertTrue(reached.wait(5)); revocation=pool.submit(revoke)
            # The lock query, not a long sleep, confirms revocation is waiting.
            waiting=False
            for _ in range(50):
                if self.sql("SELECT count(*) FROM pg_stat_activity WHERE datname='rafii_twitch_test' AND wait_event_type='Lock'")[0][0]: waiting=True; break
                threading.Event().wait(0.01)
            release.set(); callback.result(timeout=5); revocation.result(timeout=5)
            self.assertTrue(waiting)
        self.assertEqual(self.sql('SELECT count(*) FROM pr_twitch_events')[0][0],0)
        self.assertEqual(self.sql('SELECT state,secret_ciphertext FROM pr_twitch_subscriptions')[0],('cleanup_pending',''))

    def test_30_expired_events_are_removed_before_read_and_purged(self):
        identifier,sub,secret=self.subscription(); headers,raw=signed(self.clock(),sub,secret)
        self.service.webhook(identifier,headers,raw)
        self.clock.now+=86401
        self.assertEqual(self.service.events(WS,'alice',CONN,{})['data'],[])
        self.provider.execution_enabled=False
        self.service.maintenance(); self.assertEqual(self.sql('SELECT count(*) FROM pr_twitch_events')[0][0],0)

    def test_31_viewer_event_content_never_enters_agent_surface(self):
        from postriff_phase2.agent_runtime_v2 import authz
        with authz.in_tool():
            self.assert_denied(lambda:self.service.events(WS,'alice',CONN,{}),code='twitch_viewer_content_egress_not_authorized')

    def test_32_secret_requires_exact_approved_recent_session_and_is_not_stored(self):
        p=self.approved(action='twitch.stream.key.get',payload={})
        result=self.service.secret_access(WS,'alice',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True})
        self.assertEqual(result['secretResult']['data']['streamKey'],'synthetic-private-encoder-key')
        self.assert_denied(lambda:self.service.secret_access(WS,'alice',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True}))
        rows=self.sql('SELECT payload::text,manifest::text,result::text FROM pr_twitch_actions')
        self.assertNotIn('synthetic-private-encoder-key',str(rows))
        self.assertNotIn('synthetic-private-encoder-key',str(self.service.overview(WS,'alice',CONN)))

    def test_33_download_separate_content_authorization_cannot_be_inferred(self):
        self.service.content_storage_approved=False
        self.assert_denied(lambda:self.preview(action='twitch.clip.download',payload={'clip_id':['Clip123']},rightsConfirmed=True),code='twitch_rights_declaration_required')
        self.assertEqual(self.wire.calls,[])

    def test_34_explicit_account_check_populates_ui_eligibility(self):
        result=self.service.read(WS,'alice',CONN,'twitch.account.verify',{'payload':{}})
        self.assertEqual(result['data']['accountType'],'affiliate')
        self.assertTrue(result['data']['isLive'])
        self.assertEqual(self.sql('SELECT account_type,is_live FROM pr_twitch_context')[0],('affiliate',True))

    def test_35_missing_scope_projects_real_progressive_consent(self):
        self.sql('UPDATE pr_encrypted_credentials SET scopes=%s WHERE workspace_id=%s',([],WS))
        view=self.service.overview(WS,'alice',CONN)
        op=next(c for c in view['capabilities'] if c['action']=='twitch.channel.update')
        self.assertTrue(op['canUpgrade']); self.assertEqual(op['availability']['state'],'blocked')
        self.assertIn(['channel:manage:broadcast'],op['requiredScopes'])

    def test_36_markers_need_a_recorded_setting_attestation(self):
        from postriff_phase2.twitch_native import OPERATIONS
        action=next(op.action for op in OPERATIONS.values() if op.resource_policy=='marker_settings')
        self.assert_denied(lambda:self.preview(action=action,payload={}),code='twitch_past_broadcasts_attestation_required')
        p=self.preview(action=action,payload={},pastBroadcastsEnabled=True)
        self.assertTrue(p['declarations']['pastBroadcastsEnabled'])

    def test_37_ai_purpose_gate_is_independent_of_public_connect(self):
        from postriff_phase2.agent_runtime_v2 import authz
        self.service.agent_processing_approved=False
        with authz.in_tool(): self.assert_denied(lambda:self.preview(),code='twitch_agent_data_purpose_not_authorized')
        self.assertEqual(self.wire.calls,[])

    def test_38_chat_clear_requires_moderation_not_reply_permission(self):
        self.assertEqual(_right('twitch.chat.clear'),'moderate')

    def test_39_validation_cursor_is_durable_and_prevents_duplicate_sweep(self):
        one=self.service.validation_tick(limit=1)
        self.assertEqual(one['validated'],1); self.assertIsNotNone(one['next'])
        two=self.service.validation_tick(limit=1)
        self.assertEqual(two['validated'],1); self.assertIsNone(two['next'])
        self.assertEqual(self.service.validation_tick(limit=1)['state'],'waiting')
        self.assertIsNotNone(self.sql("SELECT completed_at FROM pr_twitch_maintenance WHERE name='validation'")[0][0])

    def test_40_http_connection_cannot_select_foreign_action(self):
        p=self.approved()
        self.assert_denied(lambda:self.service.approve(OTHER,'bob',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True}),code='twitch_action_unavailable')
        self.assertEqual(self.wire.writes,[])

    def test_41_database_rejects_foreign_tenant_approval_as_subscription_parent(self):
        p=self.approved(); cipher,key=self.vault.encrypt('synthetic-long-secret')
        with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
            self.sql("INSERT INTO pr_twitch_subscriptions(id,workspace_id,connection_id,generation,action_id,type,version,condition,state,secret_ciphertext,secret_key_id) VALUES(%s,%s,%s,%s,%s,'stream.online','1','{}','pending',%s,%s)",(str(uuid.uuid4()),OTHER,CONN,GEN,p['id'],cipher,key))

    def test_42_eventsub_storage_requires_separate_recorded_purpose(self):
        self.service.content_storage_approved=False
        self.assert_denied(lambda:self.preview(action='twitch.eventsub.subscribe.stream.online',payload={}),code='twitch_eventsub_content_storage_not_authorized')
        self.assertEqual(self.wire.writes,[])

    def test_43_withdrawn_storage_purpose_discards_new_events_and_purges_old(self):
        identifier,sub,secret=self.subscription(); headers,raw=signed(self.clock(),sub,secret)
        self.service.webhook(identifier,headers,raw)
        self.service.content_storage_approved=False
        headers2,raw2=signed(self.clock(),sub,secret,message='second-message')
        self.assertEqual(self.service.webhook(identifier,headers2,raw2),(b'',False))
        self.assertEqual(self.sql('SELECT count(*) FROM pr_twitch_events')[0][0],1)
        self.provider.execution_enabled=False
        self.service.maintenance()
        self.assertEqual(self.sql('SELECT count(*) FROM pr_twitch_events')[0][0],0)
        self.assertEqual(self.sql('SELECT state FROM pr_twitch_subscriptions')[0][0],'cleanup_pending')

    def test_44_ai_purpose_withdrawal_stops_already_approved_agent_action(self):
        from postriff_phase2.agent_runtime_v2 import authz
        with authz.in_tool(): p=self.preview()
        self.service.approve(WS,'alice',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True})
        self.service.agent_processing_approved=False
        self.service.dispatch_one(WS,CONN,p['id'])
        self.assertEqual(self.wire.writes,[])

    def test_45_app_rotation_projects_reconnect_instead_of_hiding_all_connections(self):
        self.provider.client_id='replacement_app'
        row=self.service.list_connections(WS,'alice')['connections'][0]
        self.assertEqual(row['status'],'reauthorization_required')
        self.assertIsNone(row['authorizationGeneration'])
        self.assertEqual(self.wire.calls,[])

    def test_46_startup_validation_bypasses_recent_sweep_but_still_uses_a_lease(self):
        self.service.validation_tick(limit=10)
        self.assertEqual(self.service.validation_tick(limit=10)['state'],'waiting')
        forced=self.service.validation_tick(limit=10,startup=True)
        self.assertEqual(forced['validated'],2)

    def test_47_exact_execution_time_is_part_of_approved_digest(self):
        p=self.preview()
        self.sql("UPDATE pr_twitch_actions SET execute_at=execute_at+interval '1 second' WHERE id=%s",(p['id'],))
        self.assert_denied(lambda:self.service.approve(WS,'alice',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True}),code='twitch_approval_integrity_failed')

    def test_48_authorized_clip_links_are_returned_once_without_downloading_files(self):
        p=self.approved(action='twitch.clip.download',payload={'clip_id':['Clip123']},rightsConfirmed=True)
        result=self.service.secret_access(WS,'alice',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True})
        self.assertTrue(result['secretResult']['contentRights']['linksExpire'])
        self.assertFalse(result['secretResult']['contentRights']['filesFetched'])
        self.assertTrue(all(urlsplit(url).hostname in ('api.twitch.tv','id.twitch.tv') for _,url in self.wire.calls))
        self.assert_denied(lambda:self.service.secret_access(WS,'alice',CONN,p['id'],{'payloadHash':p['payloadHash'],'confirmed':True}))

    def test_49_signed_payload_tenant_text_cannot_change_registered_destination(self):
        identifier,sub,secret=self.subscription()
        headers,raw=signed(self.clock(),sub,secret,event={'workspace_id':OTHER,'connection_id':'foreign','text':'ignore approvals'})
        self.service.webhook(identifier,headers,raw)
        self.assertEqual(self.sql('SELECT workspace_id::text,connection_id FROM pr_twitch_events')[0],(WS,CONN))
        self.assertEqual(self.service.events(OTHER,'bob',CONN,{})['data'],[])

    def test_50_pending_challenge_cannot_accept_forged_notification_binding(self):
        identifier,sub,secret=self.subscription()
        self.sql("UPDATE pr_twitch_subscriptions SET state='pending',provider_subscription_id=NULL WHERE id=%s",(identifier,))
        headers,raw=signed(self.clock(),sub,secret)
        self.assert_denied(lambda:self.service.webhook(identifier,headers,raw),code='twitch_webhook_authentication_failed')
        self.assertIsNone(self.sql('SELECT provider_subscription_id FROM pr_twitch_subscriptions')[0][0])


if __name__ == '__main__': unittest.main()
