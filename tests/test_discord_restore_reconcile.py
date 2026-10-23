"""The restore reconciliation tool (scripts/discord_restore_reconcile.py): matching rules, ambiguity, idempotency.

Unit tests drive the pure planner with synthetic jobs and Discord messages (no database, no network). One small
real-PostgreSQL test runs the whole procedure on a throw-away archived cluster: base backup, the lane sending to the
mock Discord, a point-in-time restore into a new data directory, the verified hold, reconciliation, lifting the hold,
and the lane again: zero duplicates. It skips cleanly without PostgreSQL server binaries (POSTRIFF_PG_BIN) and psycopg,
and under the synthetic transport fence, like the W-02 real-PostgreSQL tests.
"""
import copy
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(Path(__file__).resolve().parent)]
spec = importlib.util.spec_from_file_location('discord_restore_reconcile', ROOT / 'scripts/discord_restore_reconcile.py')
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

BOT, OTHER_BOT, USER = '9000009', '9000010', '5550001'
RESTORE, END = 1_800_000_000.0, 1_800_000_600.0  # the rewound interval: ten minutes


def snowflake(at, sequence=1):
    return str(((int(at * 1000) - T.DISCORD_EPOCH_MS) << 22) | sequence)


def job(n, text, *, channel='7000001', due=RESTORE + 60, state='scheduled', expires=None, kind='text', **extra):
    manifest = {'platform': 'Discord', 'workspaceId': 'w%d' % n, 'payload': {'text': text}, 'media': [],
                'expiresAt': (due + 3600) if expires is None else expires,
                'discord': {'target': {'channelId': channel, 'guildId': '6000001', 'botUserId': BOT,
                                       'applicationId': '1234567'},
                            'wireDigest': T.digest({'content': text, 'allowed_mentions': {'parse': []}, 'files': []})}}
    if kind == 'media':
        manifest['media'] = [{'mime': 'image/png', 'hash': 'a' * 64, 'bytes': 10}]
    elif kind == 'webhook':
        manifest['senderKind'] = 'webhook'
    elif kind == 'reply':
        manifest['operation'] = 'discord.reply'
    elif kind == 'tampered':
        manifest['discord']['wireDigest'] = 'b' * 64
    value = {'id': 'job-%d' % n, 'state': state, 'manifest': manifest, 'nextAt': due, 'leaseUntil': 0,
             'leaseOwner': None, 'approvalDigest': 'c' * 64, 'events': [],
             'discordAuthorization': {'digest': 'd' * 64}}
    value.update(extra)
    return value


def message(at, text, *, channel='7000001', author=BOT, bot=True, sequence=1, **extra):
    value = {'id': snowflake(at, sequence), 'channel_id': channel, 'content': text, 'author': {'id': author, 'bot': bot},
             'type': 0, 'edited_timestamp': None, 'mention_everyone': False, 'mentions': [], 'mention_roles': [],
             'attachments': []}
    value.update(extra)
    return value


def history(*messages, readable=True, complete=True):
    return {'readable': readable, 'complete': complete,
            'messages': sorted(messages, key=lambda m: int(m['id']), reverse=True)}


def decide(jobs, channels, owned=(), bot=BOT, **options):
    views = [T.job_view(j['manifest']['workspaceId'], j) for j in jobs]
    decisions, summary = T.plan(views, channels, set(owned), restore_point=options.pop('restore', RESTORE),
                                interval_end=options.pop('end', END), bot_id=bot, **options)
    return {d['jobId']: (d['decision'], d['reason']) for d in decisions}, summary, decisions


class MatchingRules(unittest.TestCase):
    def test_one_exact_message_from_the_bot_after_the_restore_point_is_matched(self):
        result, summary, decisions = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE + 70, 'Hello'))})
        self.assertEqual(result, {'job-1': ('matched', None)})
        self.assertEqual(decisions[0]['messageId'], snowflake(RESTORE + 70))
        self.assertEqual(summary['decisions']['matched'], 1)

    def test_a_message_older_than_the_restore_point_is_not_this_posts(self):
        result, _, _ = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE - 30, 'Hello'))})
        self.assertEqual(result, {'job-1': ('ambiguous', 'due_in_interval_not_found')})

    def test_the_clock_skew_allowance_is_bounded(self):
        inside, _, _ = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE - 4, 'Hello'))})
        self.assertEqual(inside['job-1'][0], 'matched')
        outside, _, _ = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE - 6, 'Hello'))})
        self.assertEqual(outside['job-1'][0], 'ambiguous')

    def test_another_author_with_the_same_text_is_ignored(self):
        user = message(RESTORE + 70, 'Hello', author=USER, bot=False)
        other_bot = message(RESTORE + 71, 'Hello', author=OTHER_BOT, sequence=2)
        result, _, _ = decide([job(1, 'Hello'), job(2, 'Hello', due=END + 60)], {'7000001': history(user, other_bot)})
        self.assertEqual(result, {'job-1': ('ambiguous', 'due_in_interval_not_found'),
                                  'job-2': ('not_sent', 'due_after_interval')})

    def test_another_channel_is_ignored(self):
        result, _, _ = decide([job(1, 'Hello')], {'7000001': history(), '7000002': history(message(RESTORE + 70, 'Hello', channel='7000002'))})
        self.assertEqual(result['job-1'], ('ambiguous', 'due_in_interval_not_found'))

    def test_mentions_or_attachments_make_it_a_partial_match(self):
        for extra in ({'mentions': [{'id': USER}]}, {'attachments': [{'id': '1'}]}, {'mention_everyone': True}):
            result, _, _ = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE + 70, 'Hello', **extra))})
            self.assertEqual(result['job-1'], ('ambiguous', 'partial_match'), extra)

    def test_two_messages_with_the_text_are_ambiguous(self):
        result, _, _ = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE + 70, 'Hello'),
                                                                       message(RESTORE + 200, 'Hello', sequence=2))})
        self.assertEqual(result['job-1'], ('ambiguous', 'several_candidates'))

    def test_two_posts_with_the_same_text_share_the_one_message_and_both_are_held(self):
        """Two identical texts to one channel at different times: the message cannot be attributed, and the later
        post (not due in the interval) is held as well: it may be the one Discord shows."""
        jobs = [job(1, 'Twin'), job(2, 'Twin', due=END + 300)]
        result, _, _ = decide(jobs, {'7000001': history(message(RESTORE + 70, 'Twin'))})
        self.assertEqual(result, {'job-1': ('ambiguous', 'shared_candidate'), 'job-2': ('ambiguous', 'shared_candidate')})

    def test_two_posts_with_the_same_text_and_two_messages_are_both_held(self):
        jobs = [job(1, 'Twin'), job(2, 'Twin', due=RESTORE + 300)]
        result, _, _ = decide(jobs, {'7000001': history(message(RESTORE + 70, 'Twin'), message(RESTORE + 310, 'Twin', sequence=2))})
        self.assertEqual(set(result.values()), {('ambiguous', 'several_candidates')})

    def test_an_edited_bot_message_in_the_window_holds_the_channel(self):
        edited = message(RESTORE + 70, 'Changed later', edited_timestamp='2027-01-15T08:00:00+00:00')
        result, _, _ = decide([job(1, 'Hello'), job(2, 'Other', due=END + 60)], {'7000001': history(edited)})
        self.assertEqual(result, {'job-1': ('ambiguous', 'partial_match'), 'job-2': ('ambiguous', 'partial_match')})

    def test_whitespace_or_case_differences_are_a_partial_match(self):
        result, _, _ = decide([job(1, 'Hello  World')], {'7000001': history(message(RESTORE + 70, 'hello world'))})
        self.assertEqual(result['job-1'], ('ambiguous', 'partial_match'))

    def test_a_deleted_message_cannot_be_seen_so_a_post_due_in_the_interval_is_held(self):
        """A moderator deleted it: Discord's history and lookup no longer show it. Never 'not sent'."""
        result, _, _ = decide([job(1, 'Deleted by a moderator')], {'7000001': history()})
        self.assertEqual(result['job-1'], ('ambiguous', 'due_in_interval_not_found'))

    def test_a_post_due_after_the_interval_with_complete_history_is_not_sent(self):
        result, _, _ = decide([job(1, 'Later', due=END + 120)], {'7000001': history(message(RESTORE + 10, 'Unrelated'))})
        self.assertEqual(result['job-1'], ('not_sent', 'due_after_interval'))

    def test_unreadable_or_incomplete_history_holds_even_a_post_due_later(self):
        for channel in (history(readable=False, complete=False), history(complete=False)):
            for due in (RESTORE + 60, END + 120):
                result, _, _ = decide([job(1, 'Hello', due=due)], {'7000001': channel})
                self.assertEqual(result['job-1'][0], 'ambiguous')
                self.assertIn(result['job-1'][1], ('channel_unreadable', 'history_incomplete'))

    def test_a_changed_bot_identity_holds(self):
        result, _, _ = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE + 70, 'Hello'))}, bot=OTHER_BOT)
        self.assertEqual(result['job-1'], ('ambiguous', 'bot_identity_changed'))
        result, _, _ = decide([job(1, 'Hello')], {'7000001': history(message(RESTORE + 70, 'Hello'))}, bot=None)
        self.assertEqual(result['job-1'], ('ambiguous', 'bot_identity_changed'))

    def test_a_message_another_job_already_owns_is_not_taken(self):
        found = message(RESTORE + 70, 'Hello')
        result, _, _ = decide([job(1, 'Hello')], {'7000001': history(found)}, owned={found['id']})
        self.assertEqual(result['job-1'], ('ambiguous', 'message_owned_by_another_job'))

    def test_unsupported_kinds_and_a_manifest_that_does_not_match_its_wire_digest_hold(self):
        for kind, reason in (('media', 'unsupported_kind'), ('webhook', 'unsupported_kind'), ('reply', 'unsupported_kind'),
                             ('tampered', 'manifest_mismatch')):
            result, _, _ = decide([job(1, 'Hello', kind=kind)], {'7000001': history(message(RESTORE + 70, 'Hello'))})
            self.assertEqual(result['job-1'], ('ambiguous', reason), kind)

    def test_an_approval_that_expired_before_the_post_could_be_sent_is_left_to_the_product(self):
        result, _, _ = decide([job(1, 'Late', due=END + 60, expires=END + 30)], {'7000001': history()})
        self.assertEqual(result['job-1'], ('left', 'approval_expired'))

    def test_an_expired_approval_whose_post_was_sent_is_matched_so_the_product_can_verify_it(self):
        result, _, _ = decide([job(1, 'Sent, then expired', due=RESTORE + 10, expires=RESTORE + 100)],
                              {'7000001': history(message(RESTORE + 20, 'Sent, then expired'))})
        self.assertEqual(result['job-1'], ('matched', None))

    def test_an_expired_unsent_post_due_inside_the_interval_is_held(self):
        result, _, _ = decide([job(1, 'Expired unsent', due=RESTORE + 10, expires=RESTORE + 100)], {'7000001': history()})
        self.assertEqual(result['job-1'], ('ambiguous', 'due_in_interval_not_found'))

    def test_a_sealed_intent_is_only_resolved_never_released(self):
        sealed = job(1, 'Sealed', state='submitting', discordDispatchIntents=[{'id': 'i', 'at': RESTORE - 100}])
        result, _, _ = decide([sealed], {'7000001': history(message(RESTORE - 99, 'Sealed'))})
        self.assertEqual(result['job-1'], ('resolved', None), 'its intent predates the restore point; so may its message')
        result, _, _ = decide([sealed], {'7000001': history()})
        self.assertEqual(result['job-1'], ('left', 'sealed_no_message'))
        uncertain = job(2, 'Uncertain', state='uncertain')
        result, _, _ = decide([uncertain], {'7000001': history(message(RESTORE + 1, 'Uncertain'), message(RESTORE + 2, 'Uncertain', sequence=2))})
        self.assertEqual(result['job-2'], ('left', 'sealed_several_candidates'))

    def test_jobs_with_a_receipt_or_a_terminal_state_are_out_of_scope(self):
        jobs = [job(1, 'A', state='verified'), job(2, 'B', providerReference='7000001/1'),
                job(3, 'C', discordReceipts=[{'reference': '7000001/2'}]), job(4, 'D', state='failed'),
                job(5, 'E', state='canceled')]
        result, summary, _ = decide(jobs, {'7000001': history()})
        self.assertEqual(result, {})
        self.assertEqual(summary['inScope'], 0)

    def test_a_held_post_is_matched_when_found_and_left_when_not(self):
        result, _, _ = decide([job(1, 'Held', state='held'), job(2, 'Held too', state='held')],
                              {'7000001': history(message(RESTORE + 30, 'Held'))})
        self.assertEqual(result, {'job-1': ('matched', None), 'job-2': ('left', 'held_no_message')})

    def test_could_have_been_sent_boundaries(self):
        view = T.job_view('w', job(1, 'x', due=END + 4))
        self.assertTrue(T.could_have_been_sent(view, RESTORE, END, 5))
        view = T.job_view('w', job(1, 'x', due=END + 6))
        self.assertFalse(T.could_have_been_sent(view, RESTORE, END, 5))
        view = T.job_view('w', job(1, 'x', due=RESTORE - 600, expires=RESTORE - 10))
        self.assertFalse(T.could_have_been_sent(view, RESTORE, END, 5), 'its approval ended before the interval')
        view = T.job_view('w', job(1, 'x', due=RESTORE - 600, leaseUntil=END + 30))
        self.assertTrue(T.could_have_been_sent(view, RESTORE, END, 5), 'the lease holder may send at once')

    def test_regression_a_post_leased_past_the_interval_end_and_then_deleted_is_held_not_resent(self):
        """Drill finding (mid-run restore point): a worker held this post's lease at the restore point, sent it, and
        a moderator deleted the message. The lease ran past the interval end. Judging 'not sent' from leaseUntil
        resent it; it must be held."""
        leased = job(1, 'Leased, sent, deleted', state='submitting', due=RESTORE - 30, leaseOwner='discord-lane-0-x',
                     leaseUntil=END + 40)
        result, _, _ = decide([leased], {'7000001': history(message(RESTORE + 1, 'Unrelated'))})
        self.assertEqual(result['job-1'], ('ambiguous', 'due_in_interval_not_found'))

    def test_unclaimed_bot_messages_and_duplicates_already_visible_are_counted(self):
        verified = job(1, 'Posted twice', state='verified', providerReference='7000001/' + snowflake(RESTORE + 10))
        jobs = [verified, job(2, 'Pending')]
        channels = {'7000001': history(message(RESTORE + 10, 'Posted twice'), message(RESTORE + 20, 'Posted twice', sequence=2),
                                       message(RESTORE + 30, 'Approved after the restore point', sequence=3),
                                       message(RESTORE + 40, 'Pending', sequence=4))}
        result, summary, _ = decide(jobs, channels, owned={snowflake(RESTORE + 10)})
        self.assertEqual(result, {'job-2': ('matched', None)})
        self.assertEqual((summary['duplicatesAlreadyVisible'], summary['unclaimedBotMessages']), (1, 1))

    def test_dry_run_summary_has_counts_only(self):
        _, summary, _ = decide([job(1, 'Secret customer text')], {'7000001': history(message(RESTORE + 70, 'Secret customer text'))})
        text = json.dumps(summary)
        self.assertNotIn('Secret', text)
        self.assertNotIn('job-1', text)
        self.assertNotIn('7000001', text)


class Idempotency(unittest.TestCase):
    RUN = {'runId': 'r1', 'restorePoint': RESTORE, 'intervalEnd': END}

    def plan_and_mutate(self, jobs, channels):
        _, _, decisions = decide(jobs, channels)
        by_id = {j['id']: j for j in jobs}
        changed = [T.mutate(by_id[d['jobId']], d, self.RUN, END + 100) for d in decisions]
        return decisions, changed

    def test_a_second_run_changes_nothing(self):
        jobs = [job(1, 'Found'), job(2, 'Deleted'), job(3, 'Later', due=END + 60)]
        channels = {'7000001': history(message(RESTORE + 70, 'Found'))}
        decisions, changed = self.plan_and_mutate(jobs, channels)
        self.assertEqual(changed, [True, True, False])
        found, deleted, later = jobs
        self.assertEqual((found['state'], found['providerReference']), ('uncertain', '7000001/' + snowflake(RESTORE + 70)))
        self.assertEqual(found['discordReceipts'][0]['reference'], found['providerReference'])
        self.assertEqual(found['events'][-1]['message'], T.ADOPTED)
        self.assertEqual((deleted['state'], deleted[T.MARKER]['reason']), ('held', 'due_in_interval_not_found'))
        self.assertEqual(later['state'], 'scheduled')
        again, changed = self.plan_and_mutate(jobs, channels)
        self.assertEqual({d['jobId']: (d['decision'], d['reason']) for d in again},
                         {'job-2': ('left', 'already_held_due_in_interval_not_found'), 'job-3': ('not_sent', 'due_after_interval')})
        self.assertEqual(changed, [False, False])

    def test_the_same_receipt_is_never_appended_twice(self):
        jobs = [job(1, 'Found')]
        decisions, _ = self.plan_and_mutate(jobs, {'7000001': history(message(RESTORE + 70, 'Found'))})
        before = copy.deepcopy(jobs[0])
        jobs[0]['providerReference'] = None  # even if a reference were cleared, the receipt id dedupes
        self.assertFalse(T.mutate(jobs[0], decisions[0], self.RUN, END + 200))
        self.assertEqual(jobs[0]['discordReceipts'], before['discordReceipts'])

    def test_the_fingerprint_changes_with_the_fields_a_decision_depends_on(self):
        base = job(1, 'x')
        for change in ({'state': 'held'}, {'nextAt': 1}, {'leaseOwner': 'w'}, {'providerReference': 'r'},
                       {'discordDispatchIntents': [{}]}, {'discordReceipts': [{}]}):
            self.assertNotEqual(T.fingerprint({**base, **change}), T.fingerprint(base), change)


class CommandLine(unittest.TestCase):
    """Refusals that happen before any connection or Discord request."""

    def refused(self, *argv):
        with self.assertRaises(T.ReconcileError) as caught:
            T.main(list(argv))
        return str(caught.exception)

    def test_reconcile_never_reads_discord_without_live(self):
        self.assertIn('--live', self.refused('reconcile', '--dsn', 'host=127.0.0.1 port=1', '--restore-point', '0',
                                             '--interval-end', '1'))

    def test_reconcile_needs_both_times(self):
        self.assertIn('--restore-point', self.refused('reconcile', '--dsn', 'host=127.0.0.1 port=1', '--live'))

    def test_lifting_the_hold_needs_confirmation_and_one_direction(self):
        self.assertIn('--confirm', self.refused('hold', '--lift', '--dsn', 'host=127.0.0.1 port=1'))
        self.assertIn('exactly one', self.refused('hold', '--dsn', 'host=127.0.0.1 port=1'))

    def test_a_live_run_needs_the_token_variable(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'POSTRIFF_DISCORD_BOT_TOKEN': ''}):
            self.assertIn('token', self.refused('reconcile', '--dsn', 'host=127.0.0.1 port=1', '--live',
                                                '--restore-point', '0', '--interval-end', '1'))

    def test_times_need_a_zone(self):
        with self.assertRaises(T.ReconcileError):
            T.epoch('2026-10-23T05:00:00')
        self.assertEqual(T.epoch('2026-10-23T05:00:00+00:00'), T.epoch('2026-10-23T05:00:00Z'))
        self.assertEqual(T.epoch('1800000000.5'), 1800000000.5)


class Reader(unittest.TestCase):
    def wire(self, pages, statuses=()):
        calls = []
        statuses = list(statuses)

        def transport(method, url, headers=None, **_):
            calls.append((method, url))
            if statuses:
                status = statuses.pop(0)
                if status != 200:
                    return {'status': status, 'headers': {}, 'body': {'retry_after': 0.01}}
            if url.endswith('/users/@me'):
                return {'status': 200, 'body': {'id': BOT, 'bot': True}}
            before = url.split('before=')[1] if 'before=' in url else None
            visible = [m for m in pages if before is None or int(m['id']) < int(before)]
            return {'status': 200, 'body': sorted(visible, key=lambda m: int(m['id']), reverse=True)[:T.PAGE]}
        return calls, transport

    def test_only_get_requests_and_pagination_back_to_the_restore_point(self):
        messages = [message(RESTORE - 1000 + 10 * n, 'm%d' % n, sequence=n) for n in range(130)]
        calls, transport = self.wire(messages)
        reader = T.DiscordReader(transport, 'token', pace=0, sleep=lambda s: None)
        result = reader.history('7000001', RESTORE - 1000 + 10 * 100)
        self.assertTrue(result['complete'] and result['readable'])
        self.assertEqual({method for method, _ in calls}, {'GET'})
        self.assertEqual(len(calls), 1, 'the first page already reaches back past the bound')
        result = reader.history('7000001', RESTORE - 2000)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['messages']), 130)

    def test_history_is_incomplete_when_the_page_limit_ends_first(self):
        messages = [message(RESTORE + n, 'm%d' % n, sequence=n) for n in range(120)]
        _, transport = self.wire(messages)
        reader = T.DiscordReader(transport, 'token', pace=0, max_pages=2, sleep=lambda s: None)
        result = reader.history('7000001', RESTORE - 10)
        self.assertEqual((result['readable'], result['complete'], len(result['messages'])), (True, False, 100))

    def test_a_429_is_waited_out_and_invalid_answers_stop_the_reader(self):
        _, transport = self.wire([], statuses=[429, 200])
        waits = []
        reader = T.DiscordReader(transport, 'token', pace=0, sleep=waits.append)
        self.assertEqual(reader.bot_identity(), BOT)
        self.assertEqual((reader.limited, len(waits)), (1, 1))
        _, transport = self.wire([], statuses=[403] * 10)
        reader = T.DiscordReader(transport, 'token', pace=0, max_invalid=3, sleep=lambda s: None)
        for _ in range(3):
            self.assertFalse(reader.history('7000001', RESTORE)['readable'])
        with self.assertRaises(T.ReconcileError):
            reader.history('7000001', RESTORE)

    def test_destination_channels_without_pending_posts_are_read_only_to_count_unclaimed_messages(self):
        """A post approved after the restore point lives in a channel where the restored database may have no
        pending job; its channel is read too (best effort), and an unreadable one never stops the run."""
        pending = job(1, 'Pending')
        found = {'7000001': [message(RESTORE + 10, 'Pending')], '7000002': [message(RESTORE + 20, 'Approved later', channel='7000002')]}

        def transport(method, url, headers=None, **_):
            if url.endswith('/users/@me'):
                return {'status': 200, 'body': {'id': BOT, 'bot': True}}
            channel = url.split('/channels/')[1].split('/')[0]
            if channel == '7000003':
                return {'status': 403, 'body': {'message': 'Missing Access'}}
            return {'status': 200, 'body': found.get(channel, [])}
        reader = T.DiscordReader(transport, 'token', pace=0, sleep=lambda s: None)
        views = [T.job_view('w1', pending)]
        channels = T.read_channels(reader, views, RESTORE, 5, destinations={'7000001', '7000002', '7000003'})
        self.assertEqual(sorted(channels), ['7000001', '7000002'], 'the unreadable destination-only channel is skipped')
        decisions, summary = T.plan(views, channels, set(), restore_point=RESTORE, interval_end=END, bot_id=BOT)
        self.assertEqual([(d['decision'], d['reason']) for d in decisions], [('matched', None)])
        self.assertEqual(summary['unclaimedBotMessages'], 1)

    def test_the_reader_paces_its_requests(self):
        clock = [0.0]
        waits = []
        _, transport = self.wire([])
        reader = T.DiscordReader(transport, 'token', pace=0.25, sleep=lambda s: (waits.append(s), clock.__setitem__(0, clock[0] + s)),
                                 monotonic=lambda: clock[0])
        for _ in range(3):
            reader.bot_identity()
        self.assertEqual([round(w, 2) for w in waits], [0.25, 0.25])


# --- the whole procedure on a real PostgreSQL ---------------------------------------------------------------------------

try:
    import discord_lane_fixture as F
    import discord_restore_fixture as R
    REAL = R.available() and not F.FENCED
except Exception:  # pragma: no cover - the fixtures need the repository's src and test helpers
    F = R = None
    REAL = False


@unittest.skipUnless(REAL, 'needs PostgreSQL server binaries (POSTRIFF_PG_BIN) and psycopg, outside the synthetic transport fence')
class RestoreProcedureOnPostgres(unittest.TestCase):
    def test_restore_hold_reconcile_lift_sends_nothing_twice(self):
        import shutil
        work = Path(tempfile.mkdtemp(prefix='prrestore-', dir=str(Path(tempfile.gettempdir()))))
        tenants = [F.Tenant(70 + n) for n in range(4)]
        clusters = []
        try:
            c0 = R.ArchivedCluster(work / 'c0', archive=work / 'archive').start()
            clusters.append(c0)
            c0.apply_schema()
            wire = R.RestoreMockDiscord(tenants)
            hosted = F.social(c0, tenants, wire, capacity=200)
            provider = hosted.providers['discord']
            provider.rate_limiter.observe(provider.rate_limiter.reserve_read('GET', '/guilds/6900000', identity=provider._rate_identity('bot')),
                                          {'status': 200, 'headers': {}})  # the coordinator's rows exist, as in production
            base, _ = c0.base_backup(work / 'base')
            F.seed(c0, tenants[:3], 1)  # due now
            F.seed(c0, tenants[3:], 1, at=c0.now() + 40)  # due after the interval
            time.sleep(1.2)
            restore_point = c0.now()
            time.sleep(1.2)
            F.run_lanes(F.base_worker(c0, F.social(c0, tenants, wire, capacity=200)), 2, seconds=20)
            first = {nonce: len(times) for nonce, times in wire.creates.items()}
            self.assertEqual(sum(first.values()), 3)
            wire.delete(next(iter(wire.messages)))  # a moderator removes one of the three
            with c0.connect() as db:
                T.set_hold(db)
            interval_end = c0.now()
            c0.flush_archive()
            c0.stop()
            restored, report = R.restore(base, work / 'archive', restore_point, work / 'restored')
            clusters.append(restored)
            self.assertIn('recovery stopping', report['recoveryStopping'] or 'recovery stopping (log line not kept)')
            states = {job['state'] for job in F.jobs(restored).values()}
            self.assertEqual(states, {'scheduled'}, 'the restore rewound every post to unsent')
            with restored.connect() as db:
                hold = T.set_hold(db)
            self.assertEqual((hold['updated'], hold['held']), (1, True))
            reader = T.DiscordReader(wire, 'synthetic-bot-token', pace=0)
            options = {'restore_point': restore_point, 'interval_end': interval_end}
            dry, _ = T.reconcile(restored.factory(), reader, dry_run=True, **options)
            self.assertEqual(dry['decisions']['matched'], 2)
            applied, decisions = T.reconcile(restored.factory(), reader, dry_run=False, **options)
            self.assertEqual((applied['decisions']['matched'], applied['decisions']['ambiguous'],
                              applied['decisions']['not_sent']), (2, 1, 1))
            self.assertEqual(applied['write']['written'], 3)
            again, _ = T.reconcile(restored.factory(), reader, dry_run=False, **options)
            self.assertEqual(again['write']['written'], 0, 'idempotent')
            with restored.connect() as db:
                self.assertFalse(T.lift_hold(db)['held'])
            worker = F.base_worker(restored, F.social(restored, tenants, wire, capacity=200))
            F.run_lanes(worker, 2, seconds=20)
            deadline = time.time() + 120
            waiting = ('scheduled', 'uncertain', 'provider_accepted')  # a create or a read-back still to come
            while time.time() < deadline and any(j['state'] in waiting for j in F.jobs(restored).values()):
                F.run_lanes(worker, 2, seconds=20)
                time.sleep(1)
            final = F.jobs(restored)
            for found in final.values():
                total = len(wire.creates.get(F.nonce(found), []))
                self.assertLessEqual(total, 1, 'never sent twice')
            self.assertEqual(sorted(j['state'] for j in final.values()), ['held', 'verified', 'verified', 'verified'])
            self.assertEqual(sum(len(v) for v in wire.creates.values()), 4, 'the later post was sent once, nothing else')
            verified = [j for j in final.values() if j['state'] == 'verified']
            self.assertEqual(sorted((j.get('verification') or {}).get('method') for j in verified), ['provider_lookup'] * 3)
            # The fence: a job changed since the read is skipped, never overwritten.
            stale = [dict(d, fingerprint='0' * 64, decision='ambiguous', reason='test') for d in decisions[:1]]
            self.assertEqual(T.apply(restored.factory(), stale, {'runId': 't', 'restorePoint': 0, 'intervalEnd': 0}),
                             {'written': 0, 'skipped': 1})
            # A database restored to before the coordinator's first request has no policy row: an UPDATE holds nothing.
            restored.sql('DELETE FROM public.pr_discord_rate_state')
            with restored.connect() as db:
                self.assertEqual(T.set_hold(db), {'updated': 0, 'inserted': 0, 'policyRows': 0, 'held': False})
                created = T.set_hold(db, application_id=F.APP, create_missing=True)
            self.assertEqual((created['inserted'], created['held']), (1, True))
            results, _ = F.run_lanes(worker, 1, seconds=5)
            self.assertEqual(results[0]['stoppedBy'], 'operator_hold')
        finally:
            for cluster in clusters:
                cluster.stop('immediate')
            shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
