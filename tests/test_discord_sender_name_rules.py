"""Sender-name rules and server-side switches. Pure functions: no database, no Discord, no credentials.

Every refusal carries a stable machine reason (the UI maps copy to it); the name abuse matrix below is the tested part
of docs/sender-name/THREAT-MODEL.md section "name abuse".
"""
import os
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import sender_names as names

ASTRAL = '\U0001F600'


class Accepted(unittest.TestCase):
    def test_ordinary_brand_names_in_several_scripts(self):
        for kind, name in [('webhook', 'D Festival 公告'), ('webhook', 'Acme Weekly'), ('webhook', 'Café Müller'),
                           ('webhook', 'Дайджест новостей'), ('webhook', 'الأخبار'), ('webhook', '週刊ニュース'),
                           ('webhook', '🎵 Daily Notes'), ('bot', 'D Festival 助手'), ('bot', 'Acme Bot'),
                           ('webhook', 'a' * 80), ('bot', 'a' * 32), ('webhook', 'Here Maps'), ('webhook', 'Everyone Welcome'),
                           ('webhook', 'Traffic Updates'), ('webhook', 'Safari News'), ('webhook', 'Star ★ Team'),
                           # Discord restricts these in webhook usernames only; a server nickname may carry them (SNR2-9)
                           ('bot', 'Discord Devs Bot'), ('bot', 'Clyde Fan Club'), ('bot', 'Here'), ('bot', 'EVERYONE'),
                           ('bot', 'D1scord Helper'), ('bot', 'd\U00000456scord news'), ('bot', 'He re')]:
            with self.subTest(kind=kind, name=name):
                self.assertEqual(names.validate_name(name, kind), name)

    def test_the_limit_is_exact_in_code_points_and_utf16_units(self):
        self.assertIsNone(names.name_problem('a' * 80, 'webhook'))
        self.assertEqual(names.name_problem('a' * 81, 'webhook'), 'too_long')
        self.assertIsNone(names.name_problem('a' * 32, 'bot'))
        self.assertEqual(names.name_problem('a' * 33, 'bot'), 'too_long')
        # 41 astral characters are 41 code points but 82 UTF-16 units: the stricter reading keeps Discord's own
        # unpublished counting from rejecting an approved post later.
        self.assertEqual(names.name_problem(ASTRAL * 41, 'webhook'), 'too_long')
        self.assertIsNone(names.name_problem(ASTRAL * 40, 'webhook'))
        self.assertEqual(names.name_problem('a' + ASTRAL * 16, 'bot'), 'too_long')       # 33 units
        self.assertIsNone(names.name_problem(ASTRAL * 16, 'bot'))                         # exactly 32 units


class Refused(unittest.TestCase):
    CASES = [
        # (name, kind, reason)
        (None, 'webhook', 'not_text'), (42, 'webhook', 'not_text'), (['a'], 'bot', 'not_text'), (b'abc', 'bot', 'not_text'),
        ('', 'webhook', 'empty'), (' ', 'webhook', 'empty'), ('\U00003000', 'bot', 'empty'),
        (' lead', 'webhook', 'surrounding_space'), ('trail ', 'bot', 'surrounding_space'),
        ('Cafe\U00000301', 'webhook', 'not_normalized'),                                   # NFD, not NFC
        # control, format, bidi, zero-width, tag, private-use and unassigned code points
        ('bad\nname', 'webhook', 'control_or_format'), ('bad\tname', 'bot', 'control_or_format'),
        ('bad\x00name', 'webhook', 'control_or_format'), ('bad\U0000202ename', 'webhook', 'control_or_format'),
        ('bad\U00002066name', 'webhook', 'control_or_format'), ('zero\U0000200bwidth', 'webhook', 'control_or_format'),
        ('join\U0000200der', 'webhook', 'control_or_format'), ('bom\U0000feffname', 'bot', 'control_or_format'),
        ('tag\U000e0041name', 'webhook', 'control_or_format'), ('pua\U0000e000name', 'webhook', 'control_or_format'),
        ('gap\U00000378name', 'webhook', 'control_or_format'), ('line\U00002028sep', 'webhook', 'control_or_format'),
        # an unpaired surrogate (what JSON "backslash-u d800" decodes to) is an invalid name, never an encoding error
        ('x' + chr(0xD800) + 'y', 'webhook', 'control_or_format'), ('x' + chr(0xDFFF) + 'y', 'bot', 'control_or_format'),
        (chr(0xDC00), 'webhook', 'control_or_format'), ('tail' + chr(0xDBFF), 'bot', 'control_or_format'),
        ('a' * 31 + chr(0xD800), 'bot', 'control_or_format'), ('a' * 32 + chr(0xD800), 'bot', 'too_long'),
        ('pair' + chr(0xD83D) + chr(0xDE00), 'webhook', 'control_or_format'),    # two separate surrogates are not one character
        # whitespace other than single ASCII spaces (Discord collapses "excessive" whitespace, so the read-back
        # of an approved post would no longer equal the approved name)
        ('a  b', 'webhook', 'spacing'), ('a\U000000a0b', 'webhook', 'spacing'), ('a\U00003000b', 'bot', 'spacing'),
        ('a\U00002003b', 'webhook', 'spacing'),
        # characters and names that render as nothing
        ('\U00003164', 'webhook', 'invisible'), ('\U00002800\U00002800', 'webhook', 'invisible'), ('a\U0000115fb', 'webhook', 'invisible'),
        ('\U00000301', 'webhook', 'invisible'), ('\U0000ffa0', 'bot', 'invisible'),
        # mention, emoji, channel and code syntax, and Discord's own username substrings
        ('@everyone', 'webhook', 'forbidden_character'), ('Team @here', 'bot', 'forbidden_character'),
        ('<@123456789012345678>', 'webhook', 'forbidden_character'), ('<@&123456789012345678>', 'webhook', 'forbidden_character'),
        ('<#123456789012345678>', 'bot', 'forbidden_character'), ('#general', 'webhook', 'forbidden_character'),
        ('News: Daily', 'webhook', 'forbidden_character'), (':smile:', 'bot', 'forbidden_character'),
        ('```code```', 'webhook', 'forbidden_character'),
        ('www.example.com', 'webhook', 'url_like'), ('Visit www.example.com', 'bot', 'url_like'),
        # reserved words after folding: case, full-width, accents, other-script look-alikes, separators, digits
        ('Discord', 'webhook', 'reserved_word'), ('DISCORD Support', 'webhook', 'reserved_word'),
        ('\U0000ff44\U0000ff49\U0000ff53\U0000ff43\U0000ff4f\U0000ff52\U0000ff44', 'webhook', 'reserved_word'), ('D\U000000efsc\U000000f6rd', 'webhook', 'reserved_word'),
        ('d\U00000456scord', 'webhook', 'reserved_word'), ('d\U00000456s\U00000441\U0000043erd clone', 'webhook', 'reserved_word'),
        ('D1scord', 'webhook', 'reserved_word'), ('d i s c o r d', 'webhook', 'reserved_word'),
        ('dis_cord', 'webhook', 'reserved_word'), ('Clyde', 'webhook', 'reserved_word'),
        ('Cl-yde', 'webhook', 'reserved_word'), ('C1yde', 'webhook', 'reserved_word'),
        ('Everyone', 'webhook', 'reserved_word'), ('HERE', 'webhook', 'reserved_word'), ('he re', 'webhook', 'reserved_word'),
        # the product's own names stay reserved for both kinds
        ('Rafii Support', 'webhook', 'reserved_word'), ('rafii', 'bot', 'reserved_word'), ('PostRiff Official', 'webhook', 'reserved_word'),
        ('P0stR1ff', 'webhook', 'reserved_word'), ('Rafii Helper', 'bot', 'reserved_word'), ('p0stR1ff bot', 'bot', 'reserved_word'),
        ('r\U00000430fii', 'bot', 'reserved_word'),
    ]

    def test_every_case_reports_its_stable_reason(self):
        for name, kind, reason in self.CASES:
            with self.subTest(name=repr(name), kind=kind):
                with self.assertRaises(AlphaError) as raised:
                    names.validate_name(name, kind)
                error = raised.exception
                self.assertEqual((error.status, error.code), (400, 'discord_sender_name_invalid'))
                self.assertEqual(error.public_fields, {'reason': reason, 'maxLength': names.LIMITS[kind]})
                self.assertEqual(names.name_problem(name, kind), reason)
                # The message never echoes the submitted text back.
                if isinstance(name, str) and len(name) > 3:
                    self.assertNotIn(name, str(error))

    def test_a_name_cannot_ping_or_link(self):
        """Mention syntax and links never reach the wire: the characters that make them are not accepted, and the
        webhook body always forbids parsing (see the wire tests). A name is plain text in Discord's author line."""
        for name in ('@everyone', '@here', '<@1234567>', '<@&1234567>', '<#1234567>', '[click](https://x.example)',
                     'https://x.example', 'Free nitro: x.example'):
            with self.subTest(name=name), self.assertRaises(AlphaError):
                names.validate_name(name, 'webhook')


class Switches(unittest.TestCase):
    def test_master_switch_is_on_only_for_the_exact_string_true_whatever_the_environment_label(self):
        """Unset is off everywhere. No label of where the code runs (a preview, a mislabelled production, a staging
        name) can turn the feature on by itself (SNR2-3)."""
        labels = [{}, {'VERCEL_ENV': 'development'}, {'VERCEL_ENV': 'preview'}, {'VERCEL_ENV': 'production'},
                  {'POSTRIFF_ENVIRONMENT': 'prod'}, {'POSTRIFF_ENVIRONMENT': ' Production '}, {'POSTRIFF_ENVIRONMENT': 'staging'},
                  {'POSTRIFF_ENVIRONMENT': 'development', 'VERCEL_ENV': 'preview'}]
        for label in labels:
            with self.subTest(label=label, switch='unset'):
                self.assertIs(names.names_enabled(dict(label)), False)
            with self.subTest(label=label, switch='true'):
                self.assertIs(names.names_enabled({**label, names.ENV_SENDER_NAMES: 'true'}), True)
            for raw in ('TRUE', 'True', '1', 'yes', 'on', '', 'false', ' true', 'true ', 'truee'):
                with self.subTest(label=label, switch=raw):
                    self.assertIs(names.names_enabled({**label, names.ENV_SENDER_NAMES: raw}), False)

    def test_the_master_switch_does_not_read_the_launch_gate_labels(self):
        """A regression guard for the above: the decision is the one variable, nothing else is consulted."""
        class OnlyThatKey(dict):
            def get(self, key, default=None):
                assert key == names.ENV_SENDER_NAMES, f'unexpected read of {key}'
                return super().get(key, default)
        self.assertIs(names.names_enabled(OnlyThatKey()), False)
        self.assertIs(names.names_enabled(OnlyThatKey({names.ENV_SENDER_NAMES: 'true'})), True)
        with patch.dict(os.environ, {'VERCEL_ENV': 'preview', 'POSTRIFF_ENVIRONMENT': 'prod'}):
            os.environ.pop(names.ENV_SENDER_NAMES, None)
            self.assertIs(names.names_enabled(), False)

    def test_nickname_switch_is_off_everywhere_unless_exactly_true(self):
        for values, expected in [({}, False), ({'VERCEL_ENV': 'development'}, False), ({'VERCEL_ENV': 'production'}, False),
                                 ({names.ENV_BOT_NICKNAME: 'true'}, True), ({names.ENV_BOT_NICKNAME: 'True'}, False),
                                 ({names.ENV_BOT_NICKNAME: '1'}, False), ({names.ENV_BOT_NICKNAME: ''}, False),
                                 ({names.ENV_BOT_NICKNAME: 'true', 'VERCEL_ENV': 'production'}, True)]:
            with self.subTest(values=values):
                self.assertIs(names.nickname_enabled(values), expected)

    def test_switches_are_read_at_call_time_from_the_process_environment(self):
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true'}):
            self.assertTrue(names.names_enabled())
        with patch.dict(os.environ, {names.ENV_SENDER_NAMES: 'false'}):
            self.assertFalse(names.names_enabled())
        with patch.dict(os.environ, {names.ENV_BOT_NICKNAME: 'true'}):
            self.assertTrue(names.nickname_enabled())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(names.ENV_BOT_NICKNAME, None)
            self.assertFalse(names.nickname_enabled())


class FrozenName(unittest.TestCase):
    def channel(self, **extra):
        return {'discordConnectionKind': 'webhook', **extra}

    def test_only_a_webhook_connection_with_a_saved_name_freezes_one_and_only_while_on(self):
        on, off = {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true'}, {names.ENV_SENDER_NAMES: 'false'}
        self.assertEqual(names.frozen_webhook_name(self.channel(discordSenderName='Acme Weekly'), on), 'Acme Weekly')
        self.assertIsNone(names.frozen_webhook_name(self.channel(discordSenderName='Acme Weekly'), off))
        self.assertIsNone(names.frozen_webhook_name(self.channel(discordSenderName='Acme Weekly'), {}), 'unset is off')
        self.assertIsNone(names.frozen_webhook_name(self.channel(), on))
        self.assertIsNone(names.frozen_webhook_name({'discordConnectionKind': 'installation', 'discordSenderName': 'Acme Weekly'}, on))
        for bad in ('', 'Discord', None, 5):
            with self.subTest(bad=bad), self.assertRaises(AlphaError):
                names.frozen_webhook_name(self.channel(discordSenderName=bad), on)
        # While off, a bad stored value cannot block a review: nothing would be sent under it.
        self.assertIsNone(names.frozen_webhook_name(self.channel(discordSenderName='Discord'), off))

    def test_dispatch_gate_holds_only_a_named_webhook_manifest_while_off(self):
        for off in ({names.ENV_SENDER_NAMES: 'false'}, {}, {'VERCEL_ENV': 'preview'}):      # explicitly off, and merely unset
            with self.subTest(off=off):
                with self.assertRaises(AlphaError) as raised:
                    names.assert_sendable({'senderKind': 'webhook', 'discordSenderName': 'Acme Weekly'}, off)
                self.assertEqual((raised.exception.status, raised.exception.code), (409, 'discord_sender_names_disabled'))
                for manifest in ({'senderKind': 'webhook'}, {'senderKind': 'bot'}, {}):
                    names.assert_sendable(manifest, off)
        names.assert_sendable({'senderKind': 'webhook', 'discordSenderName': 'Acme Weekly'}, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true'})


class ReadBack(unittest.TestCase):
    """The created message's author name is compared with the frozen one after Unicode NFC and whitespace canonicalisation
    (which Discord is documented to apply), not byte for byte (SNR-8); every real difference still fails."""
    def manifest(self, name='Acme Weekly'):
        return {'discord': {'target': {'channelId': '71', 'webhookId': '81'}}, 'payload': {'text': 'hello'},
                **({'discordSenderName': name} if name is not None else {})}

    @staticmethod
    def body(username):
        return {'id': '9', 'channel_id': '71', 'webhook_id': '81', 'author': {'id': '81', 'bot': True, 'username': username},
                'content': 'hello', 'mentions': [], 'mention_roles': [], 'mention_everyone': False, 'attachments': [], 'embeds': []}

    def matches(self, username, name='Acme Weekly'):
        from postriff_phase2.discord.webhooks import message_matches
        return message_matches(self.body(username), self.manifest(name), '9')

    def test_equal_and_normalised_names_match(self):
        self.assertTrue(self.matches('Acme Weekly'))
        self.assertTrue(self.matches('Acme  Weekly'), 'Discord collapses repeated spaces')
        self.assertTrue(self.matches(' Acme Weekly '))
        self.assertTrue(self.matches('Acme\u00a0Weekly'))
        self.assertTrue(self.matches('Cafe\u0301 Weekly', 'Caf\u00e9 Weekly'), 'decomposed Unicode equals composed')
        self.assertTrue(self.matches('Caf\u00e9 Weekly', 'Cafe\u0301 Weekly'))

    def test_every_real_difference_fails(self):
        for username in ('acme weekly', 'Acme Weekl', 'Acme Weekly!', 'Acme Wee\u043aly', 'AcmeWeekly', '', None, 5, ['Acme Weekly']):
            with self.subTest(username=username):
                self.assertFalse(self.matches(username))

    def test_an_unnamed_manifest_does_not_compare_the_author_name(self):
        self.assertTrue(self.matches('Spare Webhook', None))
        self.assertTrue(self.matches(None, None))

    def test_the_other_checks_are_unchanged(self):
        from postriff_phase2.discord.webhooks import message_matches
        body = self.body('Acme Weekly')
        self.assertTrue(message_matches(body, self.manifest(), '9'))
        for key, value in (('id', '10'), ('channel_id', '72'), ('webhook_id', '82'), ('content', 'other'), ('mention_everyone', True),
                           ('mentions', [{'id': '1'}]), ('mention_roles', ['5']), ('attachments', [{}]), ('embeds', [{}]),
                           ('author', {'id': '82', 'bot': True, 'username': 'Acme Weekly'}),
                           ('author', {'id': '81', 'bot': False, 'username': 'Acme Weekly'}),
                           ('author', {'id': '81', 'username': 'Acme Weekly'}), ('author', None)):
            for manifest in (self.manifest(), self.manifest(None)):
                with self.subTest(key=key, named=bool(manifest.get('discordSenderName'))):
                    self.assertFalse(message_matches({**body, key: value}, manifest, '9'))
        for not_a_message in (None, [], 'text', 5):
            self.assertFalse(message_matches(not_a_message, self.manifest(), '9'))
        self.assertFalse(message_matches({k: v for k, v in body.items() if k != 'mention_everyone'}, self.manifest(), '9'))


class Equivalence(unittest.TestCase):
    def test_only_text_can_be_equivalent(self):
        self.assertTrue(names.names_equivalent('Acme', 'Acme'))
        self.assertFalse(names.names_equivalent(None, None))
        self.assertFalse(names.names_equivalent(5, 5))
        self.assertFalse(names.names_equivalent('Acme', None))
        self.assertFalse(names.names_equivalent(None, 'Acme'))


class Joiners(unittest.TestCase):
    """Two invisible characters real text needs (emoji sequences, Persian and Indic words) and nothing else invisible."""
    ZWJ, ZWNJ, VS16, SKIN = chr(0x200D), chr(0x200C), chr(0xFE0F), chr(0x1F3FD)
    MAN, LAPTOP, FLAG, RAINBOW = chr(0x1F468), chr(0x1F4BB), chr(0x1F3F3), chr(0x1F308)
    MEEM, FARSI_YEH = chr(0x0645), chr(0x06CC)

    def problem(self, name, kind='webhook'):
        return names.name_problem(name, kind)

    def test_a_joiner_inside_one_emoji_sequence_is_accepted(self):
        for name in (self.MAN + self.ZWJ + self.LAPTOP,
                     self.MAN + self.SKIN + self.ZWJ + self.LAPTOP,
                     self.FLAG + self.VS16 + self.ZWJ + self.RAINBOW,
                     'Team ' + self.MAN + self.ZWJ + self.LAPTOP):
            with self.subTest(name=name.encode('unicode_escape')):
                self.assertIsNone(self.problem(name))
                self.assertIsNone(self.problem(name, 'bot'))

    def test_a_joiner_anywhere_else_is_refused(self):
        cases = {
            'leading': self.ZWJ + self.LAPTOP, 'trailing': self.LAPTOP + self.ZWJ,
            'between Latin letters': 'a' + self.ZWJ + 'b', 'letter and emoji': 'a' + self.ZWJ + self.LAPTOP,
            'emoji and letter': self.LAPTOP + self.ZWJ + 'b', 'after a variation selector only': self.VS16 + self.ZWJ + self.LAPTOP,
            'a bare joiner': 'ab' + self.ZWJ, 'two in a row': self.MAN + self.ZWJ + self.ZWJ + self.LAPTOP}
        for label, name in cases.items():
            with self.subTest(label):
                self.assertEqual(self.problem('x ' + name if label != 'leading' else name), 'control_or_format', label)

    def test_a_non_joiner_is_only_for_scripts_that_need_it(self):
        persian = self.MEEM + self.ZWNJ + self.FARSI_YEH
        self.assertIsNone(self.problem(persian))
        for label, name in {'Latin letters': 'a' + self.ZWNJ + 'b', 'leading': self.ZWNJ + self.MEEM, 'trailing': self.MEEM + self.ZWNJ,
                            'between emoji': self.LAPTOP + self.ZWNJ + self.LAPTOP, 'letter and emoji': self.MEEM + self.ZWNJ + self.LAPTOP,
                            'Latin extended-A': chr(0x0101) + self.ZWNJ + chr(0x0113),
                            'Latin then Persian': 'a' + self.ZWNJ + self.MEEM, 'Persian then Latin': self.MEEM + self.ZWNJ + 'b',
                            'emoji then Persian': self.LAPTOP + self.ZWNJ + self.MEEM,
                            'punctuation then Persian': chr(0x060C) + self.ZWNJ + self.MEEM,
                            'Persian then punctuation': self.MEEM + self.ZWNJ + chr(0x060C)}.items():
            with self.subTest(label):
                self.assertEqual(self.problem('x ' + name if label != 'leading' else name), 'control_or_format', label)

    def test_no_other_format_character_is_let_through_by_the_joiner_rule(self):
        for code in (0x200B, 0x2060, 0xFEFF, 0x202E, 0x2066, 0x00AD):
            with self.subTest(hex(code)):
                self.assertEqual(self.problem('a' + chr(code) + 'b'), 'control_or_format')


class Hierarchy(unittest.TestCase):
    """Discord's role hierarchy for the person who installed the bot: the owner, or a role strictly above the bot's highest."""
    GUILD = {'owner_id': '1', 'roles': [{'id': 'r1', 'position': 5}, {'id': 'r2', 'position': 2}, {'id': 'r3', 'position': 5},
                                        {'id': 'bad', 'position': '7'}, {'id': 'none'}]}

    def above(self, person, bot, user='9'):
        return names._above(self.GUILD, person, bot, user)

    def test_strictly_above_or_the_owner(self):
        self.assertTrue(self.above(['r1'], ['r2']))
        self.assertTrue(self.above(['r2', 'r1'], ['r2']))
        self.assertFalse(self.above(['r2'], ['r1']))
        self.assertFalse(self.above(['r1'], ['r3']), 'an equal position is not above')
        self.assertTrue(self.above([], [], user='1'), 'the owner needs no role')
        self.assertTrue(self.above(['r2'], ['r1'], user='1'))

    def test_anything_unknown_fails_closed(self):
        self.assertFalse(self.above(['unknown'], ['r2']))
        self.assertFalse(self.above(['r1'], ['unknown']))
        self.assertFalse(self.above(['bad'], ['r2']), 'a position that is not an integer')
        self.assertFalse(self.above(['r1'], ['bad']))
        self.assertFalse(self.above(['none'], ['r2']))
        self.assertFalse(self.above(['r1'], ['none']))
        self.assertFalse(names._above({'owner_id': '1', 'roles': 'x'}, ['r1'], ['r2'], '9'))
        self.assertFalse(names._above({'owner_id': '1', 'roles': [None, 5]}, ['r1'], ['r2'], '9'))


class NicknameFreeze(unittest.TestCase):
    ON = {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true', 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}

    def channel(self, **extra):
        return {'discordConnectionKind': 'installation', 'discordBotNickname': {'value': 'Brand Bot', 'observedAt': 1.0}, **extra}

    def test_the_observed_nickname_is_frozen_when_both_switches_are_on(self):
        self.assertEqual(names.frozen_bot_nickname(self.channel(), self.ON), ('Brand Bot',))
        self.assertEqual(names.frozen_bot_nickname(self.channel(discordBotNickname={'value': None, 'observedAt': 1}), self.ON), (None,))

    def test_nothing_is_frozen_otherwise(self):
        cases = {
            'a webhook connection': (self.channel(discordConnectionKind='webhook'), self.ON),
            'a connection of no kind': ({'discordBotNickname': {'value': 'Brand Bot', 'observedAt': 1}}, self.ON),
            'master switch off': (self.channel(), {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'false', 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}),
            'nickname switch off': (self.channel(), {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true', 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'false'}),
            'nickname switch unset': (self.channel(), {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true'}),
            'never observed': ({'discordConnectionKind': 'installation'}, self.ON),
            'record is not an object': (self.channel(discordBotNickname='Brand Bot'), self.ON),
            'record has no value': (self.channel(discordBotNickname={'observedAt': 1}), self.ON),
            'value is not text': (self.channel(discordBotNickname={'value': 5, 'observedAt': 1}), self.ON)}
        for label, (channel, values) in cases.items():
            with self.subTest(label):
                self.assertIsNone(names.frozen_bot_nickname(channel, values))

    def test_the_dispatch_gate_fails_closed(self):
        names.assert_nickname_unchanged({'discordBotNickname': 'A'}, {'botNickname': 'A'})
        names.assert_nickname_unchanged({'discordBotNickname': None}, {'botNickname': None})
        for manifest, evidence in (({'discordBotNickname': 'A'}, {'botNickname': 'B'}), ({'discordBotNickname': 'A'}, {'botNickname': None}),
                                   ({'discordBotNickname': None}, {'botNickname': 'B'}),
                                   ({'discordBotNickname': 'A'}, {}), ({'discordBotNickname': None}, {})):
            with self.subTest(manifest=manifest, evidence=evidence), self.assertRaises(AlphaError) as raised:
                names.assert_nickname_unchanged(manifest, evidence)
            self.assertEqual((raised.exception.status, raised.exception.code), (409, 'discord_bot_nickname_changed'))


if __name__ == '__main__':
    unittest.main()
