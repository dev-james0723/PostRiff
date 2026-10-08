"""Offline contracts only. Synthetic tests never qualify live capabilities."""
import copy
import hashlib
import json
import unittest
import io
import base64
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from postriff_alpha.domain import AlphaError
from postriff_phase2.official_social import CATALOG, capability_states, implementation_revision
from postriff_phase2.official_publishers import OfficialPublishers
from postriff_phase2.official_operations import OfficialAPI
from postriff_phase2.social_formats import options, web_url
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.providers import LinkedInProvider, ThreadsProvider, InstagramProvider, registry_from_environment
from postriff_phase2.wave3_connectors import YouTubeProvider, PinterestProvider, FacebookPagesProvider
from postriff_phase2.outcomes import normalize_result
from postriff_phase2.social_budget import BudgetedToken, XRequestBudget
from postriff_phase2.social_connectors import XProvider
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.social_documents import decode_pdf, decode_gif
from postriff_phase2.official_action_contracts import validate


class Transport:
    def __init__(self, replies): self.replies, self.calls = list(replies), []
    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.replies: raise AssertionError('Unexpected provider request: '+method+' '+url)
        response = self.replies.pop(0)
        if isinstance(response, Exception): raise response
        return response


def response(body=None, status=200, **headers): return {'status': status, 'body': body or {}, 'headers': headers}

def runtime(provider, replies, media=(), options=None):
    transport = Transport(replies);provider.transport = transport;provider.production_reviewed = True
    grant = {'accessToken': 'TOKEN', 'scopes': list({s for scope in provider.SCOPES.values() for s in scope})}
    if provider.id in ('youtube', 'pinterest', 'tiktok', 'x'): grant['accessToken'] = json.dumps({'v':1,'at':'TOKEN'})
    raw = b'media';digest = hashlib.sha256(raw).hexdigest()
    assets = [dict(id=str(i), mime=mime, hash=digest, bytes=len(raw), rightsConfirmed=True, alt='Scene') for i, mime in enumerate(media)]
    storage = SimpleNamespace(get=lambda *_: raw, signed_url=lambda *_: 'https://media.example/approved', tiktok_transfer_url=lambda *_: 'https://media.example/approved')
    vault = CredentialVault(CredentialVault.generate_key())
    host = SimpleNamespace(transport=transport, _provider=lambda _: provider, oauth=SimpleNamespace(vault=vault, token_for_worker=lambda *_: grant), assets=SimpleNamespace(storage=storage), _video=lambda m: ((raw, m['media'][0]), None))
    manifest = {'workspaceId': 'W', 'channelId': 'C', 'platform': provider.platform, 'providerAccountId': 'urn:li:person:abc' if provider.id=='linkedin' else '12345', 'payload': {'text': 'Approved'}, 'media': assets, 'publishOptions': options or {}}
    return OfficialPublishers(host), manifest, transport, grant


def job(stage, result=None):
    return {**(result or {}), 'progress': {'version': 1, 'stage': stage}}


class CapabilityQualification(unittest.TestCase):
    def test_all_eight_catalogued_and_unsupported_surfaces_are_explicit(self):
        self.assertEqual(len(CATALOG), 8)
        self.assertEqual(CATALOG['youtube']['community_posts'].support, 'unsupported')
        self.assertEqual(CATALOG['x']['article_publish'].support, 'documented')
        self.assertIn('organization_image', CATALOG['linkedin'])
    def test_identity_does_not_promote_other_capabilities(self):
        channel = {'evidenceSource': 'live_provider', 'providerAccountId': '123', 'identityVerified': True, 'expiresAt': 5000, 'scopes': ['threads_basic'], 'eligibility': {'identity': True}}
        rows = capability_states('threads', channel, now=1000)
        self.assertFalse(rows['publish']['granted']);self.assertFalse(rows['identity']['liveE2E'])
        self.assertTrue(all(row['state']!='READY' for row in rows.values()))
    def test_linkedin_member_identity_uses_only_minimum_connection_review(self):
        channel = {'evidenceSource': 'live_provider', 'providerAccountId': 'member-1', 'accountType': 'member', 'identityVerified': True, 'expiresAt': 5000, 'scopes': ['openid', 'profile', 'w_member_social']}
        review = {'state': 'approved', 'audience': 'external', 'appId': 'APP', 'approvedScopes': ['openid', 'profile'], 'evidenceRef': 'synthetic-unit-only'}
        rows = capability_states('linkedin', channel, connection_approval=review, now=1000)
        for key in ('connected', 'member_identity'):
            self.assertTrue(rows[key]['appApproved'])
            self.assertTrue(rows[key]['eligible'])
            self.assertTrue(rows[key]['granted'])
            self.assertFalse(rows[key]['liveE2E'])
            self.assertEqual(rows[key]['state'], 'BLOCKED')
            self.assertEqual(rows[key]['blockers'], ['LIVE E2E NOT PROVEN'])
        self.assertFalse(rows['member_publish']['appApproved'])
        self.assertFalse(rows['organization_identity']['eligible'])
        review['approvedScopes'] = ['openid']
        self.assertFalse(capability_states('linkedin', channel, connection_approval=review, now=1000)['member_identity']['appApproved'])
        channel['identityVerified'] = False
        self.assertFalse(capability_states('linkedin', channel, now=1000)['member_identity']['eligible'])

    def test_six_dimensions_and_exact_account_grant_revision_evidence(self):
        channel = {'evidenceSource': 'live_provider', 'providerAccountId': '123', 'identityVerified': True, 'expiresAt': 5000, 'scopes': ['threads_basic'], 'eligibility': {'identity': True}}
        approval = {'threads': {'state': 'approved', 'appId': 'APP', 'evidenceRef': 'review'}}
        proof = {'identity': {'state': 'passed', 'kind': 'live_api', 'accountId': '123', 'destinationId': None, 'implementationRevision': implementation_revision(), 'grantHash': hashlib.sha256(json.dumps(['threads_basic']).encode()).hexdigest(), 'appId': 'APP', 'evidenceRef': 'receipt', 'at': 900}}
        self.assertEqual(capability_states('threads', channel, approvals=approval, evidence=proof, now=1000)['identity']['state'], 'READY')
        proof['identity']['kind'] = 'fixture'
        self.assertFalse(capability_states('threads', channel, approvals=approval, evidence=proof, now=1000)['identity']['liveE2E'])
        proof['identity'].update(kind='live_api', accountId='OTHER')
        self.assertFalse(capability_states('threads', channel, approvals=approval, evidence=proof, now=1000)['identity']['liveE2E'])
    def test_linkedin_restricted_permissions_not_requested_speculatively(self):
        p=LinkedInProvider('app','secret')
        self.assertEqual(p.capability_scopes('identity'), ['openid','profile'])
        self.assertEqual(p.capability_scopes('organization_publish'), [])
        self.assertEqual(p.capability_scopes('posts_read'), [])
        p.approved_scopes={'w_organization_social','rw_organization_admin'}
        self.assertIn('w_organization_social', p.capability_scopes('organization_publish'))
    def test_progressive_basic_does_not_include_writes_or_messaging(self):
        for pid, catalog in CATALOG.items():
            identity=[f for f in catalog.values() if f.key in ('identity','member_identity','channel_identity','connected_person')]
            self.assertTrue(identity,pid)
            self.assertFalse(any('write' in s or 'publish' in s or 'messages' in s for f in identity for s in f.scopes),pid)
        self.assertNotIn('pages_manage_engagement',CATALOG['facebook']['comments'].scopes)
        self.assertEqual(CATALOG['youtube']['comments_read'].scopes,('https://www.googleapis.com/auth/youtube.readonly',))
        c={'evidenceSource':'live_provider','providerAccountId':'UCtest','identityVerified':True,'expiresAt':5000,'scopes':['https://www.googleapis.com/auth/youtube.force-ssl']}
        self.assertTrue(capability_states('youtube',c,now=1000)['thumbnail']['granted'])


class MediaLifecycle(unittest.TestCase):
    def test_tiktok_video_url_inbox_needs_verified_domain_and_never_uploads_bytes(self):
        from postriff_phase2.wave3_connectors import TikTokProvider
        p=TikTokProvider('app','secret');p.verified_media_domains={'media.example'}
        owner,m,t,g=runtime(p,[response({'data':{'publish_id':'inbox123'},'error':{'code':'ok'}})],['video/mp4'],{'mode':'inbox','consent':True,'transferMode':'url'})
        g['scopes']=['video.upload']
        result=owner.advance(m,job('create_attempted'),'create')
        self.assertEqual(result['state'],'provider_accepted');self.assertIn('creator must',result['confirmed'])
        self.assertEqual(t.calls[0][2]['body']['source_info'],{'source':'PULL_FROM_URL','video_url':'https://media.example/approved'})
        self.assertEqual(len(t.calls),1)
        p.verified_media_domains=set();t.replies=[];t.calls=[]
        self.assertEqual(owner.advance(m,job('create_attempted'),'create')['state'],'held');self.assertFalse(t.calls)
    def test_tiktok_photo_inbox_preserves_order_cover_and_top_level_disclosure(self):
        from postriff_phase2.wave3_connectors import TikTokProvider
        p=TikTokProvider('app','secret');p.verified_media_domains={'media.example'}
        owner,m,t,g=runtime(p,[response({'data':{'publish_id':'photo123'},'error':{'code':'ok'}})],['image/jpeg','image/jpeg'],{'mode':'inbox','consent':True,'coverIndex':1,'title':'Approved title','isAigc':True})
        owner.host.assets.storage.tiktok_transfer_url=lambda _w,_category,aid,*_: 'https://media.example/'+aid
        g['scopes']=['video.upload']
        result=owner.advance(m,job('create_attempted'),'create');body=t.calls[0][2]['body']
        self.assertEqual(body['post_mode'],'MEDIA_UPLOAD');self.assertTrue(body['is_aigc'])
        self.assertEqual(body['source_info']['photo_images'],['https://media.example/0','https://media.example/1'])
        self.assertEqual(body['source_info']['photo_cover_index'],1);self.assertNotIn('privacy_level',body['post_info'])
        self.assertEqual(result['state'],'provider_accepted');self.assertEqual(len(t.calls),1)
    def test_no_durable_intent_no_mutation(self):
        owner,m,t,_=runtime(ThreadsProvider('app','secret'), [])
        self.assertEqual(owner.advance(m,{},'create')['state'],'uncertain');self.assertEqual(t.calls,[])
    def test_processing_failure_is_not_published(self):
        owner,m,t,_=runtime(InstagramProvider('app','secret'), [response({'status_code':'ERROR'})], ['image/jpeg'])
        result=owner.advance(m,job('container_created',{'container':'10001'}),'status')
        self.assertEqual(result['state'],'failed');self.assertEqual(len(t.calls),1)
    def test_permission_loss_holds_before_create(self):
        owner,m,t,g=runtime(ThreadsProvider('app','secret'), [])
        g['scopes']=['threads_basic']
        self.assertEqual(owner.advance(m,job('create_attempted'),'create')['state'],'held');self.assertFalse(t.calls)
    def test_ordered_carousel_children_parent_and_publish(self):
        quota=response({'data':[{'quota_usage':0,'config':{'quota_total':250}}]})
        replies=[quota,response({'id':'101'}),response({'id':'102'}),response({'status_code':'FINISHED'}),response({'status_code':'FINISHED'}),response({'id':'103'}),response({'status_code':'FINISHED'}),quota,response({'id':'104'})]
        owner,m,t,_=runtime(ThreadsProvider('app','secret'),replies,['image/jpeg','video/mp4'],{'reply_to_id':'999'})
        r=owner.advance(m,job('create_attempted'),'create');self.assertEqual(r['state'],'processing')
        r=owner.advance(m,job('children_created',r),'status');self.assertEqual(r['progress']['stage'],'children_ready')
        r=owner.advance(m,job('parent_attempted',r),'parent')
        self.assertEqual(t.calls[5][2]['form']['children'],'101,102');self.assertEqual(t.calls[5][2]['form']['reply_to_id'],'999')
        r=owner.advance(m,job('container_created',r),'status')
        r=owner.advance(m,job('publish_attempted',r),'publish')
        self.assertEqual(r['reference'],'104');self.assertEqual(r['state'],'provider_accepted')
        self.assertEqual(t.calls[-1][2]['form']['creation_id'],'103')
    def test_parent_publish_timeout_is_uncertain_not_retried(self):
        quota=response({'data':[{'quota_usage':0,'config':{'quota_total':250}}]})
        owner,m,t,_=runtime(ThreadsProvider('app','secret'),[quota,AlphaError('timeout',502)])
        result=owner.advance(m,job('publish_attempted',{'container':'123'}),'publish')
        self.assertEqual(result['state'],'uncertain');self.assertEqual(len(t.calls),2)
    def test_quota_exhaustion_holds_without_container(self):
        owner,m,t,_=runtime(ThreadsProvider('app','secret'),[response({'data':[{'quota_usage':250,'config':{'quota_total':250}}]})])
        self.assertEqual(owner.advance(m,job('create_attempted'),'create')['state'],'held');self.assertEqual(len(t.calls),1)
    def test_linkedin_image_write_only_grant_does_not_skip_processing(self):
        owner,m,t,_=runtime(LinkedInProvider('app','secret'),[response(status=403),response(status=403)],['image/jpeg'])
        result=owner.advance(m,job('assets_uploaded',{'container':'urn:li:image:123','providerAssets':[{'id':'urn:li:image:123','kind':'images'}]}),'status')
        self.assertEqual(result['state'],'held');self.assertFalse(any(call[0]=='POST' for call in t.calls))
    def test_youtube_upload_session_encrypted_and_resumable(self):
        p=YouTubeProvider('app','secret')
        replies=[response(location='https://www.googleapis.com/upload/youtube/v3/videos?upload_id=secret'),response(status=308,range='bytes=0-1'),response({'id':'Abcdefghijk'})]
        owner,m,t,g=runtime(p,replies,['video/mp4'],{'title':'Video','privacyStatus':'private','madeForKids':False})
        r=owner.advance(m,job('create_attempted'),'create')
        self.assertNotIn('secret',json.dumps(r));self.assertEqual(r['progress']['stage'],'upload_session')
        # Reconcile an interrupted byte transfer before attempting further bytes.
        r=owner.additional.youtube(m,job('upload_attempted',r),'status',p,g)
        self.assertEqual(owner.additional.opened(r)['offset'],2)
        r=owner.advance(m,job('upload_attempted',r),'upload')
        self.assertEqual(r['state'],'provider_accepted');self.assertEqual(t.calls[-1][2]['headers']['Content-Range'],'bytes 2-4/5')
    def test_pinterest_waits_for_processing_before_pin(self):
        owner,m,t,_=runtime(PinterestProvider('app','secret'),[response({'status':'processing'})],['video/mp4'],{'boardId':'10001','coverImageUrl':'https://media.example/cover.jpg'})
        r=owner.advance(m,job('assets_uploaded',{'container':'12345'}),'status')
        self.assertEqual(r['progress']['stage'],'assets_uploaded');self.assertEqual(t.calls[0][0],'GET')
    def test_media_hash_changed_no_upload(self):
        owner,m,t,_=runtime(LinkedInProvider('app','secret'),[],['application/pdf'])
        m['media'][0]['hash']='bad'
        self.assertEqual(owner.advance(m,job('create_attempted'),'create')['state'],'uncertain');self.assertFalse(t.calls)


class NativeReadsAndBudget(unittest.TestCase):
    def test_x_article_official_entities_and_quote_enterprise_gate(self):
        body={'title':'Approved Article','content_state':{'blocks':[{'text':'Hello','type':'unstyled'}],'entities':[]},'cover_media':{'media_category':'tweet_image','media_id':'123'}}
        validate('x','article_draft',body)
        with self.assertRaises(AlphaError): validate('x','article_draft',{'title':'Old shape','content_state':{'blocks':[],'entityMap':{}}})
        p=XProvider('app','secret',transport=Transport([]));p.production_reviewed=p.official_social_enabled=True
        g={'accessToken':json.dumps({'v':1,'at':'token'}),'scopes':['tweet.read','tweet.write','users.read']}
        with self.assertRaises(AlphaError): OfficialAPI(p,g).write('quote','123',{'text':'Approved quote'})
        with self.assertRaises(AlphaError): OfficialAPI(p,g).write('article_draft','new',body)
        self.assertFalse(p.transport.calls)
        p.official_approvals={'x_articles':{'state':'approved','appId':'app','evidenceRef':'fixture-only'}}
        g['accessToken']=BudgetedToken(g['accessToken'],SimpleNamespace(available=lambda:True,reserve=lambda *_:None))
        p.transport=Transport([response({'data':{'id':'321'}},201)])
        self.assertEqual(OfficialAPI(p,g).write('article_draft','new',body)['executionState'],'submitted')
        self.assertEqual(p.transport.calls[0][2]['body'],body)
    def test_tiktok_transfer_cancel_is_permissioned_and_best_effort(self):
        from postriff_phase2.wave3_connectors import TikTokProvider
        p=TikTokProvider('app','secret',transport=Transport([]));p.production_reviewed=p.official_social_enabled=True
        token=json.dumps({'v':1,'at':'token'})
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':token,'scopes':['user.info.basic']}).write('cancel_transfer','publish_id',{})
        self.assertFalse(p.transport.calls)
        p.transport=Transport([response({'error':{'code':'ok'}}),response({'error':{'code':'publish_not_cancellable'}},400)])
        api=OfficialAPI(p,{'accessToken':token,'scopes':['video.upload']})
        self.assertEqual(api.write('cancel_transfer','publish_id',{})['executionState'],'submitted')
        self.assertEqual(p.transport.calls[0][2]['body'],{'publish_id':'publish_id'})
        self.assertEqual(api.write('cancel_transfer','publish_id',{})['executionState'],'held')
    def test_linkedin_feed_roles_and_nested_parent_do_not_require_content_admin(self):
        parent='urn:li:comment:(urn:li:activity:123,456)';org='urn:li:organization:77'
        t=Transport([response({'sub':'abc'}),response({'elements':[{'organization':org,'state':'APPROVED','role':'RECRUITING_POSTER','roleAssignee':'urn:li:person:abc'}]}),response({'id':'789'},201)])
        p=LinkedInProvider('app','secret',transport=t);p.production_reviewed=p.official_social_enabled=True
        r=OfficialAPI(p,{'accessToken':'token','scopes':['r_organization_admin','w_organization_social_feed']}).write('reply',parent,{'actor':org,'text':'Approved reply','rootPostUrn':'urn:li:activity:123'})
        self.assertEqual(r['executionState'],'submitted');self.assertEqual(t.calls[-1][2]['body']['parentComment'],parent)
        self.assertFalse(any('organizationAuthorizations' in c[1] for c in t.calls))
        t=Transport([response({'sub':'abc'}),response({'elements':[{'organization':org,'state':'APPROVED','role':'RECRUITING_POSTER'}]})]);p.transport=t
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':'token','scopes':['r_organization_admin','r_organization_social_feed']}).read('organization_comments_read','urn:li:share:123',{'organizationUrn':org})
        self.assertTrue(all(c[0]=='GET' for c in t.calls))
    def test_instagram_unverified_insights_contract_is_not_requested(self):
        p=InstagramProvider('app','secret',transport=Transport([]))
        self.assertEqual(p.capability_scopes('analytics'),[])
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':'token','scopes':['instagram_business_basic','instagram_business_manage_insights']}).read('insights','123',{'metric':'views'})
        self.assertFalse(p.transport.calls)
    def test_reporting_download_uses_owned_metadata_and_rejects_token_exfiltration(self):
        p=YouTubeProvider('app','secret',transport=Transport([response({'id':'report','downloadUrl':'https://youtubereporting.googleapis.com/v1/media/file?alt=media','startTime':'2026-10-01T00:00:00Z'}),response({'columns':['views'],'rows':[['0']]})]))
        grant={'accessToken':json.dumps({'v':1,'at':'token'}),'scopes':['https://www.googleapis.com/auth/yt-analytics.readonly']}
        r=OfficialAPI(p,grant).read('reporting_download','job',{'reportId':'report'})
        self.assertEqual(r['data']['rows'],[['0']]);self.assertEqual(p.transport.calls[-1][2]['response_format'],'csv')
        self.assertEqual(r['provenance']['reportingPeriod']['startTime'],'2026-10-01T00:00:00Z')
        p.transport=Transport([response({'downloadUrl':'https://attacker.invalid/report'})])
        with self.assertRaises(AlphaError): OfficialAPI(p,grant).read('reporting_download','job',{'reportId':'report'})
        self.assertEqual(len(p.transport.calls),1)
    def test_commerce_write_is_separate_and_credential_free(self):
        from postriff_phase2.official_operations import ACTION_FIELDS
        p=PinterestProvider('app','secret',transport=Transport([]));p.production_reviewed=p.official_social_enabled=True
        body={'catalog_type':'RETAIL','name':'Approved feed','location':'https://shop.example/catalog.csv','format':'CSV','default_country':'US','default_locale':'en-US'}
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':json.dumps({'v':1,'at':'token'}),'scopes':['pins:write']}).write('feed_create','new',body)
        p.transport=Transport([response({'id':'123'},201)])
        r=OfficialAPI(p,{'accessToken':json.dumps({'v':1,'at':'token'}),'scopes':['catalogs:write']}).write('feed_create','new',body)
        self.assertEqual(r['executionState'],'submitted');self.assertNotIn('credentials',ACTION_FIELDS['feed_create'])
        with self.assertRaises(AlphaError): validate('pinterest','product_group_create',{'feed_id':'123','name':'Products','filters':{'all_of':[]}})
    def test_linkedin_analytics_union_dates_and_invalid_daily(self):
        t=Transport([response({'elements':[{'count':0}]})]);p=LinkedInProvider('app','secret',transport=t)
        api=OfficialAPI(p,{'accessToken':'token','scopes':['r_member_postAnalytics']})
        r=api.read('analytics','urn:li:share:123',{'startDate':'2026-10-01','endDate':'2026-10-05','queryType':'REACTION','aggregation':'DAILY'})
        self.assertIn('entity=(share:urn%3Ali%3Ashare%3A123)',t.calls[0][1]);self.assertIn('dateRange=(start:(day:1,month:10,year:2026)',t.calls[0][1])
        self.assertEqual(r['provenance']['reportingPeriod']['startDate'],'2026-10-01')
        with self.assertRaises(AlphaError): api.read('analytics','urn:li:share:123',{'queryType':'MEMBERS_REACHED','aggregation':'DAILY'})
        self.assertEqual(len(t.calls),1)
    def test_tiktok_inbox_processing_uses_upload_grant(self):
        from postriff_phase2.wave3_connectors import TikTokProvider
        t=Transport([response({'data':{'status':'SEND_TO_USER_INBOX'}})]);p=TikTokProvider('app','secret',transport=t)
        r=OfficialAPI(p,{'accessToken':json.dumps({'v':1,'at':'token'}),'scopes':['video.upload']}).read('processing','publish_id')
        self.assertEqual(r['availability'],'available');self.assertEqual(len(t.calls),1)
    def test_youtube_money_requires_separate_grant(self):
        p=YouTubeProvider('app','secret',transport=Transport([]))
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':'token','scopes':['https://www.googleapis.com/auth/yt-analytics.readonly']}).read('monetary_analytics','channel',{'startDate':'2026-10-01','endDate':'2026-10-05','metrics':'estimatedRevenue'})
    def test_native_actions_reject_unrequested_effects(self):
        with self.assertRaises(AlphaError): validate('pinterest','reply',{'text':'Hi'})
        with self.assertRaises(AlphaError): validate('linkedin','react',{'reactionType':'MAYBE'})
        with self.assertRaises(AlphaError): validate('youtube','video_edit',{'resource':{'status':{'billingDetails':{}}}})
        with self.assertRaises(AlphaError): validate('pinterest','product_tag',{'product_tags':[{'pin_id':'1'},{'pin_id':'1'}]})
    def test_reply_tree_raw_and_native_metrics_have_provenance(self):
        transport=Transport([response({'data':[{'id':'1','root_post':'7','replied_to':'8'}]}),response({'data':[{'name':'views','values':[{'value':12}]}]})])
        p=ThreadsProvider('app','secret',transport=transport)
        api=OfficialAPI(p,{'accessToken':'token','scopes':['threads_basic','threads_read_replies','threads_manage_insights']})
        r=api.read('replies_read','7');self.assertEqual(r['data']['data'][0]['replied_to'],'8')
        r=api.read('insights','7');self.assertEqual(r['provenance']['kind'],'provider_native');self.assertNotIn('reach',r)
        self.assertTrue(all('/v1.0/' in c[1] for c in transport.calls))
    def test_reply_permission_not_inferred_from_basic(self):
        p=ThreadsProvider('app','secret',transport=Transport([]))
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':'token','scopes':['threads_basic']}).read('replies_read','7')
    def test_x_budget_required_and_identity_is_metered(self):
        p=XProvider('app','secret',transport=Transport([]));p.budget_enforced=True
        with self.assertRaises(AlphaError): p.identity(json.dumps({'v':1,'at':'token'}))
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':'token','scopes':['tweet.read','users.read']}).read('analytics','123')
    def test_x_every_actual_request_reserves_before_dispatch(self):
        seen=[];transport=Transport([response({'data':{'id':'123','username':'me'}})])
        p=XProvider('app','secret',transport=transport);p.budget_enforced=True
        budget=SimpleNamespace(reserve=lambda method,path:seen.append((method,path)))
        p.identity(BudgetedToken(json.dumps({'v':1,'at':'secret'}),budget))
        self.assertEqual(seen[0][0],'GET');self.assertEqual(len(transport.calls),1)
    def test_foreign_member_actor_rejected(self):
        p=LinkedInProvider('app','secret',transport=Transport([response({'sub':'abc'})]));p.production_reviewed=p.official_social_enabled=True
        with self.assertRaises(AlphaError): OfficialAPI(p,{'accessToken':'token','scopes':['w_member_social_feed']}).write('reply','urn:li:share:123',{'actor':'urn:li:person:other','text':'Reply','rootPostUrn':'urn:li:share:123'})
    def test_safe_urls_and_poll_validation(self):
        for url in ['http://example.com','https://user:pass@example.com','javascript:alert(1)']:
            with self.assertRaises(AlphaError): web_url(url)
        self.assertEqual(web_url('https://example.com'),'https://example.com')
        with self.assertRaises(AlphaError): options('X',{'poll':{'options':['one'],'duration_minutes':5}},[],'text')
        with self.assertRaises(AlphaError): options('LinkedIn',{'unknown':True},[],'text')
    def test_result_accepts_encrypted_resume_without_exposing_url(self):
        p=YouTubeProvider('app','secret');owner,m,_,_=runtime(p,[],['video/mp4'])
        result=owner.additional.progress('upload_session','youtube_upload',upload={'url':'https://www.googleapis.com/upload?secret=1','offset':0,'total':5})
        r=normalize_result(result,{'manifest':m})
        self.assertEqual(r['state'],'processing');self.assertNotIn('https://',json.dumps(r))
        self.assertEqual(normalize_result({'state':'processing','confirmed':'Resumed','container':'youtube_upload','progress':{'version':1,'stage':'upload_session'},'verification':'resumable_upload_status'}, {'manifest':m},True)['state'],'processing')


class DurableFormats(unittest.TestCase):
    def test_pdf_and_gif_decode_original_bytes_and_reject_active_pdf(self):
        from pypdf import PdfWriter
        from PIL import Image
        writer=PdfWriter();writer.add_blank_page(width=72,height=72);out=io.BytesIO();writer.write(out)
        raw=out.getvalue();result=decode_pdf({'data':base64.b64encode(raw).decode()})
        self.assertEqual(result['pages'],1);self.assertEqual(result['hash'],hashlib.sha256(raw).hexdigest())
        writer.add_js('app.alert("active")');out=io.BytesIO();writer.write(out)
        with self.assertRaises(AlphaError): decode_pdf({'data':base64.b64encode(out.getvalue()).decode()})
        first,second=Image.new('RGB',(2,2),'red'),Image.new('RGB',(2,2),'blue');out=io.BytesIO()
        first.save(out,format='GIF',save_all=True,append_images=[second],duration=100)
        raw=out.getvalue();result=decode_gif({'data':base64.b64encode(raw).decode()})
        self.assertEqual(result['frames'],2);self.assertEqual(base64.b64decode(result['data']),raw)
    def test_x_each_thread_reply_has_exact_parent_and_no_extra_create(self):
        owner,m,t,g=runtime(XProvider('app','secret'),[response({'data':{'id':'101'}},201),response({'data':{'id':'102'}},201),response({'data':{'id':'103'}},201)],options={'thread':['Second','Third']})
        budget=SimpleNamespace(available=lambda:True,reserve=lambda *_:None)
        g['accessToken']=BudgetedToken(g['accessToken'],budget)
        r=owner.advance(m,job('create_attempted'),'create')
        self.assertEqual(r['providerThread'],['101']);self.assertEqual(r['progress']['stage'],'thread_ready')
        r=owner.advance(m,job('publish_attempted',r),'publish')
        self.assertEqual(t.calls[-1][2]['body']['reply']['in_reply_to_tweet_id'],'101')
        r=owner.advance(m,job('publish_attempted',r),'publish')
        self.assertEqual(r['providerThread'],['101','102','103']);self.assertEqual(r['state'],'provider_accepted')
        self.assertEqual(owner.advance(m,job('publish_attempted',r),'publish')['state'],'uncertain');self.assertEqual(len(t.calls),3)
    def test_facebook_ready_video_is_not_published(self):
        t=Transport([response({'id':'123456','from':{'id':'12345'},'description':'Approved','published':False,'status':{'video_status':'ready'}}),response({'id':'123456','from':{'id':'12345'},'description':'Approved','published':True,'status':{'video_status':'ready'}})])
        p=SimpleNamespace(session=lambda _: {'page':{'id':'12345','token':'page'}},graph=lambda method,path,token,params:t(method,path,form=params))
        m={'platform':'Facebook','payload':{'text':'Approved'},'publishOptions':{'format':'reel'},'media':[{'mime':'video/mp4'}]}
        social=object.__new__(HostedSocial)
        self.assertEqual(social._reconcile_wave3(m,p,'token','123456')['state'],'provider_accepted')
        self.assertEqual(social._reconcile_wave3(m,p,'token','123456')['state'],'verified')
    def test_facebook_story_uses_story_surface_and_preserves_expiry(self):
        p=SimpleNamespace(session=lambda _: {'page':{'id':'12345','token':'page'}},graph=lambda *_:response({'data':[{'post_id':'12345_33333','media_id':'44444','status':'ARCHIVED'}]}))
        m={'platform':'Facebook','payload':{'text':''},'publishOptions':{'format':'story'},'media':[{'mime':'image/jpeg'}]}
        r=object.__new__(HostedSocial)._reconcile_wave3(m,p,'token','12345_33333',{'providerAssets':[{'id':'44444'}]})
        self.assertEqual(r['state'],'verified');self.assertIn('archived',r['confirmed'])


if __name__=='__main__': unittest.main()
