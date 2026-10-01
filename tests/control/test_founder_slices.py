"""Founder P1/P2 slice registries (CONTRACTS §8): one loader, no duplicate ids, failures stay inside one slice."""
import importlib
import json
import sys
import types
import unittest
from unittest import mock

from rafii_control import demo_metrics, founder_cron, http, live_metrics, slices
from rafii_control.auth import CAPABILITIES
from rafii_control.intelligence import ACTIVATED, PACK, Catalog


class SliceRegistryTests(unittest.TestCase):
    def test_every_installed_slice_imports_cleanly(self):
        failed = {}
        for name in slices.SLICES:
            try:
                importlib.import_module('rafii_control.' + name)
            except ModuleNotFoundError as error:
                if error.name != 'rafii_control.' + name:
                    failed[name] = repr(error)
            except Exception as error:  # noqa: BLE001
                failed[name] = repr(error)
        self.assertEqual(failed, {}, 'a slice module must import without errors')

    def test_catalog_extensions_are_activated_rows_with_live_and_demo_adapters(self):
        catalog = Catalog()
        live_metrics.load_extensions()
        for path in sorted((PACK / 'catalogs/metrics.d').glob('*.json')):
            for row in json.loads(path.read_text()):
                self.assertEqual(row['status'], ACTIVATED, path.name)
                self.assertTrue(catalog.activated(row['id']), row['id'])
                self.assertTrue(live_metrics.known(row['id']), 'no live adapter for ' + row['id'])
                self.assertIn(row['id'], live_metrics.METRIC_SOURCES, 'no source for ' + row['id'])

    def test_live_register_refuses_duplicates_and_unknown_sources(self):
        with self.assertRaises(ValueError):
            live_metrics.register(specs={'paid_customers': {}})
        with self.assertRaises(ValueError):
            live_metrics.register(custom={'slice_test_metric': {'rows': lambda *a: []}}, sources={'slice_test_metric': 'no_such_source'})
        live_metrics.CUSTOM.pop('slice_test_metric', None)

    def test_unknown_activated_metric_reports_adapter_unavailable_not_a_failure(self):
        metric = dict(id='slice_missing_metric', unit='count')
        self.assertFalse(live_metrics.known(metric['id']))
        row = live_metrics.build_row(metric, dict(start='2026-09-01T00:00:00Z', end='2026-10-01T00:00:00Z', timeZone=live_metrics.TIME_ZONE), {},
                                     value=None, unit='count', state='unavailable', reason='adapter_unavailable', collecting_since='2026-10-01T00:00:00Z',
                                     history={'availableDays': 3, 'requiredDays': 56})
        self.assertEqual(row['collectingSince'], '2026-10-01T00:00:00Z')
        self.assertEqual(row['history'], {'availableDays': 3, 'requiredDays': 56})
        self.assertIsNone(row['value'])

    def test_demo_register_and_not_simulated(self):
        with self.assertRaises(ValueError):
            demo_metrics.register({'x': 'not callable'})
        metric = dict(id='slice_demo_metric', unit='count')
        rows = demo_metrics.not_simulated(metric, {}, {}, dict(start='a', end='b', timeZone='UTC'), None, False)
        self.assertEqual(rows[0]['reason'], 'demo_not_simulated')
        self.assertIsNone(rows[0]['value'])

    def test_route_registry_validates_capability_and_resolves_full_matches(self):
        with self.assertRaises(ValueError):
            http.register_route('GET', r'/slice-test', 'not.a.capability', 'm', 'f')
        with self.assertRaises(ValueError):
            http.register_route('PATCH', r'/slice-test', 'control.read', 'm', 'f')
        before = list(http.EXTENSION_ROUTES)
        try:
            http.register_route('POST', r'/slice-test/([A-Za-z0-9_-]{1,80})/confirm', 'usage.reconcile', 'founder_actions', 'confirm', step_up=True, budget='founder.action')
            route, match = http.extension_route('/slice-test/abc/confirm', 'POST')
            self.assertEqual(route[2], 'usage.reconcile')
            self.assertEqual(match.groups(), ('abc',))
            self.assertTrue(route[5]['step_up'])
            self.assertEqual(http.ControlApplication._capability('/slice-test/abc/confirm', 'POST'), 'usage.reconcile')
            self.assertEqual(http.extension_route('/slice-test/abc/confirm/extra', 'POST'), (None, None))
            with self.assertRaises(ValueError):
                http.register_route('POST', r'/slice-test/([A-Za-z0-9_-]{1,80})/confirm', 'usage.reconcile', 'founder_actions', 'confirm')
        finally:
            http.EXTENSION_ROUTES[:] = before

    def test_cron_stage_registry_and_failure_isolation(self):
        before = list(founder_cron.STAGES)
        try:
            founder_cron.register_stage('slice_ok', lambda fstore, service, values, now: {'status': 'ok'})
            founder_cron.register_stage('slice_broken', lambda fstore, service, values, now: 1 / 0)
            with self.assertRaises(ValueError):
                founder_cron.register_stage('slice_ok', lambda *a: None)

            class Store:
                environment = 'local'
                def founder_operators(self): return []

            with mock.patch.object(founder_cron, 'probe', return_value={'status': 'ok'}), \
                 mock.patch.object(founder_cron, 'subscription_snapshot', return_value={'status': 'ok'}), \
                 mock.patch.object(founder_cron, 'incidents_stage', return_value={}), \
                 mock.patch.object(founder_cron, 'schedules_stage', return_value={}), \
                 mock.patch.object(founder_cron, 'reconcile_stage', return_value={}):
                result = founder_cron.tick(object(), {'RAFII_CONTROL_ENABLED': '1'}, fstore=Store(), observe=lambda *a: {}, clock=lambda: 1_790_000_000.0)
            self.assertEqual(result['slice_ok'], {'status': 'ok'})
            self.assertEqual(result['slice_broken'], {'status': 'unavailable', 'error': 'ZeroDivisionError'})
            self.assertEqual(result['status'], 'partial')
        finally:
            founder_cron.STAGES[:] = before

    def test_failed_slice_is_recorded_by_class_only(self):
        state = dict(slices.STATE)
        failed_name = 'rafii_control.founder_metrics_ops'
        broken = types.ModuleType(failed_name)
        try:
            slices.STATE.update(loaded=False, failed={})
            with mock.patch('importlib.import_module', side_effect=lambda name: (_ for _ in ()).throw(RuntimeError('postgres://secret@host')) if name == failed_name else broken):
                failed = slices.load()
            self.assertEqual(failed, {'founder_metrics_ops': 'RuntimeError'})
        finally:
            slices.STATE.clear()
            slices.STATE.update(state)
            sys.modules.pop(failed_name, None) if sys.modules.get(failed_name) is broken else None

    def test_new_capabilities_are_declared_and_budgeted(self):
        from rafii_control.auth import BUDGETS
        for capability in ('usage.reconcile', 'credits.adjust', 'accounts.block', 'refunds.prepare', 'founder.export'):
            self.assertIn(capability, CAPABILITIES)
        for purpose in ('founder.action', 'founder.voice', 'founder.export'):
            self.assertIn(purpose, BUDGETS)


if __name__ == '__main__':
    unittest.main()
