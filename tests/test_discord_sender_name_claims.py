"""The edit claim of a bot-nickname write, the rate admission it points at, and what survives a reconnect.

Reviewer findings SNR-5 (a claim must not outlive a write that provably never left, or that Discord refused) and SNR-6 (an
uncertain admission must stay resolvable: reconnect, bot-token rotation, ambiguous transport). The coordinator is the scriptable
stand-in in discord_sender_name_fixture.py; the real coordinator on PostgreSQL is driven in test_discord_sender_name_postgres.py.
"""
import json
import os
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import discord_sender_name_fixture as F
from discord_sender_name_settings_fixture import Settings
from postriff_phase2.discord import sender_names as names
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, RateDelayed
from postriff_phase2.hosted import HostedPhase2Commands
from test_discord_installation_reverification import reverify_fixture
from test_discord_publish_authorization import BOT, GUILD, NOW, WORKSPACE
from test_discord_sender_name_routes import BODY, Base as RouteBase


class Claims(RouteBase):
    def setUp(self):
        super().setUp()
        self.limiter = self.w.use_limiter()
        self.config = self.w.hooks.guild_config[self.ia.guild]
        self.profile = self.w.get(self.A, self.ta, self.ia.connection)

    def post(self, name='Claim Bot'):
        return self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                              {'name': name, 'fingerprint': self.profile['fingerprint'], **BODY})

    def claim(self):
        return self.w.channel(self.A, self.ia.connection).get('discordSenderEdit')

    def kinds(self):
        return [event['kind'] for event in self.w.audit]

    def share(self):
        return self.w.installation(self.B, 7, self.ub, guild=self.ia.guild)


class UnsentWrites(Claims):
    """Nothing reached Discord: the person must not be made to wait for a claim that protects nothing."""

    def assert_saves_at_once(self):
        saved = self.w.post(self.A, self.ta, self.ia.connection,
                            {'name': 'Claim Bot', 'fingerprint': self.profile['fingerprint'], **BODY})
        self.assertEqual(saved['savedName'], 'Claim Bot')
        self.assertEqual(self.config.patches, [{'nick': 'Claim Bot'}])

    def test_a_coordinator_delay_before_the_admission_releases_the_claim_and_says_nothing_was_sent(self):
        self.limiter.reserve_error = RateDelayed(17.2)
        outcome = self.post()
        self.assertEqual(outcome[:2], (429, 'discord_rate_delayed'))
        self.assertEqual(outcome[3], {'retryAfterSeconds': 18})
        self.assertIsNone(self.claim())
        self.assertEqual((self.config.patches, self.limiter.patch_admissions()), ([], []))
        self.limiter.reserve_error = None
        self.assert_saves_at_once()

    def test_a_delay_raised_while_consuming_the_admission_also_releases_the_claim(self):
        self.limiter.consume_error = RateDelayed(5)
        outcome = self.post()
        self.assertEqual(outcome[:2], (429, 'discord_rate_delayed'))
        self.assertIsNone(self.claim())
        self.assertEqual([row['state'] for row in self.limiter.patch_admissions()], ['reserved'])   # expires by itself
        self.assertEqual(self.config.patches, [])
        self.limiter.consume_error = None
        self.assert_saves_at_once()

    def test_an_unavailable_coordinator_before_any_admission_releases_the_claim(self):
        self.limiter.reserve_error = RateCoordinatorUnavailable()
        outcome = self.post()
        self.assertEqual(outcome[:2], (503, 'discord_sender_name_unavailable'))
        self.assertEqual(outcome[3], {'reasons': [{'code': 'provider_unavailable'}]})
        self.assertIsNone(self.claim())
        self.assertEqual(self.config.patches, [])
        self.limiter.reserve_error = None
        self.assert_saves_at_once()

    def test_the_final_guard_refusing_after_the_admission_blocks_it_and_releases_the_claim(self):
        self.limiter.after_consume = self.share       # the second installation appears after the admission, before transport
        outcome = self.post()
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
        self.assertEqual(outcome[3], {'reasons': [{'code': 'nickname_authority_other_workspace'}]})
        self.assertIsNone(self.claim())
        self.assertEqual(self.config.patches, [])
        self.assertEqual([row['state'] for row in self.limiter.patch_admissions()], ['blocked'])

    def test_a_custody_change_while_the_admission_is_recorded_is_its_own_refusal_and_frees_the_claim(self):
        original = self.limiter.reserve

        def reserve(method, path, **kwargs):
            permit = original(method, path, **kwargs)
            if method == 'PATCH':
                self.w.channel(self.A, self.ia.connection)['discordSenderRevision'] = 'changed-by-another-tab'
            return permit
        self.limiter.reserve = reserve
        outcome = self.post()
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_required'))
        self.assertIsNone(self.claim())
        self.assertEqual(self.config.patches, [])


class ObservedRefusal(Claims):
    def test_a_discord_refusal_releases_the_claim_has_its_own_code_and_is_never_retried(self):
        self.config.reject_patch = True
        outcome = self.post()
        self.assertEqual(outcome[:2], (409, 'discord_sender_write_refused'))
        self.assertIsNone(self.claim())
        self.assertEqual(len(self.config.patches), 1, 'one attempt only: a refused write is never replayed')
        self.assertEqual([row['state'] for row in self.limiter.patch_admissions()], ['observed'])
        self.assertIsNone(self.w.channel(self.A, self.ia.connection).get('discordSenderName'))
        self.config.reject_patch = False
        saved = self.w.post(self.A, self.ta, self.ia.connection,
                            {'name': 'Claim Bot', 'fingerprint': self.profile['fingerprint'], **BODY})
        self.assertEqual(saved['savedName'], 'Claim Bot')
        self.assertEqual(len(self.config.patches), 2)

    def test_the_refusal_code_is_not_the_unconfirmed_or_pending_code(self):
        codes = {'discord_sender_write_refused', 'discord_sender_write_unconfirmed', 'discord_sender_edit_pending'}
        self.assertEqual(len(codes), 3)
        self.config.reject_patch = True
        self.assertEqual(self.post()[1], 'discord_sender_write_refused')

    def test_a_readback_that_cannot_be_made_keeps_the_claim_and_does_not_claim_nothing_was_sent(self):
        original = self.limiter.reserve_read

        def reserve_read(method, path, *, identity):
            if path.endswith(f'/members/{F.BOT}') and self.config.nick == 'Claim Bot':     # the read after the write
                raise RateDelayed(3)
            return original(method, path, identity=identity)
        self.limiter.reserve_read = reserve_read
        outcome = self.post()
        self.assertEqual(outcome[:2], (409, 'discord_sender_write_unconfirmed'))
        self.assertNotIn('no request was sent', outcome[2])
        self.assertIsNotNone(self.claim())
        self.assertEqual(self.config.patches, [{'nick': 'Claim Bot'}])


class LostResponses(Claims):
    def lose(self):
        self.w.hooks.lose_patch_response = True
        outcome = self.post()
        self.assertEqual(outcome[:2], (409, 'discord_sender_edit_pending'))
        self.assertEqual(outcome[3], {'retryAfterSeconds': 120})
        admission = self.claim()['rateAdmissionId']
        self.assertEqual(self.limiter.state_of(admission), 'uncertain')
        self.assertEqual(self.config.patches, [{'nick': 'Claim Bot'}], 'applied once, never replayed')
        return admission

    def test_a_lost_response_keeps_claim_and_uncertain_admission_until_a_read_after_the_deadline_settles_both(self):
        admission = self.lose()
        pending = self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)
        self.assertEqual(pending[:2], (409, 'discord_sender_edit_pending'))
        self.assertEqual(self.limiter.state_of(admission), 'uncertain', 'a read before the deadline settles nothing')
        self.w.now += 121
        recovered = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertIsNone(self.claim())
        self.assertEqual(self.limiter.state_of(admission), 'observed')
        self.assertEqual(self.limiter.reconciled, [('permit', admission)])
        self.assertEqual(recovered['savedName'], 'Claim Bot', 'what Discord reports becomes the saved nickname')
        self.assertIn('discord.sender_name_reconciled', self.kinds())
        self.assertNotIn('discord.sender_name_claim_abandoned', self.kinds())
        self.assertEqual(len(self.config.patches), 1)

    def test_an_error_raised_by_the_coordinator_after_the_admission_keeps_the_claim_too(self):
        self.limiter.consume_error = RateCoordinatorUnavailable()
        outcome = self.post()
        self.assertEqual(outcome[:2], (409, 'discord_sender_edit_pending'))
        admission = self.claim()['rateAdmissionId']
        self.assertEqual(self.config.patches, [])
        self.limiter.consume_error = None
        self.w.now += 121
        self.w.get(self.A, self.ta, self.ia.connection)
        self.assertIsNone(self.claim())
        self.assertEqual(self.limiter.state_of(admission), 'observed')

    def rotate_the_bot_token(self):
        self.w.s.adapter.bot_token = 'synthetic-rotated-bot'

    def test_after_a_bot_token_rotation_the_permit_based_reconcile_waits_for_the_grace_then_abandons_the_claim(self):
        admission = self.lose()
        self.rotate_the_bot_token()
        self.w.now += 121
        outcome = self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)
        self.assertEqual(outcome[:2], (409, 'discord_sender_edit_pending'), 'the person never sees the coordinator error')
        self.assertEqual(outcome[3], {'retryAfterSeconds': 60})
        self.assertIsNotNone(self.claim())
        self.w.now += names.CLAIM_GRACE_SECONDS
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertIsNone(self.claim())
        self.assertIn('discord.sender_name_claim_abandoned', self.kinds())
        self.assertEqual(self.limiter.state_of(admission), 'uncertain', 'left to the coordinator: see REQUESTS-TO-RATE-LIMITER R2/R3')
        self.assertTrue(profile['editable'])

    def test_a_coordinator_that_resolves_by_id_settles_the_admission_after_a_token_rotation(self):
        self.limiter = self.w.use_limiter(by_id=True)
        admission = self.lose()
        self.rotate_the_bot_token()
        self.w.now += 121
        self.w.get(self.A, self.ta, self.ia.connection)
        self.assertIsNone(self.claim())
        self.assertEqual(self.limiter.state_of(admission), 'observed')
        self.assertEqual(self.limiter.reconciled, [('id', admission)])
        self.assertIn('discord.sender_name_reconciled', self.kinds())
        self.assertNotIn('discord.sender_name_claim_abandoned', self.kinds())

    def test_reconciliation_is_idempotent_when_the_admission_is_already_terminal(self):
        self.limiter = self.w.use_limiter(by_id=True)
        admission = self.lose()
        self.limiter.admissions[admission]['state'] = 'blocked'      # resolved elsewhere in the meantime
        self.w.now += 121
        self.w.get(self.A, self.ta, self.ia.connection)
        self.assertIsNone(self.claim())
        self.assertEqual(self.limiter.state_of(admission), 'blocked')

    def test_coordination_switched_off_keeps_the_claim_pending_instead_of_dropping_the_admission(self):
        self.lose()
        self.w.s.adapter.rate_v1_enabled = False
        self.w.now += 121
        outcome = self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)
        self.assertEqual(outcome[:2], (409, 'discord_sender_edit_pending'))
        self.assertIsNotNone(self.claim())
        self.w.s.adapter.rate_v1_enabled = True
        self.w.get(self.A, self.ta, self.ia.connection)
        self.assertIsNone(self.claim())

    def test_a_degraded_coordinator_is_not_flagged_by_a_denied_nickname_write(self):
        """A guard that refuses before transport must not stop publishing for the whole process (SNR-11)."""
        self.limiter.after_consume = self.share
        adapter = self.w.s.adapter
        self.limiter.abandon_unsent_nickname = Mock(side_effect=RateCoordinatorUnavailable())
        self.assertEqual(self.post()[1], 'discord_sender_name_unavailable')
        self.assertFalse(adapter.rate_coordinator_degraded)


class ReadyGate(unittest.TestCase):
    """The settings routes need the same shared request coordinator that a post needs: when it cannot admit a request, the
    profile says so and nothing is asked of Discord (SNR-4, the gate the sibling routes have)."""
    FLAGS = {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true', 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true'}
    # Answered with a profile that says why (and 503 on a write): the coordinator cannot admit a request.
    CONDITIONS = {
        'rate limits off': lambda a, lim: setattr(a, 'rate_v1_enabled', False),
        'provider not production reviewed': lambda a, lim: setattr(a, 'production_reviewed', False),
        'no coordinator': lambda a, lim: setattr(a, 'rate_limiter', None),
        'coordinator without a policy': lambda a, lim: setattr(lim, 'policy', None),
        'coordinator degraded': lambda a, lim: setattr(a, 'rate_coordinator_degraded', True),
    }
    # Already refused for every Discord connection route by DiscordConnections.adapter, before any sender-name code runs.
    PAUSED = {
        'authorization v2 off': lambda a, lim: setattr(a, 'authorization_v2_enabled', False),
        'connections v2 off': lambda a, lim: setattr(a, 'connections_v2_enabled', False),
        'execution paused': lambda a, lim: setattr(a, 'execution_enabled', False),
    }

    def setUp(self):
        patcher = patch.dict(os.environ, self.FLAGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = Settings()
        self.ua = self.w.user(1)
        self.A = self.w.workspace(1)
        self.ta = self.w.member(self.A, self.ua, 'owner')
        self.wa = self.w.webhook(self.A, 1, self.ua, name='Alpha Weekly')
        self.ia = self.w.installation(self.A, 1, self.ua, guild='6400001')
        self.limiter = self.w.use_limiter()
        self.adapter = self.w.s.adapter

    def test_a_ready_provider_answers(self):
        for ids in (self.wa, self.ia):
            self.assertTrue(self.w.get(self.A, self.ta, ids.connection)['editable'])

    def test_each_missing_condition_makes_the_edit_unavailable_without_a_discord_request_or_a_state_change(self):
        for label, break_it in self.CONDITIONS.items():
            for ids in (self.wa, self.ia):
                with self.subTest(condition=label, connection=ids.connection[:14]):
                    self.setUp()
                    break_it(self.adapter, self.limiter)
                    before = self.w.snapshot()
                    profile = self.w.get(self.A, self.ta, ids.connection)
                    self.assertEqual((profile['editable'], profile['unavailable']), (False, [{'code': 'provider_unavailable'}]))
                    self.assertEqual(self.w.snapshot(), before, 'no Discord request, no state change')
                    refused = self.w.attempt(self.w.post, self.A, self.ta, ids.connection,
                                             {'name': 'Gated Name', 'fingerprint': profile['fingerprint'], **BODY})
                    self.assertEqual(refused[:2], (503, 'discord_sender_name_unavailable'))
                    self.assertEqual(refused[3], {'reasons': [{'code': 'provider_unavailable'}]})
                    self.assertEqual(self.w.snapshot(), before)

    def test_a_paused_provider_refuses_both_routes_like_every_other_discord_route(self):
        for label, break_it in self.PAUSED.items():
            for ids in (self.wa, self.ia):
                with self.subTest(condition=label, connection=ids.connection[:14]):
                    self.setUp()
                    break_it(self.adapter, self.limiter)
                    before = self.w.snapshot()
                    for call in (lambda: self.w.get(self.A, self.ta, ids.connection),
                                 lambda: self.w.post(self.A, self.ta, ids.connection, {'name': 'Gated Name', 'fingerprint': 'f' * 64, **BODY})):
                        outcome = self.w.attempt(call)
                        self.assertEqual(outcome[:2], (503, 'discord_connection_required'))
                    self.assertEqual(self.w.snapshot(), before)

    def test_the_webhook_route_switch_gates_only_webhook_connections(self):
        self.adapter.webhook_v1_enabled = False
        self.assertEqual([r['code'] for r in self.w.get(self.A, self.ta, self.wa.connection)['unavailable']], ['provider_unavailable'])
        self.assertTrue(self.w.get(self.A, self.ta, self.ia.connection)['editable'])

    def test_the_provider_view_tells_the_page_what_the_routes_would_answer(self):
        from postriff_phase2.oauth import OAuthService
        modes = OAuthService.discord_modes
        view = modes(self.adapter)
        self.assertEqual((view['bot']['nickname']['enabled'], view['webhook']['senderName']['enabled']), (True, True))
        for label, break_it in {**self.CONDITIONS, **self.PAUSED}.items():
            with self.subTest(condition=label):
                self.setUp()
                break_it(self.adapter, self.limiter)
                view = modes(self.adapter)
                self.assertEqual((view['bot']['nickname']['enabled'], view['webhook']['senderName']['enabled']), (False, False))
        self.setUp()
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'false'}):
            view = modes(self.adapter)
            self.assertEqual((view['bot']['nickname']['enabled'], view['webhook']['senderName']['enabled']), (False, True))
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'false'}):
            view = modes(self.adapter)
            self.assertEqual((view['bot']['nickname']['enabled'], view['webhook']['senderName']['enabled']), (False, False))
        self.adapter.webhook_v1_enabled = False
        view = modes(self.adapter)
        self.assertEqual((view['bot']['nickname']['enabled'], view['webhook']['senderName']['enabled']), (True, False))


class InstallationOrdering(RouteBase):
    def test_the_installation_commit_takes_the_server_lock_before_it_writes_the_credential_row(self):
        """SNR-1a: the installation path takes the same server-level lock as the nickname authority check, first."""
        commands = HostedPhase2Commands.__new__(HostedPhase2Commands)
        commands.engine = SimpleNamespace(invalidate=Mock())
        s = self.w.s
        s.oauth.commands = commands
        order, real = [], s.guild_lock
        s.guild_lock = lambda cur, guild: (order.append(('lock', guild)), real(cur, guild))[1]
        s.upsert = lambda *args, **kwargs: (order.append(('upsert',)), 'synthetic-installation-generation')[1]
        s.oauth._capabilities = lambda *args, **kwargs: {'publish': {'level': 'Direct', 'evidence': 'synthetic', 'capabilityVersion': 1,
                                                                    'verifiedAt': None}}
        link = self.w.workspaces[self.A].state['phase2']['discordIdentityLinks'][0]
        context = {'identityConnectionId': link['id'], 'identityGeneration': link['authorizationGeneration'], 'guildId': '6400099'}
        result = s.save_installation(self.A, self.ta, context, {'v': 2, 'kind': 'installation'}, ['bot', 'identify'],
                                     {'name': 'Synthetic server'})
        self.assertTrue(result['connected'])
        self.assertEqual(order, [('lock', '6400099'), ('upsert',)])
        self.assertEqual(self.w.locks, [f'rafii.discord.nickname:{F.APP}:6400099'], 'one lock, keyed by application and server')

    def test_the_authority_check_takes_the_same_lock_key(self):
        before = len(self.w.locks)
        self.w.get(self.A, self.ta, self.ia.connection)
        keys = self.w.locks[before:]
        self.assertTrue(keys)
        self.assertEqual(set(keys), {f'rafii.discord.nickname:{F.APP}:{self.ia.guild}'})


# ---------------------------------------------------------------------------------------------------------------------
# What the first independent mutation pass showed no test depended on (docs/sender-name/EVIDENCE.md, "Mutation pass")

class Hooked(Claims):
    def before_transaction(self, number, action):
        """Run `action()` right before the `number`-th workspace transaction of what follows (1-based)."""
        inner, count = self.w.s.local, [0]

        def local(workspace, token):
            count[0] += 1
            if count[0] == number:
                action()
            return inner(workspace, token)
        self.w.s.local = local
        self.addCleanup(setattr, self.w.s, 'local', inner)


class Races(Hooked):
    """A bot POST is eight workspace transactions: 1 first look, 2 re-proof, 3 after the reads, 4 claim, 5 first guard, 6 admission
    recorded, 7 final guard, 8 save. Each injection below is another request landing exactly before one of them."""
    def channel_record(self):
        return self.w.channel(self.A, self.ia.connection)

    def test_a_claim_appearing_before_this_one_is_created_stops_the_write(self):
        other = {'id': 'other-tab', 'name': 'Other', 'expiresAt': self.w.now + 100}
        self.before_transaction(4, lambda: self.channel_record().update(discordSenderEdit=other))
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.channel_record()['discordSenderEdit'], other, 'the other request keeps its claim')
        self.assertEqual((self.config.patches, self.limiter.patch_admissions()), ([], []))

    def test_the_connection_changing_before_the_claim_is_created_stops_the_write(self):
        self.before_transaction(4, lambda: self.channel_record().update(discordSenderRevision='changed-by-another-tab'))
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertNotIn('discordSenderEdit', self.channel_record())
        self.assertEqual(self.config.patches, [])

    def test_a_replaced_claim_before_the_admission_is_recorded_stops_the_write_and_leaves_the_replacement_alone(self):
        other = {'id': 'other-tab', 'name': 'Other', 'expiresAt': self.w.now + 100}
        self.before_transaction(6, lambda: self.channel_record().update(discordSenderEdit=other))
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.channel_record()['discordSenderEdit'], other)
        self.assertEqual(self.config.patches, [])

    def test_the_connection_changing_between_the_admission_and_the_final_guard_stops_the_write(self):
        self.before_transaction(7, lambda: self.channel_record().update(discordSenderRevision='changed-by-another-tab'))
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.config.patches, [])
        self.assertEqual([row['state'] for row in self.limiter.patch_admissions()], ['blocked'])
        self.assertNotIn('discordSenderEdit', self.channel_record())

    def test_the_claim_vanishing_before_the_final_guard_stops_the_write(self):
        self.before_transaction(7, lambda: self.channel_record().pop('discordSenderEdit', None))
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.config.patches, [])
        self.assertEqual([row['state'] for row in self.limiter.patch_admissions()], ['blocked'])

    def test_the_claim_running_out_before_the_final_guard_stops_the_write(self):
        def time_passes():
            self.w.now += 1000
        self.before_transaction(7, time_passes)
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.config.patches, [])
        self.assertEqual([row['state'] for row in self.limiter.patch_admissions()], ['blocked'])

    def test_the_connection_changing_during_the_provider_reads_makes_the_answer_stale(self):
        self.w.hooks.after_read = lambda: self.channel_record().update(discordSenderRevision='raced')
        self.assertEqual(self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)[:2], (409, 'discord_sender_name_required'))
        self.w.hooks.after_read = lambda: self.channel_record().update(discordSenderRevision='raced-again')
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.config.patches, [])
        self.assertNotIn('discordSenderEdit', self.channel_record())

    def test_a_claim_appearing_during_the_provider_reads_is_not_adopted_by_the_write(self):
        other = {'id': 'other-tab', 'name': 'Other', 'expiresAt': self.w.now + 100}
        self.w.hooks.after_read = lambda: self.channel_record().update(discordSenderEdit=other)
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.channel_record()['discordSenderEdit'], other)
        self.assertEqual(self.config.patches, [])

    def test_a_connection_changing_before_the_final_save_leaves_the_claim_for_a_later_read_to_settle(self):
        self.before_transaction(8, lambda: self.channel_record().update(discordSenderRevision='changed-by-another-tab'))
        self.assertEqual(self.post()[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(self.config.patches, [{'nick': 'Claim Bot'}], 'the nickname did change on Discord')
        self.assertIn('discordSenderEdit', self.channel_record(), 'so the claim stays until a read settles it')
        self.w.now += 121
        recovered = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual(recovered['savedName'], 'Claim Bot')
        self.assertNotIn('discordSenderEdit', self.channel_record())


class GuardTimeSwitches(Claims):
    def test_a_switch_turned_off_between_the_admission_and_the_transport_stops_the_write(self):
        for variable, code in (('POSTRIFF_DISCORD_SENDER_NAMES_ENABLED', 'sender_names_disabled'),
                               ('POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED', 'bot_nickname_disabled')):
            with self.subTest(variable):
                self.limiter.after_consume = lambda v=variable: os.environ.__setitem__(v, 'false')
                outcome = self.post()
                os.environ[variable] = 'true'
                self.assertEqual(outcome[:2], (409, 'discord_sender_name_unavailable'))
                self.assertEqual(outcome[3], {'reasons': [{'code': code}]})
                self.assertEqual(self.config.patches, [])
                self.assertNotIn('discordSenderEdit', self.w.channel(self.A, self.ia.connection))
                self.assertEqual(self.limiter.patch_admissions()[-1]['state'], 'blocked')


class PatchAnswers(Claims):
    CASES = {
        'another user': lambda body: {'status': 200, 'body': {'user': {'id': '1234567'}, 'nick': body['nick']}, 'headers': {}},
        'a user-less answer': lambda body: {'status': 200, 'body': {'nick': body['nick']}, 'headers': {}},
        'status 201': lambda body: {'status': 201, 'body': {'user': {'id': F.BOT}, 'nick': body['nick']}, 'headers': {}},
        'an answer that is not an object': lambda body: {'status': 200, 'body': ['x'], 'headers': {}},
        'no body': lambda body: {'status': 200, 'body': None, 'headers': {}},
        'a server error': lambda body: {'status': 502, 'body': {}, 'headers': {}},
        'a status that is not a number': lambda body: {'status': 'ok', 'body': {'user': {'id': F.BOT}, 'nick': body['nick']}, 'headers': {}},
    }

    def test_an_answer_that_is_not_the_requested_nickname_for_the_bot_is_unconfirmed_and_keeps_the_claim(self):
        for label, answer in self.CASES.items():
            with self.subTest(label):
                self.setUp()
                self.config.patch_response = answer
                outcome = self.post()
                self.assertEqual(outcome[:2], (409, 'discord_sender_write_unconfirmed'), label)
                self.assertIsNotNone(self.claim())
                self.assertIsNone(self.w.channel(self.A, self.ia.connection).get('discordSenderName'))
                self.assertEqual(len(self.config.patches), 1, 'never replayed')

    def test_a_readback_by_another_user_or_without_one_is_unconfirmed(self):
        for label, change in (('another user', lambda: setattr(self.config, 'readback_user_id', '1234567')),
                              ('no user', lambda: setattr(self.config, 'readback_no_user', True))):
            with self.subTest(label):
                self.setUp()
                change()
                outcome = self.post()
                self.assertEqual(outcome[:2], (409, 'discord_sender_write_unconfirmed'))
                self.assertIsNotNone(self.claim())

    def test_an_unexpected_error_before_the_transport_is_an_unavailable_provider_and_frees_the_claim(self):
        self.limiter.reserve_error = RuntimeError('synthetic database trouble')
        outcome = self.post()
        self.assertEqual(outcome[:2], (503, 'discord_sender_name_unavailable'))
        self.assertEqual(outcome[3], {'reasons': [{'code': 'provider_unavailable'}]})
        self.assertIsNone(self.claim())
        self.assertEqual(self.config.patches, [])


class WhatDiscordSays(RouteBase):
    def test_a_different_bot_server_or_a_missing_bot_member_asks_for_a_reconnect_on_both_routes(self):
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        for label, change in {'another bot': lambda: setattr(self.w.hooks, 'bot_id', '1234567'),
                              'another server': lambda: setattr(self.w.hooks.guild_config[self.ia.guild], 'report_guild_id', '1234567'),
                              'no bot member': lambda: setattr(self.w.hooks.guild_config[self.ia.guild], 'bot_member_missing', True)}.items():
            with self.subTest(label):
                change()
                self.assertEqual(self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)[:2],
                                 (409, 'discord_connection_required'), label)
                outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                         {'name': 'Gone Bot', 'fingerprint': profile['fingerprint'], **BODY})
                self.assertEqual(outcome[:2], (409, 'discord_connection_required'), label)
                self.assertEqual(self.w.hooks.guild_config[self.ia.guild].patches, [])
                self.w.hooks.bot_id = F.BOT
                config = self.w.hooks.guild_config[self.ia.guild]
                config.report_guild_id, config.bot_member_missing = None, False

    def test_a_person_who_is_no_longer_in_the_server_is_a_reason_not_an_error(self):
        self.w.hooks.guild_config[self.ia.guild].user_member_missing = True
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual([r['code'] for r in profile['unavailable']], ['person_missing_manage_nicknames'])
        self.assertFalse(profile['editable'])

    def test_the_bots_displayed_name_is_its_nickname_then_its_global_name_then_its_username(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        config.bot_global_name = 'Global Rafii'
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual((profile['observedName'], profile['nameSource']), ('Global Rafii', 'bot_username'))
        config.nick = 'Server Rafii'
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual((profile['observedName'], profile['nameSource']), ('Server Rafii', 'observed_nickname'))
        config.nick, config.bot_global_name = None, None
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual((profile['observedName'], profile['nameSource']), ('Rafii', 'bot_username'))

    def test_a_name_discord_returns_that_cannot_be_shown_is_an_upstream_error(self):
        def stored():
            return json.dumps({w.id: w.state for w in self.w.workspaces.values()}, sort_keys=True) + json.dumps(self.w.audit)
        for bad in ('', None, 'x' * 81, 5, ['a']):
            with self.subTest(bad=bad):
                self.w.hooks.webhook_name = bad
                before = stored()
                outcome = self.w.attempt(self.w.get, self.A, self.ta, self.wa.connection)
                self.assertNotEqual(outcome[0], 'ok')
                self.assertIn(outcome[0], (409, 502), (bad, outcome))
                self.assertEqual(stored(), before)
        self.w.hooks.webhook_name = 'Spare Webhook'
        self.assertEqual(self.w.get(self.A, self.ta, self.wa.connection)['observedName'], 'Spare Webhook')


class Shapes(RouteBase):
    def test_a_switched_off_answer_shows_the_saved_name_and_claims_to_know_nothing_else(self):
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'false'}):
            profile = self.w.get(self.A, self.ta, self.wa.connection)
        self.assertEqual((profile['name'], profile['savedName']), ('Alpha Weekly', 'Alpha Weekly'))
        self.assertEqual((profile['effectiveName'], profile['nameSource'], profile['observedName'], profile['observedAt']),
                         (None, 'none', None, None))
        self.assertEqual(profile['preview']['currentDisplayName'], None)
        self.assertEqual([r['code'] for r in profile['unavailable']], ['sender_names_disabled'])

    def test_the_name_is_never_null(self):
        other = self.w.webhook(self.A, 5, self.ua)            # no saved name
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'false'}):
            profile = self.w.get(self.A, self.ta, other.connection)
        self.assertEqual((profile['name'], profile['savedName']), ('', None))
        self.assertIsInstance(profile['fingerprint'], str)
        self.assertEqual(len(profile['fingerprint']), 64)
        live = self.w.get(self.A, self.ta, other.connection)
        self.assertEqual((live['name'], live['nameSource']), ('Spare Webhook', 'webhook_default'))

    def test_an_external_rename_is_reported_only_for_a_bot_whose_observed_name_differs_from_the_saved_one(self):
        config = self.w.hooks.guild_config[self.ia.guild]
        config.nick = 'Their Name'
        self.assertFalse(self.w.get(self.A, self.ta, self.ia.connection)['externalChange'], 'nothing saved yet')
        self.w.channel(self.A, self.ia.connection)['discordSenderName'] = 'Our Name'
        self.assertTrue(self.w.get(self.A, self.ta, self.ia.connection)['externalChange'])
        config.nick = 'Our Name'
        self.assertFalse(self.w.get(self.A, self.ta, self.ia.connection)['externalChange'])
        self.assertFalse(self.w.get(self.A, self.ta, self.wa.connection)['externalChange'], 'a webhook has no shared name to be renamed')

    def test_a_bot_save_records_the_nickname_it_set_and_a_webhook_save_records_none(self):
        self.save(self.ta, self.A, self.ia, 'Our Bot')
        self.assertEqual(self.w.channel(self.A, self.ia.connection)['discordBotNickname']['value'], 'Our Bot')
        self.save(self.ta, self.A, self.wa, 'Alpha Daily')
        self.assertNotIn('discordBotNickname', self.w.channel(self.A, self.wa.connection))

    def test_a_webhook_is_not_blocked_by_another_workspaces_bot_in_its_server(self):
        self.w.installation(self.B, 9, self.ub, guild=self.wa.guild)
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        self.assertEqual((profile['editable'], profile['unavailable']), (True, []))
        self.assertEqual(self.save(self.ta, self.A, self.wa, 'Alpha Daily')['savedName'], 'Alpha Daily')

    def test_the_installer_is_found_through_the_installations_own_identity_link_among_look_alikes(self):
        links = self.w.workspaces[self.A].state['phase2']['discordIdentityLinks']
        other_id = {'id': 'discord-identity-decoy', 'workspaceId': self.A, 'applicationId': F.APP, 'authorizedBy': self.ub,
                    'userId': F.USER, 'status': 'linked', 'authorizationGeneration': 'decoy-generation'}
        other_workspace = dict(links[0], workspaceId=self.B, authorizedBy=self.ub)      # the same id, another workspace's record
        links.insert(0, other_id)
        links.insert(0, other_workspace)
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual((profile['editable'], profile['unavailable']), (True, []))

    def test_a_switched_off_bot_answer_never_claims_an_external_rename(self):
        self.w.channel(self.A, self.ia.connection)['discordSenderName'] = 'Our Name'
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'false'}):
            profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual((profile['externalChange'], profile['savedName'], profile['observedName']), (False, 'Our Name', None))

    def test_a_nickname_changed_in_discord_after_the_form_was_loaded_makes_the_form_stale(self):
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        config = self.w.hooks.guild_config[self.ia.guild]
        config.nick = 'Changed By A Server Admin'
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                 {'name': 'Brand Bot', 'fingerprint': profile['fingerprint'], **BODY})
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_required'))
        self.assertEqual(config.patches, [])
        self.assertNotIn('discordSenderEdit', self.w.channel(self.A, self.ia.connection))
        fresh = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual(self.w.post(self.A, self.ta, self.ia.connection,
                                     {'name': 'Brand Bot', 'fingerprint': fresh['fingerprint'], **BODY})['savedName'], 'Brand Bot')

    def test_only_a_bot_write_refreshes_the_linked_identity(self):
        refresh = self.w.s._fresh_identity
        self.w.get(self.A, self.ta, self.ia.connection)
        self.save(self.ta, self.A, self.wa, 'Alpha Daily')
        refresh.assert_not_called()
        self.save(self.ta, self.A, self.ia, 'Our Bot')
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.args[0], self.A)
        self.assertIsNone(refresh.call_args.args[1])
        self.assertTrue(refresh.call_args.args[2].startswith('discord-identity-'))


class Throttles(RouteBase):
    def test_the_workspace_throttle_counts_across_connections(self):
        extra = [self.w.webhook(self.A, 20 + number, self.ua, name=f'Extra {number}') for number in range(4)]
        outcomes = [self.w.attempt(self.w.get, self.A, self.ta, ids.connection)[:2] for ids in extra for _ in range(11)]
        self.assertEqual(sum(1 for o in outcomes if o[0] == 'ok'), 40, 'forty reads per workspace in ten minutes')
        self.assertEqual([o for o in outcomes if o[0] != 'ok'], [(429, 'rate_limited')] * 4)
        calls = len(self.w.hooks.calls)
        self.assertEqual(self.w.attempt(self.w.get, self.A, self.ta, extra[0].connection)[:2], (429, 'rate_limited'))
        self.assertEqual(len(self.w.hooks.calls), calls, 'a throttled request makes no Discord request')
        self.assertEqual(self.w.get(self.B, self.tb, self.wb.connection)['savedName'], 'Beta Weekly', 'another workspace is unaffected')


class PendingAnswers(Claims):
    def claim_record(self, **fields):
        claim = {'id': 'earlier', 'name': 'Earlier', 'expiresAt': self.w.now + 60, **fields}
        self.w.channel(self.A, self.ia.connection)['discordSenderEdit'] = claim
        return claim

    def test_a_pending_write_accompanies_the_other_reasons_when_discord_is_not_read(self):
        self.claim_record()
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'false'}):
            profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual([r['code'] for r in profile['unavailable']], ['bot_nickname_disabled', 'edit_pending'])
        self.assertEqual(profile['unavailable'][1]['retryAfterSeconds'], 60)

    def test_a_stale_session_adds_its_reason_to_a_switched_off_answer(self):
        self.w.stale.add(self.ta)
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'false'}):
            profile = self.w.get(self.A, self.ta, self.ia.connection)
        self.assertEqual([r['code'] for r in profile['unavailable']], ['bot_nickname_disabled', 'session_reverification_required'])

    def test_a_malformed_claim_stays_pending_and_is_never_cleared_by_a_read(self):
        for claim in ('garbage', {'id': 'c'}, {'id': 'c', 'expiresAt': 'soon'}, {'id': 'c', 'expiresAt': None},
                      {'id': 'c', 'expiresAt': True}):
            with self.subTest(claim=repr(claim)):
                self.w.channel(self.A, self.ia.connection)['discordSenderEdit'] = claim
                outcome = self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)
                self.assertEqual(outcome[:2], (409, 'discord_sender_edit_pending'))
                self.assertEqual(outcome[3], {'retryAfterSeconds': 120})
                self.assertIs(self.w.channel(self.A, self.ia.connection)['discordSenderEdit'], claim)
                self.w.now += 5000
                self.assertEqual(self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)[:2], (409, 'discord_sender_edit_pending'))
                self.w.now -= 5000

    def test_a_post_whose_fingerprint_matches_the_claimed_state_still_cannot_settle_an_expired_claim(self):
        """The Rafii-state half of the fingerprint is not a secret worth relying on: settling is for a GET, never a POST."""
        claim = self.claim_record(expiresAt=self.w.now - 1)
        with self.w.s.local(self.A, self.ta) as (cur, state, actor):
            _, _, stamp = names.SenderNames(self.w.s, self.A, self.ta, self.ia.connection).custody(
                cur, state, actor, fresh=False, require_authorizer=False)
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                 {'name': 'Brand Bot', 'fingerprint': names.fingerprint_of(stamp, 'Rafii'), **BODY})
        self.assertEqual(outcome[:2], (409, 'discord_sender_edit_pending'))
        self.assertIs(self.w.channel(self.A, self.ia.connection)['discordSenderEdit'], claim)
        self.assertEqual(self.config.patches, [])

    def test_a_claim_that_is_not_due_when_the_reads_finish_is_not_settled(self):
        claim = self.claim_record(expiresAt=self.w.now - 1)
        self.w.hooks.after_read = lambda: setattr(self.w, 'now', self.w.now - 100)      # the clock the final check sees is earlier
        outcome = self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)
        self.assertEqual(outcome[:2], (409, 'discord_sender_name_required'))
        self.assertIs(self.w.channel(self.A, self.ia.connection)['discordSenderEdit'], claim)

    def test_a_delayed_read_is_a_rate_delay_and_changes_nothing(self):
        def delayed(method, path, *, identity):
            raise RateDelayed(7)
        self.limiter.reserve_read = delayed
        before = self.w.snapshot()
        outcome = self.w.attempt(self.w.get, self.A, self.ta, self.ia.connection)
        self.assertEqual(outcome[:2], (429, 'discord_rate_delayed'))
        self.assertEqual(outcome[3], {'retryAfterSeconds': 7})
        self.assertEqual(self.w.snapshot(), before)


class NicknameObservation(unittest.TestCase):
    """The member verification actions record the nickname Discord reports, which is what a later review freezes."""
    def verify(self, s, channel, **kwargs):
        with patch('postriff_phase2.hosted.audit'):
            return s.reverify_installation(WORKSPACE, channel['id'], token='synthetic-session', **kwargs)

    @staticmethod
    def member(nick):
        body = {'user': {'id': BOT}, 'roles': [], 'pending': False, 'communication_disabled_until': None}
        if nick is not None:
            body['nick'] = nick
        return {'status': 200, 'body': body}

    def test_the_reported_nickname_is_recorded_with_the_time_it_was_seen(self):
        s, wire, state, channel, *_ = reverify_fixture(ready=False)
        wire.route_overrides[('GET', f'/guilds/{GUILD}/members/{BOT}')] = self.member('Seen Nick')
        self.assertEqual(self.verify(s, channel)['state'], 'read_verified')
        self.assertEqual(channel['discordBotNickname'], {'value': 'Seen Nick', 'observedAt': NOW})

    def test_a_bot_without_a_nickname_is_recorded_as_none(self):
        s, wire, state, channel, *_ = reverify_fixture(ready=False)
        channel['discordBotNickname'] = {'value': 'Earlier Nick', 'observedAt': 1.0}
        wire.route_overrides[('GET', f'/guilds/{GUILD}/members/{BOT}')] = self.member(None)
        self.assertEqual(self.verify(s, channel)['state'], 'read_verified')
        self.assertEqual(channel['discordBotNickname'], {'value': None, 'observedAt': NOW})

    def test_evidence_without_a_nickname_field_records_nothing(self):
        s, wire, state, channel, *_ = reverify_fixture(ready=False)
        real = s.adapter.destinations
        s.adapter.destinations = lambda envelope: [{k: v for k, v in entry.items() if k != 'botNickname'} for entry in real(envelope)]
        self.assertEqual(self.verify(s, channel)['state'], 'read_verified')
        self.assertNotIn('discordBotNickname', channel)

    def test_a_failed_verification_records_nothing_and_keeps_the_earlier_observation(self):
        s, wire, state, channel, *_ = reverify_fixture(ready=False)
        earlier = {'value': 'Earlier Nick', 'observedAt': 1.0}
        channel['discordBotNickname'] = dict(earlier)
        wire.identity_revoked = True
        outcome = self.verify(s, channel)
        self.assertNotEqual(outcome['state'], 'read_verified')
        self.assertEqual(channel['discordBotNickname'], earlier)
        # and a server whose destinations cannot be read leaves it too
        s, wire, state, channel, *_ = reverify_fixture(ready=False)
        wire.route_overrides[('GET', f'/guilds/{GUILD}/members/{BOT}')] = self.member('Not Recorded')
        wire.route_overrides[('GET', f'/guilds/{GUILD}/channels')] = {'status': 200, 'body': [], 'headers': {}}
        self.assertEqual(self.verify(s, channel)['state'], 'permission_missing')
        self.assertNotIn('discordBotNickname', channel)


class Reconnect(unittest.TestCase):
    def commands(self):
        commands = HostedPhase2Commands.__new__(HostedPhase2Commands)
        commands.engine = SimpleNamespace(invalidate=Mock())
        return commands

    RECORD = dict(id='discord-install-0001', platform='Discord', account='Synthetic server', accountType='server',
                  scopes=['bot', 'identify'], verifiedAt=1, expiresAt=2, capabilityVersion=1, providerAccountId='6400001',
                  discordAuthorizationGeneration='generation-two')

    def test_a_discord_reconnect_keeps_the_sender_record_and_a_pending_claim(self):
        claim = {'id': 'claim-1', 'name': 'Alpha Bot', 'expiresAt': 5.0, 'rateAdmissionId': 'admission-1', 'rateExpiresAt': 6.0}
        existing = dict(self.RECORD, discordAuthorizationGeneration='generation-one', discordSenderName='Alpha Bot',
                        discordSenderRevision='revision-1', discordSenderEdit=claim,
                        discordBotNickname={'value': 'Alpha Bot', 'observedAt': 3.0},
                        discordDestinations=[{'id': 'd', 'status': 'authorized'}])
        state = {'phase2': {'channels': [existing]}}
        self.commands().upsert_verified_channel(state, 'owner', dict(self.RECORD))
        saved = state['phase2']['channels'][0]
        self.assertEqual(len(state['phase2']['channels']), 1)
        self.assertEqual(saved['discordAuthorizationGeneration'], 'generation-two')
        self.assertEqual((saved['discordSenderName'], saved['discordSenderRevision']), ('Alpha Bot', 'revision-1'))
        self.assertEqual(saved['discordSenderEdit'], claim)
        self.assertEqual(saved['discordBotNickname'], {'value': 'Alpha Bot', 'observedAt': 3.0})
        self.assertEqual([d['status'] for d in saved['discordDestinations']], ['reauthorization_required'],
                         'consent is still renewed: a reconnect never inherits an approval')

    def test_a_first_connection_has_no_sender_record_and_other_platforms_are_untouched(self):
        state = {'phase2': {'channels': []}}
        self.commands().upsert_verified_channel(state, 'owner', dict(self.RECORD))
        self.assertFalse({'discordSenderName', 'discordSenderEdit', 'discordBotNickname'} & set(state['phase2']['channels'][0]))


class WebhookReconnect(RouteBase):
    """A same-actor webhook reconnect creates a new remote webhook and a new connection: the Rafii-side name is carried."""
    def reconnect(self, *, actor=None, prior_generation=None, connection=None):
        number = 9
        hook, channel = str(8300000 + number), self.wa.channel
        credential = 'synthetic-' + secrets.token_urlsafe(24)
        self.w.hooks.by_hook[hook] = SimpleNamespace(hook=hook, hook_credential=credential, guild=self.wa.guild, channel=channel,
                                                     workspace=self.A, name=None, kind='webhook')
        body = {'scope': 'webhook.incoming identify',
                'webhook': {'id': hook, 'token': credential, 'application_id': F.APP, 'type': 1,
                            'guild_id': self.wa.guild, 'channel_id': channel}}
        context = {'memberId': actor or self.ua, 'connectionId': connection or self.wa.connection,
                   'priorGeneration': prior_generation or self.wa.generation}
        self.w.s.upsert = Mock(return_value='synthetic-new-generation')
        return self.w.s.save_webhook_callback(self.A, self.ta, context, body, {'id': F.USER}, ['identify'])

    def test_the_saved_name_moves_to_the_new_connection_with_a_new_revision(self):
        before = self.w.channel(self.A, self.wa.connection)
        old_revision = before.get('discordSenderRevision')
        result = self.reconnect()
        new = self.w.channel(self.A, result['connectionId'])
        self.assertEqual(new['discordSenderName'], 'Alpha Weekly')
        self.assertNotEqual(new['discordSenderRevision'], old_revision)
        self.assertTrue(self.w.channel(self.A, self.wa.connection)['revoked'], 'the old connection stays revoked')
        self.assertEqual(new['discordDestinations'], [], 'the new connection still needs its own destination consent')
        self.assertFalse(new['capabilityVerified'])

    def test_a_reconnect_by_someone_else_or_with_a_stale_generation_carries_nothing_and_changes_nothing(self):
        def stored():
            return json.dumps({'states': {w.id: w.state for w in self.w.workspaces.values()}, 'audit': self.w.audit,
                               'revoked': {f'{k[0]}/{k[1]}': v['revoked'] for k, v in self.w.credentials.items()}},
                              sort_keys=True, default=str)
        for kwargs in ({'actor': self.ub}, {'prior_generation': 'not-the-generation'}):
            before = stored()
            outcome = self.w.attempt(lambda: self.reconnect(**kwargs))
            self.assertEqual(outcome[0], 409, kwargs)
            self.assertEqual(stored(), before, kwargs)

    def test_a_brand_new_webhook_starts_without_a_name(self):
        hook, credential = str(8399999), 'synthetic-' + secrets.token_urlsafe(24)
        self.w.hooks.by_hook[hook] = SimpleNamespace(hook=hook, hook_credential=credential, guild=self.wa.guild, channel=self.wa.channel,
                                                     workspace=self.A, name=None, kind='webhook')
        body = {'scope': 'webhook.incoming identify',
                'webhook': {'id': hook, 'token': credential, 'application_id': F.APP, 'type': 1,
                            'guild_id': self.wa.guild, 'channel_id': self.wa.channel}}
        self.w.s.upsert = Mock(return_value='synthetic-generation')
        result = self.w.s.save_webhook_callback(self.A, self.ta, {'memberId': self.ua}, body, {'id': F.USER}, ['identify'])
        self.assertNotIn('discordSenderName', self.w.channel(self.A, result['connectionId']))


class Reset(RouteBase):
    def post(self, ids, token=None, **body):
        profile = self.w.get(self.A, token or self.ta, ids.connection)
        return self.w.attempt(self.w.post, self.A, token or self.ta, ids.connection,
                              {'fingerprint': profile['fingerprint'], 'confirmed': True, **body})

    def test_a_webhook_name_can_be_cleared_back_to_the_webhooks_own_name(self):
        revision = self.w.channel(self.A, self.wa.connection).get('discordSenderRevision')
        outcome = self.post(self.wa, reset=True)
        self.assertEqual(outcome[0], 'ok')
        result = outcome[2]
        self.assertEqual((result['saved'], result['reset'], result['savedName']), (True, True, None))
        self.assertEqual(result['nameSource'], 'webhook_default')
        self.assertEqual(result['effectiveName'], F.DEFAULT_HOOK_NAME)
        channel = self.w.channel(self.A, self.wa.connection)
        self.assertNotIn('discordSenderName', channel)
        self.assertNotEqual(channel['discordSenderRevision'], revision)
        self.assertIn('discord.sender_name_reset', [event['kind'] for event in self.w.audit])
        self.assertEqual(self.w.hooks.posts, [])

    def test_a_cleared_name_is_not_frozen_into_the_next_review(self):
        self.post(self.wa, reset=True)
        self.assertIsNone(names.frozen_webhook_name(self.w.channel(self.A, self.wa.connection)))

    def test_a_bot_nickname_cannot_be_cleared_and_nothing_is_asked_of_discord(self):
        profile = self.w.get(self.A, self.ta, self.ia.connection)
        before = len(self.w.hooks.calls)
        outcome = self.w.attempt(self.w.post, self.A, self.ta, self.ia.connection,
                                 {'fingerprint': profile['fingerprint'], 'confirmed': True, 'reset': True})
        self.assertEqual(outcome[:2], (400, 'discord_sender_reset_unsupported'))
        self.assertEqual(len(self.w.hooks.calls), before)
        self.assertEqual(self.w.hooks.guild_config[self.ia.guild].patches, [])

    def test_reset_cannot_be_combined_with_a_name_or_be_false(self):
        for body in ({'reset': True, 'name': 'Alpha Daily'}, {'reset': False}, {'reset': 'yes'}):
            outcome = self.post(self.wa, **body)
            self.assertEqual(outcome[:2], (400, 'discord_sender_name_unconfirmed'), body)
        self.assertEqual(self.w.channel(self.A, self.wa.connection)['discordSenderName'], 'Alpha Weekly')

    def test_reset_needs_the_same_confirmation_and_current_fingerprint_as_a_save(self):
        profile = self.w.get(self.A, self.ta, self.wa.connection)
        stale = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                               {'reset': True, 'confirmed': True, 'fingerprint': 'f' * 64})
        self.assertEqual(stale[:2], (409, 'discord_sender_name_required'))
        unconfirmed = self.w.attempt(self.w.post, self.A, self.ta, self.wa.connection,
                                     {'reset': True, 'fingerprint': profile['fingerprint']})
        self.assertEqual(unconfirmed[:2], (400, 'discord_sender_name_unconfirmed'))
        self.assertEqual(self.w.channel(self.A, self.wa.connection)['discordSenderName'], 'Alpha Weekly')


if __name__ == '__main__':
    unittest.main()
