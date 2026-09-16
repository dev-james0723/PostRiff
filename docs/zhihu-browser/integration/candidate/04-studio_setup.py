"""Network-free, non-authorizing setup candidates for Studio Phase D preparation.

There is deliberately no connection/approval importer or credential input. A
downloaded candidate cannot be used as a route test or execution receipt.
"""
from .execution import payload_hash
from .studio import StudioError, channel_catalog

CATALOG_VERSION = 'studio-setup/1'
INPUT_FIELDS = {'channel', 'nativeFormat', 'accountLabel', 'destinationLabel'}


def _pilot(channel):
    if channel == 'zhihu':
        return {'candidateRoute': 'controlled_browser', 'pilotScope': 'Dedicated browser login and exact-approval text idea pilot',
                'documentationState': 'partial_review', 'sources': [{'url': 'https://github.com/liuboacean/zhihu-automation-skill',
                'checkedAt': '2026-09-13', 'state': 'reviewed', 'note': 'Selective adaptation at 9aca95da75ffd0238174ba9ed2438f4c519ce233. Live selectors and account remain unqualified.'}]}
    if channel == 'bluesky':
        return {'candidateRoute': 'official_api', 'pilotScope': 'Text-only post candidate',
                'documentationState': 'partial_review',
                'sources': [{'url': 'https://atproto.com/specs/oauth', 'checkedAt': '2026-09-13',
                             'state': 'reviewed', 'note': 'OAuth architecture reviewed; exact scopes, client and account remain unqualified.'},
                            {'url': 'https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/feed/post.json',
                             'checkedAt': None, 'state': 'needs_pinned_review',
                             'note': 'Pin and review the exact post schema before transport implementation.'}]}
    if channel == 'wechat-channels':
        return {'candidateRoute': 'controlled_browser', 'pilotScope': 'Video through a qualified creator-centre browser flow',
                'documentationState': 'documentation_unavailable',
                'sources': [{'url': 'https://channels.weixin.qq.com', 'checkedAt': '2026-09-13',
                             'state': 'unavailable', 'note': 'Research tool could not read the portal; no authenticated inspection or API qualification.'}]}
    return {'candidateRoute': None, 'pilotScope': 'Choose a route after operation-specific review',
            'documentationState': 'not_reviewed', 'sources': []}


def readiness():
    rows = []
    for channel in channel_catalog():
        rows.append({**channel, **_pilot(channel['id']), 'availableRoute': 'manual_handoff',
                     'routeDriver': None, 'routeTestId': None,
                     'blockers': ['Review current documentation for this exact format and operation.',
                                  'Implement and qualify a private account connection and delivery driver.',
                                  'Confirm the intended account; verify two independent identity signals.',
                                  'Review exact scopes, destination, costs and setup consequences.',
                                  'Approve and verify immediate and due-time pilot tests separately.']})
    return {'catalogVersion': CATALOG_VERSION, 'phase': 'D-preparation', 'channels': rows,
            'connectedCount': 0, 'publishReadyCount': 0, 'externalActions': []}


def _label(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 160
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise StudioError('invalid_setup_label', 'Use a non-empty, single-line public label of at most 160 characters.', 422)
    return value


def prepare_candidate(data):
    if not isinstance(data, dict) or set(data) != INPUT_FIELDS:
        raise StudioError('invalid_setup_fields', 'Only channel, format and public account/destination labels are accepted.', 422)
    if not isinstance(data['channel'], str) or not isinstance(data['nativeFormat'], str):
        raise StudioError('invalid_setup_target', 'Choose a channel and one of its native formats.', 422)
    row = next((item for item in readiness()['channels'] if item['id'] == data['channel']), None)
    if row is None or data['nativeFormat'] not in {fmt['id'] for fmt in row['formats']}:
        raise StudioError('invalid_setup_target', 'Choose a channel and one of its native formats.', 422)
    body = {
        'schemaVersion': 1, 'catalogVersion': CATALOG_VERSION, 'state': 'candidate_only',
        'scope': 'setup_assessment_only',
        'target': {'channel': row['id'], 'nativeFormat': data['nativeFormat'],
                   'accountLabel': _label(data['accountLabel']), 'destinationLabel': _label(data['destinationLabel']),
                   'identityState': 'unverified_labels', 'operation': 'publish'},
        'availableRoute': row['availableRoute'], 'candidateRoute': row['candidateRoute'],
        'routeDriver': None, 'routeTestId': None, 'pilotScope': row['pilotScope'],
        'documentationState': row['documentationState'], 'sources': row['sources'],
        'requirements': [
            {'id': 'documentation', 'state': 'required', 'detail': row['blockers'][0]},
            {'id': 'driver', 'state': 'not_implemented', 'detail': row['blockers'][1]},
            {'id': 'identity', 'state': 'unverified', 'detail': row['blockers'][2]},
            {'id': 'setup_consent', 'state': 'not_requested', 'detail': row['blockers'][3]},
            {'id': 'private_auth', 'state': 'not_started', 'detail': 'Private authentication only after exact setup approval. Never paste passwords, cookies or tokens here.'},
            {'id': 'pilot_tests', 'state': 'not_requested', 'detail': row['blockers'][4]},
            {'id': 'remote_safety', 'state': 'not_implemented', 'detail': 'Bind exact content/time/derivatives, retain submission locks across ambiguous outcomes and reconcile before any retry.'},
            {'id': 'verification', 'state': 'not_implemented', 'detail': 'Independently match remote account, destination, post ID, content and visibility; a supplied link alone is unverified.'},
        ],
        'unresolved': ['exact_account_identity', 'credential_broker', 'minimum_scopes', 'callback_configuration',
                       'costs_and_quotas', 'app_review_requirements', 'adapter_version', 'operation_test_evidence'],
        'setupAuthorized': False, 'publicationAuthorized': False, 'remoteScheduling': False,
        'connected': False, 'publishReady': False, 'externalActions': [],
    }
    return {**body, 'manifestHash': payload_hash(body)}


def register_setup_routes(app, body_parser, connection_broker=None):
    from fastapi import Request

    @app.get('/api/setup/readiness')
    def status():
        result = readiness()
        if connection_broker is not None:
            states = {'bluesky': connection_broker.status(),
                      'instagram': connection_broker.instagram_status(),
                      'tiktok': connection_broker.tiktok_status(),
                      'pinterest': connection_broker.pinterest_status(),
                      'reddit': connection_broker.reddit_status()}
            connected = {'bluesky': states['bluesky']['state'] == 'connected_identity',
                         'instagram': states['instagram']['state'] == 'connected_identity',
                         'tiktok': states['tiktok']['state'] == 'connected_identity',
                         'pinterest': states['pinterest']['state'] in {'connected_identity', 'connected_browser_identity'},
                         'reddit': states['reddit']['state'] in {'connected_identity', 'connected_browser_identity'}}
            result['connectedCount'] = sum(connected.values())
            result['publishReadyCount'] = sum(item.get('publishReady') is True for item in states.values())
            for channel in result['channels']:
                if connected.get(channel['id']):
                    channel['connection'] = 'connected_identity'
                    channel['publishReady'] = states[channel['id']].get('publishReady') is True
                    if channel['id'] == 'reddit' and channel['publishReady']:
                        channel['availableRoute'] = 'controlled_browser'
                        channel['candidateRoute'] = 'controlled_browser'
                        channel['routeDriver'] = states['reddit']['routeDriver']
                        channel['routeTestId'] = states['reddit']['routeTestId']
                        channel['pilotScope'] = 'Text or link post through the qualified Reddit composer'
                        channel['documentationState'] = 'route_tested'
        return result

    @app.post('/api/setup/candidates')
    async def candidate(request: Request):
        return {'candidate': prepare_candidate(await body_parser(request))}
