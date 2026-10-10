"""Server-owned templates. User fields narrow parameters, never executable steps or authority."""
from __future__ import annotations

import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from postriff_alpha.domain import AlphaError

VERSION = 1
MAX_RECIPES = 5
MAX_ASSETS = 20
TEMPLATES = {
    'weekly_performance': {
        'id': 'weekly_performance', 'version': VERSION, 'name': 'Review stored performance',
        'description': 'Review available metrics for one connected account. No sync, model call or new provider request.',
        'triggers': ['weekly'], 'capabilityId': 'tool.workflow_performance_review',
        'domains': ['analytics', 'connections'], 'risk': 'R0', 'costUsdMicro': 0,
        'steps': ['Read the selected account’s stored metrics for the previous 7 days', 'Save an attributed report and a task receipt'],
        'preconditions': ['Current explicit Assist permission for reads', 'The selected account still belongs to this workspace'],
        'approvalPolicy': 'Only these free reads run automatically. Any R2 action requires its own native approval; R3 actions are forbidden.',
    },
    'library_review': {
        'id': 'library_review', 'version': VERSION, 'name': 'Review Library metadata',
        'description': 'Review up to 20 selected-scope assets. Titles, tags and collection membership only; no file contents leave the Library.',
        'triggerNote': 'New-upload triggers cover Universal Library files uploaded after enabling. Weekly review also includes legacy images and videos.',
        'triggers': ['weekly', 'new_asset'], 'capabilityId': 'tool.workflow_library_review',
        'domains': ['library'], 'risk': 'R0', 'costUsdMicro': 0,
        'steps': ['Read bounded metadata from the selected Library collection or whole Library', 'Save references and a task receipt'],
        'preconditions': ['Current explicit Assist permission for reads', 'The selected collection remains available'],
        'approvalPolicy': 'Only these free reads run automatically. Any R2 action requires its own native approval; R3 actions are forbidden.',
    },
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def ident(value, label='resource'):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
        raise AlphaError(f'Choose a valid {label}.', 400)
    return value.replace('-', '')


def integer(value, low, high, label):
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise AlphaError(f'{label} must be from {low} to {high}.', 400)
    return value


def validate(body, now):
    keys = {'templateId', 'name', 'trigger', 'planningDay', 'planningHour', 'timeZone', 'connectionId', 'collectionId',
            'expiresAt', 'actionsPerDay', 'actionsTotal', 'usdMicroPerDay', 'notificationPolicy'}
    if not isinstance(body, dict) or set(body) - keys:
        raise AlphaError('Choose a server-owned recipe and its listed settings.', 400)
    template = TEMPLATES.get(body.get('templateId'))
    if template is None:
        raise AlphaError('This recipe template is unavailable.', 400)
    name = body.get('name') or template['name']
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or '\x00' in name:
        raise AlphaError('Recipe name must be 1–80 characters.', 400)
    trigger = body.get('trigger', 'weekly')
    if trigger not in template['triggers']:
        raise AlphaError('Choose a supported trigger for this recipe.', 400)
    zone = body.get('timeZone', 'UTC')
    try:
        if not isinstance(zone, str) or len(zone) > 64:
            raise ValueError()
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError):
        raise AlphaError('Choose a valid time zone.', 400) from None
    expires = body.get('expiresAt')
    if not isinstance(expires, (int, float)) or isinstance(expires, bool) or not now + 60 < expires <= now + 30 * 86400:
        raise AlphaError('Set an expiry within the next 30 days.', 400)
    actions_day = integer(body.get('actionsPerDay', 1), 1, 5, 'Daily operation limit')
    actions_total = integer(body.get('actionsTotal', 4), 1, 50, 'Total operation limit')
    if body.get('usdMicroPerDay', 0) != 0 or isinstance(body.get('usdMicroPerDay'), bool):
        raise AlphaError('These recipes are free. Their cost ceiling must be zero.', 400)
    notifications = body.get('notificationPolicy', 'failures_and_approvals')
    if notifications not in ('none', 'failures_and_approvals', 'all'):
        raise AlphaError('Choose a notification preference.', 400)
    connection = body.get('connectionId')
    collection = body.get('collectionId')
    if template['id'] == 'weekly_performance':
        if not isinstance(connection, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', connection) or collection:
            raise AlphaError('Choose one connected account for this report.', 400)
    elif connection:
        raise AlphaError('A Library recipe cannot select a connected account.', 400)
    elif collection:
        collection = ident(collection, 'collection')
    return {'templateId': template['id'], 'templateVersion': template['version'], 'name': name.strip(), 'trigger': trigger,
            'planningDay': integer(body.get('planningDay', 0), 0, 6, 'Day'), 'planningHour': integer(body.get('planningHour', 9), 0, 23, 'Hour'),
            'timeZone': zone, 'connectionId': connection or None, 'collectionId': collection or None,
            'expiresAt': int(expires), 'actionsPerDay': actions_day, 'actionsTotal': actions_total, 'usdMicroPerDay': 0,
            'notificationPolicy': notifications, 'errorPolicy': {'maxAttempts': 3, 'failedRunBackoffSeconds': [300, 600, 1200], 'circuitAfterFailures': 3},
            'approvalPolicy': 'R0_template_only; R2_native_per_action; R3_forbidden', 'maxAssets': MAX_ASSETS}
