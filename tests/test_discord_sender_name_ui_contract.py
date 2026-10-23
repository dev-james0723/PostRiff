"""The sender-name editor in the web app validates a name before saving with a copy of
`sender_names.validate_name`. This test keeps the verdict fixture that both sides share honest:
the real validator must give exactly the verdicts the editor's tests assume. If the backend rules
change (limit, reserved words, normalization, character classes) this fails until the fixture and
`web/src/lib/channels/discord-sender-name.ts` are updated together.
"""
import json
import unittest
from pathlib import Path

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord.sender_names import validate_name

FIXTURE = Path(__file__).resolve().parents[1] / 'web' / 'tests' / 'fixtures' / 'discord-sender-name-verdicts.json'


def name_of(case):
    return case['unit'] * case['repeat'] if 'unit' in case else case['name']


class SenderNameUiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_fixture_shape(self):
        self.assertEqual(self.document['schema'], 'rafii.discord-sender-name-verdicts.v1')
        self.assertEqual(self.document['limits'], {'webhook': 80, 'bot': 32})
        self.assertGreaterEqual(len(self.document['cases']), 50)
        for case in self.document['cases']:
            self.assertIn(case['kind'], ('webhook', 'bot'))
            self.assertIsInstance(case['accepted'], bool)
            # An accepted name breaks no rule; a rejected one names at least one rule the editor can show.
            self.assertEqual(bool(case['issues']), not case['accepted'], case)

    def test_backend_gives_the_fixture_verdicts(self):
        for case in self.document['cases']:
            name = name_of(case)
            with self.subTest(kind=case['kind'], note=case['note']):
                if case['accepted']:
                    self.assertEqual(validate_name(name, case['kind']), name)
                else:
                    with self.assertRaises(AlphaError) as raised:
                        validate_name(name, case['kind'])
                    self.assertEqual(raised.exception.code, 'discord_sender_name_required')
                    self.assertEqual(raised.exception.status, 400)

    def test_limits_are_counted_in_code_points(self):
        # 80 and 32 are in the fixture as exact boundaries; one more is refused. An astral character is one unit.
        for kind, limit in (('webhook', 80), ('bot', 32)):
            self.assertEqual(validate_name('\U0001F600' * limit, kind), '\U0001F600' * limit)
            with self.assertRaises(AlphaError):
                validate_name('\U0001F600' * (limit + 1), kind)

    def test_reserved_words_are_webhook_only(self):
        self.assertEqual(validate_name('Discord', 'bot'), 'Discord')
        with self.assertRaises(AlphaError):
            validate_name('Discord', 'webhook')


if __name__ == '__main__':
    unittest.main()
