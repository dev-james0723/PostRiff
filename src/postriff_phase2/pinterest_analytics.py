"""Native Pin metrics through existing bound custody/quota transport; disabled until separately enabled."""
from datetime import datetime, timezone, timedelta
import math
import re
from urllib.parse import urlencode
from postriff_alpha.domain import AlphaError

SCOPES = frozenset({'user_accounts:read', 'boards:read', 'pins:read'})
METRICS = {'IMPRESSION': 'impressions', 'SAVE': 'saves', 'PIN_CLICK': 'pin_clicks', 'OUTBOUND_CLICK': 'outbound_clicks'}
DEFINITION = 'pinterest-pin-utc-window-v1'


def enabled(adapter):
    return bool(adapter and getattr(adapter, 'analytics_enabled', False) is True
                and getattr(adapter, 'production_reviewed', False) is True
                and getattr(adapter, 'execution_enabled', True) is True
                and not getattr(adapter, 'trial_readonly', False))


def fetch(adapter, token, pin_id, *, start_at, end_at):
    if not enabled(adapter):
        raise AlphaError('Pinterest analytics is not enabled for this integration.', 403)
    if not isinstance(pin_id, str) or not re.fullmatch(r'\d{1,30}', pin_id):
        raise AlphaError('Choose a verified Pinterest Pin.', 400)
    if any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in (start_at, end_at)) or start_at > end_at:
        raise AlphaError('Choose a valid Pinterest reporting window.', 400)
    try:
        first = datetime.fromtimestamp(start_at, timezone.utc).date()
        last = datetime.fromtimestamp(end_at, timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        raise AlphaError('Choose a valid Pinterest reporting window.', 400) from None
    if first < last - timedelta(days=89):
        raise AlphaError('Pinterest Pin analytics needs a reporting window within the last 90 days.', 409)
    envelope = adapter._bound(token, 'at')
    account = envelope.get('accountId')
    if not isinstance(account, str) or not re.fullmatch(r'\d{1,30}', account):
        raise AlphaError('Reconnect Pinterest to bind analytics to the expected account.', 409)
    if not SCOPES <= set(envelope.get('scope') or []):
        raise AlphaError('Reconnect Pinterest with Pin analytics read permission.', 403)
    identity = adapter.identity(token)
    if identity.get('providerAccountId') != account:
        raise AlphaError('Pinterest account changed. Reconnect before reading analytics.', 409)
    path = f'/v5/pins/{pin_id}/analytics'
    query = urlencode({'start_date': first.isoformat(), 'end_date': last.isoformat(), 'metric_types': ','.join(METRICS)})
    response = adapter.api(token, 'GET', path + '?' + query)
    body = response.get('body')
    report = (body.get('all') if 'all' in body else body.get('ALL')) if isinstance(body, dict) else None
    summary = report.get('summary_metrics') if isinstance(report, dict) else None
    found = {}
    if response.get('status') == 200 and isinstance(summary, dict):
        for native, name in METRICS.items():
            value = summary.get(native)
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                found[name] = value
    return {'status': response.get('status'), 'found': found, 'endpoint': adapter.content_api + path + '?' + query,
            'periodStart': datetime.combine(first, datetime.min.time(), timezone.utc).timestamp()}


def describe(matrix, scopes, *, analytics_enabled=False):
    """Explain stored levels truthfully without promoting an unverified permission to Direct."""
    result = {key: dict(value) if isinstance(value, dict) else value for key, value in matrix.items()}
    granted = set(scopes or [])
    publishing = {'user_accounts:read', 'boards:read', 'pins:read', 'pins:write'} <= granted
    if not publishing:
        for name, detail in {'publish': 'Publishing needs Pinterest publishing permission and Rafii release approval. This connection is read-only.',
                             'schedule': 'Rafii supports scheduling approved Pins through its queue after publishing access is enabled. This read-only connection cannot schedule.'}.items():
            value = result.setdefault(name, {})
            if value.get('level') != 'Direct':
                value['evidence'] = detail
    value = result.setdefault('analytics', {})
    if analytics_enabled is not True:
        value.update(level='Unsupported', verifiedAt=None)
    if value.get('level') != 'Direct':
        value['evidence'] = ('Pinterest offers Pin analytics. Rafii analytics is not enabled for this connection; separate read permission and release approval are required.'
                             if not analytics_enabled else 'Pinterest offers Pin analytics; this connection has not granted Pin-read analytics permission.'
                             if not SCOPES <= granted else 'Analytics read permission is granted; provider and release approval gates remain closed.')
    for name in ('comments_read', 'reply'):
        value = result.setdefault(name, {})
        value.update(level='Unsupported', evidence='Pinterest public API v5 does not expose Pin comment-reading or reply endpoints. Use Pinterest directly.', verifiedAt=None)
    return result
