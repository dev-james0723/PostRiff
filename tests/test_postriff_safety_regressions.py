"""Synthetic regressions for approval authority and ambiguous provider outcomes."""
import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import test_postriff_phase2 as p2
from postriff_alpha.domain import AlphaError
from postriff_phase2.store import Phase2Store


class SafetyRegressions(unittest.TestCase):
    setUp = p2.Phase2Acceptance.setUp
    tearDown = p2.Phase2Acceptance.tearDown
    channel = p2.Phase2Acceptance.channel
    draft = p2.Phase2Acceptance.draft
    review = p2.Phase2Acceptance.review
    enqueue = p2.Phase2Acceptance.enqueue

    def test_removed_fact_cannot_be_reapproved_as_current_draft(self):
        self.draft()
        source = self.j.state['sources'][0]
        self.j.act('approve_source', sourceId=source['id'], factIds=[])
        v = self.j.state['variants'][0]
        with self.assertRaises(AlphaError):
            self.j.act('p2_variant_review', variantId=v['id'], variantRevision=v['revision'],
                       confirmed=True, excludedUnknowns=v['unknowns'])

    def test_manifest_is_bound_to_workspace_and_brief(self):
        job = self.enqueue()
        for key, value in [('workspaceId', 'other-workspace'), ('brandHubId', 'other-brand'),
                           ('briefRevision', -1)]:
            with self.subTest(key=key):
                manifest = copy.deepcopy(job['manifest'])
                manifest[key] = value
                self.assertFalse(self.store.current(self.j.state, manifest))

    def test_source_change_requires_replacement_even_after_edit_or_reapproval(self):
        self.draft()
        source = self.j.state['sources'][0]
        facts = [f['id'] for f in source['facts']]
        self.j.act('approve_source', sourceId=source['id'], factIds=facts[:1])
        self.j.edit()
        for selected in (facts[:1], facts):
            self.j.act('approve_source', sourceId=source['id'], factIds=selected)
            v = self.j.state['variants'][0]
            with self.assertRaises(AlphaError):
                self.j.act('p2_variant_review', variantId=v['id'], variantRevision=v['revision'],
                           confirmed=True, excludedUnknowns=v['unknowns'])

    def test_fresh_source_replacement_can_be_reviewed_and_scheduled(self):
        self.draft()
        source = self.j.state['sources'][0]
        self.j.act('approve_source', sourceId=source['id'], factIds=[source['facts'][0]['id']])
        v = self.j.state['variants'][0]
        self.j.act('preview_update', variantId=v['id'])
        self.j.act('accept_update', variantId=v['id'])
        v = self.j.state['variants'][0]
        self.j.act('p2_variant_review', variantId=v['id'], variantRevision=v['revision'],
                   confirmed=True, excludedUnknowns=v['unknowns'])
        review = self.review(self.channel())
        self.j.act('p2_approve', reviewId=review['id'], digest=review['digest'], confirmed=True)
        self.assertEqual(self.j.state['phase2']['jobs'][0]['state'], 'scheduled')

    def test_source_change_discards_pending_replacement(self):
        self.draft()
        v = self.j.state['variants'][0]
        self.j.act('preview_update', variantId=v['id'])
        source = self.j.state['sources'][0]
        self.j.act('approve_source', sourceId=source['id'], factIds=[])
        with self.assertRaises(AlphaError):
            self.j.act('accept_update', variantId=v['id'])

    def test_hosted_commands_reject_source_stale_review(self):
        from postriff_phase2.hosted import HostedPhase2Commands
        self.draft()
        state = copy.deepcopy(self.j.state)
        commands = HostedPhase2Commands(clock=lambda: self.now)
        commands(state, 'synthetic-owner', 'approve_source',
                 {'sourceId': state['sources'][0]['id'], 'factIds': []})
        v = state['variants'][0]
        with self.assertRaises(AlphaError):
            commands(state, 'synthetic-owner', 'p2_variant_review',
                     {'variantId': v['id'], 'variantRevision': v['revision'],
                      'confirmed': True, 'excludedUnknowns': v['unknowns']})

    def test_viewer_cannot_mutate(self):
        with self.store.connect() as db:
            db.execute("UPDATE alpha_memberships SET role='viewer' WHERE workspace_id=?", (self.j.id,))
        self.j.refresh()
        with self.assertRaises(AlphaError):
            self.j.act('idea', idea='Unauthorized edit')

    def test_revoked_approver_holds_waiting_job(self):
        self.enqueue()
        with self.store.connect() as db:
            db.execute("UPDATE alpha_memberships SET status='revoked' WHERE workspace_id=?", (self.j.id,))
        self.now += 61
        self.store.worker_step()
        with self.store.connect() as db:
            state = json.loads(db.execute('SELECT state FROM workspaces WHERE id=?', (self.j.id,)).fetchone()[0])
        self.assertEqual(state['phase2']['jobs'][0]['state'], 'held')
        self.assertEqual(state['phase2']['jobs'][0]['attempts'], [])

    def test_reconciliation_cannot_restore_automatic_submission(self):
        class BrokenAdapter:
            submits = 0
            def submit(adapter, *_):
                adapter.submits += 1
                return {'state': 'uncertain', 'confirmed': 'Timed out'}
            def reconcile(adapter, *_):
                return {'state': 'scheduled', 'confirmed': 'Try again'}
        adapter = BrokenAdapter()
        self.store.social = adapter
        self.enqueue()
        self.now += 61
        for _ in range(4):
            self.store.worker_step()
            self.now += 61
        self.assertEqual(adapter.submits, 1)
        self.assertEqual(self.j.refresh().state['phase2']['jobs'][0]['state'], 'uncertain')

    def test_cancel_during_rate_limit_does_not_retry(self):
        class CancelDuringSubmit:
            submits = 0
            def submit(adapter, *_):
                adapter.submits += 1
                job = self.j.refresh().state['phase2']['jobs'][0]
                self.j.act('p2_cancel', jobId=job['id'])
                return {'state': 'scheduled', 'confirmed': 'Rejected before acceptance'}
        adapter = CancelDuringSubmit()
        self.store.social = adapter
        self.enqueue()
        self.now += 61
        self.store.worker_step()
        self.now += 61
        self.store.worker_step()
        self.assertEqual(adapter.submits, 1)
        self.assertEqual(self.j.refresh().state['phase2']['jobs'][0]['state'], 'canceled')

    def test_provider_exception_is_recorded_without_error_secrets(self):
        class BrokenAdapter:
            def submit(adapter, *_):
                raise TimeoutError('PRIVATE_PROVIDER_SECRET')
        self.store.social = BrokenAdapter()
        self.enqueue()
        self.now += 61
        self.store.worker_step()
        job = self.j.refresh().state['phase2']['jobs'][0]
        self.assertEqual(job['state'], 'uncertain')
        self.assertNotIn('PRIVATE_PROVIDER_SECRET', json.dumps(job))

    def test_malformed_receipt_does_not_crash_or_claim_publication(self):
        class BrokenAdapter:
            def submit(adapter, *_):
                return {'state': 'verified'}
        self.store.social = BrokenAdapter()
        self.enqueue()
        self.now += 61
        self.store.worker_step()
        self.assertEqual(self.j.refresh().state['phase2']['jobs'][0]['state'], 'uncertain')

    def test_non_string_provider_state_is_uncertain(self):
        from postriff_phase2.outcomes import normalize_result
        for state in (None, [], {}, True, 1):
            self.assertEqual(normalize_result({'state': state, 'confirmed': 'bad'}, {})['state'], 'uncertain')

    def test_one_draft_edit_memory_export_without_social_connection(self):
        self.j.setup().act('generate', platform='LinkedIn', language='English')
        self.j.edit()
        self.assertEqual(self.j.state['preferences'], [], 'an edit alone proposes nothing')
        pref = self.j.propose()
        self.j.act('preference', preferenceId=pref['id'], decision='remember')
        self.j.act('preference', preferenceId=pref['id'], decision='undo')
        self.assertEqual(self.j.state['phase2']['channels'], [])
        self.assertEqual(self.j.state['speaker']['activeRevision'], 1)
        with zipfile.ZipFile(io.BytesIO(self.store.export(self.j.id, self.j.token))) as archive:
            state = json.loads(archive.read('phase2/workspace.json'))
        self.assertEqual(len(state['variants']), 1)
        self.assertEqual(state['preferences'][0]['status'], 'undone')
        self.assertEqual((state['learning']['revision'], state['learning']['retired'][0]['id']), (2, pref['id']))
        self.assertEqual(state['phase2']['jobs'], [])


if __name__ == '__main__':
    unittest.main()
