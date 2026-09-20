import unittest
from postriff_phase2.outcomes import normalize_result

class ReceiptContract(unittest.TestCase):
    job = {'manifest': {'platform': 'Instagram'}}
    def result(self, **kw):
        return {'state': 'verified', 'confirmed': 'Lookup matched', 'reference': '999', 'container': '555', 'url': 'https://www.instagram.com/p/ABC/', 'verification': 'provider_lookup', **kw}

    def test_container_and_canonical_receipt_survive_normalization(self):
        r = normalize_result(self.result(access_token='discard'), self.job)
        self.assertEqual(r.get('container'), '555')
        self.assertEqual(r.get('url'), 'https://www.instagram.com/p/ABC/')
        self.assertEqual(r.get('schema'), 'postriff.result.v1')
        self.assertNotIn('access_token', r)

    def test_invalid_receipt_urls_do_not_become_verified(self):
        for url in ('javascript:alert(1)', 'https://evil.test/p/ABC', 'https://www.instagram.com.evil.test/p/A', 'https://www.instagram.com/p/A?access_token=secret', 'https://user:secret@www.instagram.com/p/A', 'https://www.instagram.com:444/p/A', 'https://www.instagram.com/accounts/login/', 'https://www.instagram.com/p/A#secret'):
            with self.subTest(url=url):
                self.assertEqual(normalize_result(self.result(url=url), self.job)['state'], 'uncertain')

    def test_container_must_be_bounded_identifier(self):
        for container in ({'token': 'x'}, 123, '', 'x'*501, 'abc\nsecret'):
            with self.subTest(container=container):
                self.assertEqual(normalize_result(self.result(container=container), self.job)['state'], 'uncertain')

    def test_missing_reference_is_recovered_from_durable_job(self):
        r = normalize_result({'state': 'verified', 'confirmed': 'Lookup', 'verification': 'provider_lookup'}, {**self.job, 'providerReference': '999'})
        self.assertEqual(r.get('reference'), '999')

    def test_container_does_not_prove_publication(self):
        self.assertEqual(normalize_result({'state': 'published', 'confirmed': 'Container ready', 'container': '555'}, self.job)['state'], 'uncertain')

    def test_manual_report_cannot_be_api_verified(self):
        for method in ('manual', 'user_reported', 'http_200', 'app_opened'):
            self.assertEqual(normalize_result(self.result(verification=method), self.job)['state'], 'uncertain')

    def test_instagram_lookup_must_match_owner(self):
        from types import SimpleNamespace
        from postriff_phase2.hosted_social import HostedSocial
        for owner in (None, {'id': 'someone-else'}):
            social = HostedSocial(SimpleNamespace(token_for_worker=lambda *_:{'accessToken':'fixture'}), {'instagram':SimpleNamespace(production_reviewed=True)}, transport=lambda *_args, **_kw: {'status':200,'body':{'id':'999','caption':'Approved','permalink':'https://www.instagram.com/p/ABC/','owner':owner}})
            manifest = {'platform':'Instagram','workspaceId':'w','channelId':'c','providerAccountId':'1789','payload':{'text':'Approved'}}
            self.assertEqual(social.reconcile(manifest, {'providerReference':'999'})['state'], 'uncertain')

    def test_reconciliation_cannot_authorize_new_forward_progress(self):
        job = {**self.job, 'container':'555', 'progress':{'version':1,'stage':'publish_attempted'}}
        result = {'state':'processing','confirmed':'try again','container':'555','progress':{'version':1,'stage':'container_ready'}}
        self.assertEqual(normalize_result(result, job, reconciliation=True)['state'], 'uncertain')

    def test_cancel_during_container_lookup_does_not_resume_publication(self):
        result = {'state':'processing','confirmed':'Ready','container':'555','progress':{'version':1,'stage':'container_ready'}}
        self.assertEqual(normalize_result(result, {**self.job,'cancelRequested':True})['state'], 'canceled')
