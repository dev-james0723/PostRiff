"""What the page is shown and echoes when it approves an automation run item for a Discord post, and the stable code of a hold.

The page (web/src/features/automations/run-decision.tsx on the UI branch) builds its approval from the CHANNEL VIEW: a webhook's
`discordSenderName`, or a bot's `discordBotNickname` when the view carries one. campaigns._decide compares that echo with what a
review would freeze now. Every approval below is built FROM the channel view, exactly as the page does, so these tests fail the
moment the view and the check disagree (the UI engineer's R1 and R2). The last class is R3: the dispatch holds carry a stable
reason code next to their English text.
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import discord_sender_name_fixture as F
from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns, publisher
from postriff_phase2.channels import assisted_matrix, customer_view
from postriff_phase2.discord import authorization as auth
from postriff_phase2.discord import sender_names as names


def flags(master=True, nickname=True):
    return patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true' if master else 'false',
                                   'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED': 'true' if nickname else 'false'})


def channel_view(tenant):
    return customer_view(tenant.channel_record, assisted_matrix(), F.NOW)


class Page:
    """The approval dialog: read the channel view, then send the approval it implies."""
    def __init__(self, tenant):
        self.tenant = tenant
        self.state, self.channel = tenant.state, tenant.channel_record
        destination = auth.destination(self.state, self.channel, self.channel['defaultDestinationId'])
        self.destination = destination
        self.task = {'id': 'synthetic-task', 'status': 'active', 'schedule': {'timeZone': 'UTC'}}
        self.item = {'key': 'synthetic-item', 'platform': 'Discord', 'channelId': self.channel['id'], 'variantId': tenant.variant['id'],
                     'state': 'ready_for_review', 'publishAt': F.NOW + 300}
        self.run = {'id': 'synthetic-run', 'taskId': self.task['id'], 'items': [self.item]}
        self.root = campaigns._root(self.state)
        self.root['recurringTasks'].append(self.task)
        self.root['occurrences'].append(self.run)

    def body(self, view):
        sender = ({'discordSenderName': view.get('discordSenderName')} if self.destination.get('senderKind') == 'webhook' else
                  {'discordBotNickname': view['discordBotNickname']} if 'discordBotNickname' in view else {})
        return {'occurrenceId': self.run['id'], 'itemKey': self.item['key'], 'decision': 'approve', 'confirmed': True,
                'variantRevision': 1, 'excludedUnknowns': [], 'acknowledgedWarnings': [], 'destinationId': self.destination['id'],
                'destinationGeneration': self.destination['resourceGeneration'], 'publishAt': F.NOW + 300, **sender}

    def approve(self, view=None, **overrides):
        body = {**self.body(view if view is not None else channel_view(self.tenant)), **overrides}
        return campaigns._decide(self.state, self.root, body, F.ACTOR, F.NOW)

    def queue(self):
        queued = publisher.commit(self.tenant.engine, self.state, F.ACTOR, {'occurrenceId': self.run['id'], 'itemKey': self.item['key']}, F.NOW + 60)
        return next(j for j in self.state['phase2']['jobs'] if j['id'] == queued['jobId'])


def bot(index, observed='unset'):
    tenant = F.Tenant(index, None, kind='bot').build()
    if observed != 'unset':
        tenant.channel_record['discordBotNickname'] = {'value': observed, 'observedAt': F.NOW}
    return tenant


class BotNicknameCarrier(unittest.TestCase):
    """R1: with the capability on and a nickname observed, the page needs the value to echo; it must come from the channel view."""

    def test_the_value_the_page_is_shown_is_the_value_the_approval_needs(self):
        tenant = bot(40, 'Brand Bot')
        with flags():
            view = channel_view(tenant)
            self.assertEqual(view['discordBotNickname'], 'Brand Bot')
            page = Page(tenant)
            page.approve(view)
            self.assertEqual(page.item['decision']['discordBotNickname'], 'Brand Bot')
            job = page.queue()
        self.assertEqual(job['manifest']['discordBotNickname'], 'Brand Bot')
        with flags():
            self.assertTrue(auth.job_authorized(tenant.state, tenant.channel_record, job))

    def test_the_approval_digest_binds_the_value(self):
        publications = {}
        for index, nick in ((41, 'Brand Bot'), (42, 'Another Bot')):
            tenant = bot(index, nick)
            with flags():
                page = Page(tenant)
                page.approve()
                job = page.queue()
            publications[nick] = (job['manifest']['discord']['publicationId'], job['approvalDigest'])
        self.assertNotEqual(publications['Brand Bot'][0], publications['Another Bot'][0])
        # and the value cannot be swapped after the approval: a manifest with another nickname is not the approved one
        tenant = bot(43, 'Brand Bot')
        with flags():
            page = Page(tenant)
            page.approve()
            job = page.queue()
            self.assertTrue(auth.job_authorized(tenant.state, tenant.channel_record, job))
            job['manifest']['discordBotNickname'] = 'Swapped After Approval'
            self.assertFalse(auth.job_authorized(tenant.state, tenant.channel_record, job))

    def test_a_bot_without_a_nickname_is_shown_null_and_that_approves(self):
        tenant = bot(44, None)
        with flags():
            view = channel_view(tenant)
            self.assertIn('discordBotNickname', view)
            self.assertIsNone(view['discordBotNickname'])
            page = Page(tenant)
            page.approve(view)
            self.assertIn('discordBotNickname', page.item['decision'])
            self.assertIsNone(page.item['decision']['discordBotNickname'])

    def test_nothing_recorded_or_the_capability_off_shows_no_field_and_that_approves(self):
        for label, tenant, switches in (('never observed', bot(45), (True, True)), ('capability off', bot(46, 'Brand Bot'), (True, False)),
                                        ('master switch off', bot(47, 'Brand Bot'), (False, True))):
            with self.subTest(label), flags(*switches):
                view = channel_view(tenant)
                self.assertNotIn('discordBotNickname', view)
                page = Page(tenant)
                page.approve(view)
                self.assertNotIn('discordBotNickname', page.item['decision'])

    def test_a_stale_echo_is_still_refused(self):
        tenant = bot(48, 'Brand Bot')
        with flags():
            view = channel_view(tenant)
            tenant.channel_record['discordBotNickname'] = {'value': 'Renamed Since', 'observedAt': F.NOW + 1}
            with self.assertRaises(AlphaError) as raised:
                Page(tenant).approve(view)
        self.assertEqual(raised.exception.status, 409)
        self.assertIn('nickname changed', str(raised.exception))

    def test_the_view_carries_the_value_and_nothing_internal(self):
        tenant = bot(49, 'Brand Bot')
        tenant.channel_record.update(
            discordSenderEdit={'id': 'claim-internal-id', 'name': 'Pending Name', 'expiresAt': F.NOW + 60,
                               'rateAdmissionId': 'admission-internal-id', 'rateExpiresAt': F.NOW + 70},
            discordSenderRevision='revision-internal', discordSenderName='Saved Nick')
        with flags():
            view = channel_view(tenant)
        text = json.dumps(view)
        self.assertEqual(view['discordBotNickname'], 'Brand Bot')
        for internal in ('observedAt', 'claim-internal-id', 'admission-internal-id', 'revision-internal', 'Pending Name', 'discordSenderEdit',
                         'discordSenderRevision', 'rateAdmissionId'):
            self.assertNotIn(internal, text)
        self.assertIsNone(view['discordSenderName'], 'a bot installation has no webhook name')

    def test_another_workspace_never_learns_the_value(self):
        a, b, c = bot(50, 'Alpha Only Nickname'), bot(51, 'Beta Own Nickname'), bot(52)
        same_server = {'guildId': a.guild}
        with flags():
            views = {name: channel_view(t) for name, t in (('a', a), ('b', b), ('c', c))}
            self.assertEqual(views['b']['discordBotNickname'], 'Beta Own Nickname')
            self.assertNotIn('discordBotNickname', views['c'], 'a connection that observed nothing is shown nothing')
            for name in ('b', 'c'):
                self.assertNotIn('Alpha Only Nickname', json.dumps(views[name]))
            # B cannot approve with A's value, even though it is a real nickname: the check is against B's own observation
            with self.assertRaises(AlphaError) as raised:
                Page(b).approve(views['b'], discordBotNickname='Alpha Only Nickname')
            self.assertEqual(raised.exception.status, 409)
            with self.assertRaises(AlphaError):
                Page(c).approve(views['c'], discordBotNickname='Alpha Only Nickname')
        self.assertTrue(same_server)


class WebhookNameCarrier(unittest.TestCase):
    """R2: the view carries the name a review would freeze now, so with the switch off the page echoes none."""

    def tenant(self, index, name='Approved brand'):
        return F.Tenant(index, name).build()

    def test_with_the_feature_on_the_view_shows_the_saved_name_and_that_approves(self):
        tenant = self.tenant(60)
        with flags():
            view = channel_view(tenant)
            self.assertEqual(view['discordSenderName'], 'Approved brand')
            page = Page(tenant)
            page.approve(view)
            self.assertEqual(page.item['decision']['discordSenderName'], 'Approved brand')
            job = page.queue()
        self.assertEqual(auth.wire_content(job['manifest']).get('username'), 'Approved brand')

    def test_with_the_master_switch_off_and_a_saved_name_the_view_shows_none_and_that_approves(self):
        for switch in ('false', None):                              # explicitly off, and merely unset
            with self.subTest(switch=switch):
                tenant = self.tenant(61 if switch else 62)
                env = {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': switch} if switch else {}
                with patch.dict(os.environ, env):
                    if not switch:
                        os.environ.pop('POSTRIFF_DISCORD_SENDER_NAMES_ENABLED', None)
                    view = channel_view(tenant)
                    self.assertIsNone(view['discordSenderName'], 'the saved name would not be frozen, so it is not offered')
                    page = Page(tenant)
                    page.approve(view)
                    self.assertIsNone(page.item['decision'].get('discordSenderName'))
                    job = page.queue()
                self.assertNotIn('username', auth.wire_content(job['manifest']))

    def test_a_stale_name_is_still_refused(self):
        tenant = self.tenant(63)
        with flags():
            view = channel_view(tenant)
            tenant.channel_record['discordSenderName'] = 'Renamed Since'
            with self.assertRaises(AlphaError) as raised:
                Page(tenant).approve(view)
        self.assertEqual(raised.exception.status, 409)
        self.assertIn('sender name changed', str(raised.exception))

    def test_a_stored_name_that_no_longer_validates_is_not_a_server_error_in_the_view(self):
        tenant = self.tenant(64, 'Discord official')
        with flags():
            view = channel_view(tenant)                         # must not raise: the channels list would break for every member
            self.assertIsNone(view['discordSenderName'])
            with self.assertRaises(AlphaError) as raised:       # the approval says why, with the settings' own code
                Page(tenant).approve(view)
        self.assertEqual((raised.exception.status, raised.exception.code), (400, 'discord_sender_name_invalid'))

    def test_a_connection_without_a_saved_name_shows_none(self):
        tenant = self.tenant(65, None)
        with flags():
            view = channel_view(tenant)
            self.assertIn('discordSenderName', view)
            self.assertIsNone(view['discordSenderName'])
            Page(tenant).approve(view)

    def test_other_platforms_and_the_other_kind_are_untouched(self):
        webhook = channel_view(self.tenant(66))
        self.assertNotIn('discordBotNickname', webhook, 'a webhook connection has no bot nickname')
        youtube = customer_view({'id': 'yt', 'platform': 'YouTube', 'account': 'Synthetic'}, assisted_matrix(), F.NOW)
        self.assertFalse({'discordSenderName', 'discordBotNickname'} & set(youtube))


class HoldReason(unittest.TestCase):
    """R3: the two dispatch holds carry a stable `reason` code on the held event (the English text is unchanged)."""
    CODES = ('discord_sender_names_disabled', 'discord_bot_nickname_changed')

    def test_the_codes_are_the_ones_the_dispatch_guards_raise(self):
        self.assertEqual(tuple(names.HOLD_REASONS), self.CODES)
        with self.assertRaises(AlphaError) as raised:
            with flags(master=False):
                names.assert_sendable({'senderKind': 'webhook', 'discordSenderName': 'Acme Weekly'})
        self.assertEqual(raised.exception.code, 'discord_sender_names_disabled')
        with self.assertRaises(AlphaError) as raised:
            names.assert_nickname_unchanged({'discordBotNickname': 'A'}, {'botNickname': 'B'})
        self.assertEqual(raised.exception.code, 'discord_bot_nickname_changed')

    def test_the_worker_maps_a_preflight_failure_to_its_text_and_code(self):
        from postriff_phase2.hosted_worker import discord_hold
        for code in self.CODES:
            message, reason = discord_hold(AlphaError('Synthetic.', 409, code=code))
            self.assertEqual(reason, code)
            self.assertIn('nothing was posted', message)
        message, reason = discord_hold(AlphaError('Synthetic.', 409, code='discord_connection_required'))
        self.assertIsNone(reason, 'the generic wording stays free of a code')
        self.assertIn('Nothing was posted', message)
        self.assertEqual(discord_hold(RuntimeError('no code at all'))[1], None)
        self.assertIn('no longer the one this post was approved under', discord_hold(AlphaError('x', 409, code='discord_bot_nickname_changed'))[0])
        self.assertIn('switched off', discord_hold(AlphaError('x', 409, code='discord_sender_names_disabled'))[0])

    def test_normalize_result_keeps_only_a_known_reason_of_a_held_discord_result(self):
        from postriff_phase2.outcomes import normalize_result
        job = {'manifest': {'platform': 'Discord'}}
        held = {'state': 'held', 'confirmed': 'Nothing was posted.', 'discordDeliveryEvidence': 'not_sent'}
        for code in self.CODES:
            self.assertEqual(normalize_result({**held, 'reason': code}, job)['reason'], code)
        for bad in ('some_other_code', '', None, 5, ['discord_bot_nickname_changed'], 'DISCORD_BOT_NICKNAME_CHANGED'):
            self.assertNotIn('reason', normalize_result({**held, 'reason': bad}, job), repr(bad))
        self.assertNotIn('reason', normalize_result(held, job))
        # a reason only describes a hold that sent nothing, and only on Discord
        for state, evidence in (('failed', 'not_sent'), ('scheduled', 'not_sent'), ('held', 'rejected'), ('failed', 'rejected')):
            self.assertNotIn('reason', normalize_result({'state': state, 'confirmed': 'x', 'discordDeliveryEvidence': evidence,
                                                         'reason': 'discord_bot_nickname_changed'}, job), (state, evidence))
        sent = {'state': 'provider_accepted', 'confirmed': 'Accepted', 'reference': 'x/y', 'discordDeliveryEvidence': 'accepted',
                'reason': 'discord_bot_nickname_changed'}
        self.assertNotIn('reason', normalize_result(sent, job))
        other = {'manifest': {'platform': 'Mastodon'}}
        self.assertNotIn('reason', normalize_result({'state': 'held', 'confirmed': 'Held.', 'reason': 'discord_bot_nickname_changed'}, other))

    def test_the_event_records_the_reason_next_to_the_english_text(self):
        from postriff_phase2.hosted_worker import PostgresWorker
        worker = SimpleNamespace(clock=lambda: 100.0, discord_workers=False, discord_stats={'held': 0, 'uncertain': 0})
        job = {'state': 'scheduled', 'manifest': {'platform': 'Discord'}}
        PostgresWorker._event(worker, job, 'held', 'The Rafii bot’s server nickname is no longer the one this post was approved under.',
                              at=101.0, reason='discord_bot_nickname_changed')
        self.assertEqual(job['events'][-1], {'at': 101.0, 'state': 'held', 'execution': 'hosted-worker',
                                             'message': 'The Rafii bot’s server nickname is no longer the one this post was approved under.',
                                             'reason': 'discord_bot_nickname_changed'})
        PostgresWorker._event(worker, job, 'held', 'Generic.', at=102.0)
        self.assertNotIn('reason', job['events'][-1], 'an event without a reason has no reason key')

    def test_the_submit_time_guard_also_carries_it(self):
        tenant = F.Tenant(70, 'Acme Weekly').build()
        world = F.World([tenant])
        with flags():
            job = tenant.approve()
            prepared = world.social.prepare_discord_dispatch(job['manifest'])
        prepared['intent'] = {'id': 'synthetic-lease', 'manifestDigest': auth.digest(job['manifest']), 'publicationId': job['id']}
        with flags(master=False):
            result = world.social.submit_discord_authorized(job['manifest'], prepared)
        self.assertEqual((result['state'], result['discordDeliveryEvidence'], result.get('reason')),
                         ('held', 'not_sent', 'discord_sender_names_disabled'))
        self.assertIn('switched off', result['confirmed'])
        self.assertEqual(world.wire.posts, [])


if __name__ == '__main__':
    unittest.main()
