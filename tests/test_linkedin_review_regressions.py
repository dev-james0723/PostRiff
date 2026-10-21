"""Review regressions: bounded synthetic services/transports, never live acceptance."""
import copy
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.contracts import digest
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.oauth import OAuthService
from postriff_phase2.official_operations import SocialActionsService, ACTION_FIELDS, ACTION_PERMISSIONS
from postriff_phase2.providers import InstagramProvider
from postriff_phase2.provider_candidates import little_text
from postriff_phase2.wave3_connectors import PinterestProvider
from test_linkedin_publishing_recovery import approved_member_app, CAPTION
from test_official_social import runtime, response, job

NOW = 1_800_000_000


class ActionRepository:
    def __init__(self):
        self.state = {'phase2': {'channels': [{'id': 'C', 'platform': 'Instagram',
            'providerAccountId': '123', 'evidenceSource': 'live_provider'}], 'jobs': [], 'reviews': []}}
        self.role, self.flags, self.depth = 'editor', [True, True, True, False], 0
        self.provider_id = 'instagram'

    @contextmanager
    def transaction(self, token, workspace):
        self.depth += 1
        try:
            yield self, [1, copy.deepcopy(self.state), self.role, *self.flags], 'member'
        finally:
            self.depth -= 1

    def execute(self, sql, params=()):
        if sql.startswith('UPDATE public.pr_workspaces'):
            self.state = json.loads(params[0])
        elif sql.startswith('SELECT provider FROM'):
            self.result = (self.provider_id,)
        elif sql.startswith('INSERT INTO public.pr_audit_events'):
            pass
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.result


def actions_fixture(linkedin=False):
    repo = ActionRepository()
    provider = approved_member_app() if linkedin else InstagramProvider('synthetic-app', 'synthetic-secret')
    provider.official_social_enabled = True
    if not linkedin:
        provider.production_reviewed = True
    account = 'urn:li:person:abc' if linkedin else '123'
    repo.provider_id = provider.id
    repo.state['phase2']['channels'][0].update(platform=provider.platform, providerAccountId=account)
    provider.identity = Mock(return_value={'providerAccountId': account})
    provider.transport = Mock(return_value=response(status=204 if linkedin else 200))
    provider.organization_authorized = Mock(return_value=True)
    oauth = OAuthService.__new__(OAuthService)
    oauth.repository, oauth.clock = repo, lambda: NOW
    oauth._assert_pinterest_context = lambda *a, **kw: None
    oauth.token_for_worker = Mock(return_value={'accessToken': 'synthetic-only', 'scopes': [
        'instagram_business_basic', 'instagram_business_manage_comments', 'w_member_social',
        'w_organization_social', 'rw_organization_admin']})
    oauth.provider_for_grant = lambda _: provider
    return SocialActionsService(oauth), repo, provider


def preview(service, action='reply', payload=None):
    return service.preview('W', 'session', 'C', action, '456', payload or ({'text': 'Same reply'} if action == 'reply' else {}))


def approve(service, item):
    return service.approve('W', 'session', item['id'], item['digest'], True)


def organization_post(repo):
    repo.state['phase2']['jobs'] = [{'id': 'post', 'state': 'provider_accepted',
        'providerReference': 'urn:li:share:123', 'manifest': {'platform': 'LinkedIn', 'channelId': 'C',
            'providerAccountId': 'urn:li:person:abc', 'publishOptions': {
                'destinationType': 'organization', 'authorUrn': 'urn:li:organization:7'}}}]


def edit_preview(service):
    return service.preview('W', 'session', 'C', 'edit', 'urn:li:share:123', {'text': 'Approved edit'})


class NativePermissions(unittest.TestCase):
    def test_every_allowed_action_requires_an_explicit_server_permission(self):
        self.assertEqual(set(ACTION_FIELDS), set(ACTION_PERMISSIONS))

    def test_preview_denies_each_operation_permission_independently(self):
        for action, flag in [('reply', 1), ('hide', 2), ('unhide', 2), ('delete_comment', 2)]:
            with self.subTest(action=action):
                service, repo, provider = actions_fixture()
                repo.flags[flag] = False
                with self.assertRaises(AlphaError):
                    preview(service, action)
                provider.transport.assert_not_called()

    def test_approval_rechecks_each_operation_permission(self):
        for action, flag in [('reply', 1), ('hide', 2), ('delete_comment', 2)]:
            with self.subTest(action=action):
                service, repo, provider = actions_fixture()
                item = preview(service, action)
                repo.flags[flag] = False
                with self.assertRaises(AlphaError):
                    approve(service, item)
                provider.transport.assert_not_called()

    def test_final_dispatch_rechecks_permission_after_identity_verification(self):
        for action, flag in [('reply', 1), ('hide', 2)]:
            with self.subTest(action=action):
                service, repo, provider = actions_fixture()
                item = preview(service, action)
                def identity(_):
                    repo.flags[flag] = False
                    return {'providerAccountId': '123'}
                provider.identity.side_effect = identity
                self.assertEqual(approve(service, item)['executionState'], 'held')
                provider.transport.assert_not_called()

    def test_reply_and_moderate_do_not_require_can_publish(self):
        for action in ('reply', 'hide'):
            with self.subTest(action=action):
                service, repo, provider = actions_fixture()
                repo.flags[0] = False
                self.assertEqual(approve(service, preview(service, action))['executionState'], 'submitted')
                provider.transport.assert_called_once()

    def test_operation_flags_follow_role_contract_without_unrelated_editor_requirement(self):
        for role in ('admin', 'approver'):
            for action in ('reply', 'hide'):
                with self.subTest(role=role, action=action):
                    service, repo, provider = actions_fixture()
                    repo.role, repo.flags[0] = role, False
                    self.assertEqual(approve(service, preview(service, action))['executionState'], 'submitted')
                    provider.transport.assert_called_once()

    def test_edit_requires_publisher_permission_and_rejects_client_authority(self):
        service, repo, provider = actions_fixture(linkedin=True)
        organization_post(repo)
        provider.production_reviewed = True
        item = edit_preview(service)
        repo.flags[0] = False
        with self.assertRaises(AlphaError):
            approve(service, item)
        provider.transport.assert_not_called()
        with self.assertRaises(AlphaError):
            preview(service, 'reply', {'text': 'Reply', 'permission': 'approve'})

    def test_member_edit_rechecks_publish_permission_at_preview_and_final_dispatch(self):
        for stage in ('preview', 'dispatch'):
            with self.subTest(stage=stage):
                service, repo, provider = actions_fixture(linkedin=True)
                organization_post(repo)
                repo.state['phase2']['jobs'][0]['manifest']['publishOptions'] = {'destinationType': 'member', 'authorUrn': 'urn:li:person:abc'}
                if stage == 'preview':
                    repo.flags[0] = False
                    with self.assertRaises(AlphaError): edit_preview(service)
                else:
                    item = edit_preview(service)
                    def revoke(_):
                        repo.flags[0] = False
                        return {'providerAccountId': 'urn:li:person:abc'}
                    provider.identity.side_effect = revoke
                    self.assertEqual(approve(service, item)['executionState'], 'held')
                provider.transport.assert_not_called()


class OrganizationEdits(unittest.TestCase):
    def test_preview_binds_canonical_author_and_requires_app_review_and_role(self):
        for reviewed, role in ((False, True), (True, False), (True, True)):
            with self.subTest(reviewed=reviewed, role=role):
                service, repo, provider = actions_fixture(linkedin=True)
                organization_post(repo)
                provider.production_reviewed = reviewed
                provider.organization_authorized.return_value = role
                if not (reviewed and role):
                    with self.assertRaises(AlphaError):
                        edit_preview(service)
                else:
                    item = edit_preview(service)
                    self.assertEqual(item['manifest']['payload']['actor'], 'urn:li:organization:7')
                    provider.organization_authorized.assert_called_with('synthetic-only', 'urn:li:person:abc', 'urn:li:organization:7', 'UPDATE')
                provider.transport.assert_not_called()

    def test_approval_rechecks_app_review_role_and_canonical_author(self):
        for drift in ('review', 'role', 'author'):
            with self.subTest(drift=drift):
                service, repo, provider = actions_fixture(linkedin=True)
                organization_post(repo)
                provider.production_reviewed = True
                item = edit_preview(service)
                if drift == 'review': provider.production_reviewed = False
                elif drift == 'role': provider.organization_authorized.return_value = False
                else: repo.state['phase2']['jobs'][0]['manifest']['publishOptions']['authorUrn'] = 'urn:li:organization:8'
                try:
                    result = approve(service, item)
                except AlphaError:
                    result = {'executionState': 'held'}
                self.assertEqual(result['executionState'], 'held')
                provider.transport.assert_not_called()

    def test_valid_organization_edit_checks_role_and_keeps_original_approval(self):
        service, repo, provider = actions_fixture(linkedin=True)
        organization_post(repo)
        provider.production_reviewed = True
        original = copy.deepcopy(repo.state['phase2']['jobs'][0]['manifest'])
        self.assertEqual(approve(service, edit_preview(service))['executionState'], 'submitted')
        self.assertGreaterEqual(provider.organization_authorized.call_count, 2)
        self.assertEqual(repo.state['phase2']['jobs'][0]['manifest'], original)
        self.assertEqual(provider.transport.call_args.kwargs['body']['patch']['$set']['commentary'], 'Approved edit')

    def test_author_change_during_preview_or_final_identity_check_sends_no_edit(self):
        for stage in ('preview', 'dispatch'):
            with self.subTest(stage=stage):
                service, repo, provider = actions_fixture(linkedin=True)
                organization_post(repo)
                provider.production_reviewed = True
                item = edit_preview(service) if stage == 'dispatch' else None
                def changed(_):
                    repo.state['phase2']['jobs'][0]['manifest']['publishOptions']['authorUrn'] = 'urn:li:organization:8'
                    return {'providerAccountId': 'urn:li:person:abc'}
                provider.identity.side_effect = changed
                if stage == 'preview':
                    with self.assertRaises(AlphaError): edit_preview(service)
                else:
                    self.assertEqual(approve(service, item)['executionState'], 'held')
                provider.transport.assert_not_called()


class UnknownCreate(unittest.TestCase):
    def test_lost_response_blocks_fresh_preview_even_after_reconnect(self):
        service, repo, provider = actions_fixture()
        first = preview(service)
        provider.transport.side_effect = TimeoutError('Synthetic response lost')
        self.assertEqual(approve(service, first)['executionState'], 'uncertain')
        original = copy.deepcopy(repo.state['phase2']['nativeSocialActions'][0])
        repo.state['phase2']['channels'][0].update(verifiedAt=NOW+1, capabilityVersion=2)
        with self.assertRaises(AlphaError) as error:
            preview(service)
        self.assertEqual(error.exception.code, 'native_action_reconcile_required')
        self.assertEqual(repo.state['phase2']['nativeSocialActions'][0], original)
        provider.transport.assert_called_once()

    def test_replacement_connection_and_legacy_intent_without_logical_id_cannot_erase_unknown(self):
        service, repo, provider = actions_fixture()
        first = preview(service)
        provider.transport.side_effect = TimeoutError('Synthetic response lost')
        approve(service, first)
        repo.state['phase2']['nativeSocialActions'][0].pop('logicalOperationId', None)
        repo.state['phase2']['channels'][0].update(id='replacement-connection', verifiedAt=NOW+1)
        with self.assertRaises(AlphaError) as error:
            service.preview('W', 'session', 'replacement-connection', 'reply', '456', {'text': 'Same reply'})
        self.assertEqual(error.exception.code, 'native_action_reconcile_required')
        provider.transport.assert_called_once()

    def test_different_payload_is_distinct_and_uncertain_receipt_is_preserved(self):
        service, repo, provider = actions_fixture()
        first = preview(service)
        provider.transport.side_effect = TimeoutError('Synthetic response lost')
        approve(service, first)
        old = copy.deepcopy(repo.state['phase2']['nativeSocialActions'][0])
        second = preview(service, payload={'text': 'A separately approved reply'})
        self.assertNotEqual(first['logicalOperationId'], second['logicalOperationId'])
        self.assertEqual(repo.state['phase2']['nativeSocialActions'][0], old)

    def test_ignored_reply_fields_cannot_disguise_the_same_provider_request(self):
        service, repo, provider = actions_fixture()
        provider.transport.side_effect = TimeoutError('Synthetic response lost')
        approve(service, preview(service))
        with self.assertRaises(AlphaError) as error:
            preview(service, payload={'text': 'Same reply', 'actor': 'different-ignored-actor', 'rootPostUrn': 'ignored-root'})
        self.assertEqual(error.exception.code, 'native_action_reconcile_required')
        provider.transport.assert_called_once()

    def test_targetless_create_cannot_replay_by_changing_unused_target(self):
        service, repo, _ = actions_fixture()
        provider = PinterestProvider('synthetic-app', 'synthetic-secret')
        provider.production_reviewed = provider.official_social_enabled = True
        provider.identity = Mock(return_value={'providerAccountId': '123'})
        provider.api = Mock(side_effect=TimeoutError('Synthetic response lost'))
        repo.provider_id = 'pinterest'
        repo.state['phase2']['channels'][0]['platform'] = 'Pinterest'
        service.oauth.provider_for_grant = lambda _: provider
        service.oauth.token_for_worker.return_value['scopes'] = ['boards:write']
        first = service.preview('W', 'session', 'C', 'board_create', 'placeholder-one', {'name': 'Approved board'})
        self.assertEqual(approve(service, first)['executionState'], 'uncertain')
        with self.assertRaises(AlphaError) as error:
            service.preview('W', 'session', 'C', 'board_create', 'placeholder-two', {'name': 'Approved board'})
        self.assertEqual(error.exception.code, 'native_action_reconcile_required')
        provider.api.assert_called_once()

    def test_two_prepared_previews_block_second_after_unknown_or_inflight(self):
        for outcome in ('uncertain', 'submitting'):
            with self.subTest(outcome=outcome):
                service, repo, provider = actions_fixture()
                first, second = preview(service), preview(service)
                if outcome == 'uncertain':
                    provider.transport.side_effect = TimeoutError('Synthetic lost response')
                    approve(service, first)
                else:
                    repo.state['phase2']['nativeSocialActions'][0]['state'] = 'submitting'
                with self.assertRaises(AlphaError) as error:
                    approve(service, second)
                self.assertEqual(error.exception.code, 'native_action_reconcile_required')
                self.assertEqual(provider.transport.call_count, int(outcome == 'uncertain'))

    def test_competing_unknown_is_rechecked_immediately_before_dispatch(self):
        service, repo, provider = actions_fixture()
        first, second = preview(service), preview(service)
        def identity(_):
            repo.state['phase2']['nativeSocialActions'][1]['state'] = 'uncertain'
            return {'providerAccountId': '123'}
        provider.identity.side_effect = identity
        result = approve(service, first)
        self.assertEqual(result['executionState'], 'held')
        self.assertTrue(result['reconcileRequired'])
        provider.transport.assert_not_called()

    def test_successful_repeated_actions_remain_distinct_approved_operations(self):
        service, repo, provider = actions_fixture()
        first = preview(service)
        self.assertEqual(approve(service, first)['executionState'], 'submitted')
        second = preview(service)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(approve(service, second)['executionState'], 'submitted')
        self.assertEqual(provider.transport.call_count, 2)


class LegacyLinkedInPayload(unittest.TestCase):
    def host(self):
        provider = approved_member_app()
        provider.production_reviewed = True
        transport = Mock(return_value=response(status=201, **{'x-restli-id': 'urn:li:share:123'}))
        host = HostedSocial(SimpleNamespace(token_for_worker=lambda *a: {
            'accessToken': 'synthetic-only', 'scopes': ['w_member_social']}), {'linkedin': provider}, transport=transport)
        manifest = {'workspaceId': 'W', 'channelId': 'C', 'platform': 'LinkedIn',
            'providerAccountId': 'urn:li:person:abc', 'operation': 'member_post', 'payload': {'text': CAPTION}, 'media': []}
        return host, manifest, transport

    def test_flag_disabled_rejects_all_unsupported_approved_options_without_transport(self):
        for options in ({'poll': {'question': 'Which?'}}, {'link': 'https://example.invalid', 'title': 'Approved'},
                        {'destinationType': 'organization', 'authorUrn': 'urn:li:organization:7'},
                        {'authorUrn': 'urn:li:person:other'}, {'futureOption': True}):
            with self.subTest(options=options):
                host, manifest, transport = self.host()
                manifest['publishOptions'] = options
                self.assertEqual(host.submit(manifest)['state'], 'held')
                transport.assert_not_called()

    def test_plain_personal_text_preserves_actual_payload_and_author(self):
        host, manifest, transport = self.host()
        manifest['publishOptions'] = {'destinationType': 'member', 'authorUrn': manifest['providerAccountId']}
        self.assertEqual(host.submit(manifest)['state'], 'provider_accepted')
        self.assertEqual(transport.call_args.kwargs['body']['author'], manifest['providerAccountId'])
        self.assertEqual(transport.call_args.kwargs['body']['commentary'], little_text(CAPTION))
        transport.assert_called_once()


class CanonicalPinterestSection(unittest.TestCase):
    def test_actual_additional_request_uses_board_section_id(self):
        owner, manifest, transport, _ = runtime(PinterestProvider('synthetic-app', 'synthetic-secret'),
            [response({'id': '123456789'}, 201)], ['image/jpeg'], {'boardId': '12345', 'boardSectionId': '67890'})
        self.assertEqual(owner.advance(manifest, job('create_attempted'), 'create')['state'], 'provider_accepted')
        self.assertEqual(transport.calls[-1][2]['body']['board_section_id'], '67890')
