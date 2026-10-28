"""Owner decision (reply 16, 2026-10-28): a workspace may have at most 300 approved, non-terminal Discord posts scheduled
within any one sliding hour; beyond that the approval is refused with 409 discord_workspace_hourly_ceiling instead of queued.

Why: a hot workspace is served one post at a time. Measured on the hosted runner it sent 292 of 300 posts, and only 236 of
1,000 queued posts inside the one-hour approval window, so the tail of a larger hour is held at expiry and the customer sees
"approve again". Before: the manual approval, the reply approval and the automation decision accepted any number.

Offline and synthetic: no database, no Discord. The 300 in the approval tests is a literal on purpose, so that on the old code
they fail by accepting the 301st post rather than by a missing name. The real-lock race and the all-or-nothing bulk approval
are in tests/phase2/postgres_discord_authorization.py."""
import copy
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2 import campaigns, publisher
from postriff_phase2.discord import authorization as auth
from postriff_phase2.discord.engagement import KEY
from test_discord_engagement import EngagementFixture
from test_discord_publish_authorization import ACTOR, FIRST, NOW, SECOND, fixture, review, approve

HOUR = 3600
T = NOW + 300  # the time of the default review in the shared helpers
CODE = 'discord_workspace_hourly_ceiling'


def fake(index, at, state='scheduled', platform='Discord', channel='other-connection', **extra):
    """A minimal waiting job. Real approvals are used wherever a test needs one; these only fill an hour."""
    return {'id': f'fill-{index}', 'state': state, 'events': [], 'attempts': [], 'approvedAt': 0,
            'manifest': {'platform': platform, 'channelId': channel, 'idempotencyKey': f'fill-key-{index}',
                         'timing': {'timestamp': at}}, **extra}


def fill(state, count, at, **kw):
    start = len(state['phase2']['jobs'])
    state['phase2']['jobs'].extend(fake(start + i, at, **kw) for i in range(count))


def bare(jobs):
    return {'phase2': {'jobs': jobs}}


def stack(count, at, **kw):
    return [fake(i, at, **kw) for i in range(count)]


class Rule(unittest.TestCase):
    def refused(self, jobs, at=T, **kw):
        with self.assertRaises(AlphaError) as raised:
            auth.assert_workspace_hourly_ceiling(bare(jobs), at, **kw)
        return raised.exception

    def test_the_numbers_the_code_and_the_state_vocabulary_are_pinned(self):
        self.assertEqual(auth.WORKSPACE_HOURLY_CEILING, 300)
        self.assertEqual(auth.WORKSPACE_HOURLY_WINDOW_SECONDS, 3600)
        self.assertEqual(auth.WORKSPACE_HOURLY_CODE, CODE)
        self.assertEqual(auth.PENDING_STATES, ('approved', 'scheduled', 'claimed', 'submitting'))

    def test_exactly_the_ceiling_is_allowed_and_one_more_is_refused(self):
        auth.assert_workspace_hourly_ceiling(bare(stack(299, T)), T)  # becomes 300
        error = self.refused(stack(300, T))  # would become 301
        self.assertEqual((error.status, error.code), (409, CODE))

    def test_the_window_slides_it_is_not_a_calendar_hour(self):
        at = (NOW // HOUR + 1) * HOUR + 600  # ten minutes into a clock hour
        earlier = [fake(i, at - 1800) for i in range(150)]  # the previous clock hour
        later = [fake(150 + i, at + 1700) for i in range(150)]  # the same clock hour as `at`
        # [at-1800, at+1800) holds 150 + 150 + this post, although no clock hour holds more than 151
        self.refused(earlier + later, at)
        auth.assert_workspace_hourly_ceiling(bare(earlier + later[:-1]), at)  # 150 + 149 + 1 = 300 fits

    def test_the_window_is_half_open_posts_exactly_an_hour_apart_do_not_share_one(self):
        auth.assert_workspace_hourly_ceiling(bare(stack(300, T - HOUR)), T)
        auth.assert_workspace_hourly_ceiling(bare(stack(300, T + HOUR)), T)
        self.refused(stack(300, T - HOUR + 1))  # one second closer: the same window
        self.refused(stack(300, T + HOUR - 1))
        # a window that starts at an earlier post ends just before the post exactly an hour after it
        auth.assert_workspace_hourly_ceiling(bare(stack(299, T - 1800) + [fake(900, T + 1800)]), T)
        self.refused(stack(299, T - 1800) + [fake(900, T + 1799)])

    def test_a_window_anywhere_around_the_new_post_counts_not_only_the_one_that_starts_at_it(self):
        # 200 posts before and 100 after, all within one hour of each other and of the new post
        self.refused(stack(200, T - 1500) + [fake(900 + i, T + 1500) for i in range(100)])
        # 300 posts spread evenly over an hour (one every 12 seconds) leave no room anywhere in it
        spread = [fake(i, T - 1800 + 12 * i) for i in range(300)]
        self.refused(spread, T)
        auth.assert_workspace_hourly_ceiling(bare(spread[:-2]), T)

    def test_only_posts_that_still_need_the_lane_count(self):
        for state in ('approved', 'scheduled', 'claimed', 'submitting'):
            with self.subTest(counted=state):
                self.refused(stack(300, T, state=state))
        for state in ('verified', 'failed', 'canceled', 'held', 'uncertain', 'provider_accepted', 'published'):
            with self.subTest(not_counted=state):
                auth.assert_workspace_hourly_ceiling(bare(stack(300, T, state=state)), T)
        # a preview deployment holds an approved post until someone dispatches it: it is still waiting for the lane
        self.refused(stack(300, T, state='held', previewDispatchPending=True))
        auth.assert_workspace_hourly_ceiling(bare(stack(300, T, state='held', previewDispatchPending=False)), T)

    def test_other_providers_are_not_counted_and_every_discord_connection_is(self):
        auth.assert_workspace_hourly_ceiling(bare(stack(300, T, platform='Mastodon')), T)
        self.refused([fake(i, T, channel=f'connection-{i % 7}') for i in range(300)])

    def test_reserved_times_count_like_posts(self):
        jobs = stack(299, T)
        self.refused(jobs, T, also=[T])
        auth.assert_workspace_hourly_ceiling(bare(jobs), T, also=[T + 2 * HOUR])
        auth.assert_workspace_hourly_ceiling(bare(jobs), T, also=iter(()))
        self.refused(stack(150, T), T, also=(T for _ in range(150)))

    def test_a_workspace_already_over_the_ceiling_is_refused_for_that_hour_only(self):
        legacy = stack(1000, T)  # queued before the rule existed (the hosted-runner measurement held 1,000)
        self.refused(legacy)
        self.refused(legacy, T + 1800)
        auth.assert_workspace_hourly_ceiling(bare(legacy), T + HOUR)
        auth.assert_workspace_hourly_ceiling(bare(legacy), T - HOUR)

    def test_unreadable_entries_are_ignored_and_a_bad_time_is_refused(self):
        odd = [None, 'x', {}, {'state': 'scheduled'}, {'state': 'scheduled', 'manifest': 'x'},
               {'state': 'scheduled', 'manifest': {'platform': 'Discord'}},
               {'state': 'scheduled', 'manifest': {'platform': 'Discord', 'timing': {'timestamp': 'soon'}}},
               {'state': 'scheduled', 'manifest': {'platform': 'Discord', 'timing': {'timestamp': float('nan')}}},
               {'state': 'scheduled', 'manifest': {'platform': 'Discord', 'timing': {'timestamp': True}}}]
        auth.assert_workspace_hourly_ceiling(bare(odd), T)
        for state in ({}, {'phase2': {}}, {'phase2': {'jobs': None}}):
            auth.assert_workspace_hourly_ceiling(state, T)
        for bad in (None, 'soon', float('nan'), float('inf'), True):
            with self.subTest(candidate=bad), self.assertRaises(AlphaError):
                auth.assert_workspace_hourly_ceiling(bare([]), bad)

    def test_the_refusal_names_the_number_says_what_to_do_and_has_no_retry_hint(self):
        error = self.refused(stack(300, T))
        self.assertIn('300', str(error))
        self.assertIn('Approve fewer posts in that hour', str(error))
        self.assertIn('spread them', str(error))
        self.assertNotIn('retry', str(error).lower())
        self.assertFalse(hasattr(error, 'retry_after'))
        self.assertEqual(error.public_fields, {'limit': 300, 'windowSeconds': 3600})
        self.assertFalse({'error', 'code', 'retryAfter'} & set(error.public_fields))  # these join the JSON body of hosted_app

    def test_the_ceiling_is_read_when_the_check_runs_so_the_race_gate_can_lower_it(self):
        with patch.object(auth, 'WORKSPACE_HOURLY_CEILING', 2):
            auth.assert_workspace_hourly_ceiling(bare(stack(1, T)), T)
            error = self.refused(stack(2, T))
        self.assertEqual(error.public_fields['limit'], 2)
        self.assertIn(' 2 ', str(error))


class Approval(unittest.TestCase):
    def setUp(self):
        self.engine, self.state, self.channel, self.variant = fixture()

    def review(self, target=FIRST, at=T):
        return review(self.engine, self.state, self.channel, self.variant, target, at)

    def test_a_manual_approval_into_a_full_hour_is_refused_and_changes_nothing(self):
        fill(self.state, 300, T)
        entry = self.review()  # preparing the review is only a draft of the approval: it is allowed
        before = copy.deepcopy(self.state['phase2']['jobs'])
        with self.assertRaises(AlphaError) as raised:
            approve(self.engine, self.state, entry)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, CODE))
        self.assertEqual(self.state['phase2']['jobs'], before)
        self.assertEqual(entry['status'], 'needs_review')
        self.assertNotIn('jobId', entry)

    def test_the_last_place_is_granted_once(self):
        fill(self.state, 298, T)
        first = approve(self.engine, self.state, self.review(FIRST, T))  # the 299th
        second = approve(self.engine, self.state, self.review(SECOND, T + 60))  # the 300th
        self.assertEqual((first['state'], second['state']), ('scheduled', 'scheduled'))
        with self.assertRaises(AlphaError) as raised:
            approve(self.engine, self.state, self.review(FIRST, T + 120))  # the 301st
        self.assertEqual(raised.exception.code, CODE)

    def test_a_cancelled_post_frees_its_place_so_a_move_inside_a_full_hour_works(self):
        fill(self.state, 299, T)
        job = approve(self.engine, self.state, self.review(FIRST, T))  # the 300th
        moved = self.review(FIRST, T + 600)
        with self.assertRaises(AlphaError):  # approving the new time first would be a 301st
            approve(self.engine, self.state, moved)
        # a move is a cancel followed by an approval (nothing moves a job in place), so it never needs room for both
        self.engine.apply_phase2(None, self.state, 'cancel', {'jobId': job['id']}, {'user_id': ACTOR})
        self.assertEqual(job['state'], 'canceled')
        self.assertEqual(approve(self.engine, self.state, moved)['state'], 'scheduled')

    def test_a_different_hour_is_not_affected_by_a_full_one(self):
        fill(self.state, 300, T)
        later = approve(self.engine, self.state, self.review(FIRST, T + HOUR))
        self.assertEqual(later['state'], 'scheduled')

    def test_approving_an_already_approved_review_again_is_not_a_new_post(self):
        fill(self.state, 299, T)
        entry = self.review()
        job = approve(self.engine, self.state, entry)  # fills the hour exactly
        again = approve(self.engine, self.state, entry)  # an idempotent repeat links to the same job
        self.assertEqual(again['id'], job['id'])
        self.assertEqual(len(self.state['phase2']['jobs']), 300)

    def test_a_bulk_approval_that_crosses_the_ceiling_is_refused(self):
        fill(self.state, 298, T)
        entries = [self.review(FIRST, T + 60 * i) for i in range(3)]
        with self.assertRaises(AlphaError) as raised:
            self.engine.apply_phase2(None, self.state, 'approve_many', {'confirmed': True, 'reviews': [
                {'reviewId': e['id'], 'digest': e['digest']} for e in entries]}, {'user_id': ACTOR})
        self.assertEqual(raised.exception.code, CODE)
        self.assertEqual(entries[2]['status'], 'needs_review')  # the one that crossed was never approved

    def test_the_site_agent_cannot_prepare_or_move_a_discord_post(self):
        """Guard pin. Its proposal builds the review without a destination, and Discord refuses that, so this path never
        creates the approval. If this stops refusing, the proposal builder must pre-check the ceiling before it cancels the
        post it moves (the approval itself is checked either way)."""
        from postriff_phase2.site_agent import proposals

        def commands(state, actor, action, payload):
            return self.engine.apply_phase2(None, state, action.removeprefix('p2_'), payload, {'user_id': actor})
        built = proposals.build_schedule(self.state, variant=self.variant, channel=self.channel, local_time='2027-01-15T18:00',
                                         zone='UTC', actor=ACTOR, now=NOW, commands=commands)
        self.assertIn('refuse', built)


class AutomationItem(unittest.TestCase):
    def setUp(self):
        self.engine, self.state, self.channel, self.variant = fixture()
        self.target = next(d for d in self.channel['discordDestinations'] if d['channelId'] == FIRST)
        self.task = {'id': 'synthetic-task', 'status': 'active', 'schedule': {'timeZone': 'UTC'}}
        self.root = campaigns._root(self.state)
        self.root['recurringTasks'].append(self.task)

    def item(self, key='synthetic-item', at=T):
        item = {'key': key, 'platform': 'Discord', 'channelId': self.channel['id'], 'variantId': self.variant['id'],
                'state': 'ready_for_review', 'publishAt': at}
        run = {'id': 'run-' + key, 'taskId': self.task['id'], 'items': [item]}
        self.root['occurrences'].append(run)
        return run, item

    def reserve(self, count, at=T, **overrides):
        """Posts a person approved whose job does not exist yet: queue commit creates it shortly before the publish time."""
        items = [{'key': f'reserved-{i}', 'platform': 'Discord', 'state': 'approved', 'jobId': None,
                  'decision': {'decision': 'approve', 'timing': {'timestamp': at}}, **overrides} for i in range(count)]
        self.root['occurrences'].append({'id': 'reserved-run', 'taskId': 'someone-else', 'items': items})

    def decide(self, run, item, at=T):
        return campaigns._decide(self.state, self.root, {
            'occurrenceId': run['id'], 'itemKey': item['key'], 'decision': 'approve', 'confirmed': True, 'variantRevision': 1,
            'excludedUnknowns': [], 'acknowledgedWarnings': [], 'destinationId': self.target['id'],
            'destinationGeneration': self.target['resourceGeneration'], 'publishAt': at}, ACTOR, NOW)

    def test_a_decision_into_a_full_hour_is_refused_before_it_is_promised(self):
        fill(self.state, 300, T)
        run, item = self.item()
        with self.assertRaises(AlphaError) as raised:
            self.decide(run, item)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, CODE))
        self.assertEqual(item['state'], 'ready_for_review')

    def test_approved_posts_whose_job_is_not_made_yet_hold_their_place(self):
        self.reserve(300)
        run, item = self.item()
        with self.assertRaises(AlphaError) as raised:
            self.decide(run, item)
        self.assertEqual(raised.exception.code, CODE)
        self.assertEqual(item['state'], 'ready_for_review')

    def test_jobs_and_reservations_are_added_but_never_counted_twice(self):
        fill(self.state, 150, T)
        self.reserve(149)  # 150 + 149 + this one = 300
        run, item = self.item()
        self.decide(run, item)
        self.assertEqual(item['state'], 'approved')
        run, item = self.item('one-too-many')
        with self.assertRaises(AlphaError):  # the item just approved is now a reservation too: 301
            self.decide(run, item)

    def test_only_approved_posts_without_a_job_in_the_same_hour_are_reservations(self):
        for label, overrides, at in (('already a job', {'jobId': 'queued-elsewhere'}, T),
                                     ('not approved any more', {'state': 'ready_for_review'}, T),
                                     ('another provider', {'platform': 'Mastodon'}, T),
                                     ('another hour', {}, T + HOUR)):
            with self.subTest(label):
                self.root['occurrences'][:] = [o for o in self.root['occurrences'] if o['id'] != 'reserved-run']
                self.reserve(300, at, **overrides)
                run, item = self.item('probe-' + label.replace(' ', '-'))
                self.assertEqual(self.decide(run, item)['state'], 'approved')

    def test_queue_commit_is_refused_at_the_ceiling_and_keeps_the_decision(self):
        run, item = self.item()
        self.decide(run, item)  # the hour had room when the person approved
        fill(self.state, 300, T)  # and was filled by manual approvals before the post was queued
        with self.assertRaises(AlphaError) as raised:
            publisher.commit(self.engine, self.state, ACTOR, {'occurrenceId': run['id'], 'itemKey': item['key']}, NOW + 60)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, CODE))
        self.assertIsNone(item.get('jobId'))
        self.assertEqual(len([j for j in self.state['phase2']['jobs'] if j['id'].startswith('fill-')]), 300)
        self.assertEqual(len(self.state['phase2']['jobs']), 300)
        self.assertEqual(item['decision']['decision'], 'approve')

    def test_queue_commit_creates_the_job_when_there_is_room(self):
        fill(self.state, 299, T)
        run, item = self.item()
        self.decide(run, item)
        queued = publisher.commit(self.engine, self.state, ACTOR, {'occurrenceId': run['id'], 'itemKey': item['key']}, NOW + 60)
        self.assertEqual(len(self.state['phase2']['jobs']), 300)
        self.assertTrue(queued['jobId'])


class ReplyApproval(unittest.TestCase):
    def setUp(self):
        from postriff_phase2 import security_holds
        self.f = EngagementFixture()
        for p in (patch('socket.socket.connect', side_effect=AssertionError('No network')),
                  patch('postriff_phase2.billing.require_publishing', return_value=None),
                  patch.dict(security_holds._INSTALLED, {'readable': True, 'checked': float('-inf')})):
            p.start()
            self.addCleanup(p.stop)

    def test_a_reply_into_a_full_hour_is_refused_and_a_freed_place_lets_it_through(self):
        f = self.f
        f.grant()
        entry = f.preview()
        at = entry['manifest']['timing']['timestamp']
        fill(f.repo.state, 300, at)
        jobs_before = len(f.repo.state['phase2']['jobs'])
        with self.assertRaises(AlphaError) as raised:
            f.approve(entry)
        self.assertEqual((raised.exception.status, raised.exception.code), (409, CODE))
        self.assertEqual(len(f.repo.state['phase2']['jobs']), jobs_before)
        row = next(r for r in f.repo.state['phase2'][KEY]['reviews'] if r['id'] == entry['reviewId'])
        self.assertEqual(row['status'], 'needs_review')
        f.repo.state['phase2']['jobs'][-1]['state'] = 'canceled'  # one place is free again
        approved = f.approve(entry)
        self.assertEqual(approved['state'], 'scheduled')


if __name__ == '__main__':
    unittest.main()
