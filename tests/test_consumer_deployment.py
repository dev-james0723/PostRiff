import hashlib
import json
import unittest
from unittest.mock import patch
from postriff_phase2.deployment import isolated_environment
from postriff_phase2.hosted_app import runtime_from_environment

class PreviewIsolation(unittest.TestCase):
    def env(self):
        stage='s'*20
        return {'VERCEL_ENV':'preview','POSTRIFF_ENVIRONMENT':'staging','POSTRIFF_STAGING_PROJECT_REF':stage,'POSTRIFF_PRODUCTION_PROJECT_REF':'p'*20,'POSTRIFF_SUPABASE_URL':f'https://{stage}.supabase.co','NEXT_PUBLIC_SUPABASE_URL':f'https://{stage}.supabase.co','POSTRIFF_DATABASE_URL':f'postgresql://postgres.{stage}:synthetic@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require','POSTRIFF_PUBLIC_BASE_URL':'https://staging.example','POSTRIFF_STAGING_PUBLIC_BASE_URL':'https://staging.example'}

    def test_valid_isolated_project_and_local_unchanged(self):
        value=self.env()
        self.assertEqual(isolated_environment(value)['POSTRIFF_RESEARCH'],'0')
        self.assertNotIn('POSTRIFF_RESEARCH',value)
        self.assertEqual(isolated_environment({'VERCEL_ENV':'production'}),{'VERCEL_ENV':'production'})

    def test_mixed_production_configuration_rejected_before_connect(self):
        mutations=[('POSTRIFF_ENVIRONMENT','production'),('POSTRIFF_PRODUCTION_PROJECT_REF','s'*20),('NEXT_PUBLIC_SUPABASE_URL','https://'+'p'*20+'.supabase.co'),('POSTRIFF_DATABASE_URL','postgresql://postgres:synthetic@db.'+'p'*20+'.supabase.co/postgres?sslmode=require'),('POSTRIFF_DATABASE_URL','host=127.0.0.1'),('POSTRIFF_API_ORIGIN','https://production.example'),('POSTRIFF_PUBLIC_BASE_URL','https://production.example'),('STRIPE_SECRET_KEY','sk_live_synthetic'),('AI_GATEWAY_API_KEY','unpinned'),('POSTRIFF_RESEARCH','1'),('POSTRIFF_LOCAL_CLI','1')]
        with patch('postriff_phase2.hosted_app.postgres_factory',side_effect=AssertionError('No connection factory may be created')):
            for key,value in mutations:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    runtime_from_environment({**self.env(),key:value})

    def test_only_exact_reviewed_credential_fingerprints_accepted(self):
        values={**self.env(),'AI_GATEWAY_API_KEY':'synthetic-staging-key'}
        values['POSTRIFF_STAGING_SECRET_SHA256']=json.dumps({'AI_GATEWAY_API_KEY':hashlib.sha256(values['AI_GATEWAY_API_KEY'].encode()).hexdigest()})
        self.assertEqual(isolated_environment(values)['AI_GATEWAY_API_KEY'],values['AI_GATEWAY_API_KEY'])
        values['AI_GATEWAY_API_KEY']='changed-synthetic-key'
        with self.assertRaises(ValueError):isolated_environment(values)
