"""A builder may normalize vercel.json, but must not change approved routes/policy.

All fixtures are disposable, credential-free and contain no provider traffic.
"""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from postriff_phase2 import release_provenance as provenance

REV='1234567890abcdef1234567890abcdef12345678'
CONFIG={
    '$schema': 'https://openapi.vercel.sh/vercel.json',
    'services': {
        'postriff_web': {'root': 'web/', 'framework': 'nextjs'},
        'postriff_api': {'root': '.', 'runtime': 'python', 'entrypoint': 'api.index:app',
                         'buildCommand': 'python3 runtime/verify_release_target.py'},
    },
    'rewrites': [{'source': '/api/(.*)', 'destination': {'service': 'postriff_api'}}],
    'headers': [{'source': '/(.*)', 'headers': [{'key': 'X-Frame-Options', 'value': 'DENY'}]}],
    'crons': [{'path': '/api/cron/worker', 'schedule': '* * * * *'}],
    'git': {'deploymentEnabled': False},
}


class VercelBuilderTransformTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=json.dumps(CONFIG, indent=2).encode()+b'\n'
        files={}
        for name in provenance.WITNESS_PATHS:
            path=self.root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            raw=self.source if name=='vercel.json' else ('witness:'+name).encode()
            path.write_bytes(raw)
            files[name]=hashlib.sha256(raw).hexdigest()
        self.receipt=self.root/provenance.MANIFEST_PATH
        self.manifest={'schemaVersion':1,'coverage':'selected_runtime_files',
                       'sourceRevision':REV,'files':files,
                       'vercelConfigSourceBase64':base64.b64encode(self.source).decode('ascii')}
        self.save()

    def save(self):
        self.receipt.write_text(json.dumps(self.manifest))

    def proof(self):
        return provenance.release_source_proof({},root=self.root)

    def test_builder_formatting_only_preserves_original_source_proof(self):
        (self.root/'vercel.json').write_bytes(json.dumps(CONFIG,sort_keys=True,separators=(',',':')).encode())
        self.assertEqual(self.proof()['status'],'verified')

    def test_builder_can_add_only_identical_metadata_mirrors(self):
        copied_command=CONFIG['services']['postriff_api']['buildCommand']
        copied_framework=CONFIG['services']['postriff_web']['framework']
        for additional in (
            {'version': 2},
            {'buildCommand':copied_command},
            {'framework':copied_framework},
            {'version':2,'buildCommand':copied_command,'framework':copied_framework},
        ):
            with self.subTest(keys=tuple(additional)):
                (self.root/'vercel.json').write_text(json.dumps({**CONFIG,**additional}))
                self.assertEqual(self.proof()['status'],'verified')

    def test_builder_rejects_dangerous_or_incorrect_extra_config(self):
        for additional in (
            {'version':3},{'version':True},
            {'buildCommand':'echo skip-release-guard'},
            {'framework':'static'},
            {'env':{'DATABASE_URL':'unexpected'}},
            {'functions':{'api/index.py':{'maxDuration':1}}},
            {'routes':[{'src':'/(.*)','dest':'https://example.invalid'}]},
        ):
            with self.subTest(keys=tuple(additional)):
                (self.root/'vercel.json').write_text(json.dumps({**CONFIG,**additional}))
                self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])

    def test_builder_adds_only_the_canonical_project_name(self):
        for extra in ({'name':'postriff-phase2-private'},
                      {'name':'postriff-phase2-private','version':2}):
            with self.subTest(extra=extra):
                (self.root/'vercel.json').write_text(json.dumps({**CONFIG,**extra}))
                self.assertEqual(self.proof()['status'],'verified')

    def test_builder_wrong_project_name_still_fails_closed(self):
        for invalid in ('postriff-staging','',True,'postriff-phase2-private-other'):
            with self.subTest(name=invalid):
                (self.root/'vercel.json').write_text(json.dumps({**CONFIG,'name':invalid}))
                self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])

    def test_builder_cannot_change_route_or_release_command(self):
        for key, value in [('rewrites',[{'source':'/api/(.*)','destination':'https://evil.invalid'}]),
                           ('services',{'postriff_api':{'runtime':'python','buildCommand':'echo skip'}}),
                           ('git',{'deploymentEnabled':True}),
                           ('headers',[]),('crons',[])]:
            with self.subTest(field=key):
                changed=dict(CONFIG);changed[key]=value
                (self.root/'vercel.json').write_text(json.dumps(changed))
                self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])

    def test_builder_cannot_add_unknown_active_config_fields(self):
        changed={**CONFIG,'routes':[{'src':'/(.*)','dest':'https://evil.invalid'}]}
        (self.root/'vercel.json').write_text(json.dumps(changed))
        self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])

    def test_builder_cannot_use_forged_source_copy(self):
        changed=dict(self.manifest)
        changed['vercelConfigSourceBase64']=base64.b64encode(b'corrupt original').decode()
        self.manifest=changed;self.save()
        self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])

    def test_no_git_build_fails_if_original_config_missing(self):
        self.manifest.pop('vercelConfigSourceBase64')
        self.save()
        (self.root/'vercel.json').write_text(json.dumps(CONFIG,sort_keys=True))
        self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])

    def test_git_checkout_must_not_allow_builder_rewrites(self):
        (self.root/'.git').write_text('fixture Git marker')
        (self.root/'vercel.json').write_text(json.dumps(CONFIG,sort_keys=True))
        self.assertFalse(self.proof()['verifiedSelectedRuntimeFiles'])


if __name__=='__main__':
    unittest.main()


class ReleaseConfigFailureDiagnosticsTests(unittest.TestCase):
    def test_effective_config_diagnostics_are_fixed_booleans_only(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('release_guard_diag',Path(__file__).resolve().parents[1] / 'runtime/verify_release_target.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertTrue(hasattr(module,'source_config_diagnostics'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'vercel.json'
            path.write_text(json.dumps(CONFIG))
            receipt=root/'src/postriff_phase2/release-source.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'vercelConfigSourceBase64':base64.b64encode(json.dumps(CONFIG).encode()).decode()}))
            report=module.source_config_diagnostics(root)
            self.assertTrue(all(type(v) is bool for v in report.values()))
            self.assertEqual(report['semanticallyEqual'],True)
            changed={**CONFIG,'git':{'deploymentEnabled':True}}
            path.write_text(json.dumps(changed))
            report=module.source_config_diagnostics(root)
            self.assertFalse(report['semanticallyEqual'])
            self.assertTrue(report['git']==False)
            self.assertTrue(report['rewrites'])
            self.assertTrue(all(type(v) is bool for v in report.values()))
            self.assertNotIn('SECRET_VALUE',json.dumps(report))
