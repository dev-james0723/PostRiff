import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from postriff_phase2 import creative_video_performance as performance
from postriff_phase2.youtube.service import fingerprint
from postriff_phase2.youtube.model import READ, ANALYTICS

WID, PID, AID, SHA = 'workspace', 'project', 'a' * 32, 'b' * 64
NOW = 1_790_000_000


def fixture(platform='Kuaishou'):
    asset = {'id': AID, 'mime': 'video/mp4', 'processing': 'ready', 'hash': SHA, 'bytes': 15, 'duration': 2,
             'objectName': AID+'.mp4', 'etag': 'etag', 'bucket': 'private', 'durationSource': 'container',
             'verified': {'container': True, 'locationChecked': True}, 'provenance': {
                 'operation': 'composition_render', 'projectId': PID, 'revision': 2, 'sha256': SHA}}
    project = {'id': PID, 'revision': 2, 'export': {'assetId': AID, 'revision': 2, 'manifest': {'sha256': SHA}}}
    manifest = {'media': [{'id': AID, 'hash': SHA, 'rightsConfirmed': True}], 'workspaceId': WID,
                'platform': platform, 'channelId': 'conn', 'providerAccountId': 'account', 'execution': 'hosted-live'}
    job = {'state': 'verified', 'id': 'job', 'verification': {'at': NOW-40, 'method': 'provider_lookup'},
           'providerReference': '0123456Abcd', 'manifest': manifest, 'approvedBy': 'owner'}
    return project, {'phase2': {'assets': [asset], 'channels': [{'id':'conn','platform':platform}], 'jobs': [job]}}


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.cur = Mock()
        self.cur.fetchone.return_value = ('account', [READ, ANALYTICS], 'grant')
        self.cur.fetchall.return_value = []
        self.oauth = SimpleNamespace(providers={'youtube': SimpleNamespace(id='youtube', creator_enabled=True)},
                                     youtube_policy=Mock(spec=['require_user', 'assert_connection']))

    def read(self, project, state):
        return performance.revision_performance(self.cur, WID, project, state, self.oauth, 'session', 'reader', NOW)

    def test_links_only_verified_exact_immutable_asset_and_live_connection(self):
        project, state = fixture()
        output = self.read(project, state)
        self.assertEqual(output['state'], 'linked')
        self.assertEqual(output['posts'][0]['providerPostId'], '0123456Abcd')
        self.assertEqual(output['posts'][0]['metrics'], [])
        for target, field, value in [('manifest', 'execution', 'synthetic'), ('manifest','workspaceId','other'),
                                      ('manifest','providerAccountId','new-account'), ('job','privacyErased',True),
                                      ('job','state','provider_accepted'), ('media','id','other'), ('media','hash','0'*64)]:
            changed = copy.deepcopy(state)
            job = changed['phase2']['jobs'][0]
            dest = {'job':job,'manifest':job['manifest'],'media':job['manifest']['media'][0]}[target]
            dest[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.read(project, changed)['state'], 'unlinked')
        self.cur.fetchone.return_value = None
        self.assertEqual(self.read(project, state)['state'], 'unlinked')

    def test_unrendered_deleted_and_wrong_revision_stop_before_lookup(self):
        project, state = fixture()
        self.assertEqual(self.read({**project,'export': None}, state)['state'], 'unrendered')
        self.assertEqual(self.read({**project,'revision': 1}, state)['state'], 'asset_unavailable')
        state['phase2']['assets'][0]['deletionPending'] = True
        self.assertEqual(self.read(project, state)['state'], 'asset_unavailable')
        self.cur.execute.assert_not_called()

    def test_tiktok_upload_operation_is_not_a_published_post_id(self):
        self.assertEqual(self.read(*fixture('TikTok'))['state'], 'unlinked')

    def test_youtube_binds_current_generation_publication_stage_and_exact_cache_key(self):
        project, state = fixture('YouTube')
        job = state['phase2']['jobs'][0]
        job.update(progress={'stage':'published', 'privacyStatus':'public', 'videoId':job['providerReference']}, youtubeProviderOutput={
            'actor':'owner','workspaceId':WID,'connectionId':'conn','authorizationGeneration':'grant','expiresAt':NOW+60})
        first, last = '2026-11-01', '2026-11-02'
        query = {'resource':'analytics','report':'daily','startDate':first,'endDate':last}
        key = 'analytics:' + fingerprint({**query,'videoId':job['providerReference']})
        self.cur.fetchall.return_value = [('analytics:'+fingerprint(query),first,last), (key,first,last)]
        report = {'source':'YouTube Analytics API','report':'daily','channelId':'account','ingestedAt':NOW-10,
                  'coverage':{'startDate':first,'endDate':last},'data':{
                      'columnHeaders':[{'name':'day'},{'name':'views'},{'name':'estimatedMinutesWatched'}],
                      'rows':[[first,0,5],['outside',999,999]]}}
        self.cur.fetchone.side_effect = [('account', [READ,ANALYTICS], 'grant'), (report,)]
        metrics = self.read(project,state)['posts'][0]['metrics']
        self.assertEqual([(m['name'],m['value']) for m in metrics], [('views',0),('estimatedMinutesWatched',5)])
        self.assertEqual(metrics[1]['unit'], 'minutes')
        self.assertEqual(metrics[0]['periodEnd']-metrics[0]['periodStart'], 25*3600)  # Pacific fall DST change
        self.assertEqual(metrics[0]['source'], 'youtube_analytics')
        self.assertTrue(self.oauth.youtube_policy.assert_connection.called)
        self.assertTrue(self.oauth.youtube_policy.require_user.called)
        self.cur.fetchone.side_effect = None
        self.cur.fetchall.return_value = [('analytics:'+fingerprint(query),first,last)]
        self.assertEqual(self.read(project,state)['posts'][0]['metrics'], [])
        self.cur.fetchone.return_value = ('account',[READ], 'grant')
        self.assertEqual(self.read(project,state)['posts'][0]['metrics'], [])
        for change in ({'progress':{'stage':'processed_private'}}, {'youtubeProviderOutput':{'expiresAt':NOW}},
                       {'youtubeProviderDataRemoved':True}):
            with self.subTest(change=change):
                changed = copy.deepcopy(state)
                changed['phase2']['jobs'][0].update(change)
                self.assertEqual(self.read(project,changed)['state'], 'unlinked')

    def test_owned_link_selects_one_verified_source_and_rechecks_limits(self):
        from postriff_alpha.domain import AlphaError
        project, state = fixture('YouTube')
        job = state['phase2']['jobs'][0]
        asset = state['phase2']['assets'][0]
        job['manifest']['media'][0].update({k:asset[k] for k in ('objectName','etag','mime','bytes','bucket')})
        job.update(progress={'stage':'published','privacyStatus':'public','videoId':job['providerReference']},
                   youtubeProviderOutput={'actor':'owner','workspaceId':WID,'connectionId':'conn',
                   'authorizationGeneration':'grant','expiresAt':NOW+60})
        def resolve(url):
            return performance.resolve_reference_link(self.cur, WID, state, self.oauth, 'session','reader',NOW,{'url':url})
        ident = job['providerReference']
        for url in ('https://youtu.be/'+ident, 'https://www.youtube.com/shorts/'+ident,
                    'https://m.youtube.com/watch?v='+ident+'&t=10'):
            self.assertEqual(resolve(url), {'assetId':AID,'durationSeconds':2})
        for url in ('https://www.youtube.com.evil.test/watch?v='+ident, 'https://youtube.com:443/shorts/'+ident,
                    'http://youtu.be/'+ident, 'https://youtu.be@other.test/'+ident,
                    'https://www.youtube.com/watch?v='+ident+'&v=other012345', 'https://youtu.be/notthisvid0'):
            with self.subTest(url=url), self.assertRaises(AlphaError):
                resolve(url)
        for target, key, value in ((job['progress'],'privacyStatus','unlisted'),(asset,'duration',91),
                                   (asset,'bytes',64*1024*1024+1),(asset,'etag','new-etag')):
            before = target[key]
            target[key] = value
            with self.subTest(key=key), self.assertRaises(AlphaError):
                resolve('https://youtu.be/'+ident)
            target[key] = before
        other = copy.deepcopy(asset)
        other.update(id='c'*32, objectName='c'*32+'.mp4')
        state['phase2']['assets'].append(other)
        other_job = copy.deepcopy(job)
        other_job['manifest']['media'][0].update(id=other['id'],objectName=other['objectName'])
        state['phase2']['jobs'].append(other_job)
        with self.assertRaises(AlphaError):
            resolve('https://youtu.be/'+ident)
