"""Execute the actual opt-in dev adapter admission without starting any server."""
import ast, os, socket, subprocess, sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests/phase2'))
from local_pg_target import LIBPQ_OVERRIDES, PSQL_OVERRIDES

class DevAdmission(unittest.TestCase):
    def invoke(self,raw='host=127.0.0.1 port=55439 dbname=pricing_v2_local_synthetic_test',dbname='pricing_v2_local_synthetic_test',env=None):
        tree=ast.parse((ROOT/'scripts/postriff_dev_hosted.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        admission=next(n for n in main.body if isinstance(n,ast.If) and ast.unparse(n.test)=='args.pricing_v2_fixture')
        args=SimpleNamespace(pricing_v2_fixture=True,credit_fixture=False,growth_fixture=False,phone_fixture=False,inbound_phone_fixture=False,notification_fixture=False,external_pg_dsn=raw,pricing_v2_fixture_database=dbname)
        start=Mock(side_effect=AssertionError('PG lifecycle must never run for external mode'))
        def refusal(message):raise ValueError(message)
        namespace={'ROOT':ROOT,'sys':sys,'os':os,'args':args,'parser':SimpleNamespace(error=refusal),'start_postgres':start}
        with patch.dict(os.environ,env or {},clear=True),patch('socket.socket',side_effect=AssertionError('No actual socket')),patch('subprocess.run',side_effect=AssertionError('No actual process')):
            exec(compile(ast.fix_missing_locations(ast.Module(body=[admission],type_ignores=[])),str(ROOT/'scripts/postriff_dev_hosted.py'),'exec'),namespace)
        start.assert_not_called();return namespace
    def test_exact_named_parent_target_has_no_lifecycle(self):
        ns=self.invoke();self.assertEqual(ns['dsn'],'host=127.0.0.1 port=55439 dbname=pricing_v2_local_synthetic_test');self.assertIsNone(ns['data'])
    def test_every_libpq_or_psql_override_presence_even_empty_refuses_before_io(self):
        for name in LIBPQ_OVERRIDES|PSQL_OVERRIDES:
            for value in ('','synthetic-not-a-file'):
                with self.subTest(name=name,value=value),self.assertRaises(ValueError):self.invoke(env={name:value})
        for env in ({'POSTRIFF_TEST_PG_PORT':'55438'},{'POSTRIFF_TEST_PG_PORT':''},{'POSTRIFF_PG_PORT':'55438'},{'POSTRIFF_TEST_DSN':'host=127.0.0.1 port=5432 dbname=postgres'}):
            with self.subTest(env=env),self.assertRaises(ValueError):self.invoke(env=env)
    def test_extra_dsn_fields_remote_targets_and_other_namespaces_are_rejected(self):
        good='host=127.0.0.1 port=55439 dbname=pricing_v2_local_synthetic_test'
        for raw in (good+' user=synthetic',good+' sslrootcert=synthetic-file',good+' port=55439',good.replace('127.0.0.1','localhost'),good.replace('55439','5432'),'postgresql://127.0.0.1:55439/postgres'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.invoke(raw=raw)
        for name in ('postgres','production','pricing_v2_local_synthetic_','pricing_v2_local_synthetic_test;SELECT1'):
            with self.subTest(db=name),self.assertRaises(ValueError):self.invoke(raw=f'host=127.0.0.1 port=55439 dbname={name}',dbname=name)

if __name__=='__main__':unittest.main()
