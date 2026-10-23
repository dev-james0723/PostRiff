"""Per-send exactness of the webhook sender name, in memory: every execute-webhook request carries the `username` of ITS
OWN approved manifest and nothing else supplies one. Real review, approval, preflight and create code; a synthetic
Discord that records each request whole. The same properties on a real PostgreSQL with the W-02 lane are in
test_discord_sender_name_postgres.py.
"""
import copy
import hashlib
import json
import os
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import discord_sender_name_fixture as F
from postriff_alpha.domain import AlphaError
from postriff_phase2.discord import authorization as auth
from postriff_phase2.discord import sender_names as names

ROOT = Path(__file__).resolve().parents[1]
RC1_AUTHORIZATION = ROOT / 'tests/phase2/fixtures/authorization_2a5a523d.py.txt'


@contextmanager
def switch(on):
    with patch.dict(os.environ, {'POSTRIFF_DISCORD_SENDER_NAMES_ENABLED': 'true' if on else 'false'}):
        yield


def rc1_authorization():
    """The release candidate's own authorization module (2a5a523d), as a rollback would run it."""
    source = RC1_AUTHORIZATION.read_bytes()
    assert b'discordSenderName' not in source, 'the pinned RC1 module must predate sender names'
    namespace = {'__name__': 'postriff_phase2.discord.authorization_2a5a523d', '__package__': 'postriff_phase2.discord',
                 '__builtins__': __builtins__}
    exec(compile(source, str(RC1_AUTHORIZATION), 'exec'), namespace)
    return type('RC1', (), namespace)


def body_keys(post):
    return set(post['body'])


class PerSendWire(unittest.TestCase):
    def named_job(self, name='Acme Weekly', index=1, **kwargs):
        tenant = F.Tenant(index, name, **kwargs).build()
        with switch(True):
            job = tenant.approve()
        return tenant, job

    # (1) the feature ON/OFF x per-connection setting matrix ---------------------------------------------------------

    def test_switch_by_setting_matrix_from_review_to_wire(self):
        for setting in (None, 'Acme Weekly'):
            for on_at_review in (True, False):
                for on_at_dispatch in (True, False):
                    with self.subTest(setting=setting, on_at_review=on_at_review, on_at_dispatch=on_at_dispatch):
                        tenant = F.Tenant(1, setting).build()
                        world = F.World([tenant])
                        with switch(on_at_review):
                            job = tenant.approve()
                        frozen = setting if on_at_review else None
                        self.assertEqual(job['manifest'].get('discordSenderName'), frozen)
                        self.assertEqual(auth.wire_content(job['manifest']).get('username'), frozen)
                        with switch(on_at_dispatch):
                            if frozen is not None and not on_at_dispatch:
                                with self.assertRaises(AlphaError) as raised:
                                    world.dispatch(job)
                                self.assertEqual((raised.exception.status, raised.exception.code),
                                                 (409, 'discord_sender_names_disabled'))
                                self.assertEqual(world.wire.posts, [])
                                continue
                            result = world.dispatch(job)
                        self.assertEqual(result['state'], 'provider_accepted', result)
                        self.assertEqual(len(world.wire.posts), 1)
                        post = world.wire.posts[0]
                        self.assertEqual(body_keys(post), {'content', 'allowed_mentions', 'flags'} | ({'username'} if frozen else set()))
                        self.assertEqual(post['body'].get('username'), frozen)
                        self.assertEqual(post['body']['allowed_mentions'], {'parse': []})
                        self.assertEqual((post['hook'], post['channel']), (tenant.hook, tenant.channel))

    def test_a_held_named_post_is_never_stripped_or_sent_under_another_name(self):
        """Even a caller that skips the preflight (the final guard inside the create) cannot send it."""
        tenant, job = self.named_job()
        world = F.World([tenant])
        prepared = world.social.prepare_discord_dispatch(job['manifest'])
        prepared['intent'] = {'id': 'synthetic-lease', 'manifestDigest': auth.digest(job['manifest']),
                              'publicationId': job['id']}
        with switch(False):
            result = world.social.submit_discord_authorized(job['manifest'], prepared)
        self.assertEqual((result['state'], result['discordDeliveryEvidence']), ('held', 'not_sent'))
        self.assertIn('switched off', result['confirmed'])
        self.assertEqual(world.wire.posts, [])
        with switch(True):   # switching back on lets the very same approval proceed with the very same name
            self.assertEqual(world.social.submit_discord_authorized(job['manifest'], prepared)['state'], 'provider_accepted')
        self.assertEqual(world.wire.posts[0]['body']['username'], 'Acme Weekly')

    # (2) bot mode ---------------------------------------------------------------------------------------------------

    def test_bot_mode_never_carries_a_username_even_with_a_saved_nickname_record(self):
        tenant = F.Tenant(2, 'Remembered Nickname', kind='bot').build()    # the installation card records the last nickname
        world = F.World([tenant])
        with switch(True):
            job = tenant.approve()
        self.assertNotIn('discordSenderName', job['manifest'])
        self.assertNotIn('username', auth.wire_content(job['manifest']))
        with switch(True):
            self.assertEqual(world.dispatch(job)['state'], 'provider_accepted')
        post = world.wire.posts[0]
        self.assertEqual(post['bot_channel'], tenant.channel)
        self.assertNotIn('username', post['body'])
        forged = copy.deepcopy(job['manifest'])
        forged['discordSenderName'] = 'Forged Nickname'
        with self.assertRaises(AlphaError):
            auth.wire_content(forged)
        self.assertFalse(auth.manifest_current(tenant.state, tenant.channel_record, forged))

    # (3) a change after approval, reconnect, deletion -------------------------------------------------------------

    def test_a_name_changed_after_approval_never_reaches_the_wire_or_the_readback(self):
        tenant, job = self.named_job('Original brand')
        world = F.World([tenant])
        tenant.channel_record['discordSenderName'] = 'New brand'
        with switch(True):
            result = world.dispatch(job)
            verified = world.social.reconcile_discord(job['manifest'], {**job, 'providerReference': result['reference']})
        self.assertEqual(world.wire.posts[0]['body']['username'], 'Original brand')
        self.assertEqual(verified['state'], 'verified')
        # A later review does use the new name.
        with switch(True):
            self.assertEqual(tenant.review()['manifest']['discordSenderName'], 'New brand')

    def test_an_approval_keeps_the_name_its_review_showed(self):
        tenant = F.Tenant(9, 'Name X').build()
        world = F.World([tenant])
        with switch(True):
            entry = tenant.review()
            self.assertEqual(entry['manifest']['discordSenderName'], 'Name X')
            tenant.channel_record['discordSenderName'] = 'Name Y'      # the setting changes between review and approval
            job = tenant.approve(entry)
            self.assertEqual(job['manifest']['discordSenderName'], 'Name X')
            self.assertEqual(world.dispatch(job)['state'], 'provider_accepted')
        self.assertEqual(world.wire.posts[0]['body']['username'], 'Name X')

    def test_automation_decisions_follow_the_switch_without_ever_changing_the_approved_name(self):
        """campaigns._decide and publisher.commit with the feature on and off (the upstream test covers on)."""
        from postriff_phase2 import campaigns, publisher
        for at_decision, at_commit, expected in [(True, True, 'Approved brand'), (False, False, None), (False, True, None),
                                                 (True, False, AlphaError)]:
            with self.subTest(at_decision=at_decision, at_commit=at_commit):
                tenant = F.Tenant(10, 'Approved brand').build()
                state, channel = tenant.state, tenant.channel_record
                destination = auth.destination(state, channel, channel['defaultDestinationId'])
                task = {'id': 'synthetic-task', 'status': 'active', 'schedule': {'timeZone': 'UTC'}}
                item = {'key': 'synthetic-item', 'platform': 'Discord', 'channelId': channel['id'],
                        'variantId': tenant.variant['id'], 'state': 'ready_for_review', 'publishAt': F.NOW + 300}
                run = {'id': 'synthetic-run', 'taskId': task['id'], 'items': [item]}
                root = campaigns._root(state)
                root['recurringTasks'].append(task)
                root['occurrences'].append(run)
                shown = 'Approved brand' if at_decision else None      # what the page displayed (nothing while off)
                body = {'occurrenceId': run['id'], 'itemKey': item['key'], 'decision': 'approve', 'confirmed': True,
                        'variantRevision': 1, 'excludedUnknowns': [], 'acknowledgedWarnings': [],
                        'destinationId': destination['id'], 'destinationGeneration': destination['resourceGeneration'],
                        'publishAt': F.NOW + 300, 'discordSenderName': shown}
                with switch(at_decision):
                    campaigns._decide(state, root, body, F.ACTOR, F.NOW)
                channel['discordSenderName'] = 'Changed afterwards'
                with switch(at_commit):
                    if expected is AlphaError:
                        with self.assertRaises(AlphaError):
                            publisher.commit(tenant.engine, state, F.ACTOR, {'occurrenceId': run['id'], 'itemKey': item['key']}, F.NOW + 60)
                        continue
                    queued = publisher.commit(tenant.engine, state, F.ACTOR, {'occurrenceId': run['id'], 'itemKey': item['key']}, F.NOW + 60)
                job = next(j for j in state['phase2']['jobs'] if j['id'] == queued['jobId'])
                self.assertEqual(auth.wire_content(job['manifest']).get('username'), expected)
                self.assertTrue(auth.job_authorized(state, channel, job))

    def test_nothing_mutable_or_process_global_is_consulted_when_executing(self):
        tenant, job = self.named_job('Original brand')
        world = F.World([tenant])
        tenant.channel_record['discordSenderName'] = 'POISONED CONNECTION VALUE'

        def consulted(*_args, **_kwargs):
            raise AssertionError('execution consulted a settings value')
        with switch(True), patch.object(names, 'frozen_webhook_name', consulted, create=True), \
                patch.object(names.SenderNames, 'get', consulted), patch.object(names.SenderNames, 'custody', consulted):
            result = world.dispatch(job)
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(world.wire.posts[0]['body']['username'], 'Original brand')

    def test_reconnect_with_a_new_authorization_generation_blocks_the_old_approval(self):
        tenant, job = self.named_job()
        world = F.World([tenant])
        tenant.generation = str(uuid.uuid4())                 # the credential row now carries a new generation
        with switch(True), self.assertRaises(AlphaError):
            world.dispatch(job)
        self.assertEqual(world.wire.posts, [])
        tenant.channel_record['discordAuthorizationGeneration'] = tenant.generation
        self.assertFalse(auth.job_authorized(tenant.state, tenant.channel_record, job))

    def test_webhook_deleted_before_the_run_sends_nothing(self):
        tenant, job = self.named_job()
        world = F.World([tenant])
        world.wire.deleted.add(tenant.hook)
        with switch(True), self.assertRaises(AlphaError) as raised:
            world.dispatch(job)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(world.wire.posts, [])

    def test_webhook_deleted_during_the_run_is_one_rejected_create_never_retried(self):
        tenant, job = self.named_job()
        world = F.World([tenant])
        with switch(True):
            prepared = world.social.prepare_discord_dispatch(job['manifest'])
            prepared['intent'] = {'id': 'synthetic-lease', 'manifestDigest': auth.digest(job['manifest']),
                                  'publicationId': job['id']}
            world.wire.deleted.add(tenant.hook)
            result = world.social.submit_discord_authorized(job['manifest'], prepared)
        self.assertEqual((result['state'], result['discordDeliveryEvidence']), ('held', 'rejected'))
        self.assertEqual(len(world.wire.posts), 0)     # the deleted webhook answered 404 before recording an execute

    # (4) missing or invalid stored name ------------------------------------------------------------------------------

    def test_missing_name_uses_the_webhooks_own_name_and_says_so_in_the_manifest(self):
        tenant = F.Tenant(3, None).build()
        self.assertNotIn('discordSenderName', tenant.channel_record)
        world = F.World([tenant])
        with switch(True):
            job = tenant.approve()
            self.assertNotIn('discordSenderName', job['manifest'])
            result = world.dispatch(job)
        post = world.wire.posts[0]
        self.assertNotIn('username', post['body'])
        self.assertEqual(world.wire.messages[result['reference'].split('/')[1]]['author']['username'], F.DEFAULT_HOOK_NAME)

    def test_an_invalid_stored_name_holds_the_review_and_nothing_is_sent_under_any_name(self):
        for bad in ('', ' ', 'Discord', 'clyde', 'a' * 81, 5, None, '@everyone', 'www.example.com'):
            with self.subTest(bad=bad):
                tenant = F.Tenant(4, None).build()
                tenant.channel_record['discordSenderName'] = bad
                world = F.World([tenant])
                with switch(True), self.assertRaises(AlphaError) as raised:
                    tenant.review()
                self.assertEqual(raised.exception.code, 'discord_sender_name_invalid')
                self.assertEqual(world.wire.posts, [])
                with switch(False):               # off: the stored value is not applied, so it cannot block
                    self.assertNotIn('discordSenderName', tenant.review()['manifest'])

    def test_a_frozen_name_that_stops_validating_is_held_before_any_request(self):
        """Rules tightened after approval: fail closed in the preflight, so the worker holds with nothing posted."""
        tenant, job = self.named_job('Acme Weekly')
        world = F.World([tenant])
        with switch(True), patch.object(names, '_RESERVED_PARTS', ('acme',), create=True), self.assertRaises(AlphaError) as raised:
            world.dispatch(job)
        self.assertEqual(raised.exception.code, 'discord_sender_name_invalid')
        self.assertEqual(world.wire.posts, [])

    # (5) compatibility and rollback -----------------------------------------------------------------------------------

    def test_an_approval_without_an_override_is_byte_identical_to_rc1(self):
        rc1 = rc1_authorization()
        tenant = F.Tenant(5, None).build()
        with switch(True):
            job = tenant.approve()
        manifest = job['manifest']
        self.assertEqual(rc1.wire_content(manifest), auth.wire_content(manifest))
        self.assertEqual(rc1.digest(rc1.wire_content(manifest)), manifest['discord']['wireDigest'])
        self.assertTrue(rc1.manifest_current(tenant.state, tenant.channel_record, manifest))
        self.assertTrue(rc1.job_authorized(tenant.state, tenant.channel_record, job))

    def test_rollback_to_the_frozen_rc1_worker_holds_every_named_manifest_and_only_those(self):
        rc1 = rc1_authorization()
        named, named_job = self.named_job('Acme Weekly', 6)
        plain = F.Tenant(7, None, kind='bot').build()
        with switch(True):
            plain_job = plain.approve()
        # RC1 builds the wire without the name: its digest cannot equal the approved one, so it holds (never sends
        # the post under the webhook's own name instead).
        rc1_wire = rc1.wire_content(named_job['manifest'])
        self.assertNotIn('username', rc1_wire)
        self.assertNotEqual(rc1.digest(rc1_wire), named_job['manifest']['discord']['wireDigest'])
        self.assertFalse(rc1.manifest_current(named.state, named.channel_record, named_job['manifest']))
        self.assertFalse(rc1.job_authorized(named.state, named.channel_record, named_job))
        # ... while RC2 keeps authorizing it, and RC1 still authorizes an unnamed (bot) approval.
        self.assertTrue(auth.job_authorized(named.state, named.channel_record, named_job))
        self.assertTrue(rc1.job_authorized(plain.state, plain.channel_record, plain_job))

    # (6) read-back ----------------------------------------------------------------------------------------------------

    def test_switching_off_after_the_create_never_blocks_the_receipt_check(self):
        tenant, job = self.named_job('Acme Weekly')
        world = F.World([tenant])
        with switch(True):
            result = world.dispatch(job)
        with switch(False):
            verified = world.social.reconcile_discord(job['manifest'], {**job, 'providerReference': result['reference']})
        self.assertEqual(verified['state'], 'verified')

    def test_a_provider_that_rewrites_the_name_is_not_verified_and_is_not_retried(self):
        tenant, job = self.named_job('Acme Weekly')
        world = F.World([tenant])
        world.wire.rewrite_username = str.upper
        with switch(True):
            result = world.dispatch(job)
            again = world.social.reconcile_discord(job['manifest'], {**job, 'providerReference': result['reference']})
        self.assertEqual((result['state'], result['discordDeliveryEvidence']), ('uncertain', 'accepted'))
        self.assertNotEqual(again['state'], 'verified')
        self.assertEqual(len(world.wire.posts), 1)

    def test_provider_400_for_a_name_is_a_rejected_create_not_an_uncertain_one(self):
        tenant, job = self.named_job('Acme Weekly')
        world = F.World([tenant])
        world.wire.fail_post = lambda _tenant, _body: {'status': 400, 'body': {'code': 50035}, 'headers': {}}
        with switch(True):
            result = world.dispatch(job)
        self.assertEqual((result['state'], result['discordDeliveryEvidence']), ('failed', 'rejected'))
        self.assertEqual(len(world.wire.posts), 1)

    # (7) many tenants at once ---------------------------------------------------------------------------------------

    def test_concurrent_creates_each_carry_exactly_their_own_name(self):
        named = [(index, f'Brand {index} Weekly') if index % 3 else (index, None) for index in range(1, 25)]
        tenants = [F.Tenant(index, name).build(text=f'Post for tenant {index}') for index, name in named]
        world = F.World(tenants)
        jobs = {}
        with switch(True):
            for tenant in tenants:
                jobs[tenant.workspace] = tenant.approve()
        barrier, results, failures = threading.Barrier(len(tenants), timeout=60), {}, []

        def run(tenant):
            try:
                barrier.wait()
                with switch(True):
                    results[tenant.workspace] = world.dispatch(jobs[tenant.workspace], lease=f'lease-{tenant.index}')
            except BaseException as error:
                failures.append((tenant.index, error))
        threads = [threading.Thread(target=run, args=(t,)) for t in tenants]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertEqual(failures, [])
        self.assertEqual({r['state'] for r in results.values()}, {'provider_accepted'})
        self.assertEqual(len(world.wire.posts), len(tenants))
        by_workspace = {p['workspace']: p for p in world.wire.posts}
        self.assertEqual(len(by_workspace), len(tenants), 'one create per tenant')
        every_name = [t.name for t in tenants if t.name]
        for tenant in tenants:
            post = by_workspace[tenant.workspace]
            self.assertEqual((post['hook'], post['guild'], post['channel']), (tenant.hook, tenant.guild, tenant.channel))
            self.assertEqual(post['body'].get('username'), tenant.name)
            self.assertEqual(post['body']['content'], f'Post for tenant {tenant.index}')
            serialized = json.dumps(post)
            for other in every_name:
                if other != tenant.name:
                    self.assertNotIn(other, serialized, 'another customer\'s name appeared in this request')
            message = world.wire.messages[results[tenant.workspace]['reference'].split('/')[1]]
            self.assertEqual(message['author']['username'], tenant.name or F.DEFAULT_HOOK_NAME)
            self.assertEqual(message['author']['id'], tenant.hook)

    def test_creates_race_with_settings_edits_and_still_carry_the_approved_names(self):
        tenants = [F.Tenant(index, f'Approved {index} Name').build() for index in range(1, 9)]
        world = F.World(tenants)
        with switch(True):
            jobs = {t.workspace: t.approve() for t in tenants}
        stop = threading.Event()

        def editor():
            counter = 0
            while not stop.is_set():
                counter += 1
                for tenant in tenants:
                    tenant.channel_record['discordSenderName'] = f'Edited {tenant.index} Name {counter}'
        thread = threading.Thread(target=editor)
        thread.start()
        try:
            with switch(True):
                for tenant in tenants:
                    self.assertEqual(world.dispatch(jobs[tenant.workspace])['state'], 'provider_accepted')
        finally:
            stop.set()
            thread.join(timeout=30)
        for post in world.wire.posts:
            tenant = world.tenants[post['workspace']]
            self.assertEqual(post['body']['username'], f'Approved {tenant.index} Name')

    def test_content_that_mentions_everyone_still_cannot_ping(self):
        tenant = F.Tenant(8, 'Acme Weekly').build(text='Hello @everyone and @here')
        with switch(True):
            job = tenant.approve()
        self.assertIn('@everyone', job['manifest']['payload']['text'])
        world = F.World([tenant])
        with switch(True):
            world.dispatch(job)
        self.assertEqual(world.wire.posts[0]['body']['allowed_mentions'], {'parse': []})


if __name__ == '__main__':
    unittest.main()
