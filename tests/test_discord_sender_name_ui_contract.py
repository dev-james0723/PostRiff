"""The sender-name editor in the web app checks a name before saving with a copy of
`sender_names.name_problem` (contract v2, docs/sender-name/UI-API-CONTRACT.md). This test keeps the verdict
fixture that both sides share honest: the real validator must give exactly the verdicts the editor's tests
assume. If the backend rules change (limit, reserved words, normalization, character classes) this fails
until the fixture and `web/src/lib/channels/discord-sender-name.ts` are updated together.

The v2 validator lives on the sender-name backend branch. On a tree that does not have it yet
(`name_problem` missing) the verdict checks are skipped with a message, never silently passed.
"""
import json
import unittest
from pathlib import Path

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import sender_names

FIXTURE = Path(__file__).resolve().parents[1] / 'web' / 'tests' / 'fixtures' / 'discord-sender-name-verdicts.json'
HAS_V2 = hasattr(sender_names, 'name_problem')


def name_of(case):
    return case['unit'] * case['repeat'] if 'unit' in case else case['name']


class SenderNameUiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_fixture_shape(self):
        self.assertEqual(self.document['schema'], 'rafii.discord-sender-name-verdicts.v2')
        self.assertEqual(self.document['limits'], {'webhook': 80, 'bot': 32})
        self.assertGreaterEqual(len(self.document['cases']), 90)
        reasons = {case['reason'] for case in self.document['cases']}
        self.assertEqual(reasons - {None}, {
            'empty', 'surrounding_space', 'not_normalized', 'too_long', 'control_or_format', 'spacing',
            'invisible', 'forbidden_character', 'url_like', 'reserved_word'})
        self.assertIn(None, reasons)
        for case in self.document['cases']:
            self.assertIn(case['kind'], ('webhook', 'bot'))

    @unittest.skipUnless(HAS_V2, 'sender_names.name_problem (contract v2) is not on this tree; run on the merged tree')
    def test_backend_gives_the_fixture_verdicts(self):
        for case in self.document['cases']:
            name = name_of(case)
            with self.subTest(kind=case['kind'], note=case['note']):
                self.assertEqual(sender_names.name_problem(name, case['kind']), case['reason'])
                if case['reason'] is None:
                    self.assertEqual(sender_names.validate_name(name, case['kind']), name)
                else:
                    with self.assertRaises(AlphaError) as raised:
                        sender_names.validate_name(name, case['kind'])
                    error = raised.exception
                    self.assertEqual((error.status, error.code), (400, 'discord_sender_name_invalid'))
                    self.assertEqual(error.public_fields['reason'], case['reason'])

    @unittest.skipUnless(HAS_V2, 'sender_names.name_problem (contract v2) is not on this tree; run on the merged tree')
    def test_limits_and_rules_the_editor_shows_match_the_contract(self):
        self.assertEqual(dict(sender_names.LIMITS), self.document['limits'])
        # The editor's rules list names exactly these.
        self.assertEqual(sender_names._FORBIDDEN, ('@', '#', ':', '```', '<', '>'))
        self.assertEqual(sender_names._RESERVED_PARTS, ('discord', 'clyde', 'rafii', 'postriff'))
        self.assertEqual(sender_names._RESERVED_WHOLE, ('everyone', 'here'))
        rules = sender_names._rules('webhook')
        self.assertEqual(rules['forbiddenCharacters'], ['@', '#', ':', '```', '<', '>'])
        self.assertTrue(rules['singleSpacesOnly'])
        self.assertTrue(rules['reservedWords'])
        self.assertFalse(rules['surroundingSpace'])


if __name__ == '__main__':
    unittest.main()
