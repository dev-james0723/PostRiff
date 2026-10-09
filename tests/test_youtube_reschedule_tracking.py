"""Approved native-schedule tracking regressions; synthetic only, zero Google calls."""
import copy
import hashlib
import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.permissions import Membership
from postriff_phase2.youtube.journal import UploadJournal
from postriff_phase2.youtube.model import upload_body
from postriff_phase2.youtube.service import YouTubeCreatorService, fingerprint
from postriff_phase2.youtube.uploads import UploadEngine


WORKSPACE, CONNECTION, CHANNEL, VIDEO = 'workspace-one', 'connection-one', 'UC' + 'a' * 22, 'abcdefghijk'
KEY = (WORKSPACE, CONNECTION, 'upload-one')
ORIGINAL, CHANGED, LATEST = '2099-01-01T00:00:00Z', '2099-02-01T00:00:00Z', '2099-03-01T00:00:00Z'


class MemoryDatabase:
    def __init__(self, fixture):
        self.fixture, self.result = fixture, []
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        f = self.fixture
        f.sql.append((sql, params))
        self.result, self.rowcount = [], 0
        if sql.startswith('SELECT state FROM public.pr_workspaces'):
            self.result = [(copy.deepcopy(f.workspace),)]
        elif sql.startswith('SELECT operation_key,state FROM public.pr_youtube_uploads'):
            workspace, connection, video_id = params
            self.result = [(key[2], copy.deepcopy(state)) for key, state in f.uploads.items()
                           if key[:2] == (workspace, connection) and state.get('videoId') == video_id]
        elif sql.startswith('SELECT id::text,manifest,manifest_digest,status,receipt FROM public.pr_youtube_actions'):
            workspace, connection, operation, upload_digest = params
            self.result = [(action_id, copy.deepcopy(row['manifest']), row['digest'], row['status'], copy.deepcopy(row['receipt']))
                           for action_id, row in f.actions.items()
                           if row['manifest']['workspaceId'] == workspace and row['manifest']['connectionId'] == connection
                           and row['manifest'].get('uploadScheduleBinding', {}).get('operationKey') == operation
                           and row['manifest'].get('uploadScheduleBinding', {}).get('uploadManifestDigest') == upload_digest
                           and row['status'] not in ('prepared', 'failed')]
        elif sql.startswith('INSERT INTO public.pr_youtube_actions'):
            workspace, connection, actor, operation, manifest, action_digest = params
            action_id = 'action-' + str(len(f.actions) + 1)
            f.actions[action_id] = {'manifest': json.loads(manifest), 'digest': action_digest, 'status': 'prepared',
                                    'receipt': None, 'actor': actor, 'operation': operation,
                                    'workspace': workspace, 'connection': connection, 'privacy_erased_at': None}
            self.result = [(action_id,)]
            self.rowcount = 1
        elif sql.startswith('SELECT manifest,manifest_digest,status,receipt,actor::text FROM public.pr_youtube_actions'):
            row = f.actions.get(params[-1])
            if row and (row['workspace'], row['connection']) == params[:2]:
                self.result = [(copy.deepcopy(row['manifest']), row['digest'], row['status'], copy.deepcopy(row['receipt']), row['actor'])]
        elif sql.startswith("UPDATE public.pr_youtube_actions SET status='started'"):
            row = f.actions.get(params[-1])
            if row:
                row['status'] = 'started'
                self.rowcount = 1
        elif sql.startswith(("UPDATE public.pr_youtube_actions SET status='accepted'",
                             'UPDATE public.pr_youtube_actions SET status=%s,receipt=%s::jsonb')):
            assert sql.endswith('WHERE workspace_id=%s AND connection_id=%s AND id::text=%s AND privacy_erased_at IS NULL'), sql
            workspace, connection, action_id = params[-3:]
            row = f.actions.get(action_id)
            if row and (row['workspace'], row['connection']) == (workspace, connection) and row['privacy_erased_at'] is None:
                accepted = sql.startswith("UPDATE public.pr_youtube_actions SET status='accepted'")
                row.update(status='accepted' if accepted else params[0], receipt=json.loads(params[0 if accepted else 1]))
                self.rowcount = 1
        else:
            raise AssertionError('Unexpected synthetic SQL: ' + sql)
        if sql.startswith('SELECT '):
            self.rowcount = len(self.result)

    def fetchall(self):
        return copy.deepcopy(self.result)

    def fetchone(self):
        return copy.deepcopy(self.result[0]) if self.result else None


class MemoryJournal:
    def __init__(self, fixture):
        self.fixture = fixture

    @contextmanager
    def lock(self, _key):
        yield

    def assert_current(self, _key):
        if self.fixture.revoked:
            raise UploadJournal._authorization_error()

    def assert_authorized(self, workspace, connection, generation, *, cursor=None, locked=False):
        self.fixture.fences.append((workspace, connection, generation, cursor, locked))
        if self.fixture.revoked or generation != 'consent-one':
            raise UploadJournal._authorization_error()

    def load(self, key):
        return copy.deepcopy(self.fixture.uploads.get(key))

    def save(self, key, state):
        self.assert_current(key)
        self.fixture.uploads[key] = copy.deepcopy(state)


class SyntheticApi:
    def __init__(self, fixture):
        self.fixture, self.channel_id = fixture, CHANNEL
        self.grant = {'authorizationGeneration': 'consent-one'}
        self.provider = SimpleNamespace(real_transport=False, transport=self.forbid_upload)
        self.before_request, self.account_usage = lambda: None, lambda *_: None

    def forbid_upload(self, *_args, **_kwargs):
        self.fixture.upload_requests += 1
        raise AssertionError('Native schedule reconciliation must never open or resume an upload')

    def owned(self, resource, resource_id):
        self.before_request()
        self.fixture.reads.append((resource, resource_id))
        assert (resource, resource_id) == ('videos', VIDEO)
        return copy.deepcopy(self.fixture.video)

    def plan(self, action, inputs, **_kwargs):
        self.owned('videos', inputs['id'])
        status = {'privacyStatus': 'private'}
        if action == 'video.schedule':
            status['publishAt'] = inputs['publishAt']
        return {'action': action, 'capability': 'schedule', 'method': 'videos.update', 'targetId': inputs['id'],
                'params': {'part': 'status'}, 'body': {'id': inputs['id'], 'status': status}, 'media': None}

    def execute(self, plan, **_kwargs):
        self.fixture.writes.append(copy.deepcopy(plan))
        self.fixture.video['status'].update(plan['body']['status'])
        if plan['action'] == 'video.cancel_schedule':
            self.fixture.video['status'].pop('publishAt', None)
        return {'id': VIDEO, 'status': copy.deepcopy(self.fixture.video['status'])}

    def call(self, method, *_args, **_kwargs):
        raise AssertionError('Unexpected forward operation during reconciliation: ' + method)


class ScheduleFixture:
    def __init__(self):
        self.now, self.revoked, self.upload_requests = 2_000_000_000, False, 0
        self.actions, self.reads, self.writes, self.sql, self.fences = {}, [], [], [], []
        self.options = {'title': 'Approved video', 'description': '', 'privacyStatus': 'public',
                        'publishAt': ORIGINAL, 'madeForKids': False, 'containsSyntheticMedia': False}
        self.manifest = {'platform': 'YouTube', 'workspaceId': WORKSPACE, 'channelId': CONNECTION,
                         'providerAccountId': CHANNEL, 'actor': 'owner', 'idempotencyKey': KEY[2],
                         'publishOptions': copy.deepcopy(self.options), 'media': [{'id': 'video-asset', 'bytes': 40, 'mime': 'video/mp4'}],
                         'payload': {'text': ''}}
        self.manifest_digest = hashlib.sha256(json.dumps(self.manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.job = {'id': 'original-job', 'manifest': copy.deepcopy(self.manifest), 'approvalDigest': digest(self.manifest),
                    'approvedBy': 'owner', 'state': 'provider_accepted'}
        self.workspace = {'phase2': {'jobs': [self.job]}}
        self.uploads = {KEY: {'version': 2, 'manifestDigest': self.manifest_digest, 'stage': 'native_scheduled',
                             'videoId': VIDEO, 'options': copy.deepcopy(self.options), 'bytesSent': 40, 'totalBytes': 40,
                             'neverPublished': True, 'steps': {'visibility': {'status': 'verified'}}}}
        self.video = upload_body(self.options) | {'id': VIDEO}
        self.video['snippet']['channelId'] = CHANNEL
        self.video['status'].update(privacyStatus='private', publishAt=ORIGINAL, uploadStatus='processed')
        self.video['processingDetails'] = {'processingStatus': 'succeeded'}
        self.journal, self.api = MemoryJournal(self), SyntheticApi(self)
        self.creator = YouTubeCreatorService.__new__(YouTubeCreatorService)
        self.creator.clock = lambda: self.now
        self.creator.service = SimpleNamespace(connection_factory=lambda: MemoryDatabase(self))
        self.creator.repository = SimpleNamespace(transaction=self.transaction, assert_fresh=lambda *_: None)
        self.creator.oauth = SimpleNamespace(vault=SimpleNamespace(encrypt=lambda _: (None, None)))
        self.creator.journal = self.journal
        self.creator._member = lambda *_args, **_kwargs: ('owner', CHANNEL, copy.deepcopy(self.workspace))
        self.creator._api = lambda *_: self.api
        self.creator._allow = lambda *_args, **_kwargs: None
        self.creator.never_published = lambda *_: True
        self.engine = UploadEngine(self.journal, lambda _: self.api, self.forbid_media,
                                   finalize=self.creator.finalize_upload, clock=lambda: self.now)

    @contextmanager
    def transaction(self, _token, _workspace):
        yield MemoryDatabase(self), (1, copy.deepcopy(self.workspace)), 'owner'

    def forbid_media(self, *_):
        raise AssertionError('An accepted video must not read or resend media')

    @contextmanager
    def hosted(self):
        with patch('postriff_phase2.hosted.audit'), patch('postriff_phase2.hosted.throttle'), \
                patch('postriff_phase2.hosted._membership', return_value=Membership.from_row('owner', can_publish=True)):
            yield

    def prepare(self, publish_at=CHANGED, **extra):
        body = {'action': 'video.schedule' if publish_at is not None else 'video.cancel_schedule',
                'inputs': {'id': VIDEO, **({'publishAt': publish_at} if publish_at is not None else {})}, **extra}
        with self.hosted():
            return self.creator.preview(WORKSPACE, 'token', CONNECTION, body)

    def approve(self, review):
        with self.hosted():
            return self.creator.approve(WORKSPACE, 'token', CONNECTION, review['id'],
                                        {'confirmed': True, 'digest': review['digest']})

    def change(self, publish_at=CHANGED):
        review = self.prepare(publish_at)
        result = self.approve(review)
        assert result['status'] == 'verified'
        return review

    def step(self):
        self.now += 301
        return self.engine.step(copy.deepcopy(self.manifest), allow_initialize=False)


class ApprovedNativeScheduleTrackingTests(unittest.TestCase):
    def test_review_binds_exact_original_upload_in_approval_digest(self):
        f = ScheduleFixture()
        review = f.prepare(uploadScheduleBinding={'operationKey': 'attacker-supplied'})
        binding = review['manifest']['uploadScheduleBinding']
        self.assertEqual(binding['operationKey'], KEY[2])
        self.assertEqual(binding['uploadManifestDigest'], f.manifest_digest)
        self.assertEqual(binding['uploadApprovalDigest'], f.job['approvalDigest'])
        self.assertEqual((binding['workspaceId'], binding['connectionId'], binding['channelId'], binding['videoId']),
                         (WORKSPACE, CONNECTION, CHANNEL, VIDEO))
        self.assertIsNone(binding['previousAction'])
        self.assertEqual(review['digest'], fingerprint(f.actions[review['id']]['manifest']))
        self.assertTrue(f.fences[-1][-1])
        self.assertIsInstance(f.fences[-1][-2], MemoryDatabase)

    def test_stale_predecessor_review_cannot_send_another_write(self):
        f = ScheduleFixture()
        first, stale = f.prepare(), f.prepare(LATEST)
        f.approve(first)
        with self.assertRaises(AlphaError) as caught:
            f.approve(stale)
        self.assertEqual(caught.exception.code, 'youtube_schedule_tracking_conflict')
        self.assertEqual(len(f.writes), 1)
        self.assertEqual(f.actions[stale['id']]['status'], 'prepared')
        self.assertTrue(any('pr_youtube_uploads' in sql and 'FOR UPDATE' in sql for sql, _ in f.sql))

    def test_tampered_review_manifest_is_rejected_before_provider_write(self):
        f = ScheduleFixture()
        review = f.prepare()
        f.actions[review['id']]['manifest']['uploadScheduleBinding']['operationKey'] = 'another-upload'
        with self.assertRaises(AlphaError):
            f.approve(review)
        self.assertEqual(f.writes, [])

    def test_verified_reschedule_follows_new_time_without_changing_original_approval(self):
        f = ScheduleFixture()
        original_manifest, original_options, original_digest = copy.deepcopy(f.manifest), copy.deepcopy(f.options), f.job['approvalDigest']
        f.change()
        result = f.step()
        self.assertEqual(result['progress']['stage'], 'native_scheduled')
        self.assertEqual(result['progress']['publishAt'], CHANGED)
        self.assertEqual(f.uploads[KEY]['options'], original_options)
        self.assertEqual(f.uploads[KEY]['manifestDigest'], f.manifest_digest)
        self.assertEqual(f.job['manifest'], original_manifest)
        self.assertEqual(f.job['approvalDigest'], original_digest)
        self.assertEqual(len(f.writes), 1)
        self.assertEqual(f.upload_requests, 0)

    def test_verified_unschedule_ends_pending_job_and_keeps_video_private(self):
        f = ScheduleFixture()
        f.change(None)
        result = f.step()
        self.assertEqual(result['state'], 'canceled')
        self.assertEqual(f.video['status']['privacyStatus'], 'private')
        self.assertNotIn('publishAt', f.video['status'])
        self.assertEqual(f.uploads[KEY]['options']['publishAt'], ORIGINAL)
        self.assertEqual(f.uploads[KEY]['videoId'], VIDEO)
        f.step()
        self.assertEqual(len(f.writes), 1)
        self.assertEqual(f.upload_requests, 0)

    def test_verified_reschedule_publication_is_checked_against_effective_time(self):
        f = ScheduleFixture()
        f.change()
        f.step()
        f.video['status'].update(privacyStatus='public')
        f.video['status'].pop('publishAt')
        f.now = datetime.fromisoformat(CHANGED.replace('Z', '+00:00')).timestamp()
        result = f.step()
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['progress']['stage'], 'published')
        self.assertFalse(f.uploads[KEY]['neverPublished'])
        self.assertEqual(len(f.writes), 1)

    def test_early_or_unapproved_provider_schedule_change_is_not_adopted(self):
        for changed_status in ({'privacyStatus': 'private', 'publishAt': CHANGED},
                               {'privacyStatus': 'private', 'publishAt': None},
                               {'privacyStatus': 'public', 'publishAt': None}):
            with self.subTest(changed_status=changed_status):
                f = ScheduleFixture()
                f.video['status'].update(changed_status)
                result = f.step()
                self.assertEqual(result['state'], 'held')
                self.assertEqual(result['progress']['errorCategory'], 'youtube_schedule_changed')
                self.assertEqual(f.uploads[KEY]['options']['publishAt'], ORIGINAL)
                self.assertEqual(f.writes, [])

    def test_unrelated_operation_or_other_channel_receipt_cannot_supply_override(self):
        for field, value in (('operationKey', 'another-upload'), ('channelId', 'UC' + 'b' * 22)):
            with self.subTest(field=field):
                f = ScheduleFixture()
                review = f.change()
                row = f.actions[review['id']]
                row['manifest']['uploadScheduleBinding'][field] = value
                row['digest'] = fingerprint(row['manifest'])
                row['receipt']['approvalDigest'] = row['digest']
                result = f.step()
                self.assertEqual(result['state'], 'held')
                self.assertEqual(len(f.writes), 1)
                self.assertEqual(f.upload_requests, 0)

    def test_old_receipt_reconciliation_cannot_override_newer_approved_action(self):
        f = ScheduleFixture()
        first = f.change(CHANGED)
        second = f.change(LATEST)
        f.actions[first['id']]['updatedAt'] = 10**12
        result = f.step()
        self.assertEqual(result['progress']['publishAt'], LATEST)
        binding = f.actions[second['id']]['manifest']['uploadScheduleBinding']
        self.assertEqual(binding['previousAction'], {'id': first['id'], 'digest': first['digest']})
        self.assertEqual(len(f.writes), 2)

    def test_verification_race_stays_read_only_and_recovers_on_later_verified_receipt(self):
        f = ScheduleFixture()
        review = f.change()
        row = f.actions[review['id']]
        verified_receipt = copy.deepcopy(row['receipt'])
        row.update(status='accepted', receipt={**row['receipt'], 'verification': {'verified': False}})
        pending = f.step()
        self.assertEqual(pending['state'], 'uncertain')
        self.assertEqual(pending['progress']['stage'], 'native_schedule_reconciling')
        self.assertTrue(pending['progress']['steps']['scheduleTracking']['reconciliationOnly'])
        row.update(status='verified', receipt=verified_receipt)
        result = f.step()
        self.assertEqual(result['progress']['stage'], 'native_scheduled')
        self.assertEqual(result['progress']['publishAt'], CHANGED)
        self.assertEqual(len(f.writes), 1)
        self.assertEqual(f.upload_requests, 0)

    def test_unknown_action_never_promotes_from_matching_state_and_has_bounded_polls(self):
        for status in ('started', 'accepted', 'outcome_unknown'):
            with self.subTest(status=status):
                f = ScheduleFixture()
                review = f.change()
                row = f.actions[review['id']]
                row['status'] = status
                self.assertEqual(f.step()['state'], 'uncertain')
                self.assertEqual(f.step()['state'], 'uncertain')
                result = f.step()
                self.assertEqual(result['state'], 'held')
                self.assertEqual(row['status'], status)
                self.assertEqual(result['progress']['errorCategory'], 'youtube_schedule_intervention_required')
                self.assertTrue(result['progress']['steps']['scheduleTracking']['humanInterventionRequired'])
                reads = len(f.reads)
                f.step()
                self.assertEqual(len(f.reads), reads)
                self.assertEqual(len(f.writes), 1)
                self.assertEqual(f.upload_requests, 0)

    def test_recovery_marker_cannot_restore_superseded_original_schedule(self):
        f = ScheduleFixture()
        review = f.change()
        row = f.actions[review['id']]
        receipt = copy.deepcopy(row['receipt'])
        row['status'] = 'outcome_unknown'
        for _ in range(3):
            f.step()
        self.assertTrue(f.uploads[KEY]['nativeScheduleTracking'])
        # Existing explicit upload recovery resets stage to uploaded_private.
        # Its immutable journal/approval and tracking marker remain unchanged.
        f.uploads[KEY].update(stage='uploaded_private', retryAt=f.now)
        f.step()
        self.assertEqual(len(f.writes), 1)
        row.update(status='verified', receipt=receipt)
        f.uploads[KEY].update(stage='uploaded_private', retryAt=f.now)
        result = f.step()
        self.assertEqual(result['progress']['stage'], 'native_scheduled')
        self.assertEqual(result['progress']['publishAt'], CHANGED)
        self.assertEqual(f.uploads[KEY]['options']['publishAt'], ORIGINAL)
        self.assertEqual(len(f.writes), 1)
        self.assertEqual(f.upload_requests, 0)

    def test_missing_or_corrupt_receipt_does_not_verify_an_action(self):
        for corruption in ('missing', 'digest', 'channel', 'video', 'transport'):
            with self.subTest(corruption=corruption):
                f = ScheduleFixture()
                review = f.change()
                receipt = f.actions[review['id']]['receipt']
                if corruption == 'missing':
                    f.actions[review['id']]['receipt'] = None
                elif corruption == 'digest':
                    receipt['approvalDigest'] = 'different'
                elif corruption == 'channel':
                    receipt['channelId'] = 'UC' + 'b' * 22
                elif corruption == 'video':
                    receipt['verification']['resourceId'] = 'another-video'
                else:
                    receipt['execution'] = 'real'
                result = f.step()
                self.assertEqual(result['state'], 'uncertain')
                self.assertEqual(result['progress']['stage'], 'native_schedule_reconciling')
                self.assertEqual(len(f.writes), 1)

    def test_pending_predecessor_blocks_new_schedule_write(self):
        f = ScheduleFixture()
        review = f.change()
        f.actions[review['id']]['status'] = 'outcome_unknown'
        with self.assertRaises(AlphaError) as caught:
            f.prepare(LATEST)
        self.assertEqual(caught.exception.code, 'youtube_schedule_verification_pending')
        self.assertEqual(len(f.writes), 1)

    def test_metadata_and_declaration_guards_precede_tracking_override(self):
        for part, field, value, category in (
                ('snippet', 'title', 'Changed outside the approval', 'youtube_metadata_readback_mismatch'),
                ('status', 'containsSyntheticMedia', True, 'youtube_declaration_readback_mismatch')):
            with self.subTest(field=field):
                f = ScheduleFixture()
                f.change()
                f.video[part][field] = value
                result = f.step()
                self.assertEqual(result['state'], 'held')
                self.assertEqual(result['progress']['errorCategory'], category)
                self.assertEqual(len(f.writes), 1)

    def test_conflicting_bound_action_branches_fail_closed(self):
        f = ScheduleFixture()
        first = f.change()
        branch = copy.deepcopy(f.actions[first['id']])
        branch['manifest']['inputs']['publishAt'] = LATEST
        branch['manifest']['plan']['body']['status']['publishAt'] = LATEST
        branch['digest'] = fingerprint(branch['manifest'])
        f.actions['conflicting-branch'] = branch
        result = f.step()
        self.assertEqual(result['state'], 'held')
        self.assertEqual(result['progress']['errorCategory'], 'youtube_schedule_tracking_conflict')
        self.assertEqual(len(f.writes), 1)

    def test_unbound_legacy_receipt_and_changed_video_identity_are_not_adopted(self):
        for corruption in ('legacy-unbound', 'provider-channel', 'provider-video'):
            with self.subTest(corruption=corruption):
                f = ScheduleFixture()
                review = f.change()
                if corruption == 'legacy-unbound':
                    f.actions[review['id']]['manifest'].pop('uploadScheduleBinding')
                    f.actions[review['id']]['digest'] = fingerprint(f.actions[review['id']]['manifest'])
                elif corruption == 'provider-channel':
                    f.video['snippet']['channelId'] = 'UC' + 'b' * 22
                else:
                    f.video['id'] = 'other-video'
                result = f.step()
                self.assertEqual(result['state'], 'held')
                self.assertEqual(len(f.writes), 1)
                self.assertEqual(f.upload_requests, 0)

    def test_late_preview_after_disconnect_cannot_recreate_prepared_action(self):
        f = ScheduleFixture()
        original_plan = f.api.plan
        def disconnect_after_plan(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            f.revoked = True
            f.uploads.clear()
            f.actions.clear()
            return plan
        f.api.plan = disconnect_after_plan
        with self.assertRaises(AlphaError) as caught:
            f.prepare()
        self.assertTrue(getattr(caught.exception, 'youtube_authorization_fence', False))
        self.assertEqual(f.actions, {})
        self.assertEqual(f.uploads, {})
        self.assertEqual(f.writes, [])

    def test_late_receipt_cannot_overwrite_an_erased_action(self):
        for stage in ('accepted', 'verified'):
            with self.subTest(stage=stage):
                f = ScheduleFixture()
                review = f.prepare()
                row = f.actions[review['id']]

                def erase():
                    row.update(status='privacy_erased', receipt=None, privacy_erased_at=f.now)

                if stage == 'accepted':
                    execute = f.api.execute

                    def erase_after_execute(*args, **kwargs):
                        result = execute(*args, **kwargs)
                        erase()
                        return result

                    f.api.execute = erase_after_execute
                else:
                    verify = f.creator.verify_action

                    def erase_after_verify(*args, **kwargs):
                        result = verify(*args, **kwargs)
                        erase()
                        return result

                    f.creator.verify_action = erase_after_verify
                result = f.approve(review)
                self.assertEqual((result['status'], result['receipt'], result['dataRemoved']), ('privacy_erased', None, True))
                self.assertEqual((row['status'], row['receipt'], row['privacy_erased_at']), ('privacy_erased', None, f.now))
                with self.assertRaises(AlphaError) as replay:
                    f.approve(review)
                self.assertEqual(replay.exception.code, 'youtube_privacy_erased')
                self.assertEqual(len(f.writes), 1)
                self.assertEqual(f.upload_requests, 0)


if __name__ == '__main__':
    unittest.main()
