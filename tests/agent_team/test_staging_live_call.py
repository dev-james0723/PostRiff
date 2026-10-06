"""Synthetic safety tests only; no PSTN call, model request or human acceptance."""
import io
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import staging_live_call as subject
from postriff_phase2.james_agent_team import PREFIX, route
from postriff_phase2.phone.session import PhoneSessionController

ID = '11111111-1111-4111-8111-111111111111'
VALUES = {'VERCEL_PROJECT_ID': 'prj_4bfvSc0AC6am9FdknFWcwNYgmcnN', 'VERCEL_ENV': 'production',
          'JAMES_AGENT_TEAM_ACCEPTANCE_ENABLED': '1', 'JAMES_AGENT_TEAM_VERIFIER_TOKEN': 'v' * 40}


class StagingLiveCallTests(unittest.TestCase):
    def service(self):
        service = MagicMock()
        service.clock.return_value = 1791324000
        daily = service.james_daily_call
        daily.cfg.max_seconds = 120
        daily.cfg.daily_cap = daily.cfg.monthly_cap = 5000000
        daily.cfg.workspace_id = 'fixed-workspace'
        daily.cfg.user_id = 'fixed-user'
        daily.cfg.destination.return_value = '+15555550123'
        daily.cfg.quiet.return_value = False
        daily.phone.provider.real = True
        daily.phone.provider.name = 'twilio'
        daily.phone.config.cap_seconds = 3600
        daily._estimate.return_value = 100000
        service.ledger.credits.view.return_value = {'availableMilliCredits': 1000000, 'debtMilliCredits': 0}
        return service

    def test_exact_staging_and_emergency_gates_precede_dial(self):
        service = self.service()
        for changed in ({'VERCEL_PROJECT_ID': 'founder'}, {'VERCEL_ENV': 'preview'},
                        {'JAMES_AGENT_TEAM_ACCEPTANCE_ENABLED': '0'},
                        {'JAMES_AGENT_TEAM_EMERGENCY_DISABLE': '1'},
                        {'JAMES_AGENT_TEAM_CALL_EMERGENCY_DISABLE': '1'}):
            with self.subTest(changed=changed), self.assertRaises(AlphaError):
                subject.start(service, {**VALUES, **changed}, {'testId': ID})
        service.james_daily_call._require_base.assert_not_called()

    def test_body_cannot_select_destination_actor_prompt_or_duration(self):
        service = self.service()
        for request in ({}, {'testId': 'bad'}, {'testId': ID, 'destination': '+15555550999'},
                        {'testId': ID, 'prompt': 'start agent'}, {'testId': ID, 'maxSeconds': 900}):
            with self.subTest(request=request), self.assertRaises(AlphaError):
                subject.start(service, VALUES, request)
        service.james_daily_call._require_base.assert_not_called()

    def test_fixed_principal_explicit_request_is_bounded_and_has_no_daily_run(self):
        service = self.service()
        phone = MagicMock()
        phone.request.return_value = {'id': 'call', 'state': 'dialing'}
        with patch.object(subject, '_prior', return_value=None), \
             patch('postriff_phase2.phone.runtime.principal_phone', return_value=(phone, 'capability')):
            result = subject.start(service, VALUES, {'testId': ID})
        args, kwargs = phone.request.call_args
        self.assertEqual(args[:2], ('fixed-workspace', 'capability'))
        self.assertEqual(args[2]['callDurationLimitSeconds'], 120)
        self.assertEqual(args[2]['idempotencyKey'], subject.REASON_PREFIX + ID)
        self.assertEqual(kwargs['kind'], 'explicit')
        self.assertEqual(kwargs['_destination'], '+15555550123')
        self.assertEqual(kwargs['_destination_ref'], 'james_env')
        self.assertFalse(result['automaticRetry'])
        service.james_daily_call.trigger.assert_not_called()
        service.james_daily_call._context.assert_not_called()
        service.james_daily_call._budget_check.assert_called_once()

    def test_retry_returns_same_call_without_dial_or_second_budget_admission(self):
        service = self.service()
        with patch.object(subject, '_prior', return_value='existing'), \
             patch.object(subject, 'status', return_value={'call': {'id': 'existing'}}), \
             patch('postriff_phase2.phone.runtime.principal_phone') as principal:
            self.assertEqual(subject.start(service, VALUES, {'testId': ID})['call']['id'], 'existing')
        principal.assert_not_called()
        service.james_daily_call._budget_check.assert_not_called()

    def test_quiet_cost_and_real_provider_failures_do_not_dial(self):
        for blocker in ('quiet', 'budget', 'fake'):
            service = self.service()
            if blocker == 'quiet': service.james_daily_call.cfg.quiet.return_value = True
            if blocker == 'budget': service.james_daily_call._budget_check.side_effect = AlphaError('cap', 409)
            if blocker == 'fake': service.james_daily_call.phone.provider.real = False
            with patch.object(subject, '_prior', return_value=None), \
                 patch('postriff_phase2.phone.runtime.principal_phone') as principal, self.assertRaises(AlphaError):
                subject.start(service, VALUES, {'testId': ID})
            principal.assert_not_called()

    def test_preflight_rejects_paused_inactive_or_insufficient_credits(self):
        for blocker in ('paused', 'inactive', 'balance', 'debt'):
            service = self.service()
            if blocker == 'paused': service.ledger.credits = None
            if blocker == 'inactive': service.ledger.credits.policy.side_effect = AlphaError('Inactive policy', 409)
            if blocker == 'balance': service.ledger.credits.view.return_value['availableMilliCredits'] = 0
            if blocker == 'debt': service.ledger.credits.view.return_value['debtMilliCredits'] = 1
            with self.subTest(blocker=blocker), self.assertRaises(AlphaError):
                subject.preview(service, VALUES)

    def test_http_requires_verifier_and_does_not_accept_reader_or_observer(self):
        app = SimpleNamespace(_runtime=MagicMock(return_value=self.service()),
                              _json=lambda _start, _code, value, **_kw: value)
        for token in ('r' * 40, 'o' * 40, ''):
            with patch.dict('os.environ', VALUES, clear=True), patch.object(subject, 'start') as start, \
                 self.assertRaises(AlphaError):
                route(app, {'HTTP_AUTHORIZATION': 'Bearer ' + token}, MagicMock(), 'POST', PREFIX + '/live-call-test')
            start.assert_not_called()
        data = json.dumps({'testId': ID}).encode()
        environ = {'HTTP_AUTHORIZATION': 'Bearer ' + 'v' * 40,
                   'wsgi.input': io.BytesIO(data), 'CONTENT_LENGTH': str(len(data))}
        with patch.dict('os.environ', VALUES, clear=True), patch.object(subject, 'start', return_value={'ok': True}) as start:
            self.assertEqual(route(app, environ, MagicMock(), 'POST', PREFIX + '/live-call-test'), {'ok': True})
        self.assertEqual(start.call_args.args[2], {'testId': ID})

    def controller(self):
        controller = object.__new__(PhoneSessionController)
        controller.call = {'destination_ref': 'james_env', 'reason_key': subject.REASON_PREFIX + ID}
        controller.runtime = MagicMock()
        controller.runtime.cfg.route.return_value.model = 'gpt-live-1'
        controller.lock = threading.Lock()
        controller.closed = False
        controller.user_text = 'please query my mail'
        return controller

    def test_voice_configuration_has_no_personal_history_or_backend(self):
        controller = self.controller()
        config = controller.configuration()
        self.assertEqual(config['model'], 'gpt-live-1')
        self.assertEqual(config['audio']['format'], {'type': 'audio/pcmu', 'rate': 8000})
        self.assertNotIn('input', config)
        self.assertIn('Cantonese', config['instructions'])
        self.assertIn('GPT Live', controller.opening_greeting)
        controller.runtime.service.repository.transaction.assert_not_called()
        response = controller.delegate({'delegation': {'id': 'test', 'target': 'client'}})
        self.assertEqual(response['delegation_id'], 'test')
        self.assertIn('no backend tools', response['content'])
        controller.runtime.turn.assert_not_called()
        controller.runtime.service.repository.transaction.assert_not_called()

    def test_other_calls_do_not_enter_voice_test_mode(self):
        for reason in ('james_daily:' + ID, subject.REASON_PREFIX + 'invalid', 'founder:test'):
            self.assertFalse(subject.is_voice_test_call({'destination_ref': 'james_env', 'reason_key': reason}))
        self.assertFalse(subject.is_voice_test_call({'destination_ref': 'other', 'reason_key': subject.REASON_PREFIX + ID}))


if __name__ == '__main__': unittest.main()
