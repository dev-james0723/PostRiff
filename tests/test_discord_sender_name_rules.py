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
                           ('webhook', 'Traffic Updates'), ('webhook', 'Safari News'), ('webhook', 'Star ★ Team')]:
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
        ('Discord', 'webhook', 'reserved_word'), ('DISCORD Support', 'bot', 'reserved_word'),
        ('\U0000ff44\U0000ff49\U0000ff53\U0000ff43\U0000ff4f\U0000ff52\U0000ff44', 'webhook', 'reserved_word'), ('D\U000000efsc\U000000f6rd', 'webhook', 'reserved_word'),
        ('d\U00000456scord', 'webhook', 'reserved_word'), ('d\U00000456s\U00000441\U0000043erd clone', 'webhook', 'reserved_word'),
        ('D1scord', 'webhook', 'reserved_word'), ('d i s c o r d', 'webhook', 'reserved_word'),
        ('dis_cord', 'webhook', 'reserved_word'), ('Clyde', 'webhook', 'reserved_word'),
        ('Cl-yde', 'bot', 'reserved_word'), ('C1yde', 'webhook', 'reserved_word'),
        ('Everyone', 'webhook', 'reserved_word'), ('HERE', 'bot', 'reserved_word'), ('he re', 'webhook', 'reserved_word'),
        ('Rafii Support', 'webhook', 'reserved_word'), ('rafii', 'bot', 'reserved_word'), ('PostRiff Official', 'webhook', 'reserved_word'),
        ('P0stR1ff', 'webhook', 'reserved_word'),
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
    def test_master_switch_default_depends_on_the_environment_and_only_exact_true_enables(self):
        cases = [({}, True), ({'VERCEL_ENV': 'development'}, True), ({'VERCEL_ENV': 'production'}, False),
                 ({'POSTRIFF_ENVIRONMENT': ' Production '}, False), ({'VERCEL_ENV': 'preview'}, True),
                 ({names.ENV_SENDER_NAMES: 'true'}, True), ({names.ENV_SENDER_NAMES: 'true', 'VERCEL_ENV': 'production'}, True),
                 ({names.ENV_SENDER_NAMES: 'TRUE'}, False), ({names.ENV_SENDER_NAMES: '1'}, False),
                 ({names.ENV_SENDER_NAMES: 'yes'}, False), ({names.ENV_SENDER_NAMES: ''}, False),
                 ({names.ENV_SENDER_NAMES: 'false'}, False), ({names.ENV_SENDER_NAMES: ' true'}, False),
                 ({names.ENV_SENDER_NAMES: 'false', 'VERCEL_ENV': 'preview'}, False)]
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertIs(names.names_enabled(values), expected)

    def test_nickname_switch_is_off_everywhere_unless_exactly_true(self):
        for values, expected in [({}, False), ({'VERCEL_ENV': 'development'}, False), ({'VERCEL_ENV': 'production'}, False),
                                 ({names.ENV_BOT_NICKNAME: 'true'}, True), ({names.ENV_BOT_NICKNAME: 'True'}, False),
                                 ({names.ENV_BOT_NICKNAME: '1'}, False), ({names.ENV_BOT_NICKNAME: ''}, False),
                                 ({names.ENV_BOT_NICKNAME: 'true', 'VERCEL_ENV': 'production'}, True)]:
            with self.subTest(values=values):
                self.assertIs(names.nickname_enabled(values), expected)

    def test_switches_are_read_at_call_time_from_the_process_environment(self):
        with patch.dict(os.environ, {names.ENV_SENDER_NAMES: 'true'}):
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
        on, off = {names.ENV_SENDER_NAMES: 'true'}, {names.ENV_SENDER_NAMES: 'false'}
        self.assertEqual(names.frozen_webhook_name(self.channel(discordSenderName='Acme Weekly'), on), 'Acme Weekly')
        self.assertIsNone(names.frozen_webhook_name(self.channel(discordSenderName='Acme Weekly'), off))
        self.assertIsNone(names.frozen_webhook_name(self.channel(), on))
        self.assertIsNone(names.frozen_webhook_name({'discordConnectionKind': 'installation', 'discordSenderName': 'Acme Weekly'}, on))
        for bad in ('', 'Discord', None, 5):
            with self.subTest(bad=bad), self.assertRaises(AlphaError):
                names.frozen_webhook_name(self.channel(discordSenderName=bad), on)
        # While off, a bad stored value cannot block a review: nothing would be sent under it.
        self.assertIsNone(names.frozen_webhook_name(self.channel(discordSenderName='Discord'), off))

    def test_dispatch_gate_holds_only_a_named_webhook_manifest_while_off(self):
        off = {names.ENV_SENDER_NAMES: 'false'}
        with self.assertRaises(AlphaError) as raised:
            names.assert_sendable({'senderKind': 'webhook', 'discordSenderName': 'Acme Weekly'}, off)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, 'discord_sender_names_disabled'))
        for manifest in ({'senderKind': 'webhook'}, {'senderKind': 'bot'}, {}):
            names.assert_sendable(manifest, off)
        names.assert_sendable({'senderKind': 'webhook', 'discordSenderName': 'Acme Weekly'}, {names.ENV_SENDER_NAMES: 'true'})


if __name__ == '__main__':
    unittest.main()
