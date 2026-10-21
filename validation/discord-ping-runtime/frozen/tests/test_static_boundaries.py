"""No network/DB/cron/secret-imports are part of the runtime artifact."""
import ast
import json
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class RuntimeStaticBoundaryTests(unittest.TestCase):
    def test_runtime_ast_import_allowlist(self):
        expected={
            'a7a0_ping_core.py': {'__future__','dataclasses','json','re','time','typing','urllib.parse','cryptography.exceptions','cryptography.hazmat.primitives.asymmetric.ed25519'},
            'api/discord/interactions.py': {'http.server','json','os','a7a0_ping_core'},
        }
        for name, allowed in expected.items():
            body=(ROOT/name).read_text()
            found=set()
            for node in ast.walk(ast.parse(body)):
                if isinstance(node,ast.Import):found.update(alias.name for alias in node.names)
                elif isinstance(node,ast.ImportFrom):found.add('.'*node.level+(node.module or ''))
            self.assertEqual(found,allowed,name)
            self.assertNotIn('eval(',body)
            self.assertNotIn('exec(',body)
            self.assertNotIn('subprocess',body)
            self.assertNotIn('sqlite3',found)
            self.assertFalse(any(item.startswith('postriff_') for item in found))
        self.assertEqual(set(expected),{str(p.relative_to(ROOT)) for p in (ROOT/'api').rglob('*.py')}|{'a7a0_ping_core.py'})

    def test_json_manifest_has_one_python_endpoint_and_no_job_or_rewrite(self):
        cfg=json.loads((ROOT/'vercel.json').read_text())
        self.assertEqual(set(cfg),{'$schema','framework','functions'})
        self.assertEqual(list(cfg['functions']),['api/discord/interactions.py'])
        self.assertEqual(cfg['functions']['api/discord/interactions.py']['maxDuration'],5)
        self.assertEqual((ROOT/'.python-version').read_text().strip(),'3.12')
        self.assertEqual((ROOT/'requirements.txt').read_text().strip(),'cryptography==50.0.1')
        self.assertNotIn('crons',cfg)
        self.assertFalse((ROOT/'api/index.py').exists())
        self.assertFalse((ROOT/'node_modules').exists())
        self.assertFalse((ROOT/'.vercel').exists())

    def test_source_attestation_is_explicitly_a_distinct_overlay(self):
        proof=json.loads((ROOT/'SOURCE_PROVENANCE.json').read_text())
        self.assertEqual(proof['original_commit_sha'],'e891af3591d8baabdb54c05d936ccd61c3299e42')
        self.assertEqual(proof['original_source_evidence'][0]['git_blob_sha1'],'a459fcb50acf08da842eccfc54e42784625e8445')
        self.assertTrue(proof['derived_overlay'])
        self.assertFalse(proof['byte_identical_to_original'])
        self.assertFalse(proof['deployment_executed'])
        self.assertIsNone(proof['vercel_project_id'])

if __name__=='__main__':
    unittest.main()
