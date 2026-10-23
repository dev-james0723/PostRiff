"""The edit claim of a bot-nickname write, the rate admission it points at, and what survives a reconnect.

Reviewer findings SNR-5 (a claim must not outlive a write that provably never left, or that Discord refused) and SNR-6 (an
uncertain admission must stay resolvable: reconnect, bot-token rotation, ambiguous transport). The coordinator is the scriptable
stand-in in discord_sender_name_fixture.py; the real coordinator on PostgreSQL is driven in test_discord_sender_name_postgres.py.
"""
import json
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import discord_sender_name_fixture as F
from discord_sender_name_settings_fixture import Settings
from postriff_phase2.discord import sender_names as names
from postriff_phase2.discord.rate_limits import RateCoordinatorUnavailable, RateDelayed
from postriff_phase2.hosted import HostedPhase2Commands
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
