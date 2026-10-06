"""Synthetic safety tests. These are never real source, phone or delivery receipts."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from agent_team.acceptance import as_of_now, acceptance_key, document_period, question_report_key
from agent_team.events import Event
from agent_team.audio import AudioBlocked, narration_for_report, validate_report
from agent_team.periods import period
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_team_acceptance import require_acceptance, acceptance_report
from postriff_phase2.agent_team_delivery import report_identity, delivery_plan
from postriff_phase2.james_agent_team import content_fingerprint

ID = '11111111-1111-4111-8111-111111111111'
NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)
VALUES = {'VERCEL_PROJECT_ID': 'prj_4bfvSc0AC6am9FdknFWcwNYgmcnN', 'VERCEL_ENV': 'production',
          'JAMES_AGENT_TEAM_ACCEPTANCE_ENABLED': '1'}

class Store:
    def __init__(self, events):
        self.events = events
        self.accepted = None
        self.writes = 0
    def get_acceptance(self, value):
        return self.accepted
    def observations(self, p, now):
        return self.events, False
    def put_report(self, doc):
        self.writes += 1
        self.accepted = {**doc, 'fingerprint': content_fingerprint(doc), 'version': 1}
        return self.accepted, True

class StagingAcceptanceTests(unittest.TestCase):
    def test_production_acceptance_document_has_verified_narration(self):
        document, created = acceptance_report(SimpleNamespace(clock=lambda: NOW.timestamp()),
            VALUES, Store([]), {'acceptanceId': ID})
        document['initialGeneratedAt'] = document['generatedAt']
        self.assertTrue(created)
        verified = validate_report(document, now=NOW)
        self.assertTrue(verified.delivery_eligible)
        self.assertEqual(verified.period_key, as_of_now(ID, NOW).key)
        self.assertEqual(narration_for_report(document), verified.narration)
        self.assertTrue(verified.narration)

    def test_acceptance_narration_rejects_changed_mode_or_period_identity(self):
        document, _ = acceptance_report(SimpleNamespace(clock=lambda: NOW.timestamp()),
            VALUES, Store([]), {'acceptanceId': ID})
        for changed in ('ordinary', None):
            candidate = {**document, 'executionMode': changed}
            candidate['fingerprint'] = content_fingerprint(candidate)
            with self.subTest(mode=changed), self.assertRaises(AudioBlocked):
                validate_report(candidate, now=NOW)
        candidate = {**document, 'period': {**document['period'],
            'acceptanceId': '22222222-2222-4222-8222-222222222222'}}
        candidate['fingerprint'] = content_fingerprint(candidate)
        with self.assertRaises(AudioBlocked):
            validate_report(candidate, now=NOW)

    def test_exact_staging_target_and_opt_in_are_both_required(self):
        require_acceptance(VALUES, phone=True)
        for changed in ({'VERCEL_PROJECT_ID': 'founder-production'}, {'VERCEL_ENV': 'preview'},
                        {'JAMES_AGENT_TEAM_ACCEPTANCE_ENABLED': '0'},
                        {'JAMES_AGENT_TEAM_EMERGENCY_DISABLE': '1'},
                        {'JAMES_AGENT_TEAM_CALL_EMERGENCY_DISABLE': '1'}):
            with self.subTest(changed=changed), self.assertRaises(AlphaError):
                require_acceptance({**VALUES, **changed}, phone=True)

    def test_general_enable_flags_never_enable_acceptance_on_other_projects(self):
        with self.assertRaises(AlphaError):
            require_acceptance({**VALUES, 'VERCEL_PROJECT_ID': 'other',
                                'JAMES_AGENT_TEAM_ENABLED': '1', 'JAMES_AGENT_TEAM_CALL_ENABLED': '1'})

    def test_distinct_snapshot_preserves_the_official_cutoff(self):
        scheduled = period('2026-10-06', 'half_day')
        p = as_of_now(ID, NOW)
        self.assertEqual(scheduled.cutoff.hour, 21)
        self.assertEqual(p.cutoff, NOW)
        self.assertNotEqual(p.key, scheduled.key)
        self.assertEqual(p.as_dict()['nominalCutoff'], scheduled.cutoff.isoformat())
        self.assertEqual(acceptance_key(p.key), ('2026-10-06', ID))

    def test_real_input_selection_and_immutable_retry(self):
        event = Event('mission', 'synthetic-mission', 'v1', '2026-10-06T13:50:00Z',
                      '2026-10-06T13:51:00Z', {'state': 'running'}, mission_id='synthetic-mission').cloud()
        store = Store([event])
        service = SimpleNamespace(clock=lambda: NOW.timestamp())
        with patch('postriff_phase2.james_agent_team.source_coverage', return_value={}):
            doc, created = acceptance_report(service, VALUES, store, {'acceptanceId': ID})
            again, created_again = acceptance_report(service, VALUES, store, {'acceptanceId': ID})
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(again, doc)
        self.assertEqual(store.writes, 1)
        self.assertEqual([x['id'] for x in doc['evidence']], [event['key']])
        self.assertIn('full_day_screen_audio_unverified', doc['gaps'])
        self.assertIn('acceptance_as_of_now_not_historical_or_scheduled', doc['gaps'])
        self.assertEqual(document_period(doc).key, doc['period']['key'])
        self.assertEqual(report_identity(doc)[0].key, doc['period']['key'])
        self.assertEqual(delivery_plan(doc, NOW)['channels'], ('in_app', 'push'))

    def test_arbitrary_report_data_cannot_be_submitted(self):
        for request in ({'acceptanceId': ID, 'events': []}, {'acceptanceId': 'invalid'}, {'report': {}}):
            with self.subTest(request=request), self.assertRaises(AlphaError):
                acceptance_report(SimpleNamespace(clock=lambda: NOW.timestamp()), VALUES, Store([]), request)

    def test_acceptance_question_requires_exact_context_identity(self):
        key = as_of_now(ID, NOW).key
        context = {'agentTeamReport': {'workday': '2026-10-06'},
                   'agentTeamAcceptance': {'schemaVersion': 1, 'acceptanceId': ID, 'reportKey': key}}
        self.assertEqual(question_report_key(context), key)
        context['agentTeamAcceptance']['acceptanceId'] = '22222222-2222-4222-8222-222222222222'
        with self.assertRaises(ValueError): question_report_key(context)

    def test_scheduled_question_contract_is_preserved(self):
        self.assertEqual(question_report_key({'agentTeamReport': {'workday': '2026-10-06'}}),
                         'agent-team:v1:2026-10-06:half_day')

if __name__ == '__main__': unittest.main()
