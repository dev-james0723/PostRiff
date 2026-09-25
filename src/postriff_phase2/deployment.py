"""Fail-closed preview composition; no connection is made while validating configuration."""
import re
from urllib.parse import parse_qs, unquote, urlparse


def isolated_environment(values):
    result = dict(values)
    if result.get('VERCEL_ENV') != 'preview':
        return result
    if result.get('POSTRIFF_ENVIRONMENT') != 'staging':
        raise ValueError('Preview requires the explicit staging environment.')
    staging = result.get('POSTRIFF_STAGING_PROJECT_REF', '')
    production = result.get('POSTRIFF_PRODUCTION_PROJECT_REF', '')
    if not all(re.fullmatch(r'[a-z0-9]{20}', ref) for ref in (staging, production)) or staging == production:
        raise ValueError('Preview requires distinct pinned staging and production project references.')
    expected = 'https://' + staging + '.supabase.co'
    if result.get('POSTRIFF_SUPABASE_URL', '').rstrip('/') != expected or result.get('NEXT_PUBLIC_SUPABASE_URL', '').rstrip('/') != expected:
        raise ValueError('Preview identity and storage must match the pinned staging project.')
    dsn = urlparse(result.get('POSTRIFF_DATABASE_URL', ''))
    direct = dsn.hostname == 'db.' + staging + '.supabase.co' and unquote(dsn.username or '') == 'postgres'
    pooler = bool(re.fullmatch(r'[a-z0-9.-]+\.pooler\.supabase\.com', dsn.hostname or '')) and unquote(dsn.username or '') == 'postgres.' + staging
    if dsn.scheme not in ('postgres', 'postgresql') or not (direct or pooler) or parse_qs(dsn.query).get('sslmode') not in (['require'], ['verify-full']):
        raise ValueError('Preview database must use TLS and match the pinned staging project.')
    origin = result.get('POSTRIFF_PUBLIC_BASE_URL', '').rstrip('/')
    approved = result.get('POSTRIFF_STAGING_PUBLIC_BASE_URL', '').rstrip('/')
    parsed = urlparse(origin)
    if not approved or origin != approved or parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Preview callbacks require the exact approved staging HTTPS origin.')
    if result.get('POSTRIFF_API_ORIGIN'):
        raise ValueError('Preview API rewrites must use the same deployment, not an external origin.')
    stripe = result.get('STRIPE_SECRET_KEY', '')
    if stripe and not stripe.startswith(('sk_test_', 'rk_test_')):
        raise ValueError('Preview billing accepts test-mode credentials only.')
    # Secrets must be deliberately bound to this staging release, never inherited from production.
    # The review manifest contains hashes, not secrets; authorizing its deployment remains external.
    import hashlib
    import json
    try:
        pins = json.loads(result.get('POSTRIFF_STAGING_SECRET_SHA256', '{}'))
    except (ValueError, TypeError) as error:
        raise ValueError('Staging secret fingerprints must be a JSON object.') from error
    if not isinstance(pins, dict):
        raise ValueError('Staging secret fingerprints must be a JSON object.')
    names = {'POSTRIFF_SUPABASE_SECRET_KEY', 'POSTRIFF_CREDENTIAL_KEY', 'CRON_SECRET', 'STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET', 'AI_GATEWAY_API_KEY', 'RESEND_API_KEY',
             'RESEND_WEBHOOK_SECRET', 'POSTRIFF_VAPID_PRIVATE_KEY', 'POSTRIFF_NOTIFICATION_SIGNING_KEY'}
    names.update(key for key in result if key.startswith('POSTRIFF_OAUTH_') and key.endswith(('CLIENT_ID', 'CLIENT_SECRET')))
    for name in names:
        value = result.get(name)
        if value and pins.get(name) != hashlib.sha256(value.encode()).hexdigest():
            raise ValueError('Preview contains an unpinned staging credential: ' + name)
    # Research/CLI have independent egress and credentials; neither is part of this deployment candidate.
    if result.get('POSTRIFF_RESEARCH', '0') != '0' or result.get('POSTRIFF_LOCAL_CLI', '0') != '0':
        raise ValueError('Preview research and local CLI must remain disabled.')
    result['POSTRIFF_RESEARCH'] = '0'
    result['POSTRIFF_LOCAL_CLI'] = '0'
    # Rafii coworker features that reach an outside service (email, push, the public web) stay off in preview.
    egress = ('RAFII_NOTIFICATIONS_V2_ENABLED', 'RAFII_WEB_PUSH_ENABLED', 'RAFII_RESEARCH_BROKER_ENABLED', 'RAFII_LISTENING_ENABLED')
    if any(str(result.get(name, '')).strip().lower() in ('1', 'true', 'yes', 'on') for name in egress):
        raise ValueError('Preview Rafii notifications, web push, research and listening must remain disabled.')
    for name in egress:
        result[name] = ''
    return result
