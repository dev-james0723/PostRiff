"""Pure local benchmark admission tests. No PostgreSQL or network is needed."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('trend_operations_bench_guard',ROOT/'scripts/trend_operations_bench.py')
bench=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)
LOCAL='host=127.0.0.1 port=56451 dbname=trend_guard'


class BenchmarkAdmission(unittest.TestCase):
    def test_accepts_exact_local_target_and_optional_user(self):
        with mock.patch.object(bench.psycopg,'connect') as connect:
            self.assertEqual(bench.validate_local_dsn(LOCAL,environ={}),
                {'host':'127.0.0.1','port':'56451','dbname':'trend_guard'})
            self.assertEqual(bench.validate_local_dsn(LOCAL+' user=fixture',environ={})['user'],'fixture')
            self.assertEqual(bench.validate_local_dsn('postgresql://fixture@127.0.0.1:56451/trend_guard',environ={})['dbname'],'trend_guard')
            connect.assert_not_called()

    def test_rejects_every_extra_dsn_field_and_uri_redirect(self):
        extras=('hostaddr=203.0.113.1','service=untrusted','options=untrusted','connect_timeout=1',
                'sslmode=disable','passfile=/fixture/unused','password=fixture','application_name=fixture')
        with mock.patch.object(bench.psycopg,'connect') as connect:
            for extra in extras:
                with self.subTest(extra=extra),self.assertRaisesRegex(ValueError,'dedicated_local_g13_database_required'):
                    bench.validate_local_dsn(LOCAL+' '+extra,environ={})
            with self.assertRaises(ValueError):
                bench.validate_local_dsn('postgresql://127.0.0.1:56451/trend_guard?hostaddr=203.0.113.1',environ={})
            connect.assert_not_called()

    def test_rejects_nonlocal_multi_host_wrong_port_and_ambiguous_names(self):
        bad=(LOCAL.replace('127.0.0.1','localhost'),LOCAL.replace('127.0.0.1','203.0.113.1'),
             LOCAL.replace('127.0.0.1','127.0.0.1,203.0.113.1'),LOCAL.replace('56451','5432'),
             LOCAL.replace('trend_guard','postgres'),LOCAL.replace('trend_guard','trend_'),
             LOCAL.replace('trend_guard',"'trend_ hostaddr=203.0.113.1'"),'service=untrusted','',None)
        with mock.patch.object(bench.psycopg,'connect') as connect:
            for dsn in bad:
                with self.subTest(dsn=dsn),self.assertRaises(ValueError):
                    bench.validate_local_dsn(dsn,environ={})
            connect.assert_not_called()

    def test_rejects_environment_overrides_even_when_empty(self):
        with mock.patch.object(bench.psycopg,'connect') as connect:
            for name in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS'):
                for value in ('','fixture'):
                    with self.subTest(name=name,value=value),self.assertRaisesRegex(ValueError,'local_g13_environment_override'):
                        bench.validate_local_dsn(LOCAL,environ={name:value})
            connect.assert_not_called()

    def test_run_checks_dsn_before_connect_or_output(self):
        with mock.patch.object(bench.os,'environ',{}),mock.patch.object(bench.psycopg,'connect') as connect,\
             mock.patch.object(Path,'write_text') as write:
            for extra in ('hostaddr=203.0.113.1','service=untrusted','options=untrusted'):
                with self.subTest(extra=extra),self.assertRaises(ValueError):
                    bench.run(SimpleNamespace(dsn=LOCAL+' '+extra))
            connect.assert_not_called();write.assert_not_called()

    def test_run_checks_real_environment_before_connect_or_output(self):
        with mock.patch.object(bench.psycopg,'connect') as connect,mock.patch.object(Path,'write_text') as write:
            for name in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR','PGOPTIONS'):
                with self.subTest(name=name),mock.patch.object(bench.os,'environ',{name:'fixture'}),self.assertRaises(ValueError):
                    bench.run(SimpleNamespace(dsn=LOCAL))
            connect.assert_not_called();write.assert_not_called()


if __name__=='__main__':
    unittest.main()
