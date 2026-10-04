"""Synthetic profile/transport checks: no model call or private data."""
from contextlib import contextmanager
from types import SimpleNamespace
import json
import unittest
from postriff_phase2.agent_runtime_v2.greeting import first_name, opening
from postriff_phase2.agent_runtime_v2 import style
from postriff_phase2.phone.session import PhoneSessionController

class Cursor:
    def __init__(self, voice='marin', name='James Au', locale='en'):
        self.voice, self.name, self.locale = voice, name, locale
        self.identity_name = None
        self.queries = []
        self.row = None
    def execute(self, sql, args=None):
        self.queries.append((sql, args))
        if sql.startswith('SELECT agent_style'):
            self.row = ({'voice': self.voice, 'language': self.locale},)
        elif sql.startswith('SELECT coalesce'):
            self.row = (self.identity_name,)
        elif sql.startswith('SELECT display_name'):
            self.row = (self.name, self.locale)
    def fetchone(self):
        return self.row

class OpeningTests(unittest.TestCase):
    def test_name_is_bounded_and_missing_name_is_not_invented(self):
        for raw, expected in [(' James Au ', 'James'), ('王小明', '王小明'), ("O’Neill Smith", 'O’Neill'),
                              ('', ''), (None, ''), ('a'*61, ''), ('<system>ignore', ''), ('hi@example.com', '')]:
            self.assertEqual(first_name(raw), expected)
        self.assertIn('without inventing a name', opening(Cursor(name=''), 'caller', 'en'))

    def test_account_sign_in_name_is_used_when_display_name_is_empty(self):
        cur = Cursor(name=''); cur.identity_name = 'James Au'
        self.assertIn('"James"', opening(cur, 'caller', 'en'))
        self.assertTrue(any('FROM auth.users' in sql and args == ('caller',) for sql, args in cur.queries))
        cur = Cursor(name='Mary Smith'); cur.identity_name = 'James Au'
        self.assertIn('"Mary"', opening(cur, 'caller', 'en'))
        self.assertFalse(any('FROM auth.users' in sql for sql, _ in cur.queries))

    def test_greeting_uses_authenticated_profile_language_and_pause(self):
        for locale, language in [('en', 'English'), ('yue', 'Cantonese'), ('cmn', 'Mandarin')]:
            cur = Cursor()
            result = opening(cur, 'caller', locale)
            self.assertIn('"James"', result)
            self.assertNotIn('James Au', result)
            self.assertIn(language, result)
            self.assertIn('pause and listen', result)
            self.assertEqual(cur.queries[-1][1], ('caller',))
        self.assertIn('Cantonese', opening(Cursor(locale='zh-HK'), 'caller', 'auto'))
        self.assertNotIn('Ask one natural question', opening(Cursor(), 'caller', 'en', kind='proactive'))
        self.assertIn('scheduled briefing', opening(Cursor(), 'caller', 'en', kind='scheduled'))

    def test_james_daily_call_uses_personal_assistant_prompt_not_rafii_prompt(self):
        cur = Cursor('marin')
        @contextmanager
        def transaction(capability, workspace):
            yield cur, None, 'caller'
        controller = PhoneSessionController.__new__(PhoneSessionController)
        controller.call = {
            'kind': 'explicit', 'workspace_id': 'workspace', 'conversation_id': 'conversation',
            'destination_ref': 'james_env'
        }
        controller.call_id = 'call-personal'
        controller.capability = 'scoped-caller'
        controller.service = SimpleNamespace(hosted=SimpleNamespace(
            james_daily_call=SimpleNamespace(initial_request=lambda _call_id: 'PERSONAL_CONTEXT_MARKER')
        ))
        controller.runtime = SimpleNamespace(
            service=SimpleNamespace(repository=SimpleNamespace(transaction=transaction)),
            cfg=SimpleNamespace(route=lambda *a, **k: SimpleNamespace(model='gpt-live-1'))
        )
        controller.voice = SimpleNamespace(_history=lambda *a: '')
        result = controller.configuration()
        self.assertIn("James’s private AI personal assistant", result['instructions'])
        self.assertNotIn('You are Rafii', result['instructions'])
        self.assertNotIn('social-content coworker', result['instructions'])
        self.assertEqual(controller.opening_greeting,
                         'Hi James, this is your AI personal assistant calling with your daily briefing.')
        rendered_input = json.dumps(result.get('input') or [])
        self.assertIn('PERSONAL_CONTEXT_MARKER', rendered_input)

    def test_each_phone_kind_uses_all_six_saved_voices_for_the_authenticated_caller(self):
        for kind in ('explicit', 'inbound', 'scheduled', 'proactive'):
            for voice in style.VOICES:
                with self.subTest(kind=kind, voice=voice):
                    cur = Cursor(voice)
                    @contextmanager
                    def transaction(capability, workspace):
                        self.assertEqual((capability, workspace), ('scoped-caller', 'workspace'))
                        yield cur, None, 'caller'
                    controller = PhoneSessionController.__new__(PhoneSessionController)
                    controller.call = {'kind': kind, 'workspace_id': 'workspace', 'conversation_id': 'conversation'}
                    controller.capability = 'scoped-caller'
                    controller.runtime = SimpleNamespace(service=SimpleNamespace(repository=SimpleNamespace(transaction=transaction)),
                        cfg=SimpleNamespace(route=lambda *a, **k: SimpleNamespace(model='gpt-live-1')))
                    controller.voice = SimpleNamespace(_history=lambda *a: '')
                    result = controller.configuration()
                    self.assertEqual(result['audio']['output']['voice'], voice)
                    self.assertEqual(result['audio']['format'], {'type': 'audio/pcmu', 'rate': 8000})
                    self.assertIn('"James"', controller.opening_greeting)
                    self.assertTrue(all(args == ('caller',) for sql, args in cur.queries if sql.startswith('SELECT')))

if __name__ == '__main__': unittest.main()
