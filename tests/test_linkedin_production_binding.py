"""Configuration-only guards; never connects to a persistent database."""
import json
import unittest
from unittest.mock import patch
from postriff_phase2.deployment import isolated_environment, production_binding_proof

class LinkedInProductionBinding(unittest.TestCase):
    def values(self):
        ref='buoyhkbodnhzngaotoel'
        return {'VERCEL_ENV':'production','VERCEL_PROJECT_ID':'prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L',
                'POSTRIFF_PRODUCTION_PROJECT_REF':ref, 'POSTRIFF_SUPABASE_URL':'https://'+ref+'.supabase.co',
                'NEXT_PUBLIC_SUPABASE_URL':'https://'+ref+'.supabase.co',
                'POSTRIFF_DATABASE_URL':'postgresql://postgres.'+ref+':SYNTHETIC@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require'}
    def test_safe_transaction_pool_metadata(self):
        values=self.values()
        proof=production_binding_proof(values)
        self.assertTrue(proof['databaseBindingVerified'])
        self.assertEqual(proof['databaseConnectionMode'],'transaction_pooler')
        self.assertEqual(proof['databasePort'],6543)
        self.assertEqual(proof['databaseTLS'],'require')
        self.assertNotIn('SYNTHETIC',json.dumps(proof))
        self.assertNotIn('aws-0',json.dumps(proof))
        self.assertEqual(isolated_environment(values),values)
    def test_wrong_database_auth_or_frontend_rejected_before_connection(self):
        from postriff_phase2.hosted_app import runtime_from_environment
        for key,value in [('POSTRIFF_DATABASE_URL', self.values()['POSTRIFF_DATABASE_URL'].replace('buoyhkbodnhzngaotoel','oxacvkhpfgytkepxcaqh')),
                          ('NEXT_PUBLIC_SUPABASE_URL','https://oxacvkhpfgytkepxcaqh.supabase.co'),
                          ('POSTRIFF_API_ORIGIN','https://elsewhere.example'),
                          ('POSTRIFF_PRODUCTION_PROJECT_REF','wrong')]:
            with self.subTest(key=key), patch('postriff_phase2.hosted_app.postgres_factory',side_effect=AssertionError('must not connect')):
                with self.assertRaises(ValueError): runtime_from_environment({**self.values(),key:value})
    def test_without_tls_is_rejected(self):
        with self.assertRaises(ValueError): isolated_environment({**self.values(),'POSTRIFF_DATABASE_URL':self.values()['POSTRIFF_DATABASE_URL'].replace('?sslmode=require','')})
