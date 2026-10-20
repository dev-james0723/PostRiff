"""Release failures are actionable without leaking values or waiving a guard."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class ReleaseGuardDiagnostics(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('release_guard_diagnostic_test', ROOT/'runtime/verify_release_target.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def invoke(self, binding_error=None, source_error=None):
        output=io.StringIO()
        with patch.dict(os.environ, {'VERCEL_ENV':'production','POSTRIFF_DATABASE_URL':'SECRET_VALUE'}, clear=True), patch.object(self.module,'verify',side_effect=binding_error,return_value={}), patch.object(self.module,'verify_source',side_effect=source_error,return_value={'status':'verified'}) as source, contextlib.redirect_stdout(output):
            code=self.module.main()
        body=json.loads(output.getvalue())
        self.assertNotIn('SECRET_VALUE',output.getvalue())
        self.assertNotIn('SECRET_EXCEPTION',output.getvalue())
        return code,body,source

    def test_binding_failure_identifies_stage_and_never_runs_source(self):
        code,body,source=self.invoke(binding_error=ValueError('SECRET_EXCEPTION'))
        self.assertEqual(code,1)
        self.assertEqual(body.get('failureStage'),'binding')
        source.assert_not_called()

    def test_source_failure_is_distinct_and_still_nonzero(self):
        code,body,_=self.invoke(source_error=ValueError('SECRET_EXCEPTION'))
        self.assertEqual(code,1)
        self.assertEqual(body.get('failureStage'),'source')

    def test_success_still_requires_both_guards(self):
        code,body,source=self.invoke()
        self.assertEqual(code,0)
        self.assertEqual(body['status'],'passed')
        source.assert_called_once()

    def test_safe_binding_diagnostics_are_only_fixed_keys_and_booleans(self):
        self.assertTrue(hasattr(self.module,'binding_diagnostics'))
        data=self.module.binding_diagnostics({'VERCEL_ENV':'production','VERCEL_PROJECT_ID':'SECRET_VALUE','POSTRIFF_DATABASE_URL':'SECRET_VALUE'})
        self.assertTrue(data)
        self.assertTrue(all(type(v) is bool for v in data.values()))
        self.assertNotIn('SECRET_VALUE',json.dumps(data))
        self.assertFalse(data['project_matches'])

    def test_bad_url_cannot_disclose_parser_exception(self):
        self.assertTrue(hasattr(self.module,'binding_diagnostics'))
        data=self.module.binding_diagnostics({'POSTRIFF_DATABASE_URL':'postgres://[SECRET_VALUE'})
        self.assertFalse(data['database_binding_verified'])
        self.assertNotIn('SECRET_VALUE',json.dumps(data))


    def test_source_failure_logs_only_safe_code_and_remains_failed(self):
        self.assertTrue(hasattr(self.module,'source_diagnostics'))
        safe={'receiptStatus':'metadata_conflict','gitPathPresent':False,'gitMetadataPresent':True,'gitMetadataMatchesReceipt':False}
        with patch.object(self.module,'source_diagnostics',return_value=safe):
            code,body,_=self.invoke(source_error=ValueError('SECRET_EXCEPTION'))
        self.assertEqual(code,1)
        self.assertEqual(body['failureStage'],'source')
        self.assertEqual(body['checks'],safe)

    def test_source_diagnostics_metadata_conflict_redacts_raw_sha(self):
        sha='SECRET_GIT_METADATA'
        with patch.object(self.module.runpy,'run_path',return_value={'release_source_proof':lambda *args,**kwargs:{'status':'metadata_conflict','sourceRevision':None}}):
            result=self.module.source_diagnostics({'VERCEL_GIT_COMMIT_SHA':sha,'POSTRIFF_DATABASE_URL':'SECRET_VALUE'})
        self.assertEqual(result['receiptStatus'],'metadata_conflict')
        self.assertTrue(result['gitMetadataPresent'])
        self.assertFalse(result['gitMetadataMatchesReceipt'])
        self.assertNotIn(sha,json.dumps(result))
        self.assertNotIn('SECRET_VALUE',json.dumps(result))
        self.assertEqual(set(result),{'receiptStatus','gitPathPresent','gitMetadataPresent','gitMetadataMatchesReceipt'})

    def test_source_diagnostics_untrusted_status_is_redacted(self):
        with patch.object(self.module.runpy,'run_path',return_value={'release_source_proof':lambda *args,**kwargs:{'status':'SECRET_LEAK','sourceRevision':'SECRET_LEAK'}}):
            result=self.module.source_diagnostics({'VERCEL_GIT_COMMIT_SHA':'SECRET_LEAK'})
        self.assertEqual(result['receiptStatus'],'unavailable')
        self.assertNotIn('SECRET_LEAK',json.dumps(result))

    def test_source_diagnostics_unreadable_status_fails_closed(self):
        with patch.object(self.module.runpy,'run_path',side_effect=OSError('SECRET_BACKEND_PATH')):
            result=self.module.source_diagnostics({'VERCEL_GIT_COMMIT_SHA':'SECRET_BACKEND_PATH'})
        self.assertEqual(result['receiptStatus'],'unavailable')
        self.assertNotIn('SECRET_BACKEND_PATH',json.dumps(result))

if __name__=='__main__':
    unittest.main()
