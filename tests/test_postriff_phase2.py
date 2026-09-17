import base64
import copy
import io
import json
import secrets
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.store import Phase2Store
from postriff_phase2.contracts import digest, resolve_time, SCENARIOS
from postriff_phase2.media import decode_upload
from postriff_phase2.provider_candidates import AuthorizedTransport, LinkedInCandidate, InstagramCandidate, OpenAIImageCandidate, SupabaseSessionCandidate
from test_postriff_alpha import Journey


class P2Journey(Journey):
    def __init__(self, store, principal=None, plan='studio', provider='google'):
        self.store = store
        self.request = {'principalKey': principal or secrets.token_hex(16), 'provider': provider, 'proof': '123456' if provider=='email' else 'postriff-fixture-verified', 'requestId': secrets.token_hex(16), 'verifier': secrets.token_hex(32), 'plan': plan}
        self.request.update(store.auth.challenge(self.request))
        self.created = store.auth.sign_in(self.request)
        self.id,self.token=self.created['workspaceId'],self.created['token']
        self.snapshot=self.created

    def refresh(self):
        self.snapshot=self.store.get(self.id,self.token)
        return self


class Phase2Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.now=1_800_000_000.0
        self.store=Phase2Store(Path(self.tmp.name)/'p2.db', clock=lambda:self.now)
        self.j=P2Journey(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def channel(self, scenario='success', platform='LinkedIn', language='English'):
        self.j.act('p2_channel_add',platform=platform,language=language)
        c=self.j.state['phase2']['channels'][-1]
        self.j.act('p2_channel_verify',channelId=c['id'],scenario=scenario)
        return self.j.state['phase2']['channels'][-1]

    def draft(self):
        self.j.setup().act('generate',platform='LinkedIn',language='English')
        v=self.j.state['variants'][0]
        self.j.act('p2_variant_review',variantId=v['id'],variantRevision=v['revision'],confirmed=True,excludedUnknowns=v['unknowns'])
        return self.j.state['variants'][0]

    def review(self, channel, variant=None):
        variant=variant or self.j.state['variants'][0]
        self.j.act('p2_review',channelId=channel['id'],variantId=variant['id'],localTime=datetime.fromtimestamp(self.now+60,timezone.utc).replace(tzinfo=None).isoformat(),timeZone='UTC',acknowledgedWarnings=variant['warnings'])
        return self.j.state['phase2']['reviews'][-1]

    def enqueue(self, scenario='success'):
        self.draft()
        c=self.channel(scenario)
        r=self.review(c)
        self.j.act('p2_approve',reviewId=r['id'],digest=r['digest'],confirmed=True)
        return self.j.state['phase2']['jobs'][-1]

    def test_auth_replay_expiry_pkce_cancel_and_no_duplicate_trial(self):
        trial=copy.deepcopy(self.j.state['phase2']['trial'])
        replay=self.store.auth.sign_in(self.j.request)
        self.assertEqual(replay['workspaceId'],self.j.id)
        self.assertTrue(replay['auth']['retryReused'])
        for change in ({'verifier':'wrong'},{'principalKey':'another-principal-key'},{'cancelled':True},{'proof':'wrong'}):
            with self.subTest(change=change),self.assertRaises((AlphaError,ValueError)):
                self.store.auth.sign_in({**self.j.request,**change})
        self.now+=301
        with self.assertRaises(AlphaError): self.store.auth.sign_in(self.j.request)
        self.j.act('p2_plan',plan='assist')
        after=self.j.state['phase2']['trial']
        self.assertEqual(after['expiresAt'],trial['expiresAt'])
        self.assertEqual(after['writingGrant'],10)
        with self.assertRaises(AlphaError): self.j.act('p2_plan',plan='business')
        with self.store.connect() as db:
            self.assertEqual(db.execute('select count(*) from p2_trial_grants').fetchone()[0],1)

    def test_all_modes_skills_trial_and_sample_isolation(self):
        for mode in ('personal','niche','business','hybrid'):
            self.j.act('mode',mode=mode)
            self.assertEqual(len(self.j.state['skillInstances']),3)
        sample=self.store.create(True)
        self.assertIsNone(sample['state']['trial'])
        self.assertNotIn('phase2',sample['state'])
        with self.assertRaises(AlphaError): self.store.mutate(sample['workspaceId'],sample['token'],1,'p2_plan',{'plan':'assist'})

    def test_two_users_cannot_read_mutate_export_or_delete(self):
        other=P2Journey(self.store)
        for fn in (lambda:self.store.get(other.id,self.j.token),lambda:self.store.export(other.id,self.j.token),lambda:self.store.mutate(other.id,self.j.token,other.snapshot['revision'],'p2_delete_account',{'confirmation':'DELETE'}),lambda:self.store.mutate(other.id,self.j.token,other.snapshot['revision'],'p2_approve',{})):
            with self.assertRaises(AlphaError): fn()
        self.assertNotEqual(self.j.state['speaker']['id'],other.state['speaker']['id'])

    def test_sign_in_same_identity_restores_and_revocation_rejects_replay(self):
        other_device=P2Journey(self.store,principal=self.j.request['principalKey'])
        self.assertEqual(other_device.id,self.j.id)
        self.j.refresh().act('p2_revoke_device',deviceId=other_device.state['device']['id'])
        with self.assertRaises(AlphaError): other_device.refresh()
        with self.assertRaises(AlphaError): self.store.auth.sign_in(other_device.request)
        self.j.act('p2_logout')
        with self.assertRaises(AlphaError): self.j.refresh()

    def test_link_recovery_collision_and_last_method(self):
        with self.assertRaises(AlphaError): self.j.act('p2_unlink_identity',provider='google')
        req={'provider':'email','proof':'123456','principalKey':secrets.token_hex(16),'requestId':secrets.token_hex(16),'verifier':secrets.token_hex(32)}
        req.update(self.store.auth.challenge(req))
        self.j.act('p2_link_identity',**req)
        recovered=P2Journey(self.store,principal=req['principalKey'],provider='email')
        self.assertEqual(recovered.id,self.j.id)
        other=P2Journey(self.store)
        collision={**req,'state':self.store.auth.challenge(req)['state']}
        with self.assertRaises(AlphaError): other.act('p2_link_identity',**collision)
        self.j.refresh().act('p2_unlink_identity',provider='google')
        self.assertEqual(self.j.state['phase2']['identities'],['email'])

    def test_session_expiry_and_account_deletion_tombstone(self):
        self.now+=86401
        with self.assertRaises(AlphaError): self.j.refresh()
        self.j=P2Journey(self.store,principal=self.j.request['principalKey'])
        self.j.act('p2_delete_account',confirmation='DELETE')
        with self.assertRaises(AlphaError): self.j.refresh()
        with self.assertRaises(AlphaError): P2Journey(self.store,principal=self.j.request['principalKey'])

    def test_manifest_approval_idempotency_and_tampering(self):
        job=self.enqueue()
        r=self.j.state['phase2']['reviews'][-1]
        with self.assertRaises(AlphaError): self.j.act('p2_approve',reviewId=r['id'],digest='forged',confirmed=True)
        self.j.act('p2_approve',reviewId=r['id'],digest=r['digest'],confirmed=True)
        self.assertEqual(len(self.j.state['phase2']['jobs']),1)
        variant=self.j.state['variants'][0]
        self.j.act('variant_edit',variantId=variant['id'],variantRevision=variant['revision'],text='A revised thought.')
        self.assertEqual(self.j.state['phase2']['jobs'][0]['state'],'held')
        self.assertEqual(self.j.state['phase2']['jobs'][0]['manifest'],job['manifest'])

    def test_no_callback_can_bypass_capability_preflight(self):
        v=self.draft()
        self.j.act('p2_channel_add',platform='LinkedIn')
        c=self.j.state['phase2']['channels'][0]
        self.assertEqual(c['displayState'],'Finish setup')
        with self.assertRaises(AlphaError): self.review(c,v)
        for scenario in ('expired','denied','capability_loss'):
            self.j.act('p2_channel_verify',channelId=c['id'],scenario=scenario)
            with self.assertRaises(AlphaError): self.review(c,v)

    def test_timezone_dst_gap_ambiguity_and_past(self):
        now=1_700_000_000
        for local,zone,fold in [('2026-03-08T02:30','America/New_York',None),('2026-11-01T01:30','America/New_York',None),('2020-01-01T12:00','UTC',None),('2030-01-01T12:00','bad/zone',None)]:
            with self.assertRaises(AlphaError):resolve_time(local,zone,fold,now)
        a=resolve_time('2026-11-01T01:30','America/New_York',0,now)
        b=resolve_time('2026-11-01T01:30','America/New_York',1,now)
        self.assertEqual(b['timestamp']-a['timestamp'],3600)

    def test_worker_verified_and_persistent_restart(self):
        self.enqueue()
        self.now+=61
        self.assertTrue(self.store.worker_step())
        self.assertEqual(self.j.refresh().state['phase2']['jobs'][0]['state'],'provider_accepted')
        self.store=Phase2Store(self.store.path,clock=lambda:self.now)
        for _ in range(2):self.now+=6;self.store.worker_step()
        job=self.store.get(self.j.id,self.j.token)['state']['phase2']['jobs'][0]
        self.assertEqual(job['state'],'verified')
        self.assertEqual(len(job['attempts']),1)
        self.assertEqual(job['verification']['method'],'fixture_lookup')

    def test_crash_before_and_after_submit_never_duplicate(self):
        for crash in ('before_submit','after_submit','after_acceptance'):
            with self.subTest(crash=crash):
                self.j=P2Journey(self.store)
                self.enqueue()
                self.now+=61
                self.store.worker_step(crash=crash)
                self.now+=31
                for _ in range(4): self.store.worker_step(); self.now+=6
                job=self.j.refresh().state['phase2']['jobs'][0]
                self.assertEqual(job['state'],'verified')
                self.assertEqual(len(job['attempts']),1)

    def test_uncertain_reconciles_without_resubmit(self):
        self.enqueue('uncertain');self.now+=61
        for _ in range(7):self.store.worker_step();self.now+=6
        j=self.j.refresh().state['phase2']['jobs'][0]
        self.assertEqual(j['state'],'uncertain')
        self.assertEqual(len(j['attempts']),1)
        self.assertIn('Manual',j['nextAction'])

    def test_rate_limit_bounded_and_other_destination_unaffected(self):
        self.enqueue('rate_limited')
        c=self.channel('success');r=self.review(c)
        self.j.act('p2_approve',reviewId=r['id'],digest=r['digest'],confirmed=True)
        self.now+=61
        for _ in range(12):self.store.worker_step();self.now+=61
        jobs=self.j.refresh().state['phase2']['jobs']
        self.assertEqual(jobs[0]['state'],'failed')
        self.assertEqual(len(jobs[0]['attempts']),3)
        self.assertEqual(jobs[1]['state'],'verified')

    def test_cancel_before_claim_and_during_submit(self):
        job=self.enqueue();self.j.act('p2_cancel',jobId=job['id']);self.now+=61
        self.store.worker_step()
        self.assertEqual(self.j.refresh().state['phase2']['jobs'][0]['attempts'],[])
        self.j=P2Journey(self.store);job=self.enqueue();self.now+=61
        self.store.worker_step(crash='after_submit')
        self.j.refresh().act('p2_cancel',jobId=job['id'])
        self.assertEqual(self.j.state['phase2']['jobs'][0]['state'],'uncertain')
        self.now+=31;self.store.worker_step()
        self.assertTrue(self.j.refresh().state['phase2']['jobs'][0]['cancelRequested'])

    def test_disconnect_expiry_and_reconnect_do_not_release(self):
        self.enqueue();c=self.j.state['phase2']['channels'][0]
        self.j.act('p2_channel_disconnect',channelId=c['id'])
        self.j.act('p2_channel_verify',channelId=c['id'],scenario='success')
        self.assertEqual(self.j.state['phase2']['jobs'][0]['state'],'held')
        self.j=P2Journey(self.store);self.enqueue()
        self.now+=15*86400;self.store.worker_step()
        with self.store.connect() as db:
            s=json.loads(db.execute('select state from workspaces where id=?',(self.j.id,)).fetchone()[0])
        self.assertEqual(s['phase2']['jobs'][0]['state'],'held')

    def art(self):
        self.draft()
        # Synthetic approved profile fixture. No generated interviews or real evidence.
        with self.store.connect() as db:
            row=db.execute('select state from workspaces where id=?',(self.j.id,)).fetchone()
            s=json.loads(row[0]);s['speaker']['revisions'][-1]['profile']['fields']=[{'id':'abstract','key':'voiceTraits','section':'voice','label':'Style','value':'warm clear PRIVATE_NAME INFP precise-address@example.invalid raw quotation','decision':'approved','privacy':'public','evidence':'user_confirmed','sourceIds':[]}]
            s['you']={'artFieldIds':['abstract'],'artwork':None,'identitySentence':'','events':[]}
            db.execute('update workspaces set state=? where id=?',(json.dumps(s),self.j.id))
        self.j.refresh()
        return self.j.state['phase2']['art']['providerBrief']

    def test_art_privacy_consent_cache_selection_deletion(self):
        brief=self.art()
        for marker in ('PRIVATE_NAME','INFP','example.invalid','sourceIds','workspaceId'):
            self.assertNotIn(marker,json.dumps(brief))
        self.j.act('p2_art_generate',consent=False)
        self.assertEqual(self.j.state['phase2']['art']['candidates'],[])
        with self.assertRaises(AlphaError):self.j.act('p2_art_generate',consent=True,briefHash=digest(brief),count=4)
        self.j.act('p2_art_generate',consent=True,briefHash=digest(brief),count=3)
        candidates=self.j.state['phase2']['art']['candidates']
        self.assertEqual(len(candidates),3)
        self.j.act('p2_art_generate',consent=True,briefHash=digest(brief),count=3)
        self.assertEqual(self.j.state['phase2']['trial']['artworkUsed'],1)
        self.j.act('p2_art_select',assetId=candidates[1]['id'],focal=[.3,.6])
        selected=self.j.state['phase2']['art']['selected']
        self.j.act('you_identity',value='Changed identity')
        self.assertEqual(self.j.state['phase2']['art']['selected'],selected)
        second=P2Journey(self.store,principal=self.j.request['principalKey'])
        self.assertEqual(second.state['phase2']['art']['selected'],selected)
        self.j.refresh().act('p2_art_delete')
        self.assertIsNone(self.j.state['phase2']['art']['selected'])
        self.assertEqual(self.j.state['phase2']['art']['candidates'],[])

    def test_art_failure_no_charge_and_private_export_no_credentials(self):
        brief=self.art()
        self.j.act('p2_art_generate',consent=True,briefHash=digest(brief),scenario='failed')
        self.assertEqual(self.j.state['phase2']['trial']['artworkUsed'],0)
        blob=self.store.export(self.j.id,self.j.token)
        with zipfile.ZipFile(io.BytesIO(blob)) as pack:
            content=''.join(pack.read(n).decode() for n in pack.namelist())
        self.assertNotIn(self.j.token,content)
        self.assertNotIn(self.j.request['principalKey'],content)

    def test_media_decoding_rejects_filename_lies_and_clears_metadata(self):
        with self.assertRaises(AlphaError):decode_upload({'data':base64.b64encode(b'<svg>bad</svg>').decode()})
        raw=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=640x640','-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True).stdout
        a=decode_upload({'data':base64.b64encode(raw).decode()})
        self.assertEqual((a['width'],a['height']),(640,640))
        self.assertEqual(a['mime'],'image/jpeg')
        self.assertNotEqual(a['sourceHash'],a['hash'])

    def test_claims_and_stale_commands_are_atomic(self):
        self.enqueue();self.now+=61
        self.store.worker_step(owner='worker-a',crash='before_submit')
        self.assertFalse(self.store.worker_step(owner='worker-b'))
        with self.assertRaises(AlphaError):self.j.act('p2_refresh')

    def test_bulk_approvals_are_atomic_and_idempotent(self):
        self.draft();r1=self.review(self.channel());r2=self.review(self.channel('failed'))
        requests=[{'reviewId':r['id'],'digest':r['digest']} for r in (r1,r2)]
        with self.assertRaises(AlphaError):self.j.act('p2_approve_many',confirmed=True,reviews=[requests[0],{'reviewId':r2['id'],'digest':'forged'}])
        self.assertEqual(self.j.refresh().state['phase2']['jobs'],[])
        self.j.act('p2_approve_many',confirmed=True,reviews=requests)
        self.j.act('p2_approve_many',confirmed=True,reviews=requests)
        self.assertEqual(len(self.j.state['phase2']['jobs']),2)

    def test_separate_process_worker_and_fenced_heartbeat(self):
        job=self.enqueue();self.now+=61
        self.store.worker_step(owner='worker-a',crash='before_submit')
        self.assertFalse(self.store.heartbeat(self.j.id,job['id'],'worker-b'))
        self.now+=10
        self.assertTrue(self.store.heartbeat(self.j.id,job['id'],'worker-a'))
        self.now+=31
        code='import sys;from postriff_phase2.store import Phase2Store;s=Phase2Store(sys.argv[1],clock=lambda:float(sys.argv[2]));s.worker_step(owner="new-process")'
        import os
        env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
        subprocess.run([sys.executable,'-c',code,str(self.store.path),str(self.now)],env=env,capture_output=True,check=True)
        saved=self.j.refresh().state['phase2']['jobs'][0]
        self.assertEqual(saved['state'],'provider_accepted')
        self.assertEqual(len(saved['attempts']),1)

    def test_media_preflight_and_deleted_asset_invalidates(self):
        self.draft();c=self.channel(platform='Instagram')
        self.j.act('generate',platform='Instagram',language='English')
        v=self.j.state['variants'][-1]
        self.j.act('p2_variant_review',variantId=v['id'],variantRevision=v['revision'],excludedUnknowns=v['unknowns'],confirmed=True)
        v=self.j.state['variants'][-1]
        with self.assertRaises(AlphaError):self.review(c,v)
        raw=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=640x640','-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True).stdout
        self.j.act('p2_media_upload',data=base64.b64encode(raw).decode())
        a=self.j.state['phase2']['assets'][-1]
        payload={'channelId':c['id'],'variantId':v['id'],'localTime':datetime.fromtimestamp(self.now+60,timezone.utc).replace(tzinfo=None).isoformat(),'timeZone':'UTC','acknowledgedWarnings':v['warnings'],'assetId':a['id'],'alt':'A solid blue square','rightsConfirmed':True}
        with self.assertRaises(AlphaError):self.j.act('p2_review',**{**payload,'rightsConfirmed':False})
        self.j.act('p2_review',**payload);r=self.j.state['phase2']['reviews'][-1]
        self.j.act('p2_approve',reviewId=r['id'],digest=r['digest'],confirmed=True)
        self.j.act('p2_media_delete',assetId=a['id'])
        self.assertEqual(self.j.state['phase2']['jobs'][-1]['state'],'held')

    def test_changed_approval_bindings_and_cross_workspace_objects(self):
        job=self.enqueue();m=job['manifest'];s=self.j.state
        mutations=[lambda s:s['speaker'].update(id='changed'),lambda s:s['brandHub'].update(speaker='different'),lambda s:s['phase2']['channels'][0].update(account='different'),lambda s:s['variants'][0].update(platform='Instagram'),lambda s:s['sources'][0].update(active=False)]
        for mutate in mutations:
            candidate=copy.deepcopy(s);mutate(candidate);self.assertFalse(self.store.current(candidate,m))
        other=P2Journey(self.store)
        for action,payload in [('p2_cancel',{'jobId':job['id']}),('p2_channel_disconnect',{'channelId':m['channelId']}),('p2_revoke_device',{'deviceId':s['device']['id']}),('p2_art_select',{'assetId':'foreign'}),('p2_approve',{'reviewId':s['phase2']['reviews'][0]['id'],'digest':digest(m),'confirmed':True})]:
            with self.subTest(action=action),self.assertRaises(AlphaError):other.act(action,**payload)

    def test_every_fixture_scenario_has_a_truthful_outcome(self):
        from postriff_phase2.contracts import FixtureSocial
        adapter=FixtureSocial();manifest={'idempotencyKey':'a'*64}
        with patch('socket.socket.connect',side_effect=AssertionError('Fixture may not send network requests')):
            for scenario in SCENARIOS:
                result=adapter.submit(manifest,scenario)
                self.assertIn(result['state'],('provider_accepted','uncertain','held','scheduled','failed'))
                self.assertNotIn(result['state'],('published','verified'))

    def test_candidate_requests_require_exact_server_authorization(self):
        job=self.enqueue();m=job['manifest']
        sent=[];authorizations={}
        transport=AuthorizedTransport(lambda request,approval:sent.append(request) or {'status':201,'headers':{'x-restli-id':'urn:li:share:123'}},lambda key:authorizations.get(key))
        li=LinkedInCandidate(transport,'202603');request=li.prepare(m,'urn:li:person:synthetic')
        with self.assertRaises(AlphaError):li.submit(request,'missing')
        self.assertEqual(sent,[])
        authorizations['test']={'state':'approved','requestDigest':digest(request)}
        self.assertEqual(li.submit(request,'test')['state'],'provider_accepted')
        self.assertEqual(li.reconciliation_request('urn:li:share:123',['w_member_social'])['state'],'uncertain')
        with self.assertRaises(AlphaError):li.submit({**request,'body':{}},'test')
        initialized=li.initialize_image_request('urn:li:person:synthetic')
        self.assertEqual(initialized['body']['initializeUploadRequest']['owner'],'urn:li:person:synthetic')
        init_result=li.classify_image_initialization({'status':200,'body':{'value':{'image':'urn:li:image:abc123','uploadUrl':'https://www.linkedin.com/dms-uploads/signed?x=1'}}})
        self.assertEqual(init_result['state'],'provider_accepted')
        upload=li.image_upload_request(init_result['uploadUrl'],b'\x89PNG\r\n\x1a\nsynthetic','image/png')
        self.assertEqual(base64.b64decode(upload['bodyBase64']),b'\x89PNG\r\n\x1a\nsynthetic')
        self.assertEqual(li.classify_image_upload({'status':201},init_result['imageUrn'])['state'],'provider_accepted')
        self.assertEqual(li.image_status_request(init_result['imageUrn'],['w_member_social'])['state'],'uncertain')
        status=li.image_status_request(init_result['imageUrn'],['r_member_social'])
        self.assertIn('/rest/images/urn%3Ali%3Aimage%3Aabc123',status['url'])
        self.assertEqual(li.classify_image_status({'status':200,'body':{'status':'AVAILABLE'}},init_result['imageUrn'])['state'],'verified')
        ig=InstagramCandidate('v23.0')
        with self.assertRaises(AlphaError):ig.publish_request('123','456','IN_PROGRESS')
        self.assertEqual(ig.publish_request('123','456','FINISHED')['body'],{'creation_id':'456'})
        self.assertEqual(ig.classify_container({'status_code':'FINISHED'})['state'],'provider_accepted')
        self.assertEqual(ig.classify_container({'status_code':'PUBLISHED'})['state'],'published')
        publish=ig.classify_publish({'status':200,'body':{'id':'123456'}})
        self.assertEqual(publish['state'],'provider_accepted')
        self.assertIn('fields=id,caption',ig.evidence_request('123456')['url'])
        evidence={'status':200,'body':{'id':'123456','caption':m['payload']['text'],'media_type':'IMAGE','media_product_type':'FEED','permalink':'https://www.instagram.com/p/ABC123/','username':'jamesaucreates','timestamp':'2026-09-14T12:00:00Z'}}
        self.assertEqual(ig.classify_evidence(evidence,m,'@jamesaucreates')['state'],'verified')
        self.assertEqual(ig.classify_evidence(evidence,m,'@someoneelse')['state'],'uncertain')

    def test_candidate_image_private_values_and_verified_user_boundary(self):
        brief=self.art();images=OpenAIImageCandidate(None,'review-required-model')
        descriptor=images.prepare(brief,3)
        self.assertEqual(descriptor['body']['n'],3)
        with self.assertRaises(AlphaError):images.prepare({**brief,'themes':['Private person','clarity']},3)
        with self.assertRaises(AlphaError):images.prepare({**brief,'sourceIds':['private']},3)
        user='00000000-0000-0000-0000-000000000001'
        auth=SupabaseSessionCandidate('https://synthetic.supabase.co',lambda url,token:{'status':200,'body':{'id':user,'email_confirmed_at':'2026-09-14','user_metadata':{'role':'admin','user_id':'forged'}}})
        self.assertEqual(auth.verify('synthetic-test'),user)
        invalid=SupabaseSessionCandidate('https://synthetic.supabase.co',lambda url,token:{'status':401,'body':{'id':user,'email_confirmed_at':'2026-09-14'}})
        with self.assertRaises(AlphaError):invalid.verify('expired')


if __name__=='__main__':unittest.main()
