"""Disposable PostgreSQL + actual adapter/worker/snapshot, injected provider only."""
import copy
import json
import unittest
from types import SimpleNamespace
import postgres_repository as fixture
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.hosted_worker import PostgresWorker
from postriff_phase2.contracts import digest, LIMITS
from postriff_phase2.content_types import content_preflight as preflight

connection, wid, service = fixture.connection, fixture.wid, fixture.service
with connection() as db:
    BASE = db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (wid,)).fetchone()[0]

class Provider:
    def __init__(self):
        self.calls = []; self.code = 'IN_PROGRESS'; self.publish_timeout = False; self.status_error = None; self.status_timeout = False; self.callback = None
    def __call__(self, method, url, **kw):
        self.calls.append((method, url))
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        if method == 'POST' and url.endswith('/media_publish'):
            if self.publish_timeout: raise TimeoutError('fixture')
            body = {'id': '999'}
        elif method == 'POST': body = {'id': '555'}
        elif '/999?' in url:
            body = {'id': '999', 'caption': self.text, 'permalink': 'https://www.instagram.com/p/ABC/', 'owner': {'id': '1789'}}
        else:
            if self.status_timeout: raise TimeoutError('read-only lookup timed out')
            if self.status_error: return {'status': self.status_error, 'body': {}, 'headers': {}}
            body = {'status_code': self.code}
        return {'status': 200, 'body': body, 'headers': {}}
    def count(self, ending): return sum(m == 'POST' and u.endswith(ending) for m,u in self.calls)

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.now = fixture.clock[0]
        s = copy.deepcopy(BASE); j = s['phase2']['jobs'][0]; m = j['manifest']; c = s['phase2']['channels'][0]
        v = next(v for v in s['variants'] if v['id'] == m['variantId'])
        c.update(platform='Instagram', accountType='professional', providerAccountId='1789', scopes=['instagram_business_basic','instagram_business_content_publish'])
        v['platform'] = 'Instagram'
        a = {'id': 'image', 'hash': 'hash', 'deleted': False}
        s['phase2']['assets'] = [a]
        m.update(platform='Instagram', providerAccountId='1789', operation='professional_image', limitsVersion=LIMITS['Instagram']['version'], media=[{'id':'image', 'hash':'hash','alt':'Approved image'}])
        m['capability']['scopes'] = c['scopes']; m['contentType']['preflight'] = preflight(s)
        j.update(state='scheduled', attempts=[], checks=0, nextAt=0, leaseUntil=0, leaseOwner=None, cancelRequested=False, approvalDigest=digest(m))
        for key in ('providerReference','providerConfirmed','verification','url','container','progress'): j.pop(key,None)
        self.assertTrue(service.commands.engine.current(s,m))
        self.save(s)
        with connection() as db: db.execute("UPDATE public.pr_memberships SET status='active',role='owner' WHERE user_id=%s",(j['approvedBy'],))
        self.provider = Provider(); self.provider.text = m['payload']['text']
        oauth = SimpleNamespace(token_for_worker=lambda *_: {'accessToken':'fixture','scopes':c['scopes']})
        assets = SimpleNamespace(storage=SimpleNamespace(signed_url=lambda *_:'https://example.invalid/fixture.jpg'))
        self.social = HostedSocial(oauth, {'instagram':SimpleNamespace(production_reviewed=True)}, assets, self.provider)
        self.worker = self.restart()
    def restart(self): return PostgresWorker(connection,self.social,clock=lambda:self.now)
    def state(self):
        with connection() as db: return db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]
    def save(self,s):
        with connection() as db: db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(s),wid))
    def job(self): return self.state()['phase2']['jobs'][0]
    def step(self, **kw):
        self.worker.step(**kw); self.now += 61; self.worker = self.restart()
    def ready(self):
        self.step(); self.provider.code='FINISHED'; self.step()
    def test_processing_container_is_persisted_and_resumed_after_restart(self):
        self.step()
        self.assertEqual(self.job().get('container'),'555')
        self.assertEqual(self.job().get('progress',{}).get('stage'),'container_created')
        self.step(); self.provider.code='FINISHED'; self.step(); self.step(); self.step()
        job=service.get(wid,'fixture-one')['state']['phase2']['jobs'][0]
        self.assertEqual(job['state'],'verified'); self.assertEqual(job['url'],'https://www.instagram.com/p/ABC/')
        self.assertEqual(job['container'],'555'); self.assertEqual(job['providerReference'],'999')
        self.assertEqual(job['verification']['method'],'provider_lookup')
        from pathlib import Path
        receipt = Path('docs/postriff-research-20260918/evidence/receipt-snapshot.json')
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(job))
        self.assertEqual(self.provider.count('/media'),1); self.assertEqual(self.provider.count('/media_publish'),1)
    def test_unknown_publish_response_does_not_resubmit(self):
        self.ready(); self.provider.publish_timeout=True
        for _ in range(8): self.step()
        self.assertEqual(self.provider.count('/media_publish'),1); self.assertEqual(self.job()['state'],'uncertain')
    def test_crash_after_create_does_not_recreate(self):
        self.step(crash='after_provider')
        for _ in range(3): self.step()
        self.assertEqual(self.provider.count('/media'),1); self.assertEqual(self.provider.count('/media_publish'),0)
        self.assertEqual(self.job()['state'],'uncertain')
    def test_crash_after_publish_does_not_republish(self):
        self.ready(); self.step(crash='after_provider')
        for _ in range(3): self.step()
        self.assertEqual(self.provider.count('/media_publish'),1); self.assertEqual(self.job()['state'],'uncertain')
    def test_two_workers_and_expired_lease_cannot_overwrite(self):
        claimed=self.worker.claim(); other=self.restart()
        self.assertIsNone(other.claim())
        self.now+=46; other.step()
        self.assertFalse(self.worker.complete(claimed,{'state':'verified','reference':'999','verification':'provider_lookup','confirmed':'stale'}))
        self.assertNotEqual(self.job()['state'],'verified')
    def test_changed_approval_account_or_membership_blocks_publish(self):
        for kind in ('text','account','time','authority','media'):
            with self.subTest(kind=kind):
                self.setUp(); self.ready(); s=self.state(); j=s['phase2']['jobs'][0]
                if kind=='text': s['variants'][0]['text']='Edited'
                elif kind=='account': s['phase2']['channels'][0]['providerAccountId']='other'
                elif kind=='time': j['manifest']['timing']['utc']='2030-01-01T00:00:00Z'
                elif kind=='media': s['phase2']['assets'][0]['hash']='changed'
                else:
                    with connection() as db: db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE user_id=%s",(j['approvedBy'],))
                self.save(s); self.step()
                self.assertEqual(self.provider.count('/media_publish'),0); self.assertEqual(self.job()['state'],'held')
    def test_rate_limit_after_creation_does_not_create_second_container(self):
        self.step(); self.provider.status_error=429; self.step(); self.provider.status_error=None
        self.provider.code='FINISHED'
        for _ in range(3): self.step()
        self.assertEqual(self.provider.count('/media'),1); self.assertEqual(self.job()['state'],'verified')
    def test_cancel_before_publish_stops_and_after_acceptance_remains_requested(self):
        self.ready(); s=self.state(); s['phase2']['jobs'][0]['cancelRequested']=True; self.save(s); self.step()
        self.assertEqual(self.provider.count('/media_publish'),0); self.assertEqual(self.job()['state'],'canceled')
        self.setUp(); self.ready(); self.step(); s=self.state(); s['phase2']['jobs'][0]['cancelRequested']=True; self.save(s); self.step()
        self.assertTrue(self.job()['cancelRequested']); self.assertEqual(self.job()['state'],'verified')
    def test_slow_response_cannot_commit_after_lease_expires(self):
        self.provider.callback=lambda: setattr(self,'now',self.now+46)
        self.step(); self.step()
        self.assertEqual(self.provider.count('/media'),1); self.assertEqual(self.job()['state'],'uncertain')

    def test_read_timeout_keeps_forward_progress_separate_from_unknown_publish(self):
        self.step(); self.provider.status_timeout=True; self.step()
        self.assertEqual(self.job()['state'],'processing')
        self.provider.status_timeout=False; self.provider.code='FINISHED'
        for _ in range(3): self.step()
        self.assertEqual(self.job()['state'],'verified')
        self.assertEqual(self.provider.count('/media'),1)
        self.assertEqual(self.provider.count('/media_publish'),1)

    def test_legacy_container_without_stage_never_recreates_or_publishes(self):
        s=self.state(); s['phase2']['jobs'][0]['container']='555'; self.save(s)
        self.provider.code='FINISHED'
        for _ in range(3): self.step()
        self.assertEqual(self.provider.count('/media'),0)
        self.assertEqual(self.provider.count('/media_publish'),0)
        self.assertEqual(self.job()['state'],'uncertain')

    def test_crash_after_publish_intent_before_network_never_retries(self):
        self.ready(); self.step(crash='after_claim')
        for _ in range(3): self.step()
        self.assertEqual(self.provider.count('/media_publish'),0)
        self.assertEqual(self.job()['state'],'uncertain')

    def test_cancel_between_claim_and_dispatch_sends_nothing(self):
        self.ready()
        original=self.worker.claim
        def claim_then_cancel():
            claimed=original(); s=self.state(); s['phase2']['jobs'][0]['cancelRequested']=True; self.save(s)
            return claimed
        self.worker.claim=claim_then_cancel
        self.step()
        self.assertEqual(self.provider.count('/media_publish'),0)
        self.assertEqual(self.job()['state'],'canceled')

    def test_permission_failure_after_container_holds_without_recreation(self):
        self.step(); self.provider.status_error=403; self.step()
        self.assertEqual(self.job()['state'],'held')
        self.assertEqual(self.provider.count('/media'),1)
        self.assertEqual(self.provider.count('/media_publish'),0)

    def test_slow_publish_and_competing_worker_never_duplicate(self):
        self.ready()
        def competing():
            self.now+=46
            self.restart().step()
        self.provider.callback=competing
        self.step(); self.step()
        self.assertEqual(self.provider.count('/media_publish'),1)
        self.assertEqual(self.job()['state'],'uncertain')

if __name__=='__main__':
    import sys
    outcome = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Lifecycle))
    sys.exit(not outcome.wasSuccessful())
