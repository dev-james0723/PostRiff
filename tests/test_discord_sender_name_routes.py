"""Authorization, isolation and refusal behaviour of GET/POST .../channels/{connection}/discord-sender-name.

Real route, SenderNames and DiscordConnections code over an in-memory store of several workspaces (see
discord_sender_name_settings_fixture.py). For every refusal the tests assert the same four things: no state change in
any workspace, no Discord request, no audit event, and a response that does not tell "not yours" from "does not exist".
The same properties against the real repository and PostgreSQL are in test_discord_sender_name_postgres.py.
"""
import collections
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import discord_sender_name_fixture as F
from discord_sender_name_settings_fixture import Settings

FLAGS = {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true', 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}
BODY = {'confirmed': True, 'sharedServerConfirmed': True}


class Base(unittest.TestCase):
    def setUp(self):
        for patcher in (patch.dict(os.environ, FLAGS),
                        patch('postriff_phase2.discord.sender_names.provider_ready', return_value=True, create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.w = Settings()
        self.ua, self.ub = self.w.user(1), self.w.user(2)
        self.A, self.B = self.w.workspace(1), self.w.workspace(2)
        self.ta, self.tb = self.w.member(self.A, self.ua, 'owner'), self.w.member(self.B, self.ub, 'owner')
        self.wa = self.w.webhook(self.A, 1, self.ua, name='Alpha Weekly')
        self.wb = self.w.webhook(self.B, 2, self.ub, name='Beta Weekly')
        self.ia = self.w.installation(self.A, 1, self.ua, guild='6400001')
        self.ib = self.w.installation(self.B, 2, self.ub, guild='6400002')

    def assert_untouched(self, before):
        self.assertEqual(self.w.snapshot(), before, 'a refusal changed state, audit or the Discord side')

    def save(self, token, workspace, ids, name, **extra):
        profile = self.w.get(workspace, token, ids.connection)
        return self.w.post(workspace, token, ids.connection,
                           {'name': name, 'fingerprint': profile['fingerprint'], **BODY, **extra})


class CrossTenant(Base):
    OWN = {'A': 'wa ia', 'B': 'wb ib'}

    def test_no_pairing_of_workspace_and_connection_id_reads_or_changes_the_other_tenant(self):
        workspaces = {'A': (self.A, self.ta), 'B': (self.B, self.tb)}
        connections = {'wa': self.wa, 'ia': self.ia, 'wb': self.wb, 'ib': self.ib}
        targets = {'A': self.A, 'B': self.B, 'missing': '90000000-0000-4000-8000-000000000009', 'malformed': 'not-a-workspace'}
        extra_connections = {'unknown': 'discord-webhook-unknown', 'malformed': '../../x'}
        foreign_workspace, foreign_connection, allowed = set(), set(), 0
        for actor, (own, token) in workspaces.items():
            for target_name, target in targets.items():
                for connection_name, ids in [*connections.items(), *[(k, SimpleNamespace(connection=v)) for k, v in extra_connections.items()]]:
                    for operation in ('GET', 'POST'):
                        before = self.w.snapshot()
                        if operation == 'GET':
                            outcome = self.w.attempt(self.w.get, target, token, ids.connection)
                        else:
                            outcome = self.w.attempt(self.w.post, target, token, ids.connection,
                                                     {'name': 'Intruder Weekly', 'fingerprint': 'f' * 64, **BODY})
                        owns = target == own and connection_name in self.OWN[actor].split()
                        label = (actor, target_name, connection_name, operation)
                        if owns:
                            # The one allowed pairing never breaches isolation; here POST needs the real fingerprint.
                            allowed += outcome[0] == 'ok'
                            continue
                        self.assertNotEqual(outcome[0], 'ok', label)
                        self.assert_untouched(before)
                        if target != own:
                            foreign_workspace.add(outcome[:3])
                        else:
                            foreign_connection.add(outcome[:3] if outcome[1] != 'discord_sender_name_required' else outcome[:3])
        # One answer for a foreign, a non-existent and a malformed workspace id, whatever connection id came with it.
        self.assertEqual(foreign_workspace, {(403, 'permission_denied', 'Workspace unavailable.')})
        # Another tenant's connection id is exactly "does not exist" inside your own workspace.
        self.assertEqual({entry for entry in foreign_connection if entry[0] == 404},
                         {(404, 'not_found', 'This Discord connection is unavailable.')})
        self.assertGreaterEqual(allowed, 4, 'the own-tenant GET pairings must work')

    def test_a_tenants_names_and_ids_never_appear_in_the_other_tenants_responses(self):
        a, b = self.w.get(self.A, self.ta, self.wa.connection), self.w.get(self.B, self.tb, self.wb.connection)
        for mine, theirs, ids, other_ids in ((a, b, self.wa, self.wb), (b, a, self.wb, self.wa)):
            text = json.dumps(mine)
            for secret in (other_ids.connection, other_ids.hook, other_ids.credential, other_ids.guild, other_ids.channel,
                           self.B if mine is a else self.A, self.ub if mine is a else self.ua, theirs['savedName']):
                self.assertNotIn(secret, text)
            self.assertNotIn(ids.credential, text, 'the webhook credential must never be returned')
        self.assertEqual((a['savedName'], b['savedName']), ('Alpha Weekly', 'Beta Weekly'))

    def test_saving_in_one_tenant_leaves_the_other_exactly_as_it_was(self):
        before_b = json.dumps(self.w.workspaces[self.B].state, sort_keys=True)
        saved = self.save(self.ta, self.A, self.wa, 'Alpha Daily')
        self.assertEqual((saved['savedName'], saved['saved']), ('Alpha Daily', True))
        self.assertEqual(self.w.channel(self.A, self.wa.connection)['discordSenderName'], 'Alpha Daily')
        self.assertEqual(json.dumps(self.w.workspaces[self.B].state, sort_keys=True), before_b)
        self.assertEqual(self.w.channel(self.B, self.wb.connection)['discordSenderName'], 'Beta Weekly')
        self.assertEqual([e['workspace'] for e in self.w.audit if e['kind'] == 'discord.sender_name_updated'], [self.A])
        # Webhook mode: only reads of the webhook itself reach Discord; no write of any kind.
        self.assertEqual({method for method, _ in self.w.hooks.calls}, {'GET'})
        self.assertEqual(self.w.hooks.posts, [])


class Roles(Base):
    def test_any_connection_manager_edits_a_webhook_name_but_only_the_authorizer_edits_the_bot_nickname(self):
        admin, editor_with_flag = self.w.user(11), self.w.user(12)
        tokens = {'admin': (admin, self.w.member(self.A, admin, 'admin')),
                  'editor_flag': (editor_with_flag, self.w.member(self.A, editor_with_flag, 'editor', can_manage_connections=True))}
        for who, (user, token) in tokens.items():
            # webhook: a Rafii-side setting, frozen into later reviews like any other connection setting
            profile = self.w.get(self.A, token, self.wa.connection)
            self.assertTrue(profile['editable'], who)
            saved = self.w.post(self.A, token, self.wa.connection, {'name': f'By {who} Weekly', 'fingerprint': profile['fingerprint'], **BODY})
            self.assertEqual(saved['savedName'], f'By {who} Weekly')
            self.assertEqual([e['actor'] for e in self.w.audit if e['kind'] == 'discord.sender_name_updated'][-1], user)
            # bot nickname: a shared Discord object, so only the member whose Discord identity installed the bot
            before = self.w.snapshot()
            nick = self.w.get(self.A, token, self.ia.connection)
            self.assertFalse(nick['editable'], who)
            self.assertEqual([r['code'] for r in nick['unavailable']], ['not_authorizing_member'], who)
            self.assertIsNone(nick['observedAt'])      # no Discord read on behalf of a refusal
            outcome = self.w.attempt(self.w.post, self.A, token, self.ia.connection,
                                     {'name': 'Takeover Bot', 'fingerprint': nick['fingerprint'], **BODY})
            self.assertEqual(outcome[:2], (403, 'discord_sender_name_unavailable'), who)
            self.assertEqual(outcome[3], {'reasons': [{'code': 'not_authorizing_member'}]})
            self.assertEqual(self.w.hooks.guild_config[self.ia.guild].patches, [])
            self.assertEqual(self.w.snapshot(), before)

    def test_roles_without_connection_management_are_refused_before_anything_is_read(self):
        for role in ('viewer', 'editor', 'approver'):
            token = self.w.member(self.A, self.w.user(20 + len(role)), role)
            for operation in ('GET', 'POST'):
                with self.subTest(role=role, operation=operation):
                    before = self.w.snapshot()
                    outcome = (self.w.attempt(self.w.get, self.A, token, self.wa.connection) if operation == 'GET' else
                               self.w.attempt(self.w.post, self.A, token, self.wa.connection,
                                              {'name': 'Nope Weekly', 'fingerprint': 'f' * 64, **BODY}))
                    self.assertEqual(outcome[:2], (403, 'permission_denied'))
                    self.assert_untouched(before)

    def test_removed_and_deleted_members_and_unknown_sessions_get_the_foreign_workspace_answer(self):
        removed, deleted = self.w.user(31), self.w.user(32)
        removed_token, deleted_token = self.w.member(self.A, removed, 'admin'), self.w.member(self.A, deleted, 'owner')
        self.w.workspaces[self.A].members[removed].status = 'removed'
        self.w.workspaces[self.A].members[deleted].deleted = True
        for token in (removed_token, deleted_token):
            for operation in ('GET', 'POST'):
                before = self.w.snapshot()
                outcome = (self.w.attempt(self.w.get, self.A, token, self.wa.connection) if operation == 'GET' else
                           self.w.attempt(self.w.post, self.A, token, self.wa.connection,
                                          {'name': 'Gone Weekly', 'fingerprint': 'f' * 64, **BODY}))
                self.assertEqual(outcome[:3], (403, 'permission_denied', 'Workspace unavailable.'))
                self.assert_untouched(before)
        outcome = self.w.attempt(self.w.get, self.A, 'synthetic-unknown-session', self.wa.connection)
        self.assertEqual(outcome[:2], (401, 'unauthenticated'))

    def test_blocked_and_deleting_accounts_cannot_use_either_route(self):
        for flag, status in (('accountBlock', 403), ('accountDeletion', 409)):
            with self.subTest(flag=flag):
                self.w.workspaces[self.A].state[flag] = {'at': 1}
                before = self.w.snapshot()
                for outcome in (self.w.attempt(self.w.get, self.A, self.ta, self.wa.connection),
                                self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                                               {'name': 'Frozen Weekly', 'fingerprint': 'f' * 64, **BODY})):
                    self.assertEqual(outcome[0], status)
                self.assert_untouched(before)
                del self.w.workspaces[self.A].state[flag]

    def test_when_the_authorizer_loses_workspace_access_the_connection_must_be_reconnected(self):
        admin = self.w.user(41)
        token = self.w.member(self.A, admin, 'admin')
        self.w.workspaces[self.A].members[self.ua].status = 'removed'
        before = self.w.snapshot()
        outcome = self.w.attempt(self.w.get, self.A, token, self.wa.connection)
        self.assertEqual(outcome[:2], (409, 'discord_connection_required'))
        self.assert_untouched(before)

    def test_a_revoked_or_missing_credential_is_unavailable_without_a_discord_request(self):
        self.w.revoke(self.A, self.wa.connection)
        before = self.w.snapshot()
        for outcome in (self.w.attempt(self.w.get, self.A, self.ta, self.wa.connection),
                        self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                                       {'name': 'Revoked Weekly', 'fingerprint': 'f' * 64, **BODY})):
            self.assertEqual(outcome[:3], (404, 'not_found', 'This Discord connection is unavailable.'))
        self.assert_untouched(before)


class Freshness(Base):
    def test_stale_session_can_read_but_cannot_write_and_nothing_is_requested(self):
        self.w.stale.add(self.ta)
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        self.assertIn('session_reverification_required', [r['code'] for r in profile['unavailable']])
        self.assertFalse(profile['editable'])
        before = self.w.snapshot()
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                                 {'name': 'Stale Weekly', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(outcome[:2], (403, 'step_up_required'))
        self.assert_untouched(before)
        self.w.stale.discard(self.ta)
        self.assertEqual(self.save(self.ta, self.A, self.wa, 'Fresh Weekly')['savedName'], 'Fresh Weekly')

    def test_an_old_fingerprint_cannot_be_replayed(self):
        first = self.w.get(self.A, self.ta, self.wa.connection)
        body = {'name': 'First Weekly', 'fingerprint': first['fingerprint'], **BODY}
        self.assertEqual(self.w.post(self.A, self.ta, self.wa.connection, body)['savedName'], 'First Weekly')
        after_first = self.w.snapshot()
        for replay in (body, {**body, 'name': 'Replayed Weekly'}):
            outcome = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection, replay)
            self.assertEqual(outcome[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.w.snapshot(), after_first)
        self.assertEqual(self.w.channel(self.A, self.wa.connection)['discordSenderName'], 'First Weekly')

    def test_two_tabs_of_the_same_member_cannot_both_save(self):
        tab_one = self.w.get(self.A, self.ta, self.wa.connection)
        tab_two = self.w.get(self.A, self.ta, self.wa.connection)
        self.assertEqual(tab_one['fingerprint'], tab_two['fingerprint'])
        self.w.post(self.A, self.ta, self.wa.connection, {'name': 'Tab One', 'fingerprint': tab_one['fingerprint'], **BODY})
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                                 {'name': 'Tab Two', 'fingerprint': tab_two['fingerprint'], **BODY})
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.w.channel(self.A, self.wa.connection)['discordSenderName'], 'Tab One')

    def test_a_setting_changed_between_read_and_save_makes_the_fingerprint_stale(self):
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        self.w.channel(self.A, self.wa.connection)['discordSenderRevision'] = 'changed-elsewhere'
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                                 {'name': 'Late Weekly', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_required'))

    def test_the_fingerprint_does_not_depend_on_the_webhooks_own_credential(self):
        before = self.w.get(self.A, self.ta, self.wa.connection)['fingerprint']
        envelope = self.w.credentials[(self.A, self.wa.connection)]['envelope']
        envelope['secret'] = 'x' * 40            # a client-visible hash must not be a function of the webhook's token
        ciphertext, key_id = self.w.s.oauth.vault.encrypt(json.dumps(envelope))
        row = list(self.w.credentials[(self.A, self.wa.connection)]['row'])
        row[0], row[1] = ciphertext, key_id
        self.w.credentials[(self.A, self.wa.connection)]['row'] = tuple(row)
        # the ciphertext column is part of custody, the token inside it is not part of the hash input
        self.w.hooks.by_hook[self.wa.hook].hook_credential = 'x' * 40
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        self.assertNotEqual(profile['fingerprint'], before)   # the stored ciphertext changed, as custody changed
        self.assertNotIn('x' * 40, json.dumps(profile))


class Bodies(Base):
    def test_malformed_requests_are_refused_before_any_work(self):
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        good = {'name': 'Body Weekly', 'fingerprint': profile['fingerprint'], **BODY}
        for label, body in [('not a dict', ['x']), ('none', None), ('extra key', {**good, 'avatarUrl': 'https://x.example/a.png'}),
                            ('extra key two', {**good, 'username': 'Other'}), ('unconfirmed', {**good, 'confirmed': False}),
                            ('truthy string', {**good, 'confirmed': 'true'}), ('number', {**good, 'confirmed': 1}),
                            ('no fingerprint', {k: v for k, v in good.items() if k != 'fingerprint'}),
                            ('fingerprint type', {**good, 'fingerprint': 12345})]:
            with self.subTest(label):
                before = self.w.snapshot()
                outcome = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection, body)
                self.assertEqual(outcome[:2], (400, 'discord_sender_name_unconfirmed'))
                self.assert_untouched(before)

    def test_invalid_names_never_cause_a_discord_request_or_a_write(self):
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        calls = len(self.w.hooks.calls)
        for bad, reason in [('', 'empty'), ('a' * 81, 'too_long'), ('Discord Weekly', 'reserved_word'), ('@everyone', 'forbidden_character'),
                            ('a  b', 'spacing'), (' lead', 'surrounding_space'), ('x\U0000202ey', 'control_or_format'), (7, 'not_text')]:
            with self.subTest(bad=repr(bad)):
                self.w.now += 601        # a refused attempt still counts toward the write throttle: one window each
                outcome = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                                         {'name': bad, 'fingerprint': profile['fingerprint'], **BODY})
                self.assertEqual(outcome[:2], (400, 'discord_sender_name_invalid'))
                self.assertEqual(outcome[3], {'reason': reason, 'maxLength': 80})
        self.assertEqual(len(self.w.hooks.calls), calls)
        self.assertEqual(self.w.channel(self.A, self.wa.connection)['discordSenderName'], 'Alpha Weekly')

    def test_a_bot_nickname_needs_the_shared_server_confirmation(self):
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                 {'name': 'Nick Weekly', 'fingerprint': profile['fingerprint'], 'confirmed': True})
        self.assertEqual(outcome[:2], (400, 'discord_sender_name_shared_unconfirmed'))
        self.assertEqual(self.w.hooks.guild_config[self.ia.guild].patches, [])

    def test_bot_nickname_limit_is_32_not_80(self):
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                 {'name': 'n' * 33, 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual((outcome[1], outcome[3]), ('discord_sender_name_invalid', {'reason': 'too_long', 'maxLength': 32}))


class Switches(Base):
    def test_master_switch_off_answers_without_discord_and_refuses_every_write(self):
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'false'}):
            for ids in (self.wa, self.ia):
                calls, before = len(self.w.hooks.calls), self.w.snapshot()
                profile = self.w.get(self.A, self.ta, ids.connection)
                self.assertEqual([r['code'] for r in profile['unavailable']], ['sender_names_disabled'])
                self.assertEqual((profile['editable'], profile['feature']['senderNames']), (False, False))
                self.assertIsNone(profile['observedAt'])
                outcome = self.w.attempt(self.w.post, self.A, self.ta, ids.connection,
                                         {'name': 'Off Weekly', 'fingerprint': profile['fingerprint'], **BODY})
                self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
                self.assertEqual(outcome[3], {'reasons': [{'code': 'sender_names_disabled'}]})
                self.assertEqual(len(self.w.hooks.calls), calls)
                self.assertEqual(self.w.snapshot(), before)

    def test_nickname_switch_off_isolates_only_the_bot_path(self):
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'false'}):
            calls = len(self.w.hooks.calls)
            profile = self.w.get(self.A, self.ta, self.ia.connection)
            self.assertEqual([r['code'] for r in profile['unavailable']], ['bot_nickname_disabled'])
            self.assertEqual(len(self.w.hooks.calls), calls)
            outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                     {'name': 'Nick Weekly', 'fingerprint': profile['fingerprint'], **BODY})
            self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
            self.assertEqual(self.w.hooks.guild_config[self.ia.guild].patches, [])
            # The webhook path is unaffected.
            self.assertEqual(self.save(self.ta, self.A, self.wa, 'Still Works')['savedName'], 'Still Works')

    def test_default_nickname_switch_is_off_without_the_environment_variable(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED', None)
            profile = self.w.get(self.A, self.ta, self.ia.connection)
            self.assertEqual([r['code'] for r in profile['unavailable']], ['bot_nickname_disabled'])

    def test_reads_are_throttled_per_connection_and_a_throttled_read_makes_no_discord_request(self):
        for _ in range(12):
            self.w.get(self.A, self.ta, self.wa.connection)
        calls = len(self.w.hooks.calls)
        outcome = self.w.attempt(self.w.get, self.A, self.ta, self.wa.connection)
        self.assertEqual(outcome[:2], (429, 'rate_limited'))
        self.assertEqual(outcome[3], {'retryAfterSeconds': 60})
        self.assertEqual(len(self.w.hooks.calls), calls)
        # Another connection of the same workspace and another workspace are not affected by it.
        self.w.get(self.A, self.ta, self.ia.connection)
        self.w.get(self.B, self.tb, self.wb.connection)
        # The window passes.
        self.w.now += 601
        self.w.get(self.A, self.ta, self.wa.connection)

    def test_writes_are_throttled_after_six_per_connection(self):
        outcomes = []
        for index in range(7):
            outcomes.append(self.w.attempt(self.save, self.ta, self.A, self.wa, f'Name {index} Weekly')[0:2])
        self.assertEqual([o[0] for o in outcomes[:6]], ['ok'] * 6)
        self.assertEqual(outcomes[6], (429, 'rate_limited'))


class GetShape(Base):
    def test_webhook_profile_matches_the_published_contract(self):
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        self.assertEqual(profile['contractVersion'], 2)
        self.assertEqual((profile['senderKind'], profile['scope'], profile['state'], profile['maxLength']), ('webhook', 'connection', 'verified', 80))
        self.assertEqual((profile['savedName'], profile['effectiveName'], profile['nameSource'], profile['name']),
                         ('Alpha Weekly', 'Alpha Weekly', 'saved_override', 'Alpha Weekly'))
        self.assertEqual((profile['observedName'], profile['externalChange']), (F.DEFAULT_HOOK_NAME, False))
        self.assertIsInstance(profile['observedAt'], float)
        self.assertEqual((profile['editable'], profile['unavailable']), (True, []))
        self.assertEqual(profile['feature'], {'senderNames': True, 'botNickname': True})
        self.assertRegex(profile['fingerprint'], r'^[0-9a-f]{64}$')
        self.assertEqual(profile['preview'], {'currentDisplayName': 'Alpha Weekly', 'badge': 'APP', 'audience': 'this_connection',
                                              'queuedPostsKeepApprovedName': True, 'queuedBotPostsHoldIfNicknameChanges': False})
        self.assertEqual(profile['rules']['forbiddenCharacters'], ['@', '#', ':', '```', '<', '>'])
        self.assertEqual(set(profile), {'contractVersion', 'connectionId', 'senderKind', 'scope', 'guildId', 'state', 'maxLength',
                                        'rules', 'name', 'effectiveName', 'nameSource', 'savedName', 'observedName', 'observedAt',
                                        'externalChange', 'fingerprint', 'feature', 'editable', 'unavailable', 'preview'})

    def test_a_webhook_without_a_saved_name_shows_its_own_name_as_the_default(self):
        ids = self.w.webhook(self.A, 3, self.ua)
        profile = self.w.get(self.A, self.ta, ids.connection)
        self.assertEqual((profile['savedName'], profile['nameSource'], profile['effectiveName']), (None, 'webhook_default', F.DEFAULT_HOOK_NAME))

    def test_bot_profile_reports_the_observed_nickname_and_never_claims_ownership(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual((profile['senderKind'], profile['scope'], profile['maxLength']), ('bot', 'server', 32))
        self.assertEqual((profile['nameSource'], profile['effectiveName'], profile['externalChange']), ('bot_username', 'Rafii', False))
        self.assertTrue(profile['editable'])
        self.assertEqual(profile['preview']['audience'], 'everyone_in_server')
        saved = self.w.post(self.A, self.ta, self.ia.connection, {'name': 'Alpha Bot', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual((saved['savedName'], saved['nameSource'], saved['effectiveName']), ('Alpha Bot', 'observed_nickname', 'Alpha Bot'))
        self.assertEqual(config.patches, [{'nick': 'Alpha Bot'}])
        # A server admin renames the bot natively: Rafii shows what Discord reports, flags the drift, keeps no claim.
        config.nick = 'Renamed By A Server Admin'
        drifted = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual((drifted['effectiveName'], drifted['savedName'], drifted['externalChange']),
                         ('Renamed By A Server Admin', 'Alpha Bot', True))
        self.assertNotEqual(drifted['fingerprint'], saved['fingerprint'])


class BotPermissions(Base):
    def reasons(self):
        return [r['code'] for r in self.w.get(self.A, self.ta, self.ia.connection)['unavailable']]

    def test_person_needs_manage_nicknames_administrator_or_ownership(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        config.user_permissions = 1 << 5                      # Manage Server alone is not enough
        self.assertEqual(self.reasons(), ['person_missing_manage_nicknames'])
        config.user_permissions = 1 << 3                      # Administrator (but below the bot's role)
        config.user_position = 1
        self.assertEqual(self.reasons(), ['person_role_below_bot'])
        config.user_position = 5
        self.assertEqual(self.reasons(), [])
        config.user_permissions, config.user_position, config.owner_id = 1 << 5, 0, USER
        self.assertEqual(self.reasons(), [])                  # the owner needs neither the permission nor a role

    def test_role_hierarchy_applies_like_discords_own_rule(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        for person, bot, expected in [(5, 2, []), (3, 3, ['person_role_below_bot']), (2, 5, ['person_role_below_bot']), (1, 0, [])]:
            config.user_position, config.bot_position = person, bot
            self.assertEqual(self.reasons(), expected, (person, bot))

    def test_bot_needs_change_nickname_or_administrator(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        config.bot_permissions = 1 << 5
        self.assertEqual(self.reasons(), ['bot_missing_change_nickname'])
        outcome = self.w.attempt(self.save, self.ta, self.A, self.ia, 'Denied Bot')
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
        self.assertEqual(config.patches, [])
        config.bot_permissions = 1 << 3
        self.assertEqual(self.reasons(), [])

    def test_every_person_bound_reason_is_a_403_and_reaches_discord_with_reads_only(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        config.user_permissions = 1 << 5
        outcome = self.w.attempt(self.save, self.ta, self.A, self.ia, 'Denied Person')
        self.assertEqual(outcome[:2], (403, 'discord_sender_name_unavailable'))
        self.assertEqual({method for method, _ in self.w.hooks.calls}, {'GET'})
        self.assertEqual(config.patches, [])


USER = F.USER


class SharedServer(Base):
    """Two Rafii workspaces holding an installation of the same Discord server."""
    def share(self):
        self.ib2 = self.w.installation(self.B, 7, self.ub, guild=self.ia.guild)
        return self.ib2

    def reasons(self, workspace, token, ids):
        return [r['code'] for r in self.w.get(workspace, token, ids.connection)['unavailable']]

    def test_neither_workspace_may_write_while_both_hold_the_server_and_nothing_names_the_other(self):
        self.assertEqual(self.reasons(self.A, self.ta, self.ia), [])
        ib2 = self.share()
        config = self.w.hooks.guild_config[self.ia.guild]
        for workspace, token, ids in ((self.A, self.ta, self.ia), (self.B, self.tb, ib2)):
            self.assertEqual(self.reasons(workspace, token, ids), ['nickname_authority_other_workspace'])
            outcome = self.w.attempt(self.w.post, workspace, token, ids.connection,
                                     {'name': 'Contested Bot', 'fingerprint': self.w.get(workspace, token, ids.connection)['fingerprint'], **BODY})
            self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
            self.assertEqual(outcome[3], {'reasons': [{'code': 'nickname_authority_other_workspace'}]})
            blob = json.dumps(self.w.get(workspace, token, ids.connection)) + json.dumps(outcome[2:])
            for forbidden in (self.A if workspace == self.B else self.B, self.ua if workspace == self.B else self.ub,
                              self.ia.connection if workspace == self.B else ib2.connection):
                self.assertNotIn(forbidden, blob)
        self.assertEqual(config.patches, [])

    def test_authority_returns_when_the_other_installation_is_revoked_and_is_lost_again_when_it_reconnects(self):
        ib2 = self.share()
        self.assertEqual(self.reasons(self.A, self.ta, self.ia), ['nickname_authority_other_workspace'])
        self.w.revoke(self.B, ib2.connection)
        self.assertEqual(self.reasons(self.A, self.ta, self.ia), [])
        self.assertEqual(self.save(self.ta, self.A, self.ia, 'Alpha Bot')['savedName'], 'Alpha Bot')
        # B reconnecting (its revoked row comes back) must not give B a write, and must stop A's.
        self.w.credentials[(self.B, ib2.connection)]['revoked'] = False
        self.w.channel(self.B, ib2.connection)['revoked'] = False
        self.assertEqual(self.reasons(self.B, self.tb, ib2), ['nickname_authority_other_workspace'])
        self.assertEqual(self.reasons(self.A, self.ta, self.ia), ['nickname_authority_other_workspace'])
        self.assertEqual(self.w.hooks.guild_config[self.ia.guild].patches, [{'nick': 'Alpha Bot'}])

    def test_a_second_installation_appearing_before_the_final_guard_stops_the_write_and_frees_the_claim(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        original, calls = self.w.s.nickname_contenders, []

        def spy(cur, workspace, connection, guild):
            result = original(cur, workspace, connection, guild)
            calls.append(result)
            if len(calls) == 1:
                self.share()      # B's installation commits right after A's preflight, before A's final guard
            return result
        self.w.s.nickname_contenders = spy
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                 {'name': 'Racing Bot', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(calls[0], 0)
        self.assertEqual(config.patches, [], 'the final guard must stop the write')
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
        self.assertEqual(outcome[3], {'reasons': [{'code': 'nickname_authority_other_workspace'}]})
        # Known unsent: no pending claim is left behind, and no admission is left unresolved.
        self.assertNotIn('discordSenderEdit', self.w.channel(self.A, self.ia.connection))

    def test_the_other_workspace_arriving_after_the_guard_cannot_itself_write(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        arrived = {}
        self.w.hooks.before_patch = lambda: arrived.setdefault('ib2', self.share())
        saved = self.w.post(self.A, self.ta, self.ia.connection, {'name': 'First Bot', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(saved['savedName'], 'First Bot')
        self.assertEqual(config.patches, [{'nick': 'First Bot'}])
        ib2 = arrived['ib2']
        outcome = self.w.attempt(self.w.post, self.B, self.tb, ib2.connection,
                                 {'name': 'Second Bot', 'fingerprint': self.w.get(self.B, self.tb, ib2.connection)['fingerprint'], **BODY})
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
        self.assertEqual(config.patches, [{'nick': 'First Bot'}])

    def test_other_servers_are_unaffected(self):
        self.share()
        self.assertEqual(self.reasons(self.B, self.tb, self.ib), [])       # B's own, different server
        self.assertEqual(self.save(self.tb, self.B, self.ib, 'Beta Bot')['savedName'], 'Beta Bot')


class AmbiguousWrites(Base):
    def test_a_failed_write_leaves_an_exclusive_claim_until_a_later_read_reconciles_it(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        profile = self.w.get(self.A, self.ta, self.ia.connection)

        def timeout():
            raise TimeoutError('synthetic ambiguous write')
        self.w.hooks.before_patch = timeout
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                 {'name': 'Unknown Outcome', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(outcome[:2], (409, 'discord_sender_edit_pending'))
        self.assertEqual(outcome[3], {'retryAfterSeconds': 120})
        self.assertIn('discordSenderEdit', self.w.channel(self.A, self.ia.connection))
        pending = self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)
        self.assertEqual(pending[:2], (409, 'discord_sender_edit_pending'))
        self.assertTrue(0 < pending[3]['retryAfterSeconds'] <= 120)
        # The claim is part of the Rafii-side state, so the form from before the failed write is simply stale.
        self.assertEqual(self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                        {'name': 'Second Try', 'fingerprint': profile['fingerprint'], **BODY})[1],
                         'discord_sender_name_required')
        self.w.now += 121
        recovered = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertNotIn('discordSenderEdit', self.w.channel(self.A, self.ia.connection))
        self.assertEqual(config.patches, [])
        self.assertTrue(recovered['editable'])

    def test_a_discord_refusal_is_a_distinct_refused_write_not_a_stale_setting(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        config.reject_patch = True
        outcome = self.w.attempt(self.save, self.ta, self.A, self.ia, 'Refused Bot')
        self.assertEqual(outcome[:2], (409, 'discord_sender_write_refused'))
        self.assertEqual(self.w.channel(self.A, self.ia.connection).get('discordSenderName'), None)
        self.assertNotIn('discordSenderEdit', self.w.channel(self.A, self.ia.connection))


class Fanout(Base):
    """What one call costs: workspace transactions (each is one bearer verification and two database connections in
    production) and Discord requests. These exact numbers are quoted in docs/sender-name/CAPACITY-NOTES.md."""
    def measure(self, call):
        counts = {'local': 0, 'bearer': 0}
        inner = self.w.s.local

        def local(workspace, token):
            counts['local'] += 1
            counts['bearer'] += token is not None
            return inner(workspace, token)
        self.w.s.local = local
        before = len(self.w.hooks.calls)
        try:
            call()
        finally:
            self.w.s.local = inner
        made = self.w.hooks.calls[before:]
        return counts['bearer'], collections.Counter(method for method, _ in made)

    def test_exact_cost_of_each_route(self):
        w = self.w
        webhook_get = self.measure(lambda: w.get(self.A, self.ta, self.wa.connection))
        profile = w.get(self.A, self.ta, self.wa.connection)
        webhook_post = self.measure(lambda: w.post(self.A, self.ta, self.wa.connection,
                                                   {'name': 'Cost Weekly', 'fingerprint': profile['fingerprint'], **BODY}))
        bot_get = self.measure(lambda: w.get(self.A, self.ta, self.ia.connection))
        profile = w.get(self.A, self.ta, self.ia.connection)
        bot_post = self.measure(lambda: w.post(self.A, self.ta, self.ia.connection,
                                               {'name': 'Cost Bot', 'fingerprint': profile['fingerprint'], **BODY}))
        refused = self.measure(lambda: w.attempt(w.post, self.A, self.ta, self.wa.connection,
                                                 {'name': 'Discord X', 'fingerprint': 'f' * 64, **BODY}))
        # (workspace transactions with a bearer check, Discord requests by method)
        self.assertEqual(webhook_get, (2, collections.Counter({'GET': 1})))
        self.assertEqual(webhook_post, (3, collections.Counter({'GET': 1})))
        self.assertEqual(bot_get, (2, collections.Counter({'GET': 5})))      # bot identity x2 (cold), server, two members
        self.assertEqual(bot_post, (7, collections.Counter({'GET': 6, 'PATCH': 1})))      # 5 reads (cold identity) + 1 read-back
        self.assertEqual(refused, (1, collections.Counter()))                # a refused name: one transaction, no Discord request


class OverHttp(Base):
    def call(self, method, workspace, connection, token, body=None, guarded=True, gate=None):
        from postriff_phase2.hosted_app import HostedApplication
        app = HostedApplication(service=SimpleNamespace(oauth=SimpleNamespace(discord_connections=self.w.s)))
        raw = json.dumps(body if body is not None else {}).encode()
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': f'/api/workspaces/{workspace}/channels/{connection}/discord-sender-name',
                   'HTTP_HOST': 'rafii.example.invalid', 'wsgi.url_scheme': 'https', 'HTTP_AUTHORIZATION': 'Bearer ' + token,
                   'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw)}
        if guarded:
            environ['HTTP_X_POSTRIFF_REQUEST'] = 'founder-alpha'
        statuses = []
        with patch('postriff_phase2.security_gate.require', side_effect=gate):
            payload = b''.join(app._handle(environ, lambda status, _: statuses.append(int(status.split()[0]))))
        return statuses[0], json.loads(payload)

    def test_get_and_post_over_the_real_router_with_machine_readable_bodies(self):
        status, profile = self.call('GET', self.A, self.wa.connection, self.ta)
        self.assertEqual((status, profile['editable'], profile['contractVersion']), (200, True, 2))
        status, saved = self.call('POST', self.A, self.wa.connection, self.ta,
                                  {'name': 'Http Weekly', 'fingerprint': profile['fingerprint'], 'confirmed': True})
        self.assertEqual((status, saved['savedName'], saved['saved']), (200, 'Http Weekly', True))
        status, stale = self.call('POST', self.A, self.wa.connection, self.ta,
                                  {'name': 'Again Weekly', 'fingerprint': profile['fingerprint'], 'confirmed': True})
        self.assertEqual((status, stale['code']), (409, 'discord_sender_name_required'))
        status, invalid = self.call('POST', self.A, self.wa.connection, self.ta,
                                    {'name': '@here', 'fingerprint': saved['fingerprint'], 'confirmed': True})
        self.assertEqual((status, invalid['code'], invalid['reason'], invalid['maxLength']),
                         (400, 'discord_sender_name_invalid', 'forbidden_character', 80))
        status, foreign = self.call('GET', self.B, self.wb.connection, self.ta)
        self.assertEqual((status, foreign['code'], foreign['error']), (403, 'permission_denied', 'Workspace unavailable.'))
        status, unavailable = self.call('GET', self.A, self.wb.connection, self.ta)
        self.assertEqual((status, unavailable['code']), (404, 'not_found'))

    def test_the_post_needs_the_application_guard_and_the_sensitive_connections_gate(self):
        status, profile = self.call('GET', self.A, self.wa.connection, self.ta)
        before = self.w.snapshot()
        status, body = self.call('POST', self.A, self.wa.connection, self.ta,
                                 {'name': 'Unguarded Weekly', 'fingerprint': profile['fingerprint'], 'confirmed': True}, guarded=False)
        self.assertEqual(status, 403)
        from postriff_phase2.security_gate import SecurityError
        seen = []

        def gate(service, token, capability):
            seen.append(capability)
            if capability == 'connections':
                raise SecurityError('Confirm it is you to continue.', 403, code='security_step_up_required',
                                    public_fields={'nextAction': 'complete_mfa'})
        status, body = self.call('POST', self.A, self.wa.connection, self.ta,
                                 {'name': 'Gated Weekly', 'fingerprint': profile['fingerprint'], 'confirmed': True}, gate=gate)
        self.assertEqual((status, body['code'], body['nextAction']), (403, 'security_step_up_required', 'complete_mfa'))
        self.assertEqual(seen, ['connections'])
        self.assertEqual(self.w.snapshot(), before)
        # The read is not a sensitive-connections action.
        seen.clear()
        status, _ = self.call('GET', self.A, self.wa.connection, self.ta, gate=gate)
        self.assertEqual((status, seen), (200, ['private_data']))

    def test_over_the_router_a_non_authorizing_member_and_a_switched_off_server_get_machine_codes(self):
        admin = self.w.user(51)
        token = self.w.member(self.A, admin, 'admin')
        status, body = self.call('GET', self.A, self.ia.connection, token)
        self.assertEqual((status, [r['code'] for r in body['unavailable']]), (200, ['not_authorizing_member']))
        status, body = self.call('POST', self.A, self.ia.connection, token, {'name': 'No Bot', 'fingerprint': 'f' * 64, 'confirmed': True,
                                                                          'sharedServerConfirmed': True})
        self.assertEqual((status, body['code'], body['reasons']), (403, 'discord_sender_name_unavailable', [{'code': 'not_authorizing_member'}]))
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'false'}):
            status, body = self.call('GET', self.A, self.wa.connection, self.ta)
            self.assertEqual((status, [r['code'] for r in body['unavailable']]), (200, ['sender_names_disabled']))


if __name__ == '__main__':
    unittest.main()
