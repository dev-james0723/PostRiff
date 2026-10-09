"""Focused synthetic history contracts. No provider or PostgreSQL acceptance."""
import base64
import copy
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube import history

WORKSPACE = '00000000-0000-0000-6000-000000000001'
OTHER_WORKSPACE = '00000000-0000-0000-6000-000000000002'
CONNECTION, OTHER = 'youtube-history-one', 'youtube-history-two'
NOW = 1_800_000_000
STAMP = datetime(2026, 10, 9, 12, 0, 0, 123456, tzinfo=timezone.utc)


def draft(identifier='d1', connection=CONNECTION, **extra):
    return {'id': identifier, 'connectionId': connection, 'channelId': 'UC' + 'a' * 22,
            'assetId': 'original-asset', 'variantId': 'variant-' + identifier,
            'status': 'proposed', 'digest': 'd' * 64, 'createdAt': NOW - 1000,
            'timing': {'timestamp': NOW - 10, 'timeZone': 'UTC'},
            'publishOptions': {'title': 'Owned video', 'description': 'Private original metadata'},
            'createdBy': 'private-owner', 'authorizationGeneration': 'private-generation',
            **extra}


def policy(identifier='p1', identifiers=('d1',), connection=CONNECTION, **extra):
    return {'id': identifier, 'connectionId': connection, 'channelId': 'UC' + 'a' * 22,
            'status': 'active', 'digest': 'e' * 64, 'endsAt': NOW - 1,
            'createdAt': NOW - 500, 'drafts': [{'id': name, 'digest': 'd' * 64} for name in identifiers],
            'grantedBy': 'private-owner', 'authorizationGeneration': 'private-generation',
            'counter': {'dailyUsed': 2}, **extra}


def state(drafts=None, policies=None, jobs=None, reviews=None):
    return {'youtubeAgent': {'drafts': drafts if drafts is not None else [draft()],
                             'policies': policies if policies is not None else [policy()],
                             'dispatchCounters': {'accepted': 5}},
            'variants': [{'id': 'variant-d1', 'text': 'Generated, independently referenced'}],
            'phase2': {'jobs': jobs or [], 'reviews': reviews or [],
                       'assets': [{'id': 'original-asset', 'objectName': 'private/original.mp4'}]}}


def cursor():
    value = Mock()
    value.connection = SimpleNamespace(autocommit=False)
    return value


def row(identifier, connection=CONNECTION):
    record = draft(identifier, connection)
    checksum = history._canonical(record)[1]
    return identifier, record, checksum, STAMP


class CandidateTests(unittest.TestCase):
    def test_expired_pair_is_closed_and_originals_are_not_mutated(self):
        value = state()
        before = copy.deepcopy(value)
        candidates = history.compaction_candidates(value, CONNECTION, NOW)
        self.assertEqual({(c['recordKind'], c['recordId']) for c in candidates}, {('draft', 'd1'), ('policy', 'p1')})
        self.assertEqual(next(c['record'] for c in candidates if c['recordKind'] == 'policy'), value['youtubeAgent']['policies'][0])
        candidates[0]['record']['status'] = 'changed'
        self.assertEqual(value, before)

    def test_future_drafts_and_live_policies_remain(self):
        for change in ('draft', 'policy'):
            value = state()
            if change == 'draft':
                value['youtubeAgent']['drafts'][0]['timing']['timestamp'] = NOW + 1
            else:
                value['youtubeAgent']['policies'][0]['endsAt'] = NOW + 1
            self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [], change)

    def test_revoked_policy_can_archive_only_with_expired_unqueued_drafts(self):
        value = state(policies=[policy(status='revoked', endsAt=NOW + 1000)])
        self.assertEqual(len(history.compaction_candidates(value, CONNECTION, NOW)), 2)
        value['youtubeAgent']['drafts'][0]['jobId'] = 'completed-job'
        self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [])

    def test_all_job_states_and_references_are_retained(self):
        for job_state in ('held', 'processing', 'uncertain', 'native_scheduled', 'verified', 'failed', 'canceled'):
            for reference in ({'youtubeAgent': {'draftId': 'd1'}}, {'youtubeAgent': {'policyId': 'p1'}},
                              {'manifest': {'variantId': 'variant-d1'}}):
                with self.subTest(job_state=job_state, reference=reference):
                    value = state(jobs=[{'id': 'job', 'state': job_state, **reference}])
                    self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [])

    def test_review_and_foreign_policy_references_prevent_draft_compaction(self):
        self.assertEqual(history.compaction_candidates(state(reviews=[{'variantId': 'variant-d1'}]), CONNECTION, NOW), [])
        value = state(policies=[policy(connection=OTHER)])
        self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [])

    def test_active_or_malformed_lease_and_account_fences_fail_closed(self):
        for lease in (None, {}, {'until': NOW - 1},
                      {'id': 'lease', 'until': NOW + 1, 'authorization': {'policyId': 'p1'}},
                      {'id': 'lease', 'until': True, 'authorization': {'policyId': 'p1'}}):
            value = state()
            value['youtubeAgent']['fleetLease'] = lease
            self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [], str(lease))
        for fence in ('accountDeletion', 'accountBlock'):
            value = state()
            value[fence] = {'pending': True}
            self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [])

    def test_valid_expired_lease_is_retained_and_does_not_block(self):
        value = state()
        lease = {'id': 'lease', 'until': NOW - 1, 'authorization': {'policyId': 'p1',
                 'policyDigest': 'e' * 64, 'grantedBy': 'owner', 'grantedAt': NOW - 100,
                 'authorizationGeneration': None, 'status': 'active'}}
        value['youtubeAgent']['fleetLease'] = lease
        self.assertEqual(len(history.compaction_candidates(value, CONNECTION, NOW)), 2)
        self.assertEqual(value['youtubeAgent']['fleetLease'], lease)

    def test_malformed_times_and_reference_shapes_fail_closed(self):
        for timestamp in (None, True, float('nan'), float('inf'), 'expired', 10 ** 1000):
            value = state()
            value['youtubeAgent']['drafts'][0]['timing']['timestamp'] = timestamp
            self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [])
        value = state(policies=[policy(drafts='unproven refs')])
        self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [])
        value = state(drafts=[draft(), draft()])
        self.assertEqual(history.compaction_candidates(value, CONNECTION, NOW), [])

    def test_bound_never_splits_group_and_later_independent_draft_progresses(self):
        identifiers = tuple('d' + str(i) for i in range(50))
        value = state(drafts=[draft(name) for name in identifiers] + [draft('independent')],
                      policies=[policy(identifiers=identifiers)])
        selected = history.compaction_candidates(value, CONNECTION, NOW)
        self.assertEqual([(c['recordKind'], c['recordId']) for c in selected], [('draft', 'independent')])
        self.assertEqual(history.compaction_candidates(state(), CONNECTION, NOW, limit=1), [])

    def test_unreferenced_expired_drafts_are_bounded_and_connection_scoped(self):
        value = state(drafts=[draft('d' + str(i)) for i in range(70)] + [draft('foreign', OTHER)], policies=[])
        self.assertEqual(len(history.compaction_candidates(value, CONNECTION, NOW)), 50)
        self.assertEqual([c['recordId'] for c in history.compaction_candidates(value, OTHER, NOW)], ['foreign'])
        for limit in (0, 51, True, '50'):
            with self.assertRaises(AlphaError):
                history.compaction_candidates(value, CONNECTION, NOW, limit)


class AtomicHistoryTests(unittest.TestCase):
    def test_archives_exact_records_and_saves_locked_state_in_same_cursor(self):
        cur, value = cursor(), state()
        before = copy.deepcopy(value)
        cur.fetchone.side_effect = [('public.pr_youtube_agent_history',), (4, value), (1,), ('d1',), ('p1',), (5,)]
        result = history.archive_and_compact(cur, WORKSPACE, CONNECTION, NOW)
        self.assertEqual((result['archived'], result['revision']), (2, 5))
        calls = cur.execute.call_args_list
        inserts = [c.args for c in calls if c.args[0].startswith('INSERT INTO')]
        self.assertEqual({json.loads(args[1][4])['id'] for args in inserts}, {'d1', 'p1'})
        for _sql, parameters in inserts:
            original = next(item for item in before['youtubeAgent']['drafts'] + before['youtubeAgent']['policies'] if item['id'] == parameters[3])
            self.assertEqual(json.loads(parameters[4]), original)
        update = next(c.args for c in calls if c.args[0].startswith('UPDATE public.pr_workspaces'))
        saved = json.loads(update[1][0])
        self.assertEqual(saved['youtubeAgent']['drafts'], [])
        self.assertEqual(saved['youtubeAgent']['policies'], [])
        self.assertEqual(saved['variants'], before['variants'])
        self.assertEqual(saved['phase2'], before['phase2'])
        self.assertEqual(saved['youtubeAgent']['dispatchCounters'], before['youtubeAgent']['dispatchCounters'])
        self.assertEqual(value, before)
        self.assertFalse(any(c.args[0].strip().upper() in ('COMMIT', 'ROLLBACK') for c in calls))
        self.assertNotIn('record', result)
        self.assertFalse(result['authorityReactivated'])

    def test_logical_immutable_conflict_rolls_back_partial_archive_before_rethrow(self):
        cur = cursor()
        cur.fetchone.side_effect = [(history.TABLE,), (1, state()), (1,), ('d1',), None,
                                    ({'id': 'p1', 'changed': True}, '0' * 64)]
        with self.assertRaises(AlphaError) as caught:
            history.archive_and_compact(cur, WORKSPACE, CONNECTION, NOW)
        self.assertEqual(caught.exception.code, 'youtube_agent_history_conflict')
        statements = [c.args[0] for c in cur.execute.call_args_list]
        self.assertIn('ROLLBACK TO SAVEPOINT youtube_agent_history_compaction', statements)
        self.assertFalse(any(sql.startswith('UPDATE public.pr_workspaces') for sql in statements))

    def test_same_original_retry_is_idempotent_without_archive_update(self):
        cur, value = cursor(), state(policies=[])
        record = value['youtubeAgent']['drafts'][0]
        cur.fetchone.side_effect = [(history.TABLE,), (1, value), (1,), None,
                                    (record, history._canonical(record)[1]), (2,)]
        self.assertEqual(history.archive_and_compact(cur, WORKSPACE, CONNECTION, NOW)['archived'], 1)
        self.assertFalse(any('UPDATE public.pr_youtube_agent_history' in c.args[0] for c in cur.execute.call_args_list))

    def test_missing_schema_and_autocommit_never_compact(self):
        cur = cursor()
        cur.fetchone.return_value = (None,)
        with self.assertRaises(AlphaError) as caught:
            history.archive_and_compact(cur, WORKSPACE, CONNECTION, NOW)
        self.assertEqual(caught.exception.code, history.UNAVAILABLE)
        self.assertEqual(cur.execute.call_count, 1)
        cur = cursor()
        cur.connection.autocommit = True
        with self.assertRaises(AlphaError) as caught:
            history.archive_and_compact(cur, WORKSPACE, CONNECTION, NOW)
        self.assertEqual(caught.exception.code, 'youtube_agent_history_transaction_required')
        cur.execute.assert_not_called()

    def test_no_live_connection_fallback(self):
        cur = cursor()
        cur.fetchone.side_effect = [(history.TABLE,), (1, state()), None]
        with self.assertRaises(AlphaError) as caught:
            history.archive_and_compact(cur, WORKSPACE, CONNECTION, NOW)
        self.assertEqual(caught.exception.status, 403)
        self.assertFalse(any(c.args[0].startswith('INSERT INTO') for c in cur.execute.call_args_list))

    def test_explicit_cleanup_only_deletes_scoped_local_archive(self):
        cur = cursor()
        cur.fetchone.return_value = (history.TABLE,)
        cur.rowcount = 3
        self.assertEqual(history.purge_connection_history(cur, WORKSPACE, CONNECTION), 3)
        self.assertEqual(cur.execute.call_args.args, (
            'DELETE FROM public.pr_youtube_agent_history WHERE workspace_id=%s AND connection_id=%s',
            (WORKSPACE, CONNECTION)))


class CursorTests(unittest.TestCase):
    def first_page(self):
        cur = cursor()
        cur.fetchone.side_effect = [(history.TABLE,), (1,)]
        cur.fetchall.return_value = [row('d2'), row('d1')]
        result = history.page(cur, WORKSPACE, CONNECTION, 'draft', limit=1)
        return cur, result

    def test_keyset_page_uses_scoped_original_anchor_and_maximum_limit(self):
        _first, result = self.first_page()
        self.assertEqual(result['items'][0]['id'], 'd2')
        cur = cursor()
        cur.fetchone.side_effect = [(history.TABLE,), (1,), (1,)]
        cur.fetchall.return_value = [row('d1')]
        last = history.page(cur, WORKSPACE, CONNECTION, 'draft', limit=1, cursor=result['nextCursor'])
        self.assertIsNone(last['nextCursor'])
        sql, values = cur.execute.call_args.args
        self.assertIn('(archived_at,record_id)<', sql)
        self.assertNotIn('OFFSET', sql)
        self.assertEqual(values[:3], (WORKSPACE, CONNECTION, 'draft'))
        self.assertEqual(values[3:], (history._utc(STAMP), 'd2', 2))

    def test_cross_tenant_connection_and_kind_cursors_fail_before_database_access(self):
        _, result = self.first_page()
        for workspace, connection, kind in ((OTHER_WORKSPACE, CONNECTION, 'draft'),
                                            (WORKSPACE, OTHER, 'draft'), (WORKSPACE, CONNECTION, 'policy')):
            cur = cursor()
            with self.assertRaises(AlphaError) as caught:
                history.page(cur, workspace, connection, kind, cursor=result['nextCursor'])
            self.assertEqual(caught.exception.code, 'youtube_agent_history_cursor')
            cur.execute.assert_not_called()

    def test_malformed_noncanonical_and_removed_anchor_fail_closed(self):
        _, result = self.first_page()
        for invalid in ('', '%%%', result['nextCursor'] + '=', 'a' * 1025, 7):
            cur = cursor()
            with self.assertRaises(AlphaError):
                history.page(cur, WORKSPACE, CONNECTION, 'draft', cursor=invalid)
            cur.execute.assert_not_called()
        cur = cursor()
        cur.fetchone.side_effect = [(history.TABLE,), (1,), None]
        with self.assertRaises(AlphaError) as caught:
            history.page(cur, WORKSPACE, CONNECTION, 'draft', cursor=result['nextCursor'])
        self.assertEqual(caught.exception.code, 'youtube_agent_history_cursor')
        cur.fetchall.assert_not_called()

    def test_changed_anchor_checksum_is_not_a_page_authority(self):
        _, result = self.first_page()
        raw = base64.urlsafe_b64decode(result['nextCursor'] + '=' * (-len(result['nextCursor']) % 4))
        payload = json.loads(raw)
        payload['s'] = '0' * 64
        forged = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
        cur = cursor()
        cur.fetchone.side_effect = [(history.TABLE,), (1,), None]
        with self.assertRaises(AlphaError):
            history.page(cur, WORKSPACE, CONNECTION, 'draft', cursor=forged)
        cur.fetchall.assert_not_called()

    def test_projection_never_exposes_private_records_or_reactivates_authority(self):
        record = draft(fleetLease={'secret': 'lease-private'}, grantedBy='private-owner',
                       accessToken='private-token', secret_ciphertext='private-ciphertext')
        view = history.public_metadata('draft', record, STAMP)
        self.assertFalse(view['canReactivate'])
        self.assertEqual(view['status'], 'archived')
        self.assertEqual(view['plannedAt'], NOW - 10)
        encoded = json.dumps(view)
        for text in ('fleetLease', 'authorizationGeneration', 'grantedBy', 'createdBy', 'accessToken',
                     'secret_ciphertext', 'private-owner', 'private-token', 'Private original metadata'):
            self.assertNotIn(text, encoded)


if __name__ == '__main__':
    unittest.main()
