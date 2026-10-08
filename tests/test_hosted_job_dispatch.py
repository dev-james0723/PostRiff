"""Single approved-job dispatch boundary; synthetic sessions and no provider I/O."""
import copy
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted import HostedPhase2Commands
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.hosted_worker import PostgresWorker
from test_postriff_phase2_hosted import invoke


TOKEN = 'synthetic-session-token-00000000000000'
PREVIEW = {'environment': 'preview', 'origin': 'https://preview.example.invalid'}


class PreviewApproval(unittest.TestCase):
    def test_new_preview_approval_is_digest_bound_and_held_for_scoped_execution(self):
        from test_postriff_phase2 import Phase2Acceptance
        fixture = Phase2Acceptance()
        fixture.setUp()
        try:
            fixture.store.worker_binding = copy.deepcopy(PREVIEW)
            job = fixture.enqueue()
            self.assertEqual(job['manifest']['workerBinding'], PREVIEW)
            self.assertEqual(job['approvalDigest'], digest(job['manifest']))
            self.assertEqual(job['state'], 'held', 'Older global workers must skip a preview approval')
            self.assertTrue(job['previewDispatchPending'])
            self.assertEqual(job['attempts'], [])
            self.assertEqual(job['events'][-1]['message'], 'Approved preview post; choose Publish approved post when due.')
            commands = HostedPhase2Commands(clock=lambda: fixture.now, worker_binding=PREVIEW)
            self.assertEqual(commands.present(fixture.j.state, 1)['workerBinding'], PREVIEW)
        finally:
            fixture.tearDown()

    def test_only_a_completed_disabled_transport_hold_is_recoverable_in_preview(self):
        worker = PostgresWorker(None, worker_binding=PREVIEW)
        job = {'manifest': {}, 'state': 'held', 'resultSchema': 'postriff.result.v1',
               'providerConfirmed': 'Live provider transport is not configured; nothing was submitted',
               'events': [{'state': 'held', 'message': 'Live provider transport is not configured; nothing was submitted'}],
               'attempts': [{'number': 1, 'startedAt': 100, 'endedAt': 101}]}
        self.assertTrue(worker._may_adopt_legacy_hold(job))
        for change in ({'providerReference': 'urn:li:share:123'}, {'container': 'container'},
                       {'providerUpload': {'id': 'upload'}}, {'progress': {'stage': 'create_attempted'}},
                       {'state': 'uncertain'}, {'resultSchema': None}, {'attempts': []},
                       {'providerConfirmed': 'Provider response unknown'}, {'workerBinding': PREVIEW}):
            with self.subTest(change=change):
                self.assertFalse(worker._may_adopt_legacy_hold({**job, **change}))
        self.assertFalse(PostgresWorker(None)._may_adopt_legacy_hold(job), 'Production cannot adopt a preview hold')

    def test_global_invalidation_filters_deployments_before_any_mutation(self):
        worker = PostgresWorker(None, worker_binding=PREVIEW)
        jobs = [{'id':'production','manifest':{}}, {'id':'preview','manifest':{'workerBinding':PREVIEW}},
                {'id':'other-preview','manifest':{'workerBinding':{**PREVIEW,'origin':'https://other.example.invalid'}}}]
        state = {'phase2': {'jobs': jobs, 'reviews': [{'id':j['id'], 'manifest':j['manifest']} for j in jobs]}}
        worker.commands.engine.invalidate = Mock()
        worker._invalidate_owned(state)
        view = worker.commands.engine.invalidate.call_args.args[0]['phase2']
        self.assertEqual([j['id'] for j in view['jobs']], ['preview'])
        self.assertEqual([r['id'] for r in view['reviews']], ['preview'])
        self.assertIs(view['jobs'][0], jobs[1], 'Only owned objects retain mutation references')
        self.assertEqual(len(state['phase2']['jobs']), 3, 'Filtering never replaces stored lists')

    def test_preview_binding_rejects_an_untrusted_origin(self):
        for binding in ({'environment':'production','origin':'https://preview.example.invalid'},
                        {**PREVIEW,'origin':'http://preview.example.invalid'},
                        {**PREVIEW,'origin':'https://preview.example.invalid/callback'},
                        {**PREVIEW,'origin':'https://user@preview.example.invalid'}, {**PREVIEW,'extra':'value'}):
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                PostgresWorker(None, worker_binding=binding)


class Repository:
    def __init__(self):
        manifest = {'workspaceId': 'workspace-one', 'actor': 'member-one', 'payload': {'text': 'Approved text'}}
        self.job = {'id': 'job-one', 'manifest': manifest, 'approvalDigest': digest(manifest)}
        self.state = {'workspace': {'id': 'workspace-one'}, 'phase2': {'jobs': [self.job]}}
        self.role = 'owner'

    @contextmanager
    def transaction(self, token, workspace_id):
        if token != TOKEN:
            raise AlphaError('Verified session required.', 401)
        if workspace_id != 'workspace-one':
            raise AlphaError('Workspace unavailable.', 403)
        yield Mock(), [1, copy.deepcopy(self.state), self.role, False, False, False, False], 'member-one'


class HostedJobDispatch(unittest.TestCase):
    def setUp(self):
        self.repository = Repository()
        self.worker = PostgresWorker(None)
        self.worker.step = Mock(return_value=True)
        self.worker.tick = Mock(side_effect=AssertionError('A user action must never run the global cron'))
        self.app = HostedApplication(SimpleNamespace(repository=self.repository), self.worker)
        self.headers = {'Authorization': 'Bearer ' + TOKEN, 'X-PostRiff-Request': 'founder-alpha'}
        self.path = '/api/workspaces/workspace-one/jobs/job-one/execute'

    def test_normal_authenticated_route_dispatches_only_the_digest_bound_job(self):
        status, _, result = invoke(self.app, 'POST', self.path,
                                   {'approvalDigest': self.repository.job['approvalDigest']}, self.headers)
        self.assertEqual(status, 202)
        self.assertEqual(result['processed'], 1)
        self.assertEqual(result['jobId'], 'job-one')
        self.worker.step.assert_called_once_with(workspace_id='workspace-one', job_id='job-one',
                                                 approval_digest=self.repository.job['approvalDigest'],
                                                 dispatch_principal='member-one')
        self.worker.tick.assert_not_called()

    def test_session_origin_and_application_guard_are_required_before_dispatch(self):
        cases = ({'Authorization': ''}, {'X-PostRiff-Request': ''}, {'Origin': 'https://foreign.invalid'})
        for change in cases:
            with self.subTest(change=change):
                status, _, _ = invoke(self.app, 'POST', self.path,
                                      {'approvalDigest': self.repository.job['approvalDigest']},
                                      {**self.headers, **change})
                self.assertIn(status, (401, 403))
        self.worker.step.assert_not_called()

    def test_workspace_membership_and_approve_permission_cannot_be_replaced_by_a_digest(self):
        for workspace, role in (('foreign-workspace', 'owner'), ('workspace-one', 'viewer'), ('workspace-one', 'editor')):
            with self.subTest(workspace=workspace, role=role):
                self.repository.role = role
                with self.assertRaises(AlphaError) as error:
                    self.worker.execute_job(self.repository, workspace, TOKEN, 'job-one', self.repository.job['approvalDigest'])
                self.assertEqual(error.exception.status, 403)
        self.worker.step.assert_not_called()

    def test_unknown_job_or_stale_approval_cannot_request_any_worker_step(self):
        cases = [('foreign-job', self.repository.job['approvalDigest']), ('job-one', 'f' * 64), ('job-one', None)]
        for job_id, approval in cases:
            with self.subTest(job=job_id, approval=approval):
                with self.assertRaises(AlphaError):
                    self.worker.execute_job(self.repository, 'workspace-one', TOKEN, job_id, approval)
        self.repository.job['manifest']['payload']['text'] = 'Changed after approval'
        with self.assertRaises(AlphaError):
            self.worker.execute_job(self.repository, 'workspace-one', TOKEN, 'job-one', self.repository.job['approvalDigest'])
        self.worker.step.assert_not_called()

    def test_user_cannot_submit_content_force_timing_or_expand_the_batch(self):
        status, _, _ = invoke(self.app, 'POST', self.path,
                              {'approvalDigest': self.repository.job['approvalDigest'], 'force': True, 'maxJobs': 25}, self.headers)
        self.assertEqual(status, 400)
        self.worker.step.assert_not_called()

    def test_sample_workspace_is_read_only(self):
        self.repository.state['workspace']['sample'] = True
        with self.assertRaises(AlphaError) as error:
            self.worker.execute_job(self.repository, 'workspace-one', TOKEN, 'job-one', self.repository.job['approvalDigest'])
        self.assertEqual(error.exception.status, 403)
        self.worker.step.assert_not_called()


if __name__ == '__main__':
    unittest.main()
